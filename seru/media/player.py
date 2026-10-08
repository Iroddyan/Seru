"""Safe external playback backends for Seru."""
from __future__ import annotations

from pathlib import Path
from typing import Protocol
import subprocess


class PlayerBackend(Protocol):
    """The intentionally small contract Seru needs from an external player."""

    def launch(self, media_path: Path) -> subprocess.Popen[object]:
        """Start playback without waiting for the player to exit."""


class CelluloidBackend:
    """Launch media in Celluloid using an argument list, never a shell."""

    def launch(self, media_path: Path) -> subprocess.Popen[object]:
        return subprocess.Popen(["celluloid", str(media_path)])
