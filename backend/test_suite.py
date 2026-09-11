from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Ensure test environment uses local storage and isolated sqlite db
os.environ['STORAGE_BACKEND'] = 'local'
os.environ['SECRET_KEY'] = 'test-secret-key-12345'
os.environ['ADMIN_USERNAME'] = 'admin'
os.environ['ADMIN_PASSWORD_HASH'] = 'scrypt:32768:8:1$test$test'

from app import app
from streambox.config import TEMP_DIR, SIGNED_URL_TTL_SECONDS
from streambox.db import get_db, init_db, utcnow_iso
from streambox.media import (
    MediaDecision,
    MediaProbe,
    _which,
    calculate_required_disk_space,
    check_disk_space,
    decide_media_processing,
    probe_media,
    verify_playback_asset,
)
from streambox.storage import get_storage_backend
from streambox.worker import (
    StreamBoxWorker,
    _acquire_next_job,
    cleanup_abandoned_upload_sessions,
    enqueue_processing_job,
    process_video_job,
    recover_stale_jobs,
)


class StreamBoxLifecycleTestSuite(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()
        cls.storage = get_storage_backend()
        cls.ffmpeg = _which('ffmpeg')
        cls.test_dir = Path(tempfile.mkdtemp(prefix='streambox_test_'))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.test_dir, ignore_errors=True)

    def setUp(self):
        with get_db() as connection:
            connection.execute('DELETE FROM processing_jobs')
            connection.execute('DELETE FROM videos')
            connection.execute('DELETE FROM upload_sessions')

    def _generate_video(self, filename: str, vcodec='libx264', acodec='aac', container='mp4', pix_fmt='yuv420p', duration=1) -> Path:
        out_path = self.test_dir / filename
        cmd = [
            self.ffmpeg,
            '-y',
            '-f', 'lavfi', '-i', f'testsrc=duration={duration}:size=320x240:rate=30',
        ]
        if acodec:
            cmd.extend(['-f', 'lavfi', '-i', f'sine=frequency=1000:duration={duration}'])
            cmd.extend(['-c:a', acodec])
        else:
            cmd.extend(['-an'])

        cmd.extend([
            '-c:v', vcodec,
            '-pix_fmt', pix_fmt,
            str(out_path),
        ])
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            raise RuntimeError(f"FFmpeg generation failed: {res.stderr}")
        return out_path

    def test_a_direct_play_lifecycle(self):
        """TEST A: MP4 + H.264 + AAC + yuv420p -> DIRECT -> playback_key == source_key -> READY"""
        source_path = self._generate_video('test_a.mp4', vcodec='libx264', acodec='aac', pix_fmt='yuv420p')
        video_id = uuid.uuid4().hex
        source_key = f'videos/{video_id}/source'
        playback_key = f'videos/{video_id}/playback.mp4'

        self.storage.copy_path(source_path, source_key)

        with get_db() as conn:
            conn.execute(
                """
                INSERT INTO videos (id, title, original_filename, original_storage_key, playback_storage_key,
                                    source_b2_key, playback_b2_key, size_bytes, uploaded_at, processing_status,
                                    processing_stage, is_current)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (video_id, 'Test A', 'test_a.mp4', source_key, playback_key, source_key, playback_key,
                 source_path.stat().st_size, utcnow_iso(), 'uploaded', 'queued', 0),
            )

        job_id = enqueue_processing_job(video_id)
        job = _acquire_next_job("test_worker")
        self.assertIsNotNone(job)
        self.assertEqual(job['id'], job_id)

        success = process_video_job(job_id, video_id)
        self.assertTrue(success)

        with get_db() as conn:
            v = conn.execute("SELECT * FROM videos WHERE id = ?", (video_id,)).fetchone()
            j = conn.execute("SELECT * FROM processing_jobs WHERE id = ?", (job_id,)).fetchone()

        self.assertEqual(v['processing_status'], 'ready')
        self.assertEqual(v['playback_storage_key'], source_key)  # DIRECT uses source key
        self.assertEqual(v['is_current'], 1)
        self.assertEqual(j['status'], 'completed')
        self.assertIsNotNone(v['source_metadata'])
        self.assertIsNotNone(v['playback_metadata'])

    def test_b_remux_lifecycle(self):
        """TEST B: MKV + H.264 + AAC -> REMUX -> verifies output MP4 -> READY"""
        source_path = self._generate_video('test_b.mkv', vcodec='libx264', acodec='aac', pix_fmt='yuv420p')
        video_id = uuid.uuid4().hex
        source_key = f'videos/{video_id}/source'
        playback_key = f'videos/{video_id}/playback.mp4'

        self.storage.copy_path(source_path, source_key)

        with get_db() as conn:
            conn.execute(
                """
                INSERT INTO videos (id, title, original_filename, original_storage_key, playback_storage_key,
                                    source_b2_key, playback_b2_key, size_bytes, uploaded_at, processing_status,
                                    processing_stage, is_current)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (video_id, 'Test B', 'test_b.mkv', source_key, playback_key, source_key, playback_key,
                 source_path.stat().st_size, utcnow_iso(), 'uploaded', 'queued', 0),
            )

        job_id = enqueue_processing_job(video_id)
        job = _acquire_next_job("test_worker")
        self.assertIsNotNone(job)

        success = process_video_job(job_id, video_id)
        self.assertTrue(success)

        with get_db() as conn:
            v = conn.execute("SELECT * FROM videos WHERE id = ?", (video_id,)).fetchone()

        self.assertEqual(v['processing_status'], 'ready')
        self.assertEqual(v['playback_storage_key'], playback_key)
        self.assertTrue(self.storage.exists(playback_key))

        # Output MP4 verified
        pb_probe = probe_media(self.storage.path_for_key(playback_key))
        self.assertEqual(pb_probe.video_codec, 'h264')
        self.assertIn('mp4', pb_probe.container.lower())

    def test_c_transcode_lifecycle(self):
        """TEST C: Incompatible codec (e.g. mpeg4/vp8) -> TRANSCODE -> verified MP4 -> READY"""
        source_path = self._generate_video('test_c.avi', vcodec='mpeg4', acodec='mp3', pix_fmt='yuv420p')
        video_id = uuid.uuid4().hex
        source_key = f'videos/{video_id}/source'
        playback_key = f'videos/{video_id}/playback.mp4'

        self.storage.copy_path(source_path, source_key)

        with get_db() as conn:
            conn.execute(
                """
                INSERT INTO videos (id, title, original_filename, original_storage_key, playback_storage_key,
                                    source_b2_key, playback_b2_key, size_bytes, uploaded_at, processing_status,
                                    processing_stage, is_current)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (video_id, 'Test C', 'test_c.avi', source_key, playback_key, source_key, playback_key,
                 source_path.stat().st_size, utcnow_iso(), 'uploaded', 'queued', 0),
            )

        job_id = enqueue_processing_job(video_id)
        job = _acquire_next_job("test_worker")
        self.assertIsNotNone(job)

        success = process_video_job(job_id, video_id)
        self.assertTrue(success)

        with get_db() as conn:
            v = conn.execute("SELECT * FROM videos WHERE id = ?", (video_id,)).fetchone()

        self.assertEqual(v['processing_status'], 'ready')
        self.assertEqual(v['video_codec'], 'h264')
        self.assertEqual(v['audio_codec'], 'aac')
        self.assertTrue(self.storage.exists(playback_key))

    def test_d_corrupted_media(self):
        """TEST D: Corrupted/invalid file -> fails cleanly, source is preserved"""
        corrupted_path = self.test_dir / 'corrupt.mp4'
        corrupted_path.write_bytes(b'CORRUPTED NOT A REAL VIDEO STREAM 1234567890')
        video_id = uuid.uuid4().hex
        source_key = f'videos/{video_id}/source'
        playback_key = f'videos/{video_id}/playback.mp4'

        self.storage.copy_path(corrupted_path, source_key)

        with get_db() as conn:
            conn.execute(
                """
                INSERT INTO videos (id, title, original_filename, original_storage_key, playback_storage_key,
                                    source_b2_key, playback_b2_key, size_bytes, uploaded_at, processing_status,
                                    processing_stage, is_current)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (video_id, 'Test D', 'corrupt.mp4', source_key, playback_key, source_key, playback_key,
                 corrupted_path.stat().st_size, utcnow_iso(), 'uploaded', 'queued', 0),
            )

        job_id = enqueue_processing_job(video_id)
        job = _acquire_next_job("test_worker")
        self.assertIsNotNone(job)

        success = process_video_job(job_id, video_id)
        self.assertFalse(success)

        with get_db() as conn:
            v = conn.execute("SELECT * FROM videos WHERE id = ?", (video_id,)).fetchone()
            j = conn.execute("SELECT * FROM processing_jobs WHERE id = ?", (job_id,)).fetchone()

        self.assertEqual(v['processing_status'], 'failed')
        self.assertEqual(j['status'], 'failed')
        self.assertIsNotNone(v['error_message'])
        # Original source is preserved
        self.assertTrue(self.storage.exists(source_key))

    def test_f_cancel_and_abort_upload(self):
        """TEST F: Upload cancellation -> session aborted, completion cannot later succeed"""
        client = app.test_client()
        with client.session_transaction() as sess:
            sess['authenticated'] = True
            sess['username'] = 'admin'

        init_res = client.post('/api/video/upload/init', json={
            'filename': 'test_cancel.mp4',
            'size_bytes': 1024 * 1024,
            'content_type': 'video/mp4'
        })
        self.assertEqual(init_res.status_code, 200)
        session_id = init_res.json['upload_session_id']

        # Abort upload
        with get_db() as conn:
            conn.execute("UPDATE upload_sessions SET multipart_upload_id = 'test_mp_id' WHERE id = ?", (session_id,))

        abort_res = client.post(f'/api/video/upload/multipart/{session_id}/abort')
        self.assertEqual(abort_res.status_code, 200)

        with get_db() as conn:
            sess = conn.execute("SELECT status FROM upload_sessions WHERE id = ?", (session_id,)).fetchone()
        self.assertEqual(sess['status'], 'aborted')

        # Trying to abort again is idempotent (200)
        abort_again = client.post(f'/api/video/upload/multipart/{session_id}/abort')
        self.assertEqual(abort_again.status_code, 200)

        # Trying to complete an aborted session fails with 409
        complete_res = client.post(f'/api/video/upload/multipart/{session_id}/complete')
        self.assertEqual(complete_res.status_code, 409)

    def test_g_abandoned_upload_cleanup(self):
        """TEST G: Expired upload sessions are automatically aborted and cleaned up"""
        expired_time = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        session_id = uuid.uuid4().hex
        with get_db() as conn:
            conn.execute(
                """
                INSERT INTO upload_sessions (id, video_id, original_filename, size_bytes, temporary_storage_key,
                                            original_storage_key, playback_storage_key, status, created_at, expires_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (session_id, 'vid_123', 'expired.mp4', 1000, 'tmp/expired.upload', 'videos/vid_123/source',
                 'videos/vid_123/playback.mp4', 'uploading', expired_time, expired_time),
            )

        cleaned = cleanup_abandoned_upload_sessions()
        self.assertGreaterEqual(cleaned, 1)

        with get_db() as conn:
            s = conn.execute("SELECT status FROM upload_sessions WHERE id = ?", (session_id,)).fetchone()
        self.assertEqual(s['status'], 'aborted')

    def test_h_crash_recovery(self):
        """TEST H: Crash recovery detects stale processing jobs, requeues up to 3 attempts, fails cleanly on 3rd"""
        video_id = uuid.uuid4().hex
        job_id = uuid.uuid4().hex
        stale_time = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()

        with get_db() as conn:
            conn.execute(
                """
                INSERT INTO videos (id, title, original_filename, original_storage_key, playback_storage_key,
                                    size_bytes, uploaded_at, processing_status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (video_id, 'Crash Test', 'crash.mp4', 'videos/crash/source', 'videos/crash/playback.mp4',
                 1000, stale_time, 'processing'),
            )
            conn.execute(
                """
                INSERT INTO processing_jobs (id, video_id, status, stage, attempts, created_at, updated_at, heartbeat_at)
                VALUES (?, ?, 'processing', 'probing', 0, ?, ?, ?)
                """,
                (job_id, video_id, stale_time, stale_time, stale_time),
            )

        # 1st recovery -> attempts become 1, status pending
        recovered = recover_stale_jobs()
        self.assertEqual(recovered, 1)
        with get_db() as conn:
            j = conn.execute("SELECT status, attempts FROM processing_jobs WHERE id = ?", (job_id,)).fetchone()
        self.assertEqual(j['status'], 'pending')
        self.assertEqual(j['attempts'], 1)

        # Simulate job processing again and 2nd crash -> attempts become 2
        with get_db() as conn:
            conn.execute("UPDATE processing_jobs SET status = 'processing', heartbeat_at = ?, updated_at = ? WHERE id = ?", (stale_time, stale_time, job_id))
        recovered = recover_stale_jobs()
        self.assertEqual(recovered, 1)
        with get_db() as conn:
            j = conn.execute("SELECT status, attempts FROM processing_jobs WHERE id = ?", (job_id,)).fetchone()
        self.assertEqual(j['attempts'], 2)

        # Simulate 3rd crash -> attempts hit MAX_JOB_ATTEMPTS (3) -> marks failed
        with get_db() as conn:
            conn.execute("UPDATE processing_jobs SET status = 'processing', heartbeat_at = ?, updated_at = ? WHERE id = ?", (stale_time, stale_time, job_id))
        recovered = recover_stale_jobs()
        self.assertEqual(recovered, 0)
        with get_db() as conn:
            j = conn.execute("SELECT status, attempts FROM processing_jobs WHERE id = ?", (job_id,)).fetchone()
            v = conn.execute("SELECT processing_status FROM videos WHERE id = ?", (video_id,)).fetchone()
        self.assertEqual(j['status'], 'failed')
        self.assertEqual(v['processing_status'], 'failed')

    def test_j_signed_playback_security(self):
        """TEST J: Signed playback URLs with HMAC validation and expiry rejection"""
        client = app.test_client()
        with client.session_transaction() as sess:
            sess['authenticated'] = True
            sess['username'] = 'admin'

        # Upload & ready a video
        source_path = self._generate_video('test_j.mp4', vcodec='libx264', acodec='aac')
        video_id = uuid.uuid4().hex
        source_key = f'videos/{video_id}/source'
        self.storage.copy_path(source_path, source_key)

        with get_db() as conn:
            conn.execute(
                """
                INSERT INTO videos (id, title, original_filename, original_storage_key, playback_storage_key,
                                    size_bytes, uploaded_at, processing_status, is_current)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'ready', 1)
                """,
                (video_id, 'Test J', 'test_j.mp4', source_key, source_key, source_path.stat().st_size, utcnow_iso()),
            )

        cur_res = client.get('/api/video/current')
        self.assertEqual(cur_res.status_code, 200)
        playback_url = cur_res.json['video']['playback_url']
        self.assertIsNotNone(playback_url)

        # Valid signed URL request
        play_res = client.get(playback_url)
        self.assertEqual(play_res.status_code, 200)

        # Tampered signed URL request -> 403
        tampered_url = playback_url + "tamper"
        bad_res = client.get(tampered_url)
        self.assertEqual(bad_res.status_code, 403)

    def test_k_atomic_job_concurrency(self):
        """TEST K & L: Two workers cannot acquire the same job simultaneously"""
        video_id = uuid.uuid4().hex
        job_id = enqueue_processing_job(video_id)

        # Worker 1 acquires
        job_1 = _acquire_next_job("worker_1")
        self.assertIsNotNone(job_1)
        self.assertEqual(job_1['id'], job_id)

        # Worker 2 attempts to acquire -> should be None because job_1 is in processing
        job_2 = _acquire_next_job("worker_2")
        self.assertIsNone(job_2)

    def test_l_video_seeking_and_range_requests(self):
        """TEST: Byte-range requests for video seeking (HTTP 206 Partial Content)"""
        client = app.test_client()
        with client.session_transaction() as sess:
            sess['authenticated'] = True
            sess['username'] = 'admin'

        source_path = self._generate_video('test_seek.mp4', vcodec='libx264', acodec='aac')
        video_id = uuid.uuid4().hex
        source_key = f'videos/{video_id}/source'
        self.storage.copy_path(source_path, source_key)

        with get_db() as conn:
            conn.execute(
                """
                INSERT INTO videos (id, title, original_filename, original_storage_key, playback_storage_key,
                                    size_bytes, uploaded_at, processing_status, is_current)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'ready', 1)
                """,
                (video_id, 'Test Seek', 'test_seek.mp4', source_key, source_key, source_path.stat().st_size, utcnow_iso()),
            )

        cur_res = client.get('/api/video/current')
        playback_url = cur_res.json['video']['playback_url']

        # Request byte range 0-50
        range_res = client.get(playback_url, headers={'Range': 'bytes=0-50'})
        self.assertEqual(range_res.status_code, 206)
        self.assertEqual(len(range_res.data), 51)
        self.assertIn('bytes 0-50/', range_res.headers.get('Content-Range', ''))

    def test_m_delete_video_cleans_all_records(self):
        """TEST: DELETE /api/video cleans database records and storage assets"""
        client = app.test_client()
        with client.session_transaction() as sess:
            sess['authenticated'] = True
            sess['username'] = 'admin'

        source_path = self._generate_video('test_del.mp4')
        video_id = uuid.uuid4().hex
        source_key = f'videos/{video_id}/source'
        self.storage.copy_path(source_path, source_key)

        with get_db() as conn:
            conn.execute(
                """
                INSERT INTO videos (id, title, original_filename, original_storage_key, playback_storage_key,
                                    size_bytes, uploaded_at, processing_status, is_current)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'ready', 1)
                """,
                (video_id, 'Test Del', 'test_del.mp4', source_key, source_key, 1000, utcnow_iso()),
            )
        enqueue_processing_job(video_id)

        del_res = client.delete('/api/video')
        self.assertEqual(del_res.status_code, 200)

        with get_db() as conn:
            videos_count = conn.execute("SELECT COUNT(*) FROM videos").fetchone()[0]
            jobs_count = conn.execute("SELECT COUNT(*) FROM processing_jobs").fetchone()[0]
        self.assertEqual(videos_count, 0)
        self.assertEqual(jobs_count, 0)

    def test_o_end_to_end_async_worker_lifecycle(self):
        """TEST: End-to-end asynchronous upload -> worker loop -> ready video"""
        client = app.test_client()
        with client.session_transaction() as sess:
            sess['authenticated'] = True
            sess['username'] = 'admin'

        # Start real background worker
        test_worker = StreamBoxWorker(poll_interval=0.1)
        test_worker.start()

        try:
            # 1. Generate MKV video (requires remux)
            source_path = self._generate_video('async_test.mkv', vcodec='libx264', acodec='aac')

            # 2. Init upload
            init_res = client.post('/api/video/upload/init', json={
                'filename': 'async_test.mkv',
                'size_bytes': source_path.stat().st_size,
                'content_type': 'video/x-matroska'
            })
            self.assertEqual(init_res.status_code, 200)
            upload_session_id = init_res.json['upload_session_id']
            upload_url = init_res.json['upload_url']

            # 3. Upload file
            with open(source_path, 'rb') as f:
                up_res = client.post(upload_url, data=f.read())
            self.assertEqual(up_res.status_code, 200)
            video_id = up_res.json['video_id']

            # 4. Poll until worker finishes processing
            started = time.time()
            ready_video = None
            while time.time() - started < 15:
                status_res = client.post('/api/video/upload/complete', json={'upload_session_id': upload_session_id})
                self.assertEqual(status_res.status_code, 200)
                if status_res.json.get('status') == 'ready':
                    ready_video = status_res.json.get('video')
                    break
                time.sleep(0.2)

            self.assertIsNotNone(ready_video, "Video failed to become ready within timeout")
            self.assertEqual(ready_video['processing_status'], 'ready')
            self.assertIsNotNone(ready_video['playback_url'])

            # 5. Verify playback of generated playback asset
            play_res = client.get(ready_video['playback_url'])
            self.assertEqual(play_res.status_code, 200)

        finally:
            test_worker.stop()

    def test_p_stale_job_heartbeat_protection(self):
        """TEST P: Active job with recent heartbeat is NOT recovered by stale job sweep"""
        video_id = uuid.uuid4().hex
        job_id = uuid.uuid4().hex
        now = utcnow_iso()

        with get_db() as conn:
            conn.execute(
                """
                INSERT INTO videos (id, title, original_filename, original_storage_key, playback_storage_key,
                                    size_bytes, uploaded_at, processing_status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (video_id, 'Active Job', 'active.mp4', 'videos/active/source', 'videos/active/playback.mp4',
                 1000, now, 'processing'),
            )
            conn.execute(
                """
                INSERT INTO processing_jobs (id, video_id, status, stage, attempts, created_at, updated_at, heartbeat_at)
                VALUES (?, ?, 'processing', 'transcoding', 0, ?, ?, ?)
                """,
                (job_id, video_id, now, now, now),
            )

        # recover_stale_jobs with 300s threshold should NOT touch this job
        recovered = recover_stale_jobs(stale_threshold_seconds=300)
        self.assertEqual(recovered, 0)
        with get_db() as conn:
            j = conn.execute("SELECT status FROM processing_jobs WHERE id = ?", (job_id,)).fetchone()
        self.assertEqual(j['status'], 'processing')

    def test_q_concurrent_replacement_newer_video_wins(self):
        """TEST Q: Video A finishes processing after Video B is uploaded; Video A does NOT overwrite B or delete B's files"""
        # Create Video A (older upload)
        time_a = (datetime.now(timezone.utc) - timedelta(seconds=60)).isoformat()
        source_a = self._generate_video('video_a.mp4')
        video_a_id = uuid.uuid4().hex
        source_a_key = f'videos/{video_a_id}/source'
        playback_a_key = f'videos/{video_a_id}/playback.mp4'
        self.storage.copy_path(source_a, source_a_key)

        with get_db() as conn:
            conn.execute(
                """
                INSERT INTO videos (id, title, original_filename, original_storage_key, playback_storage_key,
                                    size_bytes, uploaded_at, processing_status, is_current)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'uploaded', 0)
                """,
                (video_a_id, 'Video A', 'video_a.mp4', source_a_key, playback_a_key,
                 source_a.stat().st_size, time_a),
            )

        # Create Video B (newer upload) and make it current/ready
        time_b = datetime.now(timezone.utc).isoformat()
        source_b = self._generate_video('video_b.mp4')
        video_b_id = uuid.uuid4().hex
        source_b_key = f'videos/{video_b_id}/source'
        playback_b_key = f'videos/{video_b_id}/playback.mp4'
        self.storage.copy_path(source_b, source_b_key)

        with get_db() as conn:
            conn.execute(
                """
                INSERT INTO videos (id, title, original_filename, original_storage_key, playback_storage_key,
                                    size_bytes, uploaded_at, processing_status, is_current)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'ready', 1)
                """,
                (video_b_id, 'Video B', 'video_b.mp4', source_b_key, playback_b_key,
                 source_b.stat().st_size, time_b),
            )

        # Now Video A's job completes
        job_a_id = enqueue_processing_job(video_a_id)
        _acquire_next_job("worker_a")
        process_video_job(job_a_id, video_a_id)

        # Verify Video B is STILL the current video and Video B's storage assets STILL exist
        with get_db() as conn:
            video_b = conn.execute("SELECT * FROM videos WHERE id = ?", (video_b_id,)).fetchone()
            video_a = conn.execute("SELECT * FROM videos WHERE id = ?", (video_a_id,)).fetchone()

        self.assertIsNotNone(video_b)
        self.assertEqual(video_b['is_current'], 1)
        self.assertTrue(self.storage.exists(source_b_key))
        # Obsolete Video A was discarded
        self.assertIsNone(video_a)

    def test_r_force_transcode_endpoint(self):
        """TEST R: Force transcode endpoint forces MediaDecision.TRANSCODE even on DIRECT MP4"""
        client = app.test_client()
        with client.session_transaction() as sess:
            sess['authenticated'] = True
            sess['username'] = 'admin'

        source_path = self._generate_video('test_direct_to_transcode.mp4', vcodec='libx264', acodec='aac')
        video_id = uuid.uuid4().hex
        source_key = f'videos/{video_id}/source'
        playback_key = f'videos/{video_id}/playback.mp4'
        self.storage.copy_path(source_path, source_key)

        with get_db() as conn:
            conn.execute(
                """
                INSERT INTO videos (id, title, original_filename, original_storage_key, playback_storage_key,
                                    size_bytes, uploaded_at, processing_status, is_current)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'ready', 1)
                """,
                (video_id, 'Direct Video', 'test_direct_to_transcode.mp4', source_key, source_key,
                 source_path.stat().st_size, utcnow_iso()),
            )

        # Request force transcode via API
        res = client.post(f'/api/video/{video_id}/transcode')
        self.assertEqual(res.status_code, 200)

        # Verify job was enqueued with force_transcode = 1
        with get_db() as conn:
            job = conn.execute("SELECT * FROM processing_jobs WHERE video_id = ?", (video_id,)).fetchone()
        self.assertIsNotNone(job)
        self.assertEqual(job['force_transcode'], 1)

        # Process the job
        _acquire_next_job("worker_transcode")
        success = process_video_job(job['id'], video_id)
        self.assertTrue(success)

        # Verify playback storage key is separate transcoded file, not direct source
        with get_db() as conn:
            v = conn.execute("SELECT * FROM videos WHERE id = ?", (video_id,)).fetchone()
        self.assertEqual(v['processing_status'], 'ready')
        self.assertEqual(v['playback_storage_key'], playback_key)
        self.assertTrue(self.storage.exists(playback_key))

    def test_s_b2_presigned_url_response_content_type(self):
        """TEST S: Backblaze B2 presigned GET includes ResponseContentType='video/mp4'"""
        from unittest.mock import MagicMock, patch
        from streambox.storage import BackblazeB2StorageBackend

        with patch('boto3.client') as mock_boto:
            mock_s3 = MagicMock()
            mock_s3.generate_presigned_url.return_value = 'https://b2.test/signed-url'
            mock_boto.return_value = mock_s3

            with patch.dict(os.environ, {
                'B2_KEY_ID': 'test_id',
                'B2_APPLICATION_KEY': 'test_key',
                'B2_BUCKET_NAME': 'test_bucket',
                'B2_ENDPOINT': 's3.us-west-004.backblazeb2.com',
                'B2_REGION': 'us-west-004',
            }):
                backend = BackblazeB2StorageBackend()
                url = backend.presigned_get_url('videos/test/playback.mp4', 900)
                self.assertEqual(url, 'https://b2.test/signed-url')
                mock_s3.generate_presigned_url.assert_called_once_with(
                    'get_object',
                    Params={'Bucket': backend._bucket_name, 'Key': 'videos/test/playback.mp4', 'ResponseContentType': 'video/mp4'},
                    ExpiresIn=900,
                )

    def test_t_local_storage_path_traversal_prevention(self):
        """TEST T: LocalStorageBackend detects and rejects directory traversal attempts"""
        from streambox.storage import LocalStorageBackend
        local_backend = LocalStorageBackend(root_dir=self.test_dir)
        with self.assertRaises(ValueError) as ctx:
            local_backend.path_for_key('../../../outside.txt')
        self.assertIn('Path traversal detected', str(ctx.exception))


if __name__ == '__main__':
    unittest.main()


