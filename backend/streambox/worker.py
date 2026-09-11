from __future__ import annotations

import json
import logging
import os
import socket
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from contextlib import contextmanager
from pathlib import Path
from typing import Callable

from .config import STORAGE_BACKEND, TEMP_DIR
from .db import DATABASE_URL, get_db, utcnow_iso
from .media import (
    InsufficientDiskSpaceError,
    MediaDecision,
    MediaProcessingError,
    MediaValidationError,
    calculate_required_disk_space,
    check_disk_space,
    decide_media_processing,
    probe_media,
    remux_for_browser,
    transcode_for_browser,
    verify_playback_asset,
)
from .storage import get_storage_backend

log = logging.getLogger(__name__)

WORKER_ID = f"{socket.gethostname()}:{os.getpid()}:{threading.get_ident()}"
MAX_JOB_ATTEMPTS = 3


@contextmanager
def _job_heartbeat(job_id: str, interval_seconds: float = 15.0):
    """Periodically update job heartbeat timestamp while processing long tasks."""
    stop_event = threading.Event()

    def _heartbeat_worker():
        while not stop_event.wait(interval_seconds):
            try:
                now = utcnow_iso()
                with get_db() as connection:
                    connection.execute(
                        "UPDATE processing_jobs SET heartbeat_at = ?, updated_at = ? WHERE id = ? AND status = 'processing'",
                        (now, now, job_id),
                    )
            except Exception:
                pass

    t = threading.Thread(target=_heartbeat_worker, daemon=True, name=f"Heartbeat-{job_id}")
    t.start()
    try:
        yield
    finally:
        stop_event.set()
        t.join(timeout=2.0)


def enqueue_processing_job(video_id: str, force_transcode: bool = False) -> str:
    """Idempotently enqueue a processing job for a video."""
    with get_db() as connection:
        # Check if an active job already exists
        existing = connection.execute(
            "SELECT id FROM processing_jobs WHERE video_id = ? AND status IN ('pending', 'processing')",
            (video_id,),
        ).fetchone()
        if existing:
            if force_transcode:
                connection.execute(
                    "UPDATE processing_jobs SET force_transcode = 1 WHERE id = ?",
                    (existing['id'],),
                )
            return existing['id']

        job_id = uuid.uuid4().hex
        now = utcnow_iso()
        connection.execute(
            """
            INSERT INTO processing_jobs (id, video_id, status, stage, attempts, force_transcode, created_at, updated_at, heartbeat_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (job_id, video_id, 'pending', 'queued', 0, 1 if force_transcode else 0, now, now, now),
        )
        return job_id


def _acquire_next_job(worker_id: str):
    """Atomically claim the next pending processing job."""
    with get_db() as connection:
        now = utcnow_iso()
        if DATABASE_URL:
            # PostgreSQL atomic claim with SKIP LOCKED
            cursor = connection.execute(
                """
                UPDATE processing_jobs
                SET status = 'processing',
                    stage = 'probing',
                    updated_at = %s,
                    heartbeat_at = %s,
                    locked_by = %s
                WHERE id = (
                    SELECT id FROM processing_jobs
                    WHERE status = 'pending'
                    ORDER BY created_at ASC
                    FOR UPDATE SKIP LOCKED
                    LIMIT 1
                )
                RETURNING id, video_id, attempts
                """,
                (now, now, worker_id),
            )
            row = cursor.fetchone()
            return row
        else:
            # SQLite atomic claim in immediate transaction
            job = connection.execute(
                "SELECT id, video_id, attempts FROM processing_jobs WHERE status = 'pending' ORDER BY created_at ASC LIMIT 1"
            ).fetchone()
            if not job:
                return None

            claimed = connection.execute(
                """
                UPDATE processing_jobs
                SET status = 'processing',
                    stage = 'probing',
                    updated_at = ?,
                    heartbeat_at = ?,
                    locked_by = ?
                WHERE id = ? AND status = 'pending'
                """,
                (now, now, worker_id, job['id']),
            )
            if claimed.rowcount == 1:
                return job
            return None


def _update_job_stage(job_id: str, stage: str, video_id: str | None = None) -> None:
    now = utcnow_iso()
    with get_db() as connection:
        connection.execute(
            "UPDATE processing_jobs SET stage = ?, updated_at = ?, heartbeat_at = ? WHERE id = ?",
            (stage, now, now, job_id),
        )
        if video_id:
            connection.execute(
                "UPDATE videos SET processing_stage = ? WHERE id = ?",
                (stage, video_id),
            )


def _mark_job_completed(job_id: str) -> None:
    now = utcnow_iso()
    with get_db() as connection:
        connection.execute(
            "UPDATE processing_jobs SET status = 'completed', stage = 'completed', updated_at = ?, heartbeat_at = ? WHERE id = ?",
            (now, now, job_id),
        )


def _mark_job_failed(job_id: str, error_message: str, video_id: str | None = None) -> None:
    now = utcnow_iso()
    with get_db() as connection:
        connection.execute(
            "UPDATE processing_jobs SET status = 'failed', error_message = ?, updated_at = ? WHERE id = ?",
            (error_message[:1000], now, job_id),
        )
        if video_id:
            connection.execute(
                "UPDATE videos SET processing_status = 'failed', error_message = ? WHERE id = ?",
                (error_message[:1000], video_id),
            )


def process_video_job(job_id: str, video_id: str, on_video_ready_callback: Callable | None = None) -> bool:
    """Execute the full media lifecycle for a claimed job."""
    storage = get_storage_backend()
    original_path: Path | None = None
    playback_path: Path | None = None

    with get_db() as connection:
        video = connection.execute("SELECT * FROM videos WHERE id = ?", (video_id,)).fetchone()
        job = connection.execute("SELECT * FROM processing_jobs WHERE id = ?", (job_id,)).fetchone()

    if not video:
        _mark_job_failed(job_id, f"Video {video_id} not found in database.")
        return False

    force_transcode = bool(job and job['force_transcode'])

    with _job_heartbeat(job_id):
        try:
            log.info("JOB[%s]: Processing video %s (original_storage_key=%s, force_transcode=%s)", job_id, video_id, video['original_storage_key'], force_transcode)

            # Set video status to processing
            with get_db() as connection:
                connection.execute(
                    "UPDATE videos SET processing_status = 'processing', processing_stage = 'probing' WHERE id = ?",
                    (video_id,),
                )

            # Stage 1: Probing
            _update_job_stage(job_id, 'probing', video_id)
            original_path = storage.read_path(video['original_storage_key'])
            if not original_path.exists():
                raise MediaValidationError(f"Original source file could not be read: {video['original_storage_key']}")

            source_probe = probe_media(original_path)
            source_metadata_json = json.dumps(source_probe.to_dict())

            # Update source metadata in database
            with get_db() as connection:
                connection.execute(
                    """
                    UPDATE videos
                    SET source_metadata = ?,
                        source_b2_key = original_storage_key
                    WHERE id = ?
                    """,
                    (source_metadata_json, video_id),
                )

            # Stage 2: Centralized Compatibility Decision
            decision = decide_media_processing(source_probe)
            if force_transcode and decision == MediaDecision.DIRECT:
                log.info("JOB[%s]: Overriding decision DIRECT -> TRANSCODE due to force_transcode=True", job_id)
                decision = MediaDecision.TRANSCODE

            log.info("JOB[%s]: Decision for video %s is %s", job_id, video_id, decision.value)

            if decision == MediaDecision.DIRECT:
                # DIRECT: no duplicate file, playback key is source key
                final_playback_key = video['original_storage_key']
                verified_probe = source_probe
                playback_metadata_json = source_metadata_json
            else:
                # REMUX or TRANSCODE: dedicated MP4 playback asset
                final_playback_key = f"videos/{video_id}/playback.mp4"
                source_size = original_path.stat().st_size
                required_disk = calculate_required_disk_space(source_size, decision)
                has_space, free_bytes, _ = check_disk_space(TEMP_DIR, required_disk)

                if not has_space:
                    raise InsufficientDiskSpaceError(
                        f"Insufficient disk space for {decision.value}: required {required_disk / (1024**2):.1f} MB, available {free_bytes / (1024**2):.1f} MB."
                    )

                playback_path = storage.path_for_key(final_playback_key)

                if decision == MediaDecision.REMUX:
                    _update_job_stage(job_id, 'remuxing', video_id)
                    try:
                        remux_for_browser(original_path, playback_path)
                    except Exception as remux_err:
                        log.warning("JOB[%s]: REMUX failed (%s), falling back to TRANSCODE", job_id, remux_err)
                        _update_job_stage(job_id, 'transcoding', video_id)
                        transcode_for_browser(original_path, playback_path, source_probe)
                else:
                    _update_job_stage(job_id, 'transcoding', video_id)
                    transcode_for_browser(original_path, playback_path, source_probe)

                # Stage 3: Verification
                _update_job_stage(job_id, 'verifying', video_id)
                verified_probe = verify_playback_asset(playback_path, source_had_audio=source_probe.has_audio)
                playback_metadata_json = json.dumps(verified_probe.to_dict())

                # Stage 4: Upload playback asset to B2/storage
                _update_job_stage(job_id, 'uploading_playback', video_id)
                storage.copy_path(playback_path, final_playback_key)

            # Stage 5: Finalize video record as READY
            keys_to_clean: list[str] = []
            final_video_row = None

            with get_db() as connection:
                # Re-verify target video still exists in DB
                current_target = connection.execute("SELECT * FROM videos WHERE id = ?", (video_id,)).fetchone()
                if not current_target:
                    log.warning("JOB[%s]: Video %s was deleted during processing; aborting finalization.", job_id, video_id)
                    _mark_job_failed(job_id, "Video was deleted during processing.")
                    return False

                # Check if a newer video was already uploaded
                newer_video = connection.execute(
                    "SELECT id FROM videos WHERE id != ? AND uploaded_at > ?",
                    (video_id, current_target['uploaded_at']),
                ).fetchone()

                if newer_video:
                    log.info("JOB[%s]: A newer video (%s) exists; discarding obsolete video %s.", job_id, newer_video['id'], video_id)
                    connection.execute("DELETE FROM videos WHERE id = ?", (video_id,))
                    keys_to_clean.append(final_playback_key)
                    if final_playback_key != current_target['original_storage_key']:
                        keys_to_clean.append(current_target['original_storage_key'])
                else:
                    # Find older videos that are being replaced
                    older_videos = connection.execute(
                        "SELECT id, original_storage_key, playback_storage_key FROM videos WHERE id != ? AND uploaded_at <= ?",
                        (video_id, current_target['uploaded_at']),
                    ).fetchall()

                    connection.execute(
                        """
                        UPDATE videos
                        SET processing_status = 'ready',
                            processing_stage = 'ready',
                            error_message = NULL,
                            playback_storage_key = ?,
                            playback_b2_key = ?,
                            source_b2_key = original_storage_key,
                            playback_mime_type = 'video/mp4',
                            video_codec = ?,
                            audio_codec = ?,
                            container = ?,
                            width = ?,
                            height = ?,
                            duration = ?,
                            has_audio = ?,
                            playback_metadata = ?,
                            is_current = 1
                        WHERE id = ?
                        """,
                        (
                            final_playback_key,
                            final_playback_key,
                            verified_probe.video_codec,
                            verified_probe.audio_codec,
                            verified_probe.container,
                            verified_probe.width,
                            verified_probe.height,
                            verified_probe.duration,
                            1 if verified_probe.has_audio else 0,
                            playback_metadata_json,
                            video_id,
                        ),
                    )

                    connection.execute("UPDATE videos SET is_current = 0 WHERE id != ?", (video_id,))

                    for old_v in older_videos:
                        for k in (old_v['original_storage_key'], old_v['playback_storage_key']):
                            if k and k != final_playback_key and k != current_target['original_storage_key']:
                                keys_to_clean.append(k)
                        connection.execute("DELETE FROM videos WHERE id = ?", (old_v['id'],))

                    final_video_row = connection.execute("SELECT * FROM videos WHERE id = ?", (video_id,)).fetchone()

            # Clean replaced storage keys OUTSIDE the db transaction
            seen_clean = set()
            for k in keys_to_clean:
                if k and k not in seen_clean:
                    seen_clean.add(k)
                    try:
                        storage.delete(k)
                    except Exception:
                        log.warning("Could not delete obsolete video key %s", k)

            _mark_job_completed(job_id)

            if on_video_ready_callback and final_video_row:
                try:
                    on_video_ready_callback(final_video_row)
                except Exception:
                    log.exception("JOB[%s]: on_video_ready_callback failed", job_id)

            log.info("JOB[%s]: Video %s successfully processed to READY (decision=%s)", job_id, video_id, decision.value)
            return True

        except (MediaValidationError, MediaProcessingError, InsufficientDiskSpaceError) as exc:
            log.warning("JOB[%s]: Media error processing video %s: %s", job_id, video_id, exc)
            _mark_job_failed(job_id, str(exc), video_id)
            return False

        except Exception as exc:
            log.exception("JOB[%s]: Unexpected error processing video %s: %s", job_id, video_id, exc)
            _mark_job_failed(job_id, f"Processing error: {exc}", video_id)
            return False

        finally:
            # Clean local temporary artifacts safely
            if STORAGE_BACKEND == 'b2':
                for temp_path in (original_path, playback_path):
                    if temp_path is not None:
                        try:
                            temp_path.unlink(missing_ok=True)
                        except OSError as exc:
                            log.warning("JOB[%s]: Failed to clean temp file %s: %s", job_id, temp_path, exc)


def recover_stale_jobs(stale_threshold_seconds: int = 300) -> int:
    """Recover processing jobs left in 'processing' status whose heartbeat is older than threshold."""
    recovered = 0
    cutoff_iso = (datetime.now(timezone.utc) - timedelta(seconds=stale_threshold_seconds)).isoformat()
    with get_db() as connection:
        stale_jobs = connection.execute(
            """
            SELECT * FROM processing_jobs
            WHERE status = 'processing'
              AND (
                (heartbeat_at IS NOT NULL AND heartbeat_at < ?)
                OR (heartbeat_at IS NULL AND updated_at < ?)
              )
            """,
            (cutoff_iso, cutoff_iso),
        ).fetchall()

    for job in stale_jobs:
        job_id = job['id']
        video_id = job['video_id']
        attempts = int(job['attempts'] or 0) + 1

        if attempts >= MAX_JOB_ATTEMPTS:
            log.warning("RECOVERY: Job %s for video %s reached max attempts (%d). Marking as failed.", job_id, video_id, attempts)
            _mark_job_failed(job_id, f"Failed after {MAX_JOB_ATTEMPTS} processing attempts due to crash/restart.", video_id)
        else:
            log.warning("RECOVERY: Requeuing stale job %s for video %s (attempt %d of %d)", job_id, video_id, attempts, MAX_JOB_ATTEMPTS)
            now = utcnow_iso()
            with get_db() as connection:
                connection.execute(
                    """
                    UPDATE processing_jobs
                    SET status = 'pending',
                        stage = 'requeued',
                        attempts = ?,
                        locked_by = NULL,
                        updated_at = ?,
                        heartbeat_at = ?
                    WHERE id = ?
                    """,
                    (attempts, now, now, job_id),
                )
                connection.execute(
                    "UPDATE videos SET processing_status = 'processing', processing_stage = 'requeued' WHERE id = ?",
                    (video_id,),
                )
            recovered += 1

    return recovered


def cleanup_abandoned_upload_sessions() -> int:
    """Find and abort expired incomplete upload sessions."""
    storage = get_storage_backend()
    cleaned = 0
    now = utcnow_iso()

    with get_db() as connection:
        expired_sessions = connection.execute(
            "SELECT * FROM upload_sessions WHERE status = 'uploading' AND expires_at < ?",
            (now,),
        ).fetchall()

    for session_row in expired_sessions:
        session_id = session_row['id']
        log.info("CLEANUP: Aborting expired upload session %s (expired at %s)", session_id, session_row['expires_at'])
        if session_row['multipart_upload_id']:
            try:
                storage.abort_multipart_upload(session_row['original_storage_key'], session_row['multipart_upload_id'])
            except Exception as exc:
                log.warning("CLEANUP: Could not abort B2 multipart for session %s: %s", session_id, exc)

        try:
            storage.delete(session_row['temporary_storage_key'])
        except Exception:
            pass

        with get_db() as connection:
            connection.execute(
                "UPDATE upload_sessions SET status = 'aborted', error_message = 'Upload session expired', completed_at = ? WHERE id = ? AND status = 'uploading'",
                (now, session_id),
            )
        cleaned += 1

    return cleaned


class StreamBoxWorker:
    """Persistent background worker loop that processes video jobs and handles crash recovery."""

    def __init__(self, on_video_ready_callback: Callable | None = None, poll_interval: float = 1.0):
        self.on_video_ready_callback = on_video_ready_callback
        self.poll_interval = poll_interval
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_cleanup = 0.0

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        # Run startup crash recovery
        recover_stale_jobs()
        cleanup_abandoned_upload_sessions()

        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, name="StreamBoxWorker", daemon=True)
        self._thread.start()
        log.info("StreamBox background worker started.")

    def stop(self, timeout: float = 5.0) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)
        log.info("StreamBox background worker stopped.")

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                # Periodic cleanup every 5 minutes
                now_ts = time.time()
                if now_ts - self._last_cleanup > 300:
                    self._last_cleanup = now_ts
                    cleanup_abandoned_upload_sessions()
                    recover_stale_jobs()

                job = _acquire_next_job(WORKER_ID)
                if job:
                    process_video_job(job['id'], job['video_id'], self.on_video_ready_callback)
                else:
                    self._stop_event.wait(self.poll_interval)
            except Exception:
                log.exception("Exception in background worker loop")
                self._stop_event.wait(self.poll_interval)


def run_worker_cli():
    """CLI entrypoint for standalone background worker process."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    log.info("Starting standalone StreamBox worker process (PID: %d)...", os.getpid())
    worker = StreamBoxWorker(poll_interval=1.0)
    worker.start()
    try:
        while True:
            time.sleep(1.0)
    except (KeyboardInterrupt, SystemExit):
        log.info("Stopping standalone StreamBox worker process...")
        worker.stop()


if __name__ == '__main__':
    run_worker_cli()
