"""Short-lived SQLite transactions shared by the API and single import worker."""
from contextlib import contextmanager
from pathlib import Path
import sqlite3

@contextmanager
def connect(database):
    connection = sqlite3.connect(database, timeout=10)
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
    with connect(database) as db:
        db.execute('CREATE TABLE IF NOT EXISTS videos (id INTEGER PRIMARY KEY, title TEXT NOT NULL, image_url TEXT NOT NULL, video_url TEXT NOT NULL)')
        db.execute('''CREATE TABLE IF NOT EXISTS imports (
            id INTEGER PRIMARY KEY AUTOINCREMENT, youtube_id TEXT UNIQUE NOT NULL,
            source_url TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'queued',
            title TEXT NOT NULL DEFAULT '', error TEXT NOT NULL DEFAULT '',
            attempts INTEGER NOT NULL DEFAULT 0, video_id INTEGER,
            created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL)''')
        db.execute('''CREATE TABLE IF NOT EXISTS media (
            id TEXT PRIMARY KEY, object_key TEXT UNIQUE NOT NULL, video_id INTEGER NOT NULL)''')
