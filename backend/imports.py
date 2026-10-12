"""Persistent FIFO imports. One worker holds a filesystem lock for its lifetime."""
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from urllib.parse import urlsplit, parse_qs
import uuid
from backend.database import connect

ACTIVE = ('queued','downloading','uploading')
MAX_VIDEO_BYTES = 1024 * 1024 * 1024
MAX_SCRATCH_BYTES = 3 * MAX_VIDEO_BYTES

class ImportFailure(Exception): pass

def normalize_url(value):
    if not isinstance(value,str) or len(value)>2048: raise ValueError('Expected YouTube video links')
    parsed=urlsplit(value.strip())
    if parsed.scheme!='https' or parsed.username or parsed.password or parsed.port not in (None,443):
        raise ValueError('Use an HTTPS YouTube video link')
    host=(parsed.hostname or '').lower()
    if host=='youtu.be': video_id=parsed.path.strip('/')
    elif host in ('youtube.com','www.youtube.com','m.youtube.com','music.youtube.com'):
        if parsed.path=='/watch': video_id=parse_qs(parsed.query).get('v',[''])[0]
        else:
            match=re.fullmatch(r'/(?:shorts|embed)/([A-Za-z0-9_-]{11})/?',parsed.path)
            video_id=match.group(1) if match else ''
    else: raise ValueError('Only individual YouTube video links are supported')
    if not re.fullmatch(r'[A-Za-z0-9_-]{11}',video_id): raise ValueError('Use an individual YouTube video, not a channel or playlist')
    return video_id,'https://www.youtube.com/watch?v='+video_id

def jobs(database):
    with connect(database) as db:
        return [dict(row) for row in db.execute('SELECT * FROM imports ORDER BY id DESC LIMIT 500')]

def enqueue(database, urls):
    if not isinstance(urls,list) or not 1<=len(urls)<=50: raise ValueError('Submit between 1 and 50 video links')
    normalized=list(dict.fromkeys(normalize_url(value) for value in urls))
    now=int(time.time()); results=[]
    with connect(database) as db:
        db.execute('BEGIN IMMEDIATE')
        new=[entry for entry in normalized if not db.execute('SELECT 1 FROM imports WHERE youtube_id=?',(entry[0],)).fetchone()]
        pending=db.execute("SELECT COUNT(*) FROM imports WHERE status IN ('queued','downloading','uploading')").fetchone()[0]
        published=db.execute('SELECT COUNT(*) FROM videos').fetchone()[0]
        if pending+len(new)>200 or published+pending+len(new)>300:
            raise ValueError('Queue or catalog is full (200 queued / 300 catalog entries maximum)')
        for video_id,url in normalized:
            db.execute('INSERT OR IGNORE INTO imports(youtube_id,source_url,created_at,updated_at) VALUES(?,?,?,?)',(video_id,url,now,now))
            results.append(dict(db.execute('SELECT * FROM imports WHERE youtube_id=?',(video_id,)).fetchone()))
    return results

def retry(database, job_id):
    with connect(database) as db:
        db.execute('BEGIN IMMEDIATE')
        row=db.execute('SELECT * FROM imports WHERE id=?',(job_id,)).fetchone()
        if not row: raise ValueError('Import not found')
        removed=row['status']=='completed' and not db.execute('SELECT 1 FROM videos WHERE id=?',(row['video_id'],)).fetchone()
        if row['status']!='failed' and not removed: raise ValueError('Only failed or removed imports can be retried')
        pending=db.execute("SELECT COUNT(*) FROM imports WHERE status IN ('queued','downloading','uploading')").fetchone()[0]
        published=db.execute('SELECT COUNT(*) FROM videos').fetchone()[0]
        if pending>=200 or published+pending>=300: raise ValueError('Queue or catalog is full')
        db.execute("UPDATE imports SET status='queued',error='',updated_at=? WHERE id=?",(int(time.time()),job_id))

def run_command(args, directory, stop, timeout, failure):
    process=subprocess.Popen(args,cwd=directory,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
    started=time.monotonic()
    try:
        while True:
            if stop.is_set(): raise InterruptedError('Worker is stopping')
            if time.monotonic()-started>timeout: raise ImportFailure('Processing timed out; try a shorter video.')
            scratch_size = 0
            for path in directory.iterdir():
                try:
                    if path.is_file(): scratch_size += path.stat().st_size
                except FileNotFoundError: pass  # yt-dlp can rename fragments while we measure.
            if scratch_size>MAX_SCRATCH_BYTES:
                raise ImportFailure('Video exceeded the temporary storage limit.')
            try:
                result=process.wait(timeout=1)
                if result: raise ImportFailure(failure)
                return
            except subprocess.TimeoutExpired: pass
    finally:
        if process.poll() is None:
            os.killpg(process.pid,signal.SIGTERM)
            try: process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid,signal.SIGKILL); process.wait()

def download(job, directory, stop):
    run_command([sys.executable,'-m','yt_dlp','--ignore-config','--no-playlist','--no-progress','--no-warnings',
        '--no-cache-dir','--socket-timeout','30','--retries','2','--fragment-retries','2',
        '--concurrent-fragments','1','--max-filesize','1G','--write-info-json','--js-runtimes','node',
        '--match-filter','!is_live & !is_upcoming & duration <= 3600',
        '-f','bv*[height<=720][vcodec^=avc1]+ba[acodec^=mp4a]/b[height<=720][ext=mp4]/bv*[height<=720]+ba/b[height<=720]',
        '--merge-output-format','mp4','-o',str(directory/'source.%(ext)s'),'--',job['source_url']],
        directory,stop,1800,'YouTube could not provide this video. It may be unavailable, restricted, or require sign-in. No catalog entry was added.')
    info=directory/'source.info.json'
    if not info.exists(): raise ImportFailure('Video is live, too long, unavailable, or outside the supported limits.')
    metadata=json.loads(info.read_text())
    if metadata.get('id')!=job['youtube_id'] or metadata.get('_type') in ('playlist','multi_video'):
        raise ImportFailure('The source did not resolve to the requested video.')
    if not 0<float(metadata.get('duration') or 0)<=3600: raise ImportFailure('Only recorded videos up to 60 minutes are supported.')
    sources=[p for p in directory.glob('source.*') if p.suffix in ('.mp4','.mkv','.webm','.mov')]
    if len(sources)!=1: raise ImportFailure('The video download was incomplete.')
    if sources[0].stat().st_size>MAX_VIDEO_BYTES: raise ImportFailure('Video exceeds the 1 GiB limit.')
    # Normalize every input to H.264/AAC for Android TV, regardless of source codecs.
    video=directory/'video.mp4'; image=directory/'image.jpg'
    run_command(['ffmpeg','-nostdin','-y','-i',str(sources[0]),'-map','0:v:0','-map','0:a:0?',
        '-vf','scale=trunc(iw/2)*2:trunc(ih/2)*2','-c:v','libx264','-preset','veryfast','-crf','23','-threads','2',
        '-pix_fmt','yuv420p','-c:a','aac','-b:a','128k','-movflags','+faststart',str(video)],
        directory,stop,3600,'Video conversion failed. Try a different source.')
    if video.stat().st_size>MAX_VIDEO_BYTES: raise ImportFailure('Converted video exceeds the 1 GiB limit.')
    run_command(['ffmpeg','-nostdin','-y','-i',str(video),'-frames:v','1','-vf','scale=640:-2',str(image)],
        directory,stop,60,'Could not create a thumbnail.')
    return (str(metadata.get('title') or '').strip() or 'Video '+job['youtube_id'])[:200],video,image

class ImportWorker:
    def __init__(self,database,storage,downloader=download):
        self.database=database; self.storage=storage; self.downloader=downloader
        self.stop=threading.Event(); self.thread=None
        self.scratch=Path(database).parent/'import-work'
        self.scratch.mkdir(exist_ok=True)

    def start(self):
        self.thread=threading.Thread(target=self.run,name='video-imports',daemon=True);self.thread.start()

    def run(self):
        with open(str(self.database)+'.worker.lock','a') as lock:
            while not self.stop.is_set():
                try: fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);break
                except BlockingIOError: self.stop.wait(2)
            else: return
            # The exclusive lock proves no previous worker is still running.
            with connect(self.database) as db:
                db.execute("UPDATE imports SET status='queued',error='',updated_at=? WHERE status IN ('downloading','uploading')",(int(time.time()),))
            for path in self.scratch.glob('job-*'):
                if path.is_dir(): shutil.rmtree(path)
            while not self.stop.is_set():
                try:
                    if not self.process_one(): self.stop.wait(2)
                except Exception:
                    # Keep serving/retrying the queue after transient SQLite failures.
                    print('Import queue temporarily unavailable',flush=True);self.stop.wait(5)

    def process_one(self):
        with connect(self.database) as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute("SELECT * FROM imports WHERE status='queued' ORDER BY id LIMIT 1").fetchone()
            if row is None: return False
            job=dict(row)
            db.execute("UPDATE imports SET status='downloading',attempts=attempts+1,error='',updated_at=? WHERE id=?",(int(time.time()),job['id']))
        try:
            if shutil.disk_usage(self.scratch).free<4*MAX_VIDEO_BYTES:
                raise ImportFailure('Not enough temporary disk space. Free at least 4 GiB and retry.')
            with tempfile.TemporaryDirectory(prefix='job-',dir=self.scratch) as tmp:
                title,video,image=self.downloader(job,Path(tmp),self.stop)
                if self.stop.is_set(): raise InterruptedError()
                with connect(self.database) as db:
                    db.execute("UPDATE imports SET status='uploading',title=?,updated_at=? WHERE id=?",(title,int(time.time()),job['id']))
                prefix='hareer-tv/imports/'+str(job['id'])+'/'
                self.storage.upload(video,prefix+'video.mp4','video/mp4')
                if self.stop.is_set(): raise InterruptedError()
                self.storage.upload(image,prefix+'image.jpg','image/jpeg')
                if self.stop.is_set(): raise InterruptedError()
                video_media=uuid.uuid4().hex; image_media=uuid.uuid4().hex
                with connect(self.database) as db:
                    db.execute('BEGIN IMMEDIATE')
                    if db.execute('SELECT COUNT(*) FROM videos').fetchone()[0]>=300:
                        raise ImportFailure('Catalog is full. Remove a video and retry.')
                    result=db.execute('INSERT INTO videos(title,image_url,video_url) VALUES(?,?,?)',
                        (title,self.storage.base_url+'/media/'+image_media,self.storage.base_url+'/media/'+video_media))
                    db.executemany('INSERT INTO media(id,object_key,video_id) VALUES(?,?,?)',
                        [(video_media,prefix+'video.mp4',result.lastrowid),(image_media,prefix+'image.jpg',result.lastrowid)])
                    db.execute("UPDATE imports SET status='completed',title=?,video_id=?,error='',updated_at=? WHERE id=?",(title,result.lastrowid,int(time.time()),job['id']))
        except InterruptedError:
            with connect(self.database) as db:
                db.execute("UPDATE imports SET status='queued',updated_at=? WHERE id=?",(int(time.time()),job['id']))
        except Exception as error:
            message=str(error) if isinstance(error,ImportFailure) else 'Processing or storage failed. Check worker configuration and S3 permissions, then retry.'
            with connect(self.database) as db:
                db.execute("UPDATE imports SET status='failed',error=?,updated_at=? WHERE id=?",(message,int(time.time()),job['id']))
        return True
