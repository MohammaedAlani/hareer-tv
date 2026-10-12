import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from backend.database import connect, initialize
from backend import imports
from backend.server import make_handler, ThreadingHTTPServer
import urllib.request
import urllib.error

FIRST='https://www.youtube.com/watch?v=4mQGIyPD0Qs'
SECOND='https://youtu.be/abcdefghijk'

class FakeStorage:
    base_url='https://tv.example'
    def __init__(self): self.objects={};self.fail=False
    def upload(self,path,key,kind):
        if self.fail and kind=='image/jpeg': raise RuntimeError('do not expose storage credentials')
        self.objects[key]=path.read_bytes()
    def signed_url(self,key): return 'https://storage.example/'+key+'?signature=test'

def fake_download(job,directory,stop):
    video=directory/'video.mp4'; image=directory/'image.jpg'
    video.write_bytes(b'video');image.write_bytes(b'image')
    return 'Story '+job['youtube_id'],video,image

class ImportTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.db=Path(self.temp.name)/'db.sqlite3';initialize(self.db)
        self.storage=FakeStorage()
        self.disk=patch('backend.imports.shutil.disk_usage',return_value=shutil._ntuple_diskusage(20*1024**3,0,20*1024**3));self.disk.start()
    def tearDown(self): self.disk.stop();self.temp.cleanup()
    def worker(self,downloader=fake_download): return imports.ImportWorker(self.db,self.storage,downloader)
    def wait_for(self,predicate):
        deadline=time.monotonic()+8
        while time.monotonic()<deadline:
            if predicate(): return
            time.sleep(.05)
        self.fail('Timed out waiting for queue')
    def test_normalization_and_dedup(self):
        result=imports.enqueue(self.db,[FIRST,'https://youtu.be/4mQGIyPD0Qs','https://www.youtube.com/shorts/4mQGIyPD0Qs'])
        self.assertEqual(len(result),1);self.assertEqual(len(imports.enqueue(self.db,[FIRST])),1)
        self.assertEqual(len(imports.jobs(self.db)),1)
    def test_rejects_arbitrary_hosts_playlists_and_atomic_batch(self):
        for link in ['http://youtube.com/watch?v=4mQGIyPD0Qs','https://youtube.com.evil.test/watch?v=4mQGIyPD0Qs','https://127.0.0.1/video','https://youtube.com/playlist?list=abc','https://evil@youtube.com/watch?v=4mQGIyPD0Qs']:
            with self.assertRaises(ValueError): imports.enqueue(self.db,[FIRST,link])
        self.assertEqual(imports.jobs(self.db),[])
    def test_publish_after_both_uploads(self):
        imports.enqueue(self.db,[FIRST]);worker=self.worker();self.assertTrue(worker.process_one())
        with connect(self.db) as db:
            row=db.execute('SELECT * FROM videos').fetchone()
            self.assertTrue(row['video_url'].startswith('https://tv.example/media/'))
            self.assertEqual(db.execute('SELECT count(*) FROM media').fetchone()[0],2)
        self.assertEqual(imports.jobs(self.db)[0]['status'],'completed');self.assertEqual(len(self.storage.objects),2)
        self.assertFalse(worker.process_one())
    def test_partial_upload_never_publishes_and_retry_is_idempotent(self):
        imports.enqueue(self.db,[FIRST]);self.storage.fail=True;worker=self.worker();worker.process_one()
        with connect(self.db) as db: self.assertEqual(db.execute('SELECT count(*) FROM videos').fetchone()[0],0)
        job=imports.jobs(self.db)[0];self.assertEqual(job['status'],'failed');self.assertNotIn('credentials',job['error'])
        imports.retry(self.db,job['id']);self.storage.fail=False;worker.process_one()
        self.assertEqual(imports.jobs(self.db)[0]['attempts'],2)
        with self.assertRaises(ValueError): imports.retry(self.db,job['id'])
        with connect(self.db) as db: self.assertEqual(db.execute('SELECT count(*) FROM videos').fetchone()[0],1)
    def test_failed_download_does_not_block_next(self):
        imports.enqueue(self.db,[FIRST,SECOND])
        def download(job,path,stop):
            if job['youtube_id']=='4mQGIyPD0Qs': raise imports.ImportFailure('Unavailable')
            return fake_download(job,path,stop)
        worker=self.worker(download);worker.process_one();worker.process_one()
        self.assertEqual([j['status'] for j in reversed(imports.jobs(self.db))],['failed','completed'])
    def test_two_workers_are_serial_and_recover_interrupted_job(self):
        imports.enqueue(self.db,[FIRST,SECOND])
        with connect(self.db) as db: db.execute("UPDATE imports SET status='uploading' WHERE id=1")
        active=0;maximum=0;order=[];guard=threading.Lock()
        def download(job,path,stop):
            nonlocal active,maximum
            with guard: active+=1;maximum=max(maximum,active);order.append(job['id'])
            time.sleep(.15)
            with guard: active-=1
            return fake_download(job,path,stop)
        workers=[self.worker(download),self.worker(download)]
        try:
            for worker in workers: worker.start()
            self.wait_for(lambda: all(j['status']=='completed' for j in imports.jobs(self.db)))
            self.assertEqual(maximum,1);self.assertEqual(order,[1,2])
        finally:
            for worker in workers: worker.stop.set()
            for worker in workers: worker.thread.join(5)
    def test_deleted_video_stops_media_gateway(self):
        imports.enqueue(self.db,[FIRST]);self.worker().process_one()
        http=ThreadingHTTPServer(('127.0.0.1',0),make_handler(self.db,self.temp.name,'x'*40,self.storage))
        thread=threading.Thread(target=http.serve_forever,daemon=True);thread.start()
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self,*args,**kwargs): return None
        opener=urllib.request.build_opener(NoRedirect)
        with connect(self.db) as db: path=db.execute('SELECT video_url FROM videos').fetchone()[0].replace(self.storage.base_url,'')
        try:
            with self.assertRaises(urllib.error.HTTPError) as result: opener.open('http://127.0.0.1:'+str(http.server_port)+path)
            self.assertEqual(result.exception.code,302);self.assertEqual(result.exception.headers['Cache-Control'],'no-store')
            with connect(self.db) as db: db.execute('DELETE FROM videos')
            with self.assertRaises(urllib.error.HTTPError) as result: opener.open('http://127.0.0.1:'+str(http.server_port)+path)
            self.assertEqual(result.exception.code,404)
        finally: http.shutdown();http.server_close();thread.join()
    def test_queue_limit(self):
        with connect(self.db) as db:
            db.executemany('INSERT INTO videos(title,image_url,video_url) VALUES(?,?,?)',[('x','https://a.example/a','https://a.example/b')]*300)
        with self.assertRaises(ValueError): imports.enqueue(self.db,[FIRST])
    @unittest.skipUnless(shutil.which('ffmpeg'),'ffmpeg unavailable')
    def test_actual_conversion_and_thumbnail_with_synthetic_source(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp);original=imports.run_command
            def command(args,directory,stop,timeout,failure):
                if 'yt_dlp' in args:
                    subprocess.run(['ffmpeg','-loglevel','error','-y','-f','lavfi','-i','color=c=pink:s=128x72:r=10','-t','1','-c:v','libx264',str(directory/'source.mp4')],check=True)
                    (directory/'source.info.json').write_text(json.dumps({'id':'4mQGIyPD0Qs','title':'Local test video','duration':1}))
                else: original(args,directory,stop,timeout,failure)
            with patch('backend.imports.run_command',side_effect=command):
                title,video,image=imports.download({'youtube_id':'4mQGIyPD0Qs','source_url':FIRST},path,threading.Event())
            self.assertEqual(title,'Local test video');self.assertGreater(video.stat().st_size,100);self.assertTrue(image.read_bytes().startswith(b'\xff\xd8'))

if __name__=='__main__': unittest.main()
