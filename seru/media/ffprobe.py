"""Safe, subprocess-based ffprobe metadata extraction."""
from __future__ import annotations
from dataclasses import dataclass
import json
from pathlib import Path
import subprocess

@dataclass(frozen=True)
class MediaMetadata:
    video_codec: str | None
    audio_codec: str | None
    width: int | None
    height: int | None
    duration_seconds: float | None

def probe_media(file_path: Path) -> MediaMetadata:
    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams", str(file_path)],
        capture_output=True, text=True, check=True, timeout=30,
    )
    data = json.loads(result.stdout)
    streams = data.get("streams", [])
    video = next((item for item in streams if item.get("codec_type") == "video"), {})
    audio = next((item for item in streams if item.get("codec_type") == "audio"), {})
    try:
        duration = float(data.get("format", {}).get("duration"))
    except (TypeError, ValueError):
        duration = None
    return MediaMetadata(video.get("codec_name"), audio.get("codec_name"), video.get("width"), video.get("height"), duration)
