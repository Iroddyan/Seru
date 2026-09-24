"""Application entry point."""

from __future__ import annotations

import sys

import gi

gi.require_version("Adw", "1")
from gi.repository import Adw, Gio

from . import APP_ID
from .ui.window import SeruWindow


class SeruApplication(Adw.Application):
    """The top-level Seru application."""

    def __init__(self) -> None:
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)

    def do_activate(self) -> None:
        window = self.props.active_window
        if window is None:
            window = SeruWindow(application=self)
        window.present()


def main() -> int:
    """Start the GNOME application."""
    app = SeruApplication()
    return app.run(sys.argv)
