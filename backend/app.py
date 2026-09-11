from __future__ import annotations

import json
import hashlib
import hmac
import os
import shutil
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
    B2_MULTIPART_PART_SIZE_BYTES,
    B2_MULTIPART_URL_BATCH_SIZE,
    B2_MULTIPART_URL_TTL_SECONDS,
    DEBUG,
    MAX_UPLOAD_BYTES,
    SECRET_KEY,
    SESSION_COOKIE_NAME,
    SIGNED_URL_TTL_SECONDS,
    STORAGE_BACKEND,
    TEMP_DIR,
    UPLOAD_SESSION_TTL_SECONDS,
)
from streambox.db import get_db, init_db, utcnow_iso
from streambox.media import (
    MediaProcessingError,
    MediaValidationError,
    probe_media,
    verify_playback_asset,
)
from streambox.storage import get_storage_backend
from streambox.worker import (
    StreamBoxWorker,
    cleanup_abandoned_upload_sessions,
    enqueue_processing_job,
    recover_stale_jobs,
)

app = Flask(__name__)
app.config.update(
    SECRET_KEY=SECRET_KEY,
    SESSION_COOKIE_NAME=SESSION_COOKIE_NAME,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    SESSION_COOKIE_SECURE=os.getenv('SESSION_COOKIE_SECURE', '0' if DEBUG else '1') == '1',
    MAX_CONTENT_LENGTH=MAX_UPLOAD_BYTES,
)

CORS(app, supports_credentials=True, origins=[API_ALLOWED_ORIGIN])

storage = get_storage_backend()
init_db()

CURRENT_VIDEO_MANIFEST_KEY = 'streambox/current.json'


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
    r = dict(row)
    playback_url = None
    playback_key = r.get('playback_storage_key') or r.get('playback_b2_key')
    if r.get('processing_status') == 'ready' and playback_key:
        expires_at = _now() + timedelta(seconds=SIGNED_URL_TTL_SECONDS)
        playback_url = f'/api/video/playback/{_signed_token(r["id"], playback_key, expires_at)}'

    source_meta = None
    if r.get('source_metadata'):
        try:
            source_meta = json.loads(r['source_metadata'])
        except Exception:
            pass

    playback_meta = None
    if r.get('playback_metadata'):
        try:
            playback_meta = json.loads(r['playback_metadata'])
        except Exception:
            pass

    return {
        'id': r['id'],
        'title': r['title'],
        'original_filename': r['original_filename'],
        'original_storage_key': r['original_storage_key'],
        'playback_storage_key': playback_key,
        'source_b2_key': r.get('source_b2_key') or r['original_storage_key'],
        'playback_b2_key': playback_key,
        'size_bytes': r['size_bytes'],
        'uploaded_at': r['uploaded_at'],
        'processing_status': r['processing_status'],
        'processing_stage': r.get('processing_stage'),
        'error_message': r.get('error_message'),
        'video_codec': r.get('video_codec'),
        'audio_codec': r.get('audio_codec'),
        'container': r.get('container'),
        'width': r.get('width'),
        'height': r.get('height'),
        'duration': r.get('duration'),
        'has_audio': bool(r.get('has_audio')),
        'source_metadata': source_meta,
        'playback_metadata': playback_meta,
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
    seen_keys = set()
    for storage_key in (video_row['original_storage_key'], video_row['playback_storage_key']):
        if storage_key:
            if storage_key in seen_keys:
                continue
            seen_keys.add(storage_key)
            try:
                storage.delete(storage_key)
            except Exception:
                app.logger.warning('Could not delete storage key %s', storage_key)


def _is_b2_storage() -> bool:
    return STORAGE_BACKEND == 'b2'


def _multipart_part_count(upload_session) -> int:
    part_size = upload_session['multipart_part_size'] or B2_MULTIPART_PART_SIZE_BYTES
    return (upload_session['size_bytes'] + part_size - 1) // part_size


def _multipart_session_error(upload_session):
    if not upload_session:
        return _json_error('Upload session not found.', 404)
    if not upload_session['multipart_upload_id']:
        return _json_error('This upload does not use B2 multipart upload.', 409)
    if upload_session['status'] != 'uploading':
        return _json_error('Upload session is no longer accepting data.', 409)
    try:
        expired = datetime.fromisoformat(upload_session['expires_at']) < _now()
    except (TypeError, ValueError):
        expired = True
    if expired:
        return _json_error('Upload session has expired.', 410)
    return None


def _create_video_from_upload_session(upload_session) -> bool:
    video_id = upload_session['video_id']
    playback_key = upload_session['playback_storage_key']
    original_key = upload_session['original_storage_key']

    with get_db() as connection:
        existing = connection.execute('SELECT 1 FROM videos WHERE id = ?', (video_id,)).fetchone()
        if existing:
            return False

        connection.execute(
            """
            INSERT INTO videos (
                id, title, original_filename, original_storage_key, playback_storage_key,
                source_b2_key, playback_b2_key, size_bytes, uploaded_at, processing_status,
                processing_stage, error_message, video_codec, audio_codec, container,
                width, height, duration, has_audio, playback_mime_type, is_current,
                uploaded_source_key, previous_video_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                video_id,
                _sanitize_title(upload_session['original_filename']),
                upload_session['original_filename'],
                original_key,
                playback_key,
                original_key,
                playback_key,
                upload_session['size_bytes'],
                utcnow_iso(),
                'uploaded',
                'queued',
                None,
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
            'UPDATE upload_sessions SET status = ?, uploaded_at = ?, completed_at = ? WHERE id = ? AND status = ?',
            ('uploaded', utcnow_iso(), utcnow_iso(), upload_session['id'], 'completing'),
        )

    enqueue_processing_job(video_id)
    return True


def _mark_multipart_session_aborted(upload_session_id: str, message: str) -> None:
    with get_db() as connection:
        connection.execute(
            'UPDATE upload_sessions SET status = ?, error_message = ?, completed_at = ? WHERE id = ? AND status = ?',
            ('aborted', message, utcnow_iso(), upload_session_id, 'completing'),
        )


def _abort_claimed_multipart_upload(upload_session, message: str) -> None:
    try:
        storage.abort_multipart_upload(upload_session['original_storage_key'], upload_session['multipart_upload_id'])
    except Exception:
        app.logger.exception('Failed to clean up B2 multipart upload after completion failure')
    _mark_multipart_session_aborted(upload_session['id'], message)


def _invalidate_storage_cache(storage_key: str) -> None:
    if not _is_b2_storage():
        return
    storage.path_for_key(storage_key).unlink(missing_ok=True)


def _current_video_manifest_from_row(row) -> dict:
    r = dict(row)
    return {
        'id': r['id'],
        'title': r['title'],
        'original_filename': r['original_filename'],
        'original_storage_key': r['original_storage_key'],
        'playback_storage_key': r['playback_storage_key'],
        'source_b2_key': r.get('source_b2_key') or r['original_storage_key'],
        'playback_b2_key': r.get('playback_b2_key') or r['playback_storage_key'],
        'size_bytes': r['size_bytes'],
        'uploaded_at': r['uploaded_at'],
        'processing_status': r['processing_status'],
        'processing_stage': r.get('processing_stage'),
        'error_message': r.get('error_message'),
        'video_codec': r.get('video_codec'),
        'audio_codec': r.get('audio_codec'),
        'container': r.get('container'),
        'width': r.get('width'),
        'height': r.get('height'),
        'duration': r.get('duration'),
        'has_audio': int(bool(r.get('has_audio'))),
        'playback_mime_type': r.get('playback_mime_type') or 'video/mp4',
        'is_current': int(bool(r.get('is_current'))),
        'uploaded_source_key': r.get('uploaded_source_key'),
        'previous_video_id': r.get('previous_video_id'),
        'source_metadata': r.get('source_metadata'),
        'playback_metadata': r.get('playback_metadata'),
    }


def _write_current_video_manifest(row) -> None:
    if not _is_b2_storage() or row is None:
        return
    try:
        if row['processing_status'] != 'ready' or row['is_current'] != 1:
            return
    except (IndexError, KeyError):
        return

    manifest_path = TEMP_DIR / f'{CURRENT_VIDEO_MANIFEST_KEY.replace("/", "_")}-{uuid.uuid4().hex}.json'
    manifest_path.write_text(json.dumps(_current_video_manifest_from_row(row), ensure_ascii=True), encoding='utf-8')

    try:
        _invalidate_storage_cache(CURRENT_VIDEO_MANIFEST_KEY)
        storage.copy_path(manifest_path, CURRENT_VIDEO_MANIFEST_KEY)
    finally:
        manifest_path.unlink(missing_ok=True)
        _invalidate_storage_cache(CURRENT_VIDEO_MANIFEST_KEY)


def _read_current_video_manifest() -> dict | None:
    if not _is_b2_storage() or not storage.exists(CURRENT_VIDEO_MANIFEST_KEY):
        return None

    try:
        _invalidate_storage_cache(CURRENT_VIDEO_MANIFEST_KEY)
        manifest_path = storage.read_path(CURRENT_VIDEO_MANIFEST_KEY)
        return json.loads(manifest_path.read_text(encoding='utf-8'))
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        app.logger.warning('Failed to read current video manifest: %s', exc)
        return None


def _restore_current_video_from_manifest() -> None:
    if not _is_b2_storage():
        return

    with get_db() as connection:
        if _get_visible_video(connection):
            return

        manifest = _read_current_video_manifest()
        if not manifest:
            return

        try:
            if manifest.get('processing_status') != 'ready' or not manifest.get('is_current'):
                return

            existing = connection.execute('SELECT 1 FROM videos WHERE id = ?', (manifest['id'],)).fetchone()
            if existing:
                return

            connection.execute(
                """
                INSERT INTO videos (
                    id, title, original_filename, original_storage_key, playback_storage_key,
                    source_b2_key, playback_b2_key, size_bytes, uploaded_at, processing_status,
                    processing_stage, error_message, video_codec, audio_codec, container,
                    width, height, duration, has_audio, playback_mime_type, is_current,
                    uploaded_source_key, previous_video_id, source_metadata, playback_metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    manifest['id'],
                    manifest['title'],
                    manifest['original_filename'],
                    manifest['original_storage_key'],
                    manifest['playback_storage_key'],
                    manifest.get('source_b2_key') or manifest['original_storage_key'],
                    manifest.get('playback_b2_key') or manifest['playback_storage_key'],
                    manifest['size_bytes'],
                    manifest['uploaded_at'],
                    'ready',
                    'ready',
                    manifest.get('error_message'),
                    manifest.get('video_codec'),
                    manifest.get('audio_codec'),
                    manifest.get('container'),
                    manifest.get('width'),
                    manifest.get('height'),
                    manifest.get('duration'),
                    1 if manifest.get('has_audio') else 0,
                    manifest.get('playback_mime_type') or 'video/mp4',
                    1,
                    manifest.get('uploaded_source_key'),
                    manifest.get('previous_video_id'),
                    manifest.get('source_metadata'),
                    manifest.get('playback_metadata'),
                ),
            )
        except KeyError as exc:
            app.logger.warning('Skipping invalid current video manifest missing field: %s', exc)
        except Exception:
            app.logger.exception('Failed to restore current video from manifest')


# Background worker instance
worker = StreamBoxWorker(on_video_ready_callback=_write_current_video_manifest)
STREAMBOX_EMBEDDED_WORKER = os.getenv('STREAMBOX_EMBEDDED_WORKER', '1' if DEBUG else '0') == '1'
if STREAMBOX_EMBEDDED_WORKER:
    if not app.debug or os.environ.get('WERKZEUG_RUN_MAIN') == 'true':
        worker.start()


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

    _restore_current_video_from_manifest()

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
    try:
        size_bytes = int(payload.get('size_bytes') or 0)
    except (TypeError, ValueError):
        return _json_error('A valid file size is required.', 400)
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
    multipart_upload_id = None
    multipart_part_size = None
    if _is_b2_storage():
        try:
            multipart_upload_id = storage.create_multipart_upload(original_key, content_type)
            multipart_part_size = B2_MULTIPART_PART_SIZE_BYTES
        except Exception as exc:
            app.logger.exception('Failed to create B2 multipart upload')
            return _json_error(f'Could not initialize upload storage: {exc}', 502)

    try:
        with get_db() as connection:
            connection.execute(
                """
                INSERT INTO upload_sessions (
                    id, video_id, original_filename, content_type, size_bytes,
                    temporary_storage_key, original_storage_key, playback_storage_key,
                    status, created_at, expires_at, multipart_upload_id, multipart_part_size
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
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
                    multipart_upload_id,
                    multipart_part_size,
                ),
            )
    except Exception:
        if multipart_upload_id:
            try:
                storage.abort_multipart_upload(original_key, multipart_upload_id)
            except Exception:
                app.logger.exception('Failed to clean up B2 multipart upload after session persistence failure')
        app.logger.exception('Failed to persist upload session')
        return _json_error('Could not initialize upload session.', 500)

    return jsonify(
        {
            'ok': True,
            'upload_session_id': upload_session_id,
            'video_id': video_id,
            'upload_url': f'/api/video/upload/{upload_session_id}',
            'temporary_storage_key': temp_key,
            'original_storage_key': original_key,
            'playback_storage_key': playback_key,
            'expires_at': expires_at.isoformat(),
            'max_bytes': MAX_UPLOAD_BYTES,
            'upload_mode': 'b2_multipart' if multipart_upload_id else 'local',
            'part_size_bytes': multipart_part_size,
            'part_count': (size_bytes + multipart_part_size - 1) // multipart_part_size if multipart_part_size else None,
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
    if upload_session['multipart_upload_id']:
        return _json_error('This upload must send parts directly to B2.', 409)
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
            """
            INSERT INTO videos (
                id, title, original_filename, original_storage_key, playback_storage_key,
                source_b2_key, playback_b2_key, size_bytes, uploaded_at, processing_status,
                processing_stage, video_codec, audio_codec, container, width, height, duration,
                has_audio, playback_mime_type, is_current, uploaded_source_key, previous_video_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                upload_session['video_id'],
                _sanitize_title(upload_session['original_filename']),
                upload_session['original_filename'],
                upload_session['original_storage_key'],
                upload_session['playback_storage_key'],
                upload_session['original_storage_key'],
                upload_session['playback_storage_key'],
                upload_session['size_bytes'],
                utcnow_iso(),
                'uploaded',
                'queued',
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

    enqueue_processing_job(upload_session['video_id'])
    return jsonify({'ok': True, 'uploaded_bytes': bytes_written, 'video_id': upload_session['video_id'], 'status': 'uploaded'})


@app.post('/api/video/upload/multipart/<upload_session_id>/parts')
def multipart_part_urls(upload_session_id: str):
    """Issue a small, validated batch of narrowly-scoped B2 UploadPart URLs."""
    error = _require_auth()
    if error:
        return error

    payload = request.get_json(silent=True) or {}
    part_numbers = payload.get('part_numbers')
    if not isinstance(part_numbers, list) or not part_numbers or len(part_numbers) > B2_MULTIPART_URL_BATCH_SIZE:
        return _json_error(f'part_numbers must contain 1 to {B2_MULTIPART_URL_BATCH_SIZE} part numbers.', 400)
    if len(set(part_numbers)) != len(part_numbers) or any(not isinstance(number, int) or isinstance(number, bool) for number in part_numbers):
        return _json_error('part_numbers must be unique integers.', 400)

    with get_db() as connection:
        upload_session = connection.execute('SELECT * FROM upload_sessions WHERE id = ?', (upload_session_id,)).fetchone()
    session_error = _multipart_session_error(upload_session)
    if session_error:
        return session_error
    total_parts = _multipart_part_count(upload_session)
    if any(number < 1 or number > total_parts for number in part_numbers):
        return _json_error('Part number is outside the declared upload size.', 400)

    try:
        urls = [
            {'part_number': number, 'url': storage.presigned_upload_part_url(upload_session['original_storage_key'], upload_session['multipart_upload_id'], number, B2_MULTIPART_URL_TTL_SECONDS)}
            for number in part_numbers
        ]
    except Exception:
        app.logger.exception('Failed to presign B2 upload parts')
        return _json_error('Could not prepare upload parts.', 502)
    return jsonify({'ok': True, 'parts': urls, 'expires_in': B2_MULTIPART_URL_TTL_SECONDS})


@app.post('/api/video/upload/multipart/<upload_session_id>/complete')
def complete_multipart_upload(upload_session_id: str):
    """Complete from B2's ListParts result, never browser-provided ETags."""
    error = _require_auth()
    if error:
        return error

    with get_db() as connection:
        upload_session = connection.execute('SELECT * FROM upload_sessions WHERE id = ?', (upload_session_id,)).fetchone()
        if upload_session and upload_session['status'] == 'uploaded' and upload_session['multipart_upload_id']:
            return jsonify({'ok': True, 'video_id': upload_session['video_id'], 'status': 'uploaded'})
        session_error = _multipart_session_error(upload_session)
        if session_error:
            return session_error
        claimed = connection.execute(
            'UPDATE upload_sessions SET status = ? WHERE id = ? AND status = ?',
            ('completing', upload_session_id, 'uploading'),
        )
        if claimed.rowcount != 1:
            return _json_error('Multipart completion is already in progress.', 409)

    expected_parts = _multipart_part_count(upload_session)
    part_size = upload_session['multipart_part_size']
    try:
        uploaded_parts = storage.list_multipart_parts(upload_session['original_storage_key'], upload_session['multipart_upload_id'])
        if len(uploaded_parts) != expected_parts:
            _abort_claimed_multipart_upload(upload_session, 'B2 does not contain every required upload part.')
            return _json_error('B2 does not contain every required upload part.', 409)
        completion_parts = []
        for index, part in enumerate(uploaded_parts, start=1):
            expected_size = part_size if index < expected_parts else upload_session['size_bytes'] - part_size * (expected_parts - 1)
            if part.get('PartNumber') != index or part.get('Size') != expected_size or not part.get('ETag'):
                _abort_claimed_multipart_upload(upload_session, 'B2 upload parts did not match the declared file.')
                return _json_error('B2 upload parts do not match the declared file.', 409)
            completion_parts.append({'PartNumber': part['PartNumber'], 'ETag': part['ETag']})
        storage.complete_multipart_upload(upload_session['original_storage_key'], upload_session['multipart_upload_id'], completion_parts)
    except Exception:
        app.logger.exception('Failed to complete B2 multipart upload')
        _abort_claimed_multipart_upload(upload_session, 'B2 multipart completion failed.')
        return _json_error('Could not complete multipart upload.', 502)

    try:
        _create_video_from_upload_session(upload_session)
    except Exception:
        app.logger.exception('Failed to persist completed B2 upload')
        _mark_multipart_session_aborted(upload_session_id, 'Completed B2 upload could not be persisted.')
        return _json_error('Could not finalize multipart upload.', 500)

    return jsonify({'ok': True, 'video_id': upload_session['video_id'], 'status': 'uploaded'})


@app.post('/api/video/upload/multipart/<upload_session_id>/abort')
def abort_multipart_upload(upload_session_id: str):
    error = _require_auth()
    if error:
        return error

    with get_db() as connection:
        upload_session = connection.execute('SELECT * FROM upload_sessions WHERE id = ?', (upload_session_id,)).fetchone()
        if not upload_session:
            return _json_error('Upload session not found.', 404)
        if not upload_session['multipart_upload_id']:
            return _json_error('This upload does not use B2 multipart upload.', 409)
        if upload_session['status'] == 'aborted':
            return jsonify({'ok': True})
        if upload_session['status'] in ('completing', 'uploaded'):
            return _json_error('Upload session can no longer be aborted.', 409)
        claimed = connection.execute(
            'UPDATE upload_sessions SET status = ?, completed_at = ? WHERE id = ? AND status = ?',
            ('aborted', utcnow_iso(), upload_session_id, 'uploading')
        )
        if claimed.rowcount != 1:
            return jsonify({'ok': True})

    try:
        storage.abort_multipart_upload(upload_session['original_storage_key'], upload_session['multipart_upload_id'])
    except Exception:
        app.logger.exception('Failed to abort B2 multipart upload %s', upload_session_id)
        return _json_error('Upload was canceled locally but B2 cleanup failed.', 502)
    return jsonify({'ok': True})


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

    _restore_current_video_from_manifest()

    with get_db() as connection:
        rows = connection.execute('SELECT * FROM videos').fetchall()
        upload_sessions = connection.execute('SELECT * FROM upload_sessions').fetchall()
        connection.execute('DELETE FROM processing_jobs')
        connection.execute('DELETE FROM videos')
        connection.execute('DELETE FROM upload_sessions')

    for row in rows:
        _delete_video_assets(row)

    for session_row in upload_sessions:
        if session_row['multipart_upload_id'] and session_row['status'] == 'uploading':
            try:
                storage.abort_multipart_upload(session_row['original_storage_key'], session_row['multipart_upload_id'])
            except Exception:
                app.logger.warning('Could not abort multipart upload during delete: %s', session_row['id'])
        try:
            storage.delete(session_row['temporary_storage_key'])
        except Exception:
            pass

    if _is_b2_storage() and storage.exists(CURRENT_VIDEO_MANIFEST_KEY):
        try:
            storage.delete(CURRENT_VIDEO_MANIFEST_KEY)
        except Exception:
            pass

    return jsonify({'ok': True})


@app.get('/api/video/playback/<path:token>')
def playback(token: str):
    parsed = _parse_signed_token(token)
    if not parsed:
        return _json_error('Invalid or expired playback URL.', 403)

    if STORAGE_BACKEND == 'b2':
        return redirect(storage.presigned_get_url(parsed['storage_key'], SIGNED_URL_TTL_SECONDS), code=302)

    path = storage.path_for_key(parsed['storage_key'])
    if not path.exists():
        return _json_error('Playback file not found.', 404)
    return send_file(path, mimetype='video/mp4', conditional=True)


@app.post('/api/video/<video_id>/transcode')
def transcode_video(video_id: str):
    """Emergency fallback endpoint for client player decode errors."""
    error = _require_auth()
    if error:
        return error

    with get_db() as connection:
        row = connection.execute('SELECT * FROM videos WHERE id = ?', (video_id,)).fetchone()
    if not row:
        return _json_error('Video not found.', 404)

    # Already has a separate playback file that is ready
    if (
        row['processing_status'] == 'ready'
        and row['playback_storage_key']
        and row['playback_storage_key'] != row['original_storage_key']
    ):
        return jsonify({'ok': True, 'video': _video_to_payload(row)})

    # Already processing
    if row['processing_status'] == 'processing':
        return jsonify({'ok': True, 'status': 'processing', 'video': _video_to_payload(row)})

    # Reset video status and re-enqueue processing job with force_transcode=True
    with get_db() as connection:
        connection.execute(
            "UPDATE videos SET processing_status = 'uploaded', processing_stage = 'queued', error_message = NULL WHERE id = ?",
            (video_id,),
        )
    enqueue_processing_job(video_id, force_transcode=True)

    with get_db() as connection:
        updated_row = connection.execute('SELECT * FROM videos WHERE id = ?', (video_id,)).fetchone()
    return jsonify({'ok': True, 'status': 'processing', 'video': _video_to_payload(updated_row)})


@app.get('/api/health')
def health():
    return jsonify({'ok': True, 'storage_backend': STORAGE_BACKEND})


def main():
    init_db()
    if not worker._thread or not worker._thread.is_alive():
        worker.start()
    app.run(host=APP_HOST, port=APP_PORT, debug=DEBUG)


if __name__ == '__main__':
    main()
