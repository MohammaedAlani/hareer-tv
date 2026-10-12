#!/usr/bin/env python3
"""Hareer TV catalog + static website. TLS is terminated by the ingress."""
from contextlib import contextmanager
import hmac
import json
import os
from pathlib import Path
import re
import sqlite3
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit, unquote


@contextmanager
def connect(database):
    connection = sqlite3.connect(database, timeout=5)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def initialize(database):
    Path(database).parent.mkdir(parents=True, exist_ok=True)
    with connect(database) as connection:
        connection.execute('CREATE TABLE IF NOT EXISTS videos (id INTEGER PRIMARY KEY, title TEXT NOT NULL, image_url TEXT NOT NULL, video_url TEXT NOT NULL)')


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


def make_handler(database, site, admin_token):
    site = Path(site).resolve()
    class Handler(SimpleHTTPRequestHandler):
        extensions_map = {**SimpleHTTPRequestHandler.extensions_map, '.apk': 'application/vnd.android.package-archive'}
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(site), **kwargs)

        def end_headers(self):
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
                decoded = unquote(path)
                allowed = decoded in ('/','/index.html','/styles.css','/app.js') or re.fullmatch(r'/(assets|downloads)/[a-zA-Z0-9_.-]+',decoded)
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
                        if method == 'DELETE': cursor = connection.execute('DELETE FROM videos WHERE id=?', (video_id,))
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
    handler = make_handler(database, os.environ.get('SITE_DIR',str(Path(__file__).resolve().parents[1]/'site')),token)
    server = ThreadingHTTPServer(('0.0.0.0', int(os.environ.get('PORT','8080'))),handler)
    print('Hareer TV listening on port '+str(server.server_port),flush=True)
    server.serve_forever()
