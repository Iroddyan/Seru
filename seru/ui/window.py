"""The primary Seru application window."""

from __future__ import annotations

import gi

gi.require_version("Adw", "1")
from gi.repository import Adw


class SeruWindow(Adw.ApplicationWindow):
    """Minimal native window; library views are added in later phases."""

    def __init__(self, **kwargs: object) -> None:
        super().__init__(default_width=960, default_height=640, title="Seru", **kwargs)
