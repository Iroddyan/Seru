"""SQLite-backed Home dashboard."""
from __future__ import annotations

from pathlib import Path

import gi

gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk

from ..database.repository import LibraryRepository
from .library import format_size
from .statistics import EPISODE_MINUTES, MOVIE_MINUTES, format_screen_time


def media_label(row: object) -> str:
    """Create a concise episode or movie label from an indexed row."""
    if row["is_movie"]:
        return "Movie"
    label = f"Episode {row['episode_number']:03d}"
    if row["season_number"] is not None:
        label = f"Season {row['season_number']} · {label}"
    if row["episode_end_number"] is not None:
        label += f"–{row['episode_end_number']:03d}"
    return label


class HomePage(Gtk.ScrolledWindow):
    """Recent Seru activity and index data; never player-resume data."""

    def __init__(self, database_path: Path) -> None:
        super().__init__(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
        self.database_path = database_path
        self.content = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, spacing=18,
            margin_top=18, margin_bottom=24, margin_start=18, margin_end=18,
        )
        clamp = Adw.Clamp(maximum_size=960, tightening_threshold=600)
        clamp.set_child(self.content)
        self.set_child(clamp)

    def _clear(self) -> None:
        while child := self.content.get_first_child():
            self.content.remove(child)

    @staticmethod
    def _section(title: str, rows: list[object], timestamp_key: str) -> Adw.PreferencesGroup:
        group = Adw.PreferencesGroup(title=title)
        if not rows:
            group.set_description("Nothing to show yet.")
            return group
        for row in rows:
            group.add(Adw.ActionRow(
                title=row["title"],
                subtitle=f"{media_label(row)} · {row[timestamp_key]}",
            ))
        return group

    def reload(self) -> None:
        self._clear()
        repository = LibraryRepository(self.database_path)
        try:
            summary, _codecs, _resolutions = repository.library_statistics("default")
            continue_watching, recently_added = repository.home_dashboard("default")
        finally:
            repository.close()

        if summary["titles"] == 0:
            self.content.append(Adw.StatusPage(
                icon_name="go-home-symbolic", title="Welcome to Seru",
                description="Rescan the library to build your local index.",
            ))
            return

        totals = Adw.PreferencesGroup(title="Library totals")
        totals.add(Adw.ActionRow(
            title=f"{summary['titles']} titles · {summary['episodes']} episodes · {summary['movies']} movies",
            subtitle=f"{format_size(summary['total_size'])} · {format_screen_time(summary['episodes'] * EPISODE_MINUTES + summary['movies'] * MOVIE_MINUTES)} estimated screen time",
        ))
        self.content.append(totals)
        self.content.append(self._section("Continue Watching", continue_watching, "timestamp"))
        self.content.append(self._section("Recently Added", recently_added, "discovered_at"))
