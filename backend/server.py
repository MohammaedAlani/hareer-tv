#!/usr/bin/env python3
"""Hareer TV catalog + static website. TLS is terminated by the ingress."""
import hmac
import json
import os
from pathlib import Path
import re
import sqlite3
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit, unquote
from backend.database import connect, initialize
from backend import imports


def validate_video(value):
    if not isinstance(value, dict):
        raise ValueError('Expected a JSON object')
    title = value.get('title')
    if not isinstance(title, str) or not 1 <= len(title.strip()) <= 200:
        raise ValueError('title must contain 1–200 characters')
    values = [title.strip()]
    for field in ('imageUrl', 'videoUrl'):
        url = value.get(field)
        if not isinstance(url, str) or len(url.encode('utf-8')) > 1024 or any(c.isspace() for c in url):
            raise ValueError(field + ' must be an HTTPS URL')
        parsed = urlsplit(url)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
            raise ValueError(field + ' must be an HTTPS URL without embedded credentials or fragments')
        if field == 'videoUrl' and (parsed.hostname in ('youtube.com', 'youtu.be') or parsed.hostname.endswith('.youtube.com')):
            raise ValueError('Use a stored video URL, not a YouTube page')
        values.append(url)
    return tuple(values)


def make_handler(database, site, admin_token, storage=None):
    site = Path(site).resolve()
    class Handler(SimpleHTTPRequestHandler):
        extensions_map = {**SimpleHTTPRequestHandler.extensions_map, '.apk': 'application/vnd.android.package-archive'}
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(site), **kwargs)

        def end_headers(self):
            if urlsplit(getattr(self,'path','')).path.startswith('/admin') or urlsplit(getattr(self,'path','')).path == '/downloads/update.json':
                self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'strict-origin-when-cross-origin')
            self.send_header('X-Frame-Options', 'DENY')
            self.send_header('Content-Security-Policy', "default-src 'self'; img-src 'self'; style-src 'self'; script-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'")
            super().end_headers()

        def send_json(self, status, value, head=False):
            body = json.dumps(value, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            if not head: self.wfile.write(body)

        def authorized(self):
            supplied = self.headers.get('Authorization', '').encode()
            if not hmac.compare_digest(supplied, ('Bearer '+admin_token).encode()):
                self.send_json(401, {'error': 'Unauthorized'})
                return False
            return True

        def catalog(self, admin=False):
            with connect(database) as connection:
                rows = connection.execute('SELECT id, title, image_url AS imageUrl, video_url AS videoUrl FROM videos ORDER BY id').fetchall()
            return {'videos': [{key: row[key] for key in (('id','title','imageUrl','videoUrl') if admin else ('title','imageUrl','videoUrl'))} for row in rows]}

        def do_GET(self): self.get_route(False)
        def do_HEAD(self): self.get_route(True)
        def get_route(self, head):
            path = urlsplit(self.path).path
            try:
                if path == '/healthz':
                    with connect(database) as connection: connection.execute('SELECT 1 FROM videos LIMIT 1')
                    return self.send_json(200, {'status': 'ok'}, head)
                if path == '/videos.json': return self.send_json(200, self.catalog(), head)
                if path == '/api/admin/videos':
                    if self.authorized(): self.send_json(200, self.catalog(True), head)
                    return
                if path == '/api/admin/imports':
                    if self.authorized(): self.send_json(200, {'enabled': storage is not None, 'jobs': imports.jobs(database)}, head)
                    return
                media = re.fullmatch(r'/media/([0-9a-f]{32})', path)
                if media:
                    if storage is None: return self.send_json(503, {'error': 'Media storage is not configured'}, head)
                    with connect(database) as db:
                        row = db.execute('SELECT m.object_key FROM media m JOIN videos v ON v.id=m.video_id WHERE m.id=? AND (v.video_url=? OR v.image_url=?)',
                            (media.group(1), storage.base_url+path, storage.base_url+path)).fetchone()
                    if row is None: return self.send_error(404)
                    try: destination = storage.signed_url(row['object_key'])
                    except Exception: return self.send_json(503, {'error': 'Media temporarily unavailable'}, head)
                    self.send_response(302)
                    self.send_header('Location', destination)
                    self.send_header('Cache-Control', 'no-store')
                    self.send_header('Content-Length', '0')
                    self.end_headers()
                    return
                if path in ('/admin','/admin/'):
                    self.path = '/admin/index.html'
                    if head: super().do_HEAD()
                    else: super().do_GET()
                    return
                decoded = unquote(path)
                allowed = decoded in ('/','/index.html','/styles.css','/app.js','/admin/admin.js','/admin/admin.css') or re.fullmatch(r'/(assets|downloads)/[a-zA-Z0-9_.-]+',decoded)
                if not allowed: return self.send_error(404)
                self.path = path
                if head: super().do_HEAD()
                else: super().do_GET()
            except sqlite3.Error:
                self.send_json(503, {'error': 'Catalog temporarily unavailable'}, head)

        def list_directory(self, path):
            self.send_error(404)
            return None

        def do_POST(self): self.mutate('POST')
        def do_PUT(self): self.mutate('PUT')
        def do_DELETE(self): self.mutate('DELETE')
        def mutate(self, method):
            path = urlsplit(self.path).path
            if method == 'POST' and (path == '/api/admin/imports' or re.fullmatch(r'/api/admin/imports/[1-9][0-9]*/retry',path)):
                if not self.authorized(): return
                if storage is None: return self.send_json(503, {'error': 'Set the S3 environment variables and PUBLIC_BASE_URL to enable imports.'})
                try:
                    if path.endswith('/retry'):
                        imports.retry(database,int(path.split('/')[-2]))
                        return self.send_json(202, {'status': 'queued'})
                    if self.headers.get_content_type() != 'application/json': return self.send_json(415, {'error': 'Use application/json'})
                    size = int(self.headers.get('Content-Length','0'))
                    if not 1 <= size <= 32768: return self.send_json(413, {'error': 'Request is too large or empty'})
                    body = json.loads(self.rfile.read(size))
                    if not isinstance(body,dict): raise ValueError('Expected a JSON object')
                    result = imports.enqueue(database,body.get('urls'))
                    return self.send_json(202, {'jobs': result})
                except (ValueError,TypeError,OverflowError):
                    return self.send_json(400, {'error': 'Invalid request, queue full, or job cannot be retried. Use 1–50 HTTPS YouTube video links.'})
                except sqlite3.Error:
                    return self.send_json(503, {'error': 'Queue temporarily unavailable'})
            match = re.fullmatch(r'/api/admin/videos/([1-9][0-9]*)', path)
            if not ((method == 'POST' and path == '/api/admin/videos') or (method in ('PUT','DELETE') and match)):
                return self.send_json(404, {'error': 'Not found'})
            if not self.authorized(): return
            try:
                values = None
                if method != 'DELETE':
                    if self.headers.get_content_type() != 'application/json':
                        return self.send_json(415, {'error': 'Use application/json'})
                    size = int(self.headers.get('Content-Length', '0'))
                    if not 1 <= size <= 32768:
                        return self.send_json(413, {'error': 'JSON body must be 1–32768 bytes'})
                    values = validate_video(json.loads(self.rfile.read(size)))
                with connect(database) as connection:
                    # Serialize count + insert so concurrent writers cannot exceed the app limit.
                    connection.execute('BEGIN IMMEDIATE')
                    if method == 'POST':
                        if connection.execute('SELECT COUNT(*) FROM videos').fetchone()[0] >= 300:
                            return self.send_json(409, {'error': 'Catalog is limited to 300 videos'})
                        cursor = connection.execute('INSERT INTO videos(title,image_url,video_url) VALUES (?,?,?)', values)
                        result = {'id': cursor.lastrowid}
                    else:
                        video_id = int(match.group(1))
                        if method == 'DELETE':
                            connection.execute('DELETE FROM media WHERE video_id=?', (video_id,))
                            cursor = connection.execute('DELETE FROM videos WHERE id=?', (video_id,))
                        else: cursor = connection.execute('UPDATE videos SET title=?,image_url=?,video_url=? WHERE id=?', (*values,video_id))
                        if cursor.rowcount == 0: return self.send_json(404, {'error': 'Video not found'})
                        result = {'id': video_id, 'deleted': method == 'DELETE'}
                self.send_json(201 if method == 'POST' else 200, result)
            except (ValueError, TypeError, json.JSONDecodeError):
                self.send_json(400, {'error': 'Invalid video. Provide title (1–200 characters), imageUrl, and stored videoUrl as HTTPS URLs.'})
            except sqlite3.Error:
                self.send_json(503, {'error': 'Catalog temporarily unavailable'})

        def setup(self):
            super().setup()
            self.connection.settimeout(20)

        def log_message(self, format, *args):
            # Do not log query strings, authorization headers, or request bodies.
            print(json.dumps({'method': self.command, 'path': urlsplit(getattr(self,'path','')).path}), flush=True)

    return Handler


if __name__ == '__main__':
    token = os.environ.get('ADMIN_TOKEN','').strip()
    if len(token) < 32: raise SystemExit('ADMIN_TOKEN must be at least 32 characters')
    database = os.environ.get('DATABASE_PATH','/data/hareer.sqlite3')
    initialize(database)
    from backend.storage import Storage, configured
    storage = None
    if configured():
        try: storage = Storage()
        except Exception: print('Invalid S3 configuration; imports disabled',flush=True)
    worker = imports.ImportWorker(database,storage) if storage is not None else None
    if worker: worker.start()
    handler = make_handler(database, os.environ.get('SITE_DIR',str(Path(__file__).resolve().parents[1]/'site')),token,storage)
    server = ThreadingHTTPServer(('0.0.0.0', int(os.environ.get('PORT','8080'))),handler)
    print('Hareer TV listening on port '+str(server.server_port),flush=True)
    import signal
    import threading
    def shutdown(signum, frame):
        if worker: worker.stop.set()
        threading.Thread(target=server.shutdown,daemon=True).start()
    signal.signal(signal.SIGTERM,shutdown)
    signal.signal(signal.SIGINT,shutdown)
    try: server.serve_forever()
    finally:
        server.server_close()
        if worker:
            worker.stop.set()
            worker.thread.join(timeout=20)
