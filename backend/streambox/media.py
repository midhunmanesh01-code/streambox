from __future__ import annotations

import glob
import json
import logging
import os
import shutil
import subprocess
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path

log = logging.getLogger(__name__)


class MediaDecision(str, Enum):
    DIRECT = 'DIRECT'
    REMUX = 'REMUX'
    TRANSCODE = 'TRANSCODE'


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
    bitrate: int | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict | None) -> MediaProbe | None:
        if not data:
            return None
        return cls(
            container=data.get('container'),
            video_codec=data.get('video_codec'),
            audio_codec=data.get('audio_codec'),
            has_audio=bool(data.get('has_audio')),
            width=data.get('width'),
            height=data.get('height'),
            duration=data.get('duration'),
            pix_fmt=data.get('pix_fmt'),
            channels=data.get('channels'),
            sample_rate=data.get('sample_rate'),
            bitrate=data.get('bitrate'),
        )


class MediaProcessingError(RuntimeError):
    pass


class MediaValidationError(RuntimeError):
    pass


class InsufficientDiskSpaceError(RuntimeError):
    pass


def _which(name: str) -> str:
    """Return the resolved path of *name* or the bare name if not on PATH."""
    found = shutil.which(name)
    if found:
        return str(found)
    if os.name == 'nt':
        local_appdata = os.getenv('LOCALAPPDATA', '')
        user_profile = os.getenv('USERPROFILE', '')
        candidates = [
            f'{local_appdata}/Microsoft/WinGet/Links/{name}.exe',
            f'{local_appdata}/Microsoft/WinGet/Packages/*/*/{name}.exe',
            f'{local_appdata}/Microsoft/WinGet/Packages/*/*/*/{name}.exe',
            f'C:/Program Files/ffmpeg/bin/{name}.exe',
            f'{user_profile}/scoop/shims/{name}.exe',
            f'C:/ProgramData/chocolatey/bin/{name}.exe',
        ]
        for pattern in candidates:
            matches = glob.glob(pattern)
            if matches:
                return matches[0]
    return name


def probe_media(file_path: Path) -> MediaProbe:
    ffprobe_exe = _which('ffprobe')
    log.info('MEDIA probe_media: ffprobe=%s file=%s exists=%s size=%s',
             ffprobe_exe, file_path, file_path.exists(),
             file_path.stat().st_size if file_path.exists() else 'n/a')

    if not file_path.exists():
        raise MediaValidationError(f'Media file not found: {file_path}')

    if file_path.stat().st_size == 0:
        raise MediaValidationError('Media file is empty.')

    command = [
        ffprobe_exe,
        '-v', 'error',
        '-print_format', 'json',
        '-show_streams',
        '-show_format',
        str(file_path),
    ]

    try:
        result = subprocess.run(command, capture_output=True, text=True, check=False)
    except FileNotFoundError as exc:
        raise MediaValidationError(f'ffprobe executable not found: {exc}') from exc

    if result.returncode != 0:
        err_msg = result.stderr.strip() or 'Unable to inspect the media file.'
        log.warning('MEDIA probe failed: %s', err_msg)
        raise MediaValidationError(err_msg)

    try:
        payload = json.loads(result.stdout or '{}')
    except json.JSONDecodeError as exc:
        log.warning('MEDIA probe JSON parse error: %s', exc)
        raise MediaValidationError(f'ffprobe returned non-JSON output: {exc}') from exc

    streams = payload.get('streams', [])
    format_info = payload.get('format', {})

    video_stream = next((s for s in streams if s.get('codec_type') == 'video'), None)
    audio_stream = next((s for s in streams if s.get('codec_type') == 'audio'), None)

    if not video_stream:
        raise MediaValidationError('The media file does not contain a valid video stream.')

    container = format_info.get('format_name')
    duration_raw = format_info.get('duration') or video_stream.get('duration')
    duration = float(duration_raw) if duration_raw else None

    bitrate_raw = format_info.get('bit_rate') or video_stream.get('bit_rate')
    bitrate = int(bitrate_raw) if bitrate_raw and str(bitrate_raw).isdigit() else None

    probe = MediaProbe(
        container=container,
        video_codec=(video_stream.get('codec_name') or '').lower(),
        audio_codec=(audio_stream.get('codec_name') or '').lower() if audio_stream else None,
        has_audio=audio_stream is not None,
        width=int(video_stream['width']) if video_stream.get('width') is not None else None,
        height=int(video_stream['height']) if video_stream.get('height') is not None else None,
        duration=duration,
        pix_fmt=video_stream.get('pix_fmt'),
        channels=int(audio_stream['channels']) if audio_stream and audio_stream.get('channels') is not None else None,
        sample_rate=int(audio_stream['sample_rate']) if audio_stream and audio_stream.get('sample_rate') is not None else None,
        bitrate=bitrate,
    )
    return probe


def has_browser_compatible_streams(probe: MediaProbe) -> bool:
    """Return True if video codec is H.264, pixel format is 8-bit YUV 4:2:0, and audio is AAC or MP3."""
    is_h264 = probe.video_codec in ('h264', 'avc1')
    compatible_pix_fmt = probe.pix_fmt in ('yuv420p', 'yuvj420p')
    compatible_audio = (not probe.has_audio) or (probe.audio_codec in ('aac', 'mp3'))
    return is_h264 and compatible_pix_fmt and compatible_audio


def is_mp4_container(probe: MediaProbe) -> bool:
    """Return True if the container is an MP4/QuickTime format supported by browsers."""
    if not probe.container:
        return False
    formats = {fmt.strip().lower() for fmt in probe.container.split(',')}
    return bool(formats & {'mp4', 'm4a', 'm4v'})


def decide_media_processing(probe: MediaProbe) -> MediaDecision:
    """Centralized authoritative decision logic: DIRECT, REMUX, or TRANSCODE."""
    if is_mp4_container(probe) and has_browser_compatible_streams(probe):
        return MediaDecision.DIRECT

    if has_browser_compatible_streams(probe):
        return MediaDecision.REMUX

    return MediaDecision.TRANSCODE


def calculate_required_disk_space(source_size_bytes: int, decision: MediaDecision | str) -> int:
    """Calculate conservative required disk space in bytes based on file size and processing type."""
    safety_buffer = 256 * 1024 * 1024  # 256 MB buffer
    decision_str = decision.value if isinstance(decision, MediaDecision) else str(decision).upper()

    if decision_str == MediaDecision.DIRECT.value:
        return source_size_bytes + (128 * 1024 * 1024)
    elif decision_str == MediaDecision.REMUX.value:
        return (source_size_bytes * 2) + safety_buffer
    else:  # TRANSCODE
        return int(source_size_bytes * 2.5) + (512 * 1024 * 1024)


def check_disk_space(directory: Path, required_bytes: int) -> tuple[bool, int, int]:
    """Check if the given directory has sufficient free disk space."""
    directory.mkdir(parents=True, exist_ok=True)
    usage = shutil.disk_usage(directory)
    has_space = usage.free >= required_bytes
    return has_space, usage.free, required_bytes


def build_transcode_command(input_path: Path, output_path: Path, probe: MediaProbe) -> list[str]:
    ffmpeg_exe = _which('ffmpeg')
    command = [
        ffmpeg_exe,
        '-y',
        '-i', str(input_path),
        '-c:v', 'libx264',
        '-pix_fmt', 'yuv420p',
        '-preset', 'fast',
        '-crf', '23',
    ]

    if probe.has_audio:
        command.extend([
            '-c:a', 'aac',
            '-b:a', '128k',
            '-ac', '2',
        ])
    else:
        command.extend(['-an'])

    command.extend([
        '-f', 'mp4',
        '-movflags', '+faststart',
        str(output_path),
    ])
    return command


def transcode_for_browser(input_path: Path, output_path: Path, probe: MediaProbe) -> None:
    ffmpeg_exe = _which('ffmpeg')
    log.info('MEDIA transcode_for_browser: input=%s output=%s', input_path, output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    command = build_transcode_command(input_path, output_path, probe)
    result = subprocess.run(command, capture_output=True, text=True, check=False)

    if result.returncode != 0:
        stderr_tail = (result.stderr or '').strip()[-1000:]
        log.warning('MEDIA transcode failed with code %d: %s', result.returncode, stderr_tail)
        raise MediaProcessingError(stderr_tail or 'Failed to transcode video to browser-compatible MP4.')


def remux_for_browser(input_path: Path, output_path: Path) -> None:
    ffmpeg_exe = _which('ffmpeg')
    log.info('MEDIA remux_for_browser: input=%s output=%s', input_path, output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    command = [
        ffmpeg_exe,
        '-y',
        '-i', str(input_path),
        '-map', '0:v:0',
        '-map', '0:a:0?',
        '-c', 'copy',
        '-f', 'mp4',
        '-movflags', '+faststart',
        str(output_path),
    ]

    result = subprocess.run(command, capture_output=True, text=True, check=False)

    if result.returncode != 0:
        stderr_tail = (result.stderr or '').strip()[-1000:]
        log.warning('MEDIA remux failed with code %d: %s', result.returncode, stderr_tail)
        raise MediaProcessingError(stderr_tail or 'Failed to remux video to browser-compatible MP4.')


def verify_playback_asset(output_path: Path, source_had_audio: bool = False) -> MediaProbe:
    """Verify that the generated playback file is non-empty, valid MP4, and browser-playable."""
    if not output_path.exists():
        raise MediaProcessingError(f'Playback output file was not generated: {output_path}')

    size = output_path.stat().st_size
    if size == 0:
        raise MediaProcessingError('Playback output file is empty (0 bytes).')

    # Probe the generated output
    probe = probe_media(output_path)

    # 1. Video stream verification
    if probe.video_codec not in ('h264', 'avc1'):
        raise MediaProcessingError(f'Generated playback video codec ({probe.video_codec}) is not browser-compatible H.264.')

    if probe.pix_fmt not in ('yuv420p', 'yuvj420p'):
        raise MediaProcessingError(f'Generated playback pixel format ({probe.pix_fmt}) is not browser-compatible YUV420P.')

    # 2. Audio stream verification
    if source_had_audio:
        if not probe.has_audio:
            raise MediaProcessingError('Playback asset lost audio stream during processing.')
        if probe.audio_codec not in ('aac', 'mp3'):
            raise MediaProcessingError(f'Generated playback audio codec ({probe.audio_codec}) is not browser-compatible AAC/MP3.')

    # 3. Container verification
    if not is_mp4_container(probe):
        raise MediaProcessingError(f'Generated playback container ({probe.container}) is not a valid MP4 format.')

    return probe

