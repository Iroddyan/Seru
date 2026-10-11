"""Debounced, event-driven monitoring of one mounted library tree."""
from __future__ import annotations

import os
from pathlib import Path
import gi
gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib


class LibraryWatcher:
    def __init__(self, root: Path, on_paths_changed: object, debounce_ms: int = 1800) -> None:
        self.root = root.resolve()
        self.on_paths_changed = on_paths_changed
        self.debounce_ms = debounce_ms
        self.monitors: dict[str, Gio.FileMonitor] = {}
        self.pending: set[Path] = set()
        self.timeout_id = 0
        self.start()

    def start(self) -> None:
        if not self.root.is_dir():
            return
        for current, directories, _files in os.walk(self.root):
            directories[:] = [name for name in directories
                              if not name.startswith(".") and name not in {"_Needs Manual Sorting", "_Duplicate Review"}]
            self._watch_directory(Path(current))

    def _watch_directory(self, directory: Path) -> None:
        key = str(directory)
        if key in self.monitors:
            return
        try:
            monitor = Gio.File.new_for_path(key).monitor_directory(Gio.FileMonitorFlags.WATCH_MOVES, None)
            monitor.connect("changed", self._changed)
            self.monitors[key] = monitor
        except (GLib.Error, OSError):
            pass

    def _changed(self, _monitor: Gio.FileMonitor, file: Gio.File, other: Gio.File | None,
                 _event: Gio.FileMonitorEvent) -> None:
        for changed in (file, other):
            if changed is None:
                continue
            path_text = changed.get_path()
            if not path_text:
                continue
            path = Path(path_text)
            if not path.exists():
                prefix = str(path).rstrip(os.sep) + os.sep
                for key in list(self.monitors):
                    if key == str(path) or key.startswith(prefix):
                        self.monitors.pop(key).cancel()
            if path.is_dir() and path.exists():
                for current, directories, _files in os.walk(path):
                    directories[:] = [name for name in directories
                                      if not name.startswith(".") and name not in {"_Needs Manual Sorting", "_Duplicate Review"}]
                    self._watch_directory(Path(current))
            self.pending.add(path)
        if self.timeout_id:
            GLib.source_remove(self.timeout_id)
        self.timeout_id = GLib.timeout_add(self.debounce_ms, self._flush)

    def _flush(self) -> bool:
        self.timeout_id = 0
        paths, self.pending = self.pending, set()
        if paths:
            self.on_paths_changed(paths)
        return GLib.SOURCE_REMOVE

    def close(self) -> None:
        if self.timeout_id:
            GLib.source_remove(self.timeout_id)
            self.timeout_id = 0
        for monitor in self.monitors.values():
            monitor.cancel()
        self.monitors.clear()
