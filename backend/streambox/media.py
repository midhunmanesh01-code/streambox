from __future__ import annotations

import json
import logging
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)


@dataclass(slots=True)
class MediaProbe:
    container: str | None
    video_codec: str | None
    audio_codec: str | None
    has_audio: bool
    width: int | None
    height: int | None
    duration: float | None
    pix_fmt: str | None
    channels: int | None
    sample_rate: int | None


class MediaProcessingError(RuntimeError):
    pass


class MediaValidationError(RuntimeError):
    pass


def _which(name: str) -> str:
    """Return the resolved path of *name* or the bare name if not on PATH."""
    found = shutil.which(name)
    return str(found) if found else name


def probe_media(file_path: Path) -> MediaProbe:
    ffprobe_exe = _which('ffprobe')
    log.warning('MEDIA probe_media: ffprobe=%s file=%s exists=%s size=%s',
                ffprobe_exe, file_path, file_path.exists(),
                file_path.stat().st_size if file_path.exists() else 'n/a')

    command = [
        ffprobe_exe,
        '-v', 'error',
        '-print_format', 'json',
        '-show_streams',
        '-show_format',
        str(file_path),
    ]
    log.warning('MEDIA probe command: %s', command)

    result = subprocess.run(command, capture_output=True, text=True, check=False)
    log.warning('MEDIA probe returncode=%d stdout_len=%d stderr_len=%d',
                result.returncode, len(result.stdout or ''), len(result.stderr or ''))
    if result.stderr.strip():
        log.warning('MEDIA probe stderr: %s', result.stderr.strip())
    if result.returncode != 0:
        raise MediaValidationError(result.stderr.strip() or 'Unable to inspect the uploaded media.')

    try:
        payload = json.loads(result.stdout or '{}')
    except json.JSONDecodeError as exc:
        log.warning('MEDIA probe JSON parse error: %s — raw stdout: %.500s', exc, result.stdout)
        raise MediaValidationError(f'ffprobe returned non-JSON output: {exc}') from exc

    streams = payload.get('streams', [])
    format_info = payload.get('format', {})
    log.warning('MEDIA probe format=%s streams=%d format_name=%s duration=%s',
                format_info.get('format_name'), len(streams),
                format_info.get('format_name'), format_info.get('duration'))
    for i, s in enumerate(streams):
        log.warning('MEDIA probe stream[%d] type=%s codec=%s pix_fmt=%s w=%s h=%s',
                    i, s.get('codec_type'), s.get('codec_name'),
                    s.get('pix_fmt'), s.get('width'), s.get('height'))

    video_stream = next((s for s in streams if s.get('codec_type') == 'video'), None)
    audio_stream = next((s for s in streams if s.get('codec_type') == 'audio'), None)

    if not video_stream:
        raise MediaValidationError('The uploaded file does not contain a valid video stream.')

    container = format_info.get('format_name')
    duration_raw = format_info.get('duration')
    duration = float(duration_raw) if duration_raw else None

    probe = MediaProbe(
        container=container,
        video_codec=video_stream.get('codec_name'),
        audio_codec=audio_stream.get('codec_name') if audio_stream else None,
        has_audio=audio_stream is not None,
        width=int(video_stream['width']) if video_stream.get('width') is not None else None,
        height=int(video_stream['height']) if video_stream.get('height') is not None else None,
        duration=duration,
        pix_fmt=video_stream.get('pix_fmt'),
        channels=int(audio_stream['channels']) if audio_stream and audio_stream.get('channels') is not None else None,
        sample_rate=int(audio_stream['sample_rate']) if audio_stream and audio_stream.get('sample_rate') is not None else None,
    )
    log.warning('MEDIA probe result: %s', probe)
    return probe


def build_ffmpeg_command(input_path: Path, output_path: Path, probe: MediaProbe) -> list[str]:
    ffmpeg_exe = _which('ffmpeg')
    command = [ffmpeg_exe, '-y', '-i', str(input_path)]

    command.extend([
        '-c:v', 'libx264',
        '-pix_fmt', 'yuv420p',
        '-preset', 'veryfast',
        '-crf', '22',
    ])

    if probe.has_audio:
        command.extend([
            '-c:a', 'aac',
            '-b:a', '192k',
            '-ac', '2',
        ])
    else:
        command.extend(['-an'])

    command.extend([
        '-movflags', '+faststart',
        str(output_path),
    ])
    return command


def transcode_for_browser(input_path: Path, output_path: Path, probe: MediaProbe) -> None:
    ffmpeg_exe = _which('ffmpeg')
    log.warning('MEDIA transcode_for_browser: ffmpeg=%s input=%s output=%s', ffmpeg_exe, input_path, output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    command = build_ffmpeg_command(input_path, output_path, probe)
    log.warning('MEDIA transcode command: %s', command)
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    log.warning('MEDIA transcode returncode=%d output_exists=%s output_size=%s',
                result.returncode,
                output_path.exists(),
                output_path.stat().st_size if output_path.exists() else 'n/a')
    if result.stderr.strip():
        # ffmpeg writes progress to stderr; log the tail where errors appear
        stderr_tail = result.stderr.strip()[-2000:]
        log.warning('MEDIA transcode stderr (tail): %s', stderr_tail)
    if result.returncode != 0:
        raise MediaProcessingError(result.stderr.strip()[-500:] or 'Unable to prepare the playback version.')


def remux_for_browser(input_path: Path, output_path: Path) -> None:
    ffmpeg_exe = _which('ffmpeg')
    log.warning('MEDIA remux_for_browser: ffmpeg=%s input=%s output=%s', ffmpeg_exe, input_path, output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        ffmpeg_exe, '-y', '-i', str(input_path),
        '-map', '0:v:0',
        '-map', '0:a:0?',
        '-c', 'copy',
        '-movflags', '+faststart',
        str(output_path),
    ]
    log.warning('MEDIA remux command: %s', command)
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    log.warning('MEDIA remux returncode=%d output_exists=%s output_size=%s',
                result.returncode,
                output_path.exists(),
                output_path.stat().st_size if output_path.exists() else 'n/a')
    if result.stderr.strip():
        stderr_tail = result.stderr.strip()[-2000:]
        log.warning('MEDIA remux stderr (tail): %s', stderr_tail)
    if result.returncode != 0:
        raise MediaProcessingError(result.stderr.strip()[-500:] or 'Unable to remux the playback version.')
