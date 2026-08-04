from __future__ import annotations

import hashlib
import hmac
import os
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from flask import redirect
from flask import Flask, jsonify, request, send_file, session
from flask_cors import CORS
from werkzeug.security import check_password_hash

from streambox.config import (
    ADMIN_PASSWORD_HASH,
    ADMIN_USERNAME,
    APP_HOST,
    APP_PORT,
    API_ALLOWED_ORIGIN,
    DEBUG,
    MAX_UPLOAD_BYTES,
    SECRET_KEY,
    SESSION_COOKIE_NAME,
    SIGNED_URL_TTL_SECONDS,
    STORAGE_BACKEND,
    UPLOAD_SESSION_TTL_SECONDS,
)
from streambox.db import get_db, init_db, utcnow_iso
from streambox.media import MediaProcessingError, MediaValidationError, probe_media, transcode_for_browser
from streambox.storage import get_storage_backend

app = Flask(__name__)
app.config.update(
    SECRET_KEY=SECRET_KEY,
    SESSION_COOKIE_NAME=SESSION_COOKIE_NAME,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='None',
    SESSION_COOKIE_SECURE=os.getenv('SESSION_COOKIE_SECURE', '0') == '1',
    MAX_CONTENT_LENGTH=MAX_UPLOAD_BYTES,
)

CORS(app, supports_credentials=True, origins=[API_ALLOWED_ORIGIN])

storage = get_storage_backend()
init_db()


def _json_error(message: str, status_code: int):
    return jsonify({'ok': False, 'error': message}), status_code


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _require_auth():
    if not session.get('authenticated'):
        return _json_error('Authentication required.', 401)
    return None


def _sanitize_title(filename: str) -> str:
    return Path(filename).stem or 'Untitled video'


def _signed_token(video_id: str, storage_key: str, expires_at: datetime) -> str:
    payload = f'{video_id}:{storage_key}:{int(expires_at.timestamp())}'
    signature = hmac.new(SECRET_KEY.encode('utf-8'), payload.encode('utf-8'), hashlib.sha256).hexdigest()
    return f'{payload}:{signature}'


def _parse_signed_token(token: str) -> dict | None:
    parts = token.split(':')
    if len(parts) < 4:
        return None
    video_id, storage_key, expires_ts, signature = parts[0], parts[1], parts[2], parts[3]
    payload = f'{video_id}:{storage_key}:{expires_ts}'
    expected = hmac.new(SECRET_KEY.encode('utf-8'), payload.encode('utf-8'), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        return None
    try:
        expires_at = datetime.fromtimestamp(int(expires_ts), tz=timezone.utc)
    except ValueError:
        return None
    if expires_at < _now():
        return None
    return {'video_id': video_id, 'storage_key': storage_key}


def _video_to_payload(row):
    if row is None:
        return None
    playback_url = None
    if row['processing_status'] == 'ready' and row['playback_storage_key']:
        expires_at = _now() + timedelta(seconds=SIGNED_URL_TTL_SECONDS)
        playback_url = f'/api/video/playback/{_signed_token(row["id"], row["playback_storage_key"], expires_at)}'
    return {
        'id': row['id'],
        'title': row['title'],
        'original_filename': row['original_filename'],
        'original_storage_key': row['original_storage_key'],
        'playback_storage_key': row['playback_storage_key'],
        'size_bytes': row['size_bytes'],
        'uploaded_at': row['uploaded_at'],
        'processing_status': row['processing_status'],
        'video_codec': row['video_codec'],
        'audio_codec': row['audio_codec'],
        'container': row['container'],
        'width': row['width'],
        'height': row['height'],
        'duration': row['duration'],
        'has_audio': bool(row['has_audio']),
        'playback_url': playback_url,
    }


def _get_current_ready_video(connection):
    return connection.execute(
        'SELECT * FROM videos WHERE is_current = 1 AND processing_status = ? ORDER BY uploaded_at DESC LIMIT 1',
        ('ready',),
    ).fetchone()


def _get_visible_video(connection):
    current = _get_current_ready_video(connection)
    if current:
        return current
    return connection.execute('SELECT * FROM videos ORDER BY uploaded_at DESC LIMIT 1').fetchone()


def _delete_video_assets(video_row):
    if not video_row:
        return
    for storage_key in (video_row['original_storage_key'], video_row['playback_storage_key']):
        if storage_key:
            storage.delete(storage_key)


def _finalize_new_video(video_id: str):
    with get_db() as connection:
        row = connection.execute('SELECT * FROM videos WHERE id = ?', (video_id,)).fetchone()
        if not row or row['processing_status'] != 'processing':
            return

        try:
            original_path = storage.read_path(row['original_storage_key'])
            probe = probe_media(original_path)

            playback_path = storage.path_for_key(row['playback_storage_key'])
            transcode_for_browser(original_path, playback_path, probe)
            storage.copy_path(playback_path, row['playback_storage_key'])

            if STORAGE_BACKEND == 'b2':
                original_path.unlink(missing_ok=True)
                playback_path.unlink(missing_ok=True)

            previous_current = _get_current_ready_video(connection)

            connection.execute(
                'UPDATE videos SET processing_status = ?, video_codec = ?, audio_codec = ?, container = ?, width = ?, height = ?, duration = ?, has_audio = ?, playback_mime_type = ? WHERE id = ?',
                (
                    'ready',
                    probe.video_codec,
                    probe.audio_codec,
                    probe.container,
                    probe.width,
                    probe.height,
                    probe.duration,
                    1 if probe.has_audio else 0,
                    'video/mp4',
                    video_id,
                ),
            )
            connection.execute('UPDATE videos SET is_current = 0 WHERE id != ?', (video_id,))
            connection.execute('UPDATE videos SET is_current = 1 WHERE id = ?', (video_id,))

            if previous_current and previous_current['id'] != video_id:
                _delete_video_assets(previous_current)
                connection.execute('DELETE FROM videos WHERE id = ?', (previous_current['id'],))

        except (MediaValidationError, MediaProcessingError) as exc:
            connection.execute(
                'UPDATE videos SET processing_status = ?, error_message = ? WHERE id = ?',
                ('failed', str(exc), video_id),
            )
        except Exception:
            connection.execute(
                'UPDATE videos SET processing_status = ?, error_message = ? WHERE id = ?',
                ('failed', 'Video processing failed.', video_id),
            )


def _launch_processing(video_id: str):
    thread = threading.Thread(target=_finalize_new_video, args=(video_id,), daemon=True)
    thread.start()


@app.post('/api/auth/login')
def login():
    payload = request.get_json(silent=True) or {}
    username = payload.get('username', '')
    password = payload.get('password', '')

    if not username or not password:
        return _json_error('Username and password are required.', 400)
    if username != ADMIN_USERNAME or not ADMIN_PASSWORD_HASH or not check_password_hash(ADMIN_PASSWORD_HASH, password):
        return _json_error('Incorrect username or password.', 401)

    session.clear()
    session['authenticated'] = True
    session['username'] = username
    return jsonify({'ok': True, 'user': {'username': username}})


@app.post('/api/auth/logout')
def logout():
    session.clear()
    return jsonify({'ok': True})


@app.get('/api/auth/status')
def auth_status():
    return jsonify({'ok': True, 'authenticated': bool(session.get('authenticated')), 'user': session.get('username')})


@app.get('/api/video/current')
def current_video():
    error = _require_auth()
    if error:
        return error

    with get_db() as connection:
        row = _get_visible_video(connection)
    if not row:
        return jsonify({'ok': True, 'video': None})
    return jsonify({'ok': True, 'video': _video_to_payload(row)})


@app.post('/api/video/upload/init')
def upload_init():
    error = _require_auth()
    if error:
        return error

    payload = request.get_json(silent=True) or {}
    filename = payload.get('filename', '')
    size_bytes = int(payload.get('size_bytes') or 0)
    content_type = payload.get('content_type') or None

    if not filename:
        return _json_error('A filename is required.', 400)
    if size_bytes <= 0:
        return _json_error('A valid file size is required.', 400)
    if size_bytes > MAX_UPLOAD_BYTES:
        return _json_error('This file exceeds the 1.5 GB maximum upload size.', 400)

    upload_session_id = uuid.uuid4().hex
    video_id = uuid.uuid4().hex
    temp_key = f'tmp/{upload_session_id}.upload'
    original_key = f'videos/{video_id}/source'
    playback_key = f'videos/{video_id}/playback.mp4'
    expires_at = _now() + timedelta(seconds=UPLOAD_SESSION_TTL_SECONDS)

    with get_db() as connection:
        connection.execute(
            'INSERT INTO upload_sessions (id, video_id, original_filename, content_type, size_bytes, temporary_storage_key, original_storage_key, playback_storage_key, status, created_at, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
            (
                upload_session_id,
                video_id,
                filename,
                content_type,
                size_bytes,
                temp_key,
                original_key,
                playback_key,
                'uploading',
                utcnow_iso(),
                expires_at.isoformat(),
            ),
        )

    return jsonify(
        {
            'ok': True,
            'upload_session_id': upload_session_id,
            'upload_url': f'/api/video/upload/{upload_session_id}',
            'temporary_storage_key': temp_key,
            'original_storage_key': original_key,
            'playback_storage_key': playback_key,
            'expires_at': expires_at.isoformat(),
            'max_bytes': MAX_UPLOAD_BYTES,
        }
    )


@app.post('/api/video/upload/<upload_session_id>')
def upload_file(upload_session_id: str):
    error = _require_auth()
    if error:
        return error

    with get_db() as connection:
        upload_session = connection.execute('SELECT * FROM upload_sessions WHERE id = ?', (upload_session_id,)).fetchone()
    if not upload_session:
        return _json_error('Upload session not found.', 404)
    if upload_session['status'] != 'uploading':
        return _json_error('Upload session is no longer accepting data.', 409)

    temp_path = storage.path_for_key(upload_session['temporary_storage_key'])
    bytes_written = 0
    try:
        with temp_path.open('wb') as target:
            while True:
                chunk = request.stream.read(1024 * 1024)
                if not chunk:
                    break
                bytes_written += len(chunk)
                if bytes_written > MAX_UPLOAD_BYTES:
                    raise ValueError('This file exceeds the 1.5 GB maximum upload size.')
                target.write(chunk)
    except ValueError as exc:
        temp_path.unlink(missing_ok=True)
        return _json_error(str(exc), 400)

    storage.copy_path(temp_path, upload_session['original_storage_key'])
    temp_path.unlink(missing_ok=True)

    with get_db() as connection:
        connection.execute(
            'INSERT INTO videos (id, title, original_filename, original_storage_key, playback_storage_key, size_bytes, uploaded_at, processing_status, video_codec, audio_codec, container, width, height, duration, has_audio, playback_mime_type, is_current, uploaded_source_key, previous_video_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
            (
                upload_session['video_id'],
                _sanitize_title(upload_session['original_filename']),
                upload_session['original_filename'],
                upload_session['original_storage_key'],
                upload_session['playback_storage_key'],
                upload_session['size_bytes'],
                utcnow_iso(),
                'processing',
                None,
                None,
                None,
                None,
                None,
                None,
                0,
                'video/mp4',
                0,
                upload_session['temporary_storage_key'],
                None,
            ),
        )
        connection.execute(
            'UPDATE upload_sessions SET status = ?, uploaded_at = ?, completed_at = ? WHERE id = ?',
            ('uploaded', utcnow_iso(), utcnow_iso(), upload_session_id),
        )

    _launch_processing(upload_session['video_id'])
    return jsonify({'ok': True, 'uploaded_bytes': bytes_written, 'video_id': upload_session['video_id']})


@app.post('/api/video/upload/complete')
def upload_complete():
    error = _require_auth()
    if error:
        return error

    payload = request.get_json(silent=True) or {}
    upload_session_id = payload.get('upload_session_id', '')
    if not upload_session_id:
        return _json_error('upload_session_id is required.', 400)

    with get_db() as connection:
        upload_session = connection.execute('SELECT * FROM upload_sessions WHERE id = ?', (upload_session_id,)).fetchone()
        if not upload_session:
            return _json_error('Upload session not found.', 404)
        video_row = connection.execute('SELECT * FROM videos WHERE id = ?', (upload_session['video_id'],)).fetchone()

    if not video_row:
        return jsonify({'ok': True, 'status': upload_session['status'], 'video': None})

    return jsonify({'ok': True, 'status': video_row['processing_status'], 'video': _video_to_payload(video_row)})


@app.delete('/api/video')
def delete_video():
    error = _require_auth()
    if error:
        return error

    with get_db() as connection:
        rows = connection.execute('SELECT * FROM videos').fetchall()
        upload_sessions = connection.execute('SELECT * FROM upload_sessions').fetchall()
        for row in rows:
            _delete_video_assets(row)
        connection.execute('DELETE FROM videos')
        connection.execute('DELETE FROM upload_sessions')
    for session_row in upload_sessions:
        storage.delete(session_row['temporary_storage_key'])
    return jsonify({'ok': True})


@app.get('/api/video/playback/<path:token>')
def playback(token: str):
    parsed = _parse_signed_token(token)
    if not parsed:
        return _json_error('Invalid or expired playback URL.', 403)

    if STORAGE_BACKEND == 'b2':
        if not storage.exists(parsed['storage_key']):
            return _json_error('Playback file not found.', 404)
        return redirect(storage.presigned_get_url(parsed['storage_key'], SIGNED_URL_TTL_SECONDS), code=302)

    path = storage.path_for_key(parsed['storage_key'])
    if not path.exists():
        return _json_error('Playback file not found.', 404)
    return send_file(path, mimetype='video/mp4', conditional=True)


@app.get('/api/health')
def health():
    return jsonify({'ok': True, 'storage_backend': STORAGE_BACKEND})


def main():
    init_db()
    app.run(host=APP_HOST, port=APP_PORT, debug=DEBUG)


if __name__ == '__main__':
    main()
