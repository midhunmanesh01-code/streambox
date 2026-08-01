from __future__ import annotations

import json
import math
import subprocess
from dataclasses import dataclass
from pathlib import Path


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


def probe_media(file_path: Path) -> MediaProbe:
    command = [
        'ffprobe',
        '-v',
        'error',
        '-print_format',
        'json',
        '-show_streams',
        '-show_format',
        str(file_path),
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise MediaValidationError(result.stderr.strip() or 'Unable to inspect the uploaded media.')

    payload = json.loads(result.stdout or '{}')
    streams = payload.get('streams', [])
    format_info = payload.get('format', {})

    video_stream = next((stream for stream in streams if stream.get('codec_type') == 'video'), None)
    audio_stream = next((stream for stream in streams if stream.get('codec_type') == 'audio'), None)

    if not video_stream:
        raise MediaValidationError('The uploaded file does not contain a valid video stream.')

    container = format_info.get('format_name')
    duration_raw = format_info.get('duration')
    duration = float(duration_raw) if duration_raw else None

    return MediaProbe(
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


def build_ffmpeg_command(input_path: Path, output_path: Path, probe: MediaProbe) -> list[str]:
    command = ['ffmpeg', '-y', '-i', str(input_path)]

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
    output_path.parent.mkdir(parents=True, exist_ok=True)
    command = build_ffmpeg_command(input_path, output_path, probe)
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise MediaProcessingError(result.stderr.strip() or 'Unable to prepare the playback version.')
