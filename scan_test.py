#!/usr/bin/env python3
"""Small, throwaway smoke test for Seru's local media toolchain."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys


DEFAULT_LIBRARY_ROOT = "/run/media/iroddyan/Warehouse/Theatre/Anime"
VIDEO_EXTENSIONS = {".mkv", ".mp4", ".avi", ".webm", ".mov", ".m4v"}
MAX_CANDIDATES = 5


def find_video_files(library_root: Path) -> list[Path]:
    """Return a small set of videos without loading the whole tree into memory."""
    found: list[Path] = []
    for root, _directories, filenames in os.walk(library_root):
        for filename in filenames:
            candidate = Path(root, filename)
            if candidate.suffix.lower() in VIDEO_EXTENSIONS:
                found.append(candidate)
                if len(found) == MAX_CANDIDATES:
                    return found
    return found


def probe_media(video_file: Path) -> dict[str, object]:
    completed = subprocess.run(
        [
            "ffprobe",
            "-v",
            "quiet",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(video_file),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    metadata = json.loads(completed.stdout)
    video_stream = next(
        (stream for stream in metadata.get("streams", []) if stream.get("codec_type") == "video"),
        None,
    )
    if video_stream is None:
        raise ValueError("ffprobe found no video stream")

    return {
        "file": str(video_file),
        "codec": video_stream.get("codec_name", "unknown"),
        "resolution": f'{video_stream.get("width", "?")}x{video_stream.get("height", "?")}',
        "duration": metadata.get("format", {}).get("duration", "unknown"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "library_root",
        nargs="?",
        default=os.environ.get("SERU_LIBRARY_ROOT", DEFAULT_LIBRARY_ROOT),
        help="Library directory to inspect (default: configured Anime collection)",
    )
    args = parser.parse_args()
    library_root = Path(args.library_root)

    if not library_root.is_dir():
        print(f"Library root is not a directory: {library_root}", file=sys.stderr)
        return 2

    candidates = find_video_files(library_root)
    print(f"Found {len(candidates)} candidate video file(s).")
    if not candidates:
        return 1

    try:
        print(probe_media(candidates[0]))
    except (subprocess.CalledProcessError, json.JSONDecodeError, OSError, ValueError) as error:
        print(f"Could not probe {candidates[0]}: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
