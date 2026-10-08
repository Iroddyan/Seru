"""SQLite-backed library statistics view."""
from __future__ import annotations

from pathlib import Path

import gi

gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk

from ..database.repository import LibraryRepository
from .library import format_size


EPISODE_MINUTES = 24
MOVIE_MINUTES = 110


def format_screen_time(minutes: int) -> str:
    """Present the smart-list estimate in a compact, readable form."""
    days, remainder = divmod(minutes, 24 * 60)
    hours = remainder // 60
    if days:
        return f"{days} day{'s' if days != 1 else ''}, {hours} hr"
    return f"{hours} hr"


class StatisticsPage(Gtk.ScrolledWindow):
    """Display stored library aggregates without rescanning the filesystem."""

    def __init__(self, database_path: Path) -> None:
        super().__init__(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
        self.database_path = database_path
        self.content = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=18,
            margin_top=18,
            margin_bottom=24,
            margin_start=18,
            margin_end=18,
        )
        clamp = Adw.Clamp(maximum_size=960, tightening_threshold=600)
        clamp.set_child(self.content)
        self.set_child(clamp)

    @staticmethod
    def _clear(container: Gtk.Box) -> None:
        while child := container.get_first_child():
            container.remove(child)

    @staticmethod
    def _add_row(group: Adw.PreferencesGroup, title: str, subtitle: str) -> None:
        group.add(Adw.ActionRow(title=title, subtitle=subtitle))

    def reload(self) -> None:
        self._clear(self.content)
        repository = LibraryRepository(self.database_path)
        try:
            summary, codecs, resolutions = repository.library_statistics("default")
        finally:
            repository.close()

        if summary["titles"] == 0:
            self.content.append(Adw.StatusPage(
                icon_name="view-list-symbolic",
                title="No statistics yet",
                description="Rescan the library to build the local index.",
            ))
            return

        totals = Adw.PreferencesGroup(title="Library")
        self._add_row(totals, "Titles", str(summary["titles"]))
        self._add_row(totals, "Episodes", str(summary["episodes"]))
        self._add_row(totals, "Movies", str(summary["movies"]))
        self._add_row(totals, "Storage", format_size(summary["total_size"]))
        minutes = summary["episodes"] * EPISODE_MINUTES + summary["movies"] * MOVIE_MINUTES
        self._add_row(totals, "Estimated screen time", format_screen_time(minutes))
        self.content.append(totals)

        codec_group = Adw.PreferencesGroup(title="Video codecs")
        for row in codecs:
            label = "Unknown" if row["label"] == "unknown" else row["label"].upper()
            self._add_row(codec_group, label, f"{row['file_count']} files · {format_size(row['total_size'])}")
        self.content.append(codec_group)

        resolution_group = Adw.PreferencesGroup(title="Resolutions")
        for row in resolutions:
            label = "Unknown" if row["label"] == "unknown" else row["label"]
            self._add_row(resolution_group, label, f"{row['file_count']} files · {format_size(row['total_size'])}")
        self.content.append(resolution_group)
