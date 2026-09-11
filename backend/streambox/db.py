from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from .config import DATABASE_URL, DB_PATH


SCHEMA = """
CREATE TABLE IF NOT EXISTS upload_sessions (
    id TEXT PRIMARY KEY,
    video_id TEXT NOT NULL,
    original_filename TEXT NOT NULL,
    content_type TEXT,
    size_bytes INTEGER NOT NULL,
    temporary_storage_key TEXT NOT NULL,
    original_storage_key TEXT NOT NULL,
    playback_storage_key TEXT NOT NULL,
    status TEXT NOT NULL,
    error_message TEXT,
    created_at TEXT NOT NULL,
    uploaded_at TEXT,
    completed_at TEXT,
    expires_at TEXT NOT NULL,
    multipart_upload_id TEXT,
    multipart_part_size INTEGER
);

CREATE TABLE IF NOT EXISTS videos (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    original_filename TEXT NOT NULL,
    original_storage_key TEXT NOT NULL,
    playback_storage_key TEXT,
    source_b2_key TEXT,
    playback_b2_key TEXT,
    size_bytes INTEGER NOT NULL,
    uploaded_at TEXT NOT NULL,
    processing_status TEXT NOT NULL,
    processing_stage TEXT,
    error_message TEXT,
    video_codec TEXT,
    audio_codec TEXT,
    container TEXT,
    width INTEGER,
    height INTEGER,
    duration REAL,
    has_audio INTEGER NOT NULL DEFAULT 0,
    playback_mime_type TEXT,
    is_current INTEGER NOT NULL DEFAULT 0,
    uploaded_source_key TEXT,
    previous_video_id TEXT,
    source_metadata TEXT,
    playback_metadata TEXT
);

CREATE TABLE IF NOT EXISTS processing_jobs (
    id TEXT PRIMARY KEY,
    video_id TEXT NOT NULL,
    status TEXT NOT NULL,
    stage TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    error_message TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    heartbeat_at TEXT,
    locked_by TEXT,
    force_transcode INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_processing_jobs_video_id ON processing_jobs (video_id);
CREATE INDEX IF NOT EXISTS idx_processing_jobs_status ON processing_jobs (status);
CREATE INDEX IF NOT EXISTS idx_videos_processing_status ON videos (processing_status);
CREATE INDEX IF NOT EXISTS idx_videos_is_current ON videos (is_current);
"""


class _PGConnectionWrapper:
    """Drop-in replacement for sqlite3.Connection's execute API using psycopg2.

    app.py calls ``connection.execute(sql, params).fetchone()`` and similar
    chained patterns everywhere.  sqlite3's ``Connection.execute()`` returns a
    cursor; psycopg2's ``Connection`` has no such shortcut and its
    ``Cursor.execute()`` returns ``None``.  This wrapper bridges the gap by
    returning the cursor from ``execute()`` so that ``.fetchone()``,
    ``.fetchall()`` and ``.rowcount`` work identically to SQLite.

    Placeholder translation (``?`` → ``%s``) is handled here so that app.py
    keeps the same SQL literals for both backends.
    """

    def __init__(self, conn, cursor_factory):
        self._conn = conn
        self._cursor_factory = cursor_factory

    def execute(self, sql, params=None):
        cursor = self._conn.cursor(cursor_factory=self._cursor_factory)
        cursor.execute(sql.replace('?', '%s'), params)
        return cursor

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        self._conn.close()


def _connect_pg():
    import psycopg2
    import psycopg2.extras

    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = False
    return _PGConnectionWrapper(conn, psycopg2.extras.RealDictCursor)


def _connect_sqlite() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH, timeout=30.0)
    connection.row_factory = sqlite3.Row
    connection.execute('PRAGMA foreign_keys = ON')
    try:
        connection.execute('PRAGMA journal_mode = WAL')
    except Exception:
        pass
    return connection


def _connect():
    if DATABASE_URL:
        return _connect_pg()
    return _connect_sqlite()


@contextmanager
def get_db() -> Iterator:
    connection = _connect()
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def init_db() -> None:
    if not DATABASE_URL:
        Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)

    with get_db() as connection:
        if DATABASE_URL:
            # psycopg2 handles multi-statement strings in a single execute().
            connection.execute(SCHEMA)
            # Idempotent column additions for existing PostgreSQL installations
            for table, column, col_type in (
                ('upload_sessions', 'multipart_upload_id', 'TEXT'),
                ('upload_sessions', 'multipart_part_size', 'INTEGER'),
                ('videos', 'source_b2_key', 'TEXT'),
                ('videos', 'playback_b2_key', 'TEXT'),
                ('videos', 'processing_stage', 'TEXT'),
                ('videos', 'source_metadata', 'TEXT'),
                ('videos', 'playback_metadata', 'TEXT'),
                ('processing_jobs', 'heartbeat_at', 'TEXT'),
                ('processing_jobs', 'locked_by', 'TEXT'),
                ('processing_jobs', 'force_transcode', 'INTEGER DEFAULT 0'),
            ):
                connection.execute(f'ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {col_type}')
        else:
            # SQLite requires executescript() for multi-statement strings.
            connection.executescript(SCHEMA)
            # Idempotent column migrations for existing SQLite installations
            def _migrate_sqlite_columns(table_name: str, cols: list[tuple[str, str]]):
                existing_cols = {row['name'] for row in connection.execute(f'PRAGMA table_info({table_name})')}
                for name, definition in cols:
                    if name not in existing_cols:
                        connection.execute(f'ALTER TABLE {table_name} ADD COLUMN {name} {definition}')

            _migrate_sqlite_columns('upload_sessions', [
                ('multipart_upload_id', 'TEXT'),
                ('multipart_part_size', 'INTEGER'),
            ])
            _migrate_sqlite_columns('videos', [
                ('source_b2_key', 'TEXT'),
                ('playback_b2_key', 'TEXT'),
                ('processing_stage', 'TEXT'),
                ('source_metadata', 'TEXT'),
                ('playback_metadata', 'TEXT'),
            ])
            _migrate_sqlite_columns('processing_jobs', [
                ('heartbeat_at', 'TEXT'),
                ('locked_by', 'TEXT'),
                ('force_transcode', 'INTEGER DEFAULT 0'),
            ])


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

