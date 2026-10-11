"""User-owned local preferences for Seru."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

LIBRARY_TYPES = ("anime", "tv", "movies", "cartoons")
LIBRARY_LABELS = {"anime": "Anime", "tv": "TV Shows", "movies": "Movies", "cartoons": "Cartoons"}


def settings_path() -> Path:
    base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "seru" / "settings.json"


class Settings:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or settings_path()
        self.data: dict[str, Any] = {
            "display_name": "", "last_library": "anime", "libraries": {},
            "theme": "system", "watch_changes": True, "advanced_pin_hash": "",
            "scan_on_startup": True,
        }
        try:
            stored = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(stored, dict):
                self.data.update(stored)
        except (OSError, json.JSONDecodeError):
            pass

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        temporary.replace(self.path)

    def library_path(self, library_type: str) -> Path | None:
        value = self.data.get("libraries", {}).get(library_type)
        if value:
            return Path(value).expanduser()
        if library_type == "anime" and os.environ.get("SERU_LIBRARY_ROOT"):
            return Path(os.environ["SERU_LIBRARY_ROOT"]).expanduser()
        return None

    def set_library_path(self, library_type: str, path: Path | None) -> None:
        libraries = self.data.setdefault("libraries", {})
        if path is None:
            libraries.pop(library_type, None)
        else:
            libraries[library_type] = str(path.expanduser().resolve())

