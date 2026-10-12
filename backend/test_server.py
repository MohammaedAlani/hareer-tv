import importlib.util
import json
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.request
import urllib.error

spec=importlib.util.spec_from_file_location('server',Path(__file__).with_name('server.py'))
server=importlib.util.module_from_spec(spec); spec.loader.exec_module(server)

class CatalogServerTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.db=Path(self.temp.name)/'catalog.sqlite3'
        self.site=Path(self.temp.name)/'site'; self.site.mkdir(); (self.site/'index.html').write_text('Hareer TV')
        server.initialize(self.db)
        self.http=server.ThreadingHTTPServer(('127.0.0.1',0),server.make_handler(self.db,self.site,'x'*40))
        self.thread=threading.Thread(target=self.http.serve_forever,daemon=True); self.thread.start()
        self.base='http://127.0.0.1:'+str(self.http.server_port)
    def tearDown(self):
        self.http.shutdown(); self.http.server_close(); self.thread.join(); self.temp.cleanup()
    def request(self,path,method='GET',body=None,auth=False):
        headers={'Content-Type':'application/json'}
        if auth: headers['Authorization']='Bearer '+'x'*40
        req=urllib.request.Request(self.base+path,data=None if body is None else json.dumps(body).encode(),method=method,headers=headers)
        try: response=urllib.request.urlopen(req)
        except urllib.error.HTTPError as error: response=error
        with response: return response.status,response.headers,response.read()
    def video(self): return {'title':'Family story','imageUrl':'https://media.example/cover.jpg','videoUrl':'https://media.example/story.mp4'}
    def test_empty_catalog_and_static_home(self):
        code,headers,body=self.request('/videos.json')
        self.assertEqual(code,200); self.assertEqual(json.loads(body),{'videos':[]}); self.assertEqual(headers['Cache-Control'],'no-store')
        self.assertEqual(self.request('/')[2],b'Hareer TV')
    def test_auth_required(self):
        self.assertEqual(self.request('/api/admin/videos')[0],401)
        self.assertEqual(self.request('/api/admin/videos','POST',self.video())[0],401)
    def test_add_update_delete_and_persistence(self):
        code,_,body=self.request('/api/admin/videos','POST',self.video(),True); self.assertEqual(code,201)
        vid=json.loads(body)['id']; self.assertEqual(vid,1)
        with server.connect(self.db) as db: self.assertEqual(db.execute('SELECT count(*) FROM videos').fetchone()[0],1)
        public=json.loads(self.request('/videos.json')[2]); self.assertNotIn('id',public['videos'][0])
        updated=self.video(); updated['title']='A new title'
        self.assertEqual(self.request('/api/admin/videos/1','PUT',updated,True)[0],200)
        self.assertEqual(json.loads(self.request('/videos.json')[2])['videos'][0]['title'],'A new title')
        self.assertEqual(self.request('/api/admin/videos/1','DELETE',auth=True)[0],200)
        self.assertEqual(json.loads(self.request('/videos.json')[2]),{'videos':[]})
        self.assertEqual(self.request('/api/admin/videos/1','DELETE',auth=True)[0],404)
    def test_rejects_invalid_media(self):
        for url in ['http://media.example/a.mp4','file:///etc/passwd','https://youtube.com/watch?v=abcd','https://user:pass@media.example/video.mp4']:
            body=self.video(); body['videoUrl']=url
            self.assertEqual(self.request('/api/admin/videos','POST',body,True)[0],400)
        self.assertEqual(json.loads(self.request('/videos.json')[2]),{'videos':[]})
    def test_private_paths_not_served(self):
        for path in ['/../catalog.sqlite3','/%2e%2e/catalog.sqlite3','/.env','/assets/../index.html','/backend/server.py']:
            self.assertEqual(self.request(path)[0],404)
    def test_catalog_limit(self):
        with server.connect(self.db) as db:
            db.executemany('INSERT INTO videos(title,image_url,video_url) VALUES(?,?,?)',[('story','https://a.example/a.jpg','https://a.example/a.mp4')]*300)
        self.assertEqual(self.request('/api/admin/videos','POST',self.video(),True)[0],409)
    def test_import_routes_require_auth_and_configuration(self):
        self.assertEqual(self.request('/api/admin/imports')[0],401)
        self.assertEqual(self.request('/api/admin/imports','POST',{'urls':['https://youtu.be/4mQGIyPD0Qs']})[0],401)
        code,_,body=self.request('/api/admin/imports',auth=True)
        self.assertEqual(code,200);self.assertFalse(json.loads(body)['enabled'])
        self.assertEqual(self.request('/api/admin/imports','POST',{'urls':['https://youtu.be/4mQGIyPD0Qs']},True)[0],503)
    def test_health_and_head(self):
        self.assertEqual(self.request('/healthz')[0],200)
        code,headers,body=self.request('/videos.json','HEAD'); self.assertEqual(code,200); self.assertEqual(body,b'')

if __name__=='__main__': unittest.main()
