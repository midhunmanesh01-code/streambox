from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from .config import DB_PATH


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
    size_bytes INTEGER NOT NULL,
    uploaded_at TEXT NOT NULL,
    processing_status TEXT NOT NULL,
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
    previous_video_id TEXT
);
"""


def _connect() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute('PRAGMA foreign_keys = ON')
    return connection


@contextmanager
def get_db() -> Iterator[sqlite3.Connection]:
    connection = _connect()
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


def init_db() -> None:
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    with get_db() as connection:
        connection.executescript(SCHEMA)
        # Existing installations predate direct B2 multipart uploads. SQLite has
        # no ADD COLUMN IF NOT EXISTS, so make this migration explicitly idempotent.
        columns = {row['name'] for row in connection.execute('PRAGMA table_info(upload_sessions)')}
        for name, definition in (
            ('multipart_upload_id', 'TEXT'),
            ('multipart_part_size', 'INTEGER'),
        ):
            if name not in columns:
                connection.execute(f'ALTER TABLE upload_sessions ADD COLUMN {name} {definition}')


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
