"""SQLite-backed library and anime-detail views."""
from __future__ import annotations
from pathlib import Path
import gi
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk
from ..database.repository import LibraryRepository
from ..media.player import CelluloidBackend, PlayerBackend

def format_size(value: int | None) -> str:
    if not value: return "0 B"
    size = float(value)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if size < 1024 or unit == "TiB": return f"{int(size)} B" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return "0 B"

def subtitle_markup(value: str) -> str:
    """Escape filesystem-derived text for Adw.ActionRow's markup subtitle."""
    return GLib.markup_escape_text(value)

class LibraryPage(Gtk.Box):
    """The title list; it only reads SQLite and never walks the library."""
    def __init__(self, database_path: Path, on_open_anime: object) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.database_path, self.on_open_anime = database_path, on_open_anime
        self.list_box = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.list_box.add_css_class("boxed-list")
        self.list_box.connect("row-activated", self._on_row_activated)
        self.count_label = Gtk.Label(xalign=0, margin_top=18, margin_bottom=8, margin_start=18, margin_end=18)
        self.count_label.add_css_class("dim-label")
        self.append(self.count_label)
        scroll = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
        clamp = Adw.Clamp(maximum_size=960, tightening_threshold=600)
        clamp.set_child(self.list_box)
        scroll.set_child(clamp)
        self.content = Gtk.Stack(vexpand=True)
        self.content.add_named(scroll, "results")

        empty_page = Adw.StatusPage(
            icon_name="folder-symbolic",
            title="No titles to show",
            description="Rescan the library after choosing a folder with anime files.",
        )
        self.empty_title = empty_page
        self.content.add_named(empty_page, "empty")
        self.append(self.content)
    def reload(self, search: str = "") -> None:
        while child := self.list_box.get_first_child(): self.list_box.remove(child)
        repository = LibraryRepository(self.database_path)
        try: rows = repository.list_anime("default", search)
        finally: repository.close()
        if not rows:
            if search.strip():
                self.count_label.set_label("No matching titles")
                self.empty_title.set_title("No matching titles")
                self.empty_title.set_description("Try a different search, or clear the search field.")
            else:
                self.count_label.set_label("No titles indexed")
                self.empty_title.set_title("No titles to show")
                self.empty_title.set_description("Rescan the library after choosing a folder with anime files.")
            self.content.set_visible_child_name("empty")
            return

        self.content.set_visible_child_name("results")
        self.count_label.set_label(f"{len(rows)} title{'s' if len(rows) != 1 else ''}")
        for anime in rows:
            row = Adw.ActionRow(title=anime["title"], activatable=True)
            row.anime_id = anime["anime_id"]
            parts = []
            if anime["episode_count"]: parts.append(f"{anime['episode_count']} episode{'s' if anime['episode_count'] != 1 else ''}")
            if anime["movie_count"]: parts.append(f"{anime['movie_count']} movie{'s' if anime['movie_count'] != 1 else ''}")
            parts.append(format_size(anime["total_size"]))
            row.set_subtitle(subtitle_markup(" · ".join(parts)))
            row.add_suffix(Gtk.Image.new_from_icon_name("go-next-symbolic"))
            self.list_box.append(row)
    def _on_row_activated(self, _list_box: Gtk.ListBox, row: Adw.ActionRow) -> None:
        self.on_open_anime(row.anime_id)

class AnimeDetailPage(Gtk.Box):
    """A cached title summary followed by its indexed files."""
    def __init__(self, database_path: Path, library_root: Path, on_back: object,
                 player_backend: PlayerBackend | None = None) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.database_path, self.library_root, self.on_back = database_path, library_root, on_back
        self.player_backend = player_backend or CelluloidBackend()
        self.anime_id: int | None = None
        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()
        back_button = Gtk.Button(icon_name="go-previous-symbolic", tooltip_text="Back to Library")
        back_button.connect("clicked", lambda _button: self.on_back())
        header.pack_start(back_button)
        self.window_title = Adw.WindowTitle(title="", subtitle="")
        header.set_title_widget(self.window_title)
        toolbar.add_top_bar(header)
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.stats_label = Gtk.Label(xalign=0, wrap=True, margin_top=18, margin_bottom=12, margin_start=18, margin_end=18)
        self.stats_label.add_css_class("dim-label")
        content.append(self.stats_label)
        self.playback_status = Gtk.Label(xalign=0, wrap=True, margin_bottom=12, margin_start=18, margin_end=18)
        self.playback_status.add_css_class("dim-label")
        content.append(self.playback_status)
        self.episodes = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.episodes.add_css_class("boxed-list")
        clamp = Adw.Clamp(maximum_size=960, tightening_threshold=600)
        clamp.set_child(self.episodes)
        scroll = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
        scroll.set_child(clamp)
        content.append(scroll)
        toolbar.set_content(content)
        self.append(toolbar)
    def show_anime(self, anime_id: int) -> None:
        self.anime_id = anime_id
        self.playback_status.set_label("")
        while child := self.episodes.get_first_child(): self.episodes.remove(child)
        repository = LibraryRepository(self.database_path)
        try:
            anime, episodes = repository.anime_detail(anime_id, "default"), repository.anime_episodes(anime_id, "default")
        finally: repository.close()
        if anime is None:
            self.window_title.set_title("Title not found")
            self.stats_label.set_label("This title is no longer present in the library index.")
            return
        self.window_title.set_title(anime["title"])
        self.stats_label.set_label(" · ".join((f"{anime['episode_count']} episodes", f"{anime['movie_count']} movies", format_size(anime["total_size"]))))
        for episode in episodes:
            if episode["is_movie"]: title = "Movie"
            elif episode["needs_review"]: title = "Unknown / Needs Review"
            elif episode["season_number"] is None: title = f"Episode {episode['episode_number']:03d}"
            else: title = f"Season {episode['season_number']} · Episode {episode['episode_number']:03d}"
            if episode["episode_end_number"] is not None:
                title += f"–{episode['episode_end_number']:03d}"
            details = []
            if episode["height"]: details.append(f"{episode['height']}p")
            if episode["duration_seconds"]: details.append(f"{round(episode['duration_seconds'] / 60)} min")
            details.append(episode["relative_path"])
            row = Adw.ActionRow(title=title, subtitle=subtitle_markup(" · ".join(details)))
            play_button = Gtk.Button(
                icon_name="media-playback-start-symbolic",
                tooltip_text="Play in Celluloid",
                valign=Gtk.Align.CENTER,
            )
            play_button.connect(
                "clicked",
                self._play_episode,
                int(episode["episode_id"]),
                str(episode["relative_path"]),
            )
            row.add_suffix(play_button)
            self.episodes.append(row)

    def _play_episode(self, _button: Gtk.Button, episode_id: int, relative_path: str) -> None:
        """Record the explicit launch, then hand the file to Celluloid."""
        if self.anime_id is None:
            return
        media_path = self.library_root / relative_path
        repository = LibraryRepository(self.database_path)
        try:
            repository.record_launch(self.anime_id, episode_id)
        except Exception as error:
            self.playback_status.set_label(f"Could not record playback: {error}")
            return
        finally:
            repository.close()
        try:
            self.player_backend.launch(media_path)
        except OSError as error:
            self.playback_status.set_label(f"Could not start Celluloid: {error}")
            return
        self.playback_status.set_label(f"Playing {media_path.name} in Celluloid")
