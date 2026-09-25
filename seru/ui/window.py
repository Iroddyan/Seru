"""The primary Seru application window."""
from __future__ import annotations
import os
from pathlib import Path
import threading
import gi
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk
from ..database.repository import LibraryRepository
from ..library.scan import DEFAULT_LIBRARY_ROOT, default_database_path
from ..library.scanner import LibraryScanner
from .library import AnimeDetailPage, LibraryPage

class SeruWindow(Adw.ApplicationWindow):
    """A GNOME library browser with a worker-thread-only rescan action."""
    def __init__(self, **kwargs: object) -> None:
        super().__init__(default_width=1080, default_height=720, title="Seru", **kwargs)
        self.database_path = default_database_path()
        self.library_root = Path(os.environ.get("SERU_LIBRARY_ROOT", DEFAULT_LIBRARY_ROOT))
        self._rescan_running = False
        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()
        self.search = Gtk.SearchEntry(placeholder_text="Search Library", width_chars=28)
        self.search.connect("search-changed", self._on_search_changed)
        header.pack_start(self.search)
        self.status = Gtk.Label(label="", xalign=1)
        self.status.add_css_class("dim-label")
        header.pack_end(self.status)
        self.rescan_button = Gtk.Button(icon_name="view-refresh-symbolic", tooltip_text="Rescan Library")
        self.rescan_button.connect("clicked", self._start_rescan)
        header.pack_end(self.rescan_button)
        header.set_title_widget(Adw.WindowTitle(title="Seru", subtitle="Library"))
        toolbar.add_top_bar(header)
        root = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, width_request=180, margin_top=12, margin_bottom=12, margin_start=12, margin_end=6)
        label = Gtk.Label(label="Library", xalign=0, margin_start=12)
        label.add_css_class("heading")
        sidebar.append(label)
        navigation = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        library_row = Adw.ActionRow(title="Library", icon_name="folder-symbolic", activatable=True)
        navigation.append(library_row)
        navigation.select_row(library_row)
        navigation.connect("row-selected", lambda _box, _row: self.show_library())
        sidebar.append(navigation)
        root.append(sidebar)
        root.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))
        self.stack = Gtk.Stack(vexpand=True, hexpand=True, transition_type=Gtk.StackTransitionType.CROSSFADE)
        self.library_page = LibraryPage(self.database_path, self.show_anime)
        self.detail_page = AnimeDetailPage(self.database_path, self.show_library)
        self.stack.add_named(self.library_page, "library")
        self.stack.add_named(self.detail_page, "detail")
        root.append(self.stack)
        toolbar.set_content(root)
        self.set_content(toolbar)
        self.show_library()
    def show_library(self) -> None:
        self.search.set_visible(True)
        self.library_page.reload(self.search.get_text())
        self.stack.set_visible_child_name("library")
    def show_anime(self, anime_id: int) -> None:
        self.search.set_visible(False)
        self.detail_page.show_anime(anime_id)
        self.stack.set_visible_child_name("detail")
    def _on_search_changed(self, _entry: Gtk.SearchEntry) -> None:
        if self.stack.get_visible_child_name() == "library": self.library_page.reload(self.search.get_text())
    def _start_rescan(self, _button: Gtk.Button) -> None:
        if self._rescan_running: return
        self._rescan_running = True
        self.rescan_button.set_sensitive(False)
        self.status.set_label("Scanning library…")
        threading.Thread(target=self._rescan_worker, name="seru-library-scan", daemon=True).start()
    def _rescan_worker(self) -> None:
        try:
            repository = LibraryRepository(self.database_path)
            try: result = LibraryScanner(repository, self.library_root).scan()
            finally: repository.close()
            GLib.idle_add(self._finish_rescan, result, None)
        except Exception as error:
            GLib.idle_add(self._finish_rescan, None, str(error))
    def _finish_rescan(self, result: object | None, error: str | None) -> bool:
        self._rescan_running = False
        self.rescan_button.set_sensitive(True)
        if error: self.status.set_label("Scan failed")
        else:
            self.status.set_label(f"Updated · {result.scanned} files")
            self.show_library()
        return False
