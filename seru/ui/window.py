"""Primary Seru window with library switching, setup, and event-driven scans."""
from __future__ import annotations

from pathlib import Path
import threading
import gi
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk

from ..config.settings import LIBRARY_LABELS, LIBRARY_TYPES, Settings
from ..database.repository import LibraryRepository
from ..library.scan import default_database_path
from ..library.scanner import LibraryScanner
from ..library.watcher import LibraryWatcher
from .dashboard import HomePage
from .library import AnimeDetailPage, LibraryPage
from ..library.organizer import OrganizationPlan, apply_plan, build_plan, undo_manifest
from .setup import SetupPage
from .statistics import StatisticsPage
from .settings import SettingsWindow

APP_ICON_PATH = Path(__file__).resolve().parents[2] / "seru-icon.svg"


class SeruWindow(Adw.ApplicationWindow):
    def __init__(self, **kwargs: object) -> None:
        super().__init__(default_width=1120, default_height=760, title="Seru", **kwargs)
        self.database_path = default_database_path()
        self.settings = Settings()
        theme = self.settings.data.get("theme", "system")
        Adw.StyleManager.get_default().set_color_scheme({
            "system": Adw.ColorScheme.DEFAULT, "light": Adw.ColorScheme.FORCE_LIGHT,
            "dark": Adw.ColorScheme.FORCE_DARK,
        }.get(theme, Adw.ColorScheme.DEFAULT))
        self.library_type = "anime"
        self.library_root: Path | None = None
        self.location_id = "default"
        self.folder_filter: str | None = None
        self.favorites_only = False
        self.active_view = "library"
        self._rescan_running = False
        self._deferred_paths: dict[tuple[str, str, str], set[Path]] = {}
        self._watchers: dict[str, LibraryWatcher] = {}
        self._building_setup = not bool(self.settings.data.get("display_name"))

        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()
        self.search = Gtk.SearchEntry(placeholder_text="Search", width_chars=24)
        self.search.connect("search-changed", self._on_search_changed)
        header.pack_start(self.search)
        self.status = Gtk.Label(label="", xalign=1)
        self.status.add_css_class("dim-label")
        header.pack_end(self.status)
        self.organize_button = Gtk.Button(icon_name="folder-move-symbolic", tooltip_text="Organize files")
        self.organize_button.connect("clicked", self._organize)
        header.pack_end(self.organize_button)
        self.undo_button = Gtk.Button(icon_name="edit-undo-symbolic", tooltip_text="Undo last organization")
        self.undo_button.connect("clicked", self._undo_organization)
        self.undo_button.set_visible(bool(self.settings.data.get("last_organization_manifest")))
        header.pack_end(self.undo_button)
        self.rescan_button = Gtk.Button(icon_name="view-refresh-symbolic", tooltip_text="Scan for changes")
        self.rescan_button.connect("clicked", self._start_rescan)
        header.pack_end(self.rescan_button)
        self.settings_button = Gtk.Button(icon_name="emblem-system-symbolic", tooltip_text="Settings")
        self.settings_button.connect("clicked", self._open_settings)
        header.pack_end(self.settings_button)
        brand = Gtk.Box(spacing=8, valign=Gtk.Align.CENTER)
        logo = Gtk.Image.new_from_file(str(APP_ICON_PATH))
        logo.set_pixel_size(28)
        brand.append(logo)
        self.window_title = Adw.WindowTitle(title="Seru", subtitle="")
        brand.append(self.window_title)
        header.set_title_widget(brand)
        toolbar.add_top_bar(header)

        self.stack = Gtk.Stack(vexpand=True, hexpand=True, transition_type=Gtk.StackTransitionType.CROSSFADE)
        self.setup_page = SetupPage(self.settings, self._setup_completed)
        self.library_page = LibraryPage(self.database_path, self.show_title)
        self.detail_page = AnimeDetailPage(self.database_path, Path("/"), self.show_active_view)
        self.statistics_page = StatisticsPage(self.database_path)
        self.home_page = HomePage(self.database_path)
        self.home_page.display_name = self.settings.data.get("display_name", "")
        self.stack.add_named(self.setup_page, "setup")
        self.stack.add_named(self.library_page, "library")
        self.stack.add_named(self.detail_page, "detail")
        self.stack.add_named(self.statistics_page, "statistics")
        self.stack.add_named(self.home_page, "home")
        self.set_content(toolbar)
        toolbar.set_content(self.stack)

        if self._building_setup:
            self.stack.set_visible_child_name("setup")
            self.search.set_visible(False)
            self.organize_button.set_visible(False)
            self.undo_button.set_visible(False)
            self.rescan_button.set_visible(False)
        else:
            self._build_navigation(toolbar)
            self._select_library(str(self.settings.data.get("last_library", "anime")), scan=False)
            self._reset_watchers()
            if self.settings.data.get("scan_on_startup", True):
                self._start_startup_scans()

    def _build_navigation(self, toolbar: Adw.ToolbarView) -> None:
        if self.stack.get_parent() is not None:
            self.stack.unparent()
        root = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, width_request=210,
                          margin_top=12, margin_bottom=12, margin_start=12, margin_end=6)
        switch_group = Adw.PreferencesGroup(title="Libraries")
        self.library_model = Gtk.StringList.new([LIBRARY_LABELS[kind] for kind in LIBRARY_TYPES])
        self.library_switcher = Gtk.DropDown(model=self.library_model, hexpand=True)
        switch_group.add(self.library_switcher)
        sidebar.append(switch_group)
        self.library_switcher.connect("notify::selected", self._on_library_selected)
        navigation = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        navigation.add_css_class("navigation-sidebar")
        self.navigation_rows = {}
        for view, label, icon in (
            ("home", "Home", "go-home-symbolic"), ("library", "Library", "folder-symbolic"),
            ("watching", "Watching", "media-playlist-repeat-symbolic"),
            ("downloads", "Downloads", "folder-download-symbolic"),
            ("favorites", "Favorites", "starred-symbolic"), ("statistics", "Statistics", "view-list-symbolic"),
        ):
            row = Adw.ActionRow(title=label, icon_name=icon, activatable=True)
            row.view_name = view
            navigation.append(row)
            self.navigation_rows[view] = row
        navigation.connect("row-selected", self._on_navigation_selected)
        sidebar.append(navigation)
        root.append(sidebar)
        root.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))
        root.append(self.stack)
        toolbar.set_content(root)
        self.navigation = navigation

    def _setup_completed(self) -> None:
        self._building_setup = False
        self._build_navigation(self.get_content())
        self._select_library("anime", scan=False)
        self._reset_watchers()
        self._start_startup_scans()

    def _on_library_selected(self, dropdown: Gtk.DropDown, _pspec: object) -> None:
        index = dropdown.get_selected()
        if index < len(LIBRARY_TYPES):
            self._select_library(LIBRARY_TYPES[index], scan=True)

    def _select_library(self, kind: str, scan: bool = False) -> None:
        if kind not in LIBRARY_TYPES:
            kind = "anime"
        self.library_type = kind
        self.location_id = "default" if kind == "anime" else kind
        self.library_root = self.settings.library_path(kind)
        self.settings.data["last_library"] = kind
        self.settings.save()
        if hasattr(self, "library_switcher"):
            self.library_switcher.set_selected(LIBRARY_TYPES.index(kind))
        title = LIBRARY_LABELS[kind]
        name = self.settings.data.get("display_name", "")
        self.window_title.set_title("Seru")
        self.window_title.set_subtitle(f"{name} · {title}" if name else title)
        self.library_page.location_id = self.location_id
        self.library_page.empty_description = (
            "Choose a folder for this library in Settings to get started."
            if self.library_root is None else
            ("This library folder is unavailable. Connect its drive and scan again."
             if not self.library_root.is_dir() else
             "This library is empty. Add media to its folder, then scan for changes.")
        )
        self.detail_page.library_root = self.library_root or Path("/")
        self.detail_page.location_id = self.location_id
        self.statistics_page.location_id = self.location_id
        self.home_page.location_id = self.location_id
        self.home_page.display_name = self.settings.data.get("display_name", "")
        self.folder_filter = None
        self.favorites_only = False
        self.show_library()
        if scan and self.library_root and self.library_root.is_dir():
            self._start_rescan(None)

    def _reset_watchers(self) -> None:
        for watcher in self._watchers.values():
            watcher.close()
        self._watchers.clear()
        if not self.settings.data.get("watch_changes", True):
            return
        for kind in LIBRARY_TYPES:
            root = self.settings.library_path(kind)
            if root and root.is_dir():
                location = "default" if kind == "anime" else kind
                self._watchers[kind] = LibraryWatcher(
                    root, lambda paths, kind=kind, root=root, location=location:
                    self._on_paths_changed(paths, kind, root, location)
                )

    def show_library(self) -> None:
        self.show_collection(None, False)

    def show_collection(self, folder_filter: str | None, favorites_only: bool) -> None:
        self.active_view, self.folder_filter, self.favorites_only = "library", folder_filter, favorites_only
        self.search.set_visible(True)
        self.library_page.reload(self.search.get_text(), folder_filter, favorites_only)
        self.stack.set_visible_child_name("library")

    def show_title(self, title_id: int) -> None:
        self.search.set_visible(False)
        self.detail_page.show_anime(title_id, self.folder_filter)
        self.stack.set_visible_child_name("detail")

    def show_active_view(self) -> None:
        if self.active_view == "home":
            self.show_home()
        elif self.active_view == "statistics":
            self.show_statistics()
        else:
            self.show_collection(self.folder_filter, self.favorites_only)

    def show_statistics(self) -> None:
        self.active_view = "statistics"
        self.search.set_visible(False)
        self.statistics_page.reload()
        self.stack.set_visible_child_name("statistics")

    def show_home(self) -> None:
        self.active_view = "home"
        self.search.set_visible(False)
        self.home_page.reload()
        self.stack.set_visible_child_name("home")

    def _on_navigation_selected(self, _box: Gtk.ListBox, row: Adw.ActionRow | None) -> None:
        view = row.view_name if row is not None else "library"
        if view == "home": self.show_home()
        elif view == "statistics": self.show_statistics()
        elif view == "watching": self.show_collection("watching", False)
        elif view == "downloads": self.show_collection("downloads", False)
        elif view == "favorites": self.show_collection(None, True)
        else: self.show_library()

    def _on_search_changed(self, _entry: Gtk.SearchEntry) -> None:
        if self.stack.get_visible_child_name() == "library":
            self.library_page.reload(self.search.get_text(), self.folder_filter, self.favorites_only)

    def _start_rescan(self, _button: Gtk.Button | None) -> None:
        if self._rescan_running or not self.library_root or not self.library_root.is_dir():
            return
        self._rescan_running = True
        self.rescan_button.set_sensitive(False)
        self.status.set_label("Updating library…")
        root, kind, location = self.library_root, self.library_type, self.location_id
        probe_enabled = bool(self.settings.data.get("probe_metadata", True))
        threading.Thread(target=self._scan_worker, args=(root, kind, location, probe_enabled), daemon=True).start()

    def _start_startup_scans(self) -> None:
        if self._rescan_running:
            return
        libraries = [(kind, self.settings.library_path(kind),
                      "default" if kind == "anime" else kind)
                     for kind in LIBRARY_TYPES]
        libraries = [(kind, root, location) for kind, root, location in libraries
                     if root is not None and root.is_dir()]
        if not libraries:
            return
        self._rescan_running = True
        self.rescan_button.set_sensitive(False)
        self.status.set_label("Updating configured libraries…")
        probe_enabled = bool(self.settings.data.get("probe_metadata", True))
        threading.Thread(target=self._scan_libraries_worker,
                         args=(libraries, probe_enabled), daemon=True).start()

    def _scan_libraries_worker(self, libraries: list[tuple[str, Path, str]], probe_enabled: bool) -> None:
        combined = type("CombinedResult", (), {"scanned": 0, "probed": 0, "reused_metadata": 0,
                                                "errors": 0, "stale_removed": 0})()
        try:
            repository = LibraryRepository(self.database_path)
            try:
                for kind, root, location in libraries:
                    try:
                        result = LibraryScanner(repository, root, location, kind, probe_enabled).scan()
                        for field in ("scanned", "probed", "reused_metadata", "errors", "stale_removed"):
                            setattr(combined, field, getattr(combined, field) + getattr(result, field))
                    except Exception:
                        combined.errors += 1
            finally:
                repository.close()
            GLib.idle_add(self._finish_scan, combined, None)
        except Exception as error:
            GLib.idle_add(self._finish_scan, None, str(error))

    def _scan_worker(self, root: Path, kind: str, location: str, probe_enabled: bool) -> None:
        try:
            repository = LibraryRepository(self.database_path)
            try: result = LibraryScanner(repository, root, location, kind, probe_enabled).scan()
            finally: repository.close()
            GLib.idle_add(self._finish_scan, result, None)
        except Exception as error:
            GLib.idle_add(self._finish_scan, None, str(error))

    def _on_paths_changed(self, paths: set[Path], kind: str | None = None,
                          root: Path | None = None, location: str | None = None) -> None:
        kind = kind or self.library_type
        root = root or self.library_root
        location = location or self.location_id
        if root is None:
            return
        context = (kind, str(root), location)
        if self._rescan_running:
            self._deferred_paths.setdefault(context, set()).update(paths)
            return
        self._rescan_running = True
        self.status.set_label("Updating changed files…")
        probe_enabled = bool(self.settings.data.get("probe_metadata", True))
        threading.Thread(target=self._changed_worker, args=(root, kind, location, paths, probe_enabled), daemon=True).start()

    def _changed_worker(self, root: Path, kind: str, location: str, paths: set[Path], probe_enabled: bool) -> None:
        try:
            repository = LibraryRepository(self.database_path)
            try: result = LibraryScanner(repository, root, location, kind, probe_enabled).refresh_paths(paths)
            finally: repository.close()
            GLib.idle_add(self._finish_scan, result, None)
        except Exception as error:
            GLib.idle_add(self._finish_scan, None, str(error))

    def _finish_scan(self, result: object | None, error: str | None) -> bool:
        self._rescan_running = False
        self.rescan_button.set_sensitive(True)
        if error:
            self.status.set_label("Library update failed")
            self.status.set_tooltip_text(error)
        else:
            details = [f"{result.scanned} files updated"]
            if result.probed: details.append(f"{result.probed} checked")
            if result.stale_removed: details.append(f"{result.stale_removed} removed")
            if result.errors: details.append(f"{result.errors} need attention")
            self.status.set_label("Updated · " + " · ".join(details))
            self.status.set_tooltip_text(None)
            self.show_active_view()
        if self._deferred_paths:
            context, deferred = self._deferred_paths.popitem()
            kind, root_text, location = context
            GLib.idle_add(self._on_paths_changed, deferred, kind, Path(root_text), location)
        return GLib.SOURCE_REMOVE

    def _open_settings(self, _button: Gtk.Button) -> None:
        dialog = SettingsWindow(self, self.settings, self._settings_saved)
        dialog.present()

    def _settings_saved(self) -> None:
        self._reset_watchers()
        self._select_library(self.library_type, scan=False)
        self._start_startup_scans()

    def _organize(self, _button: Gtk.Button) -> None:
        if not self.library_root or not self.library_root.is_dir() or self._rescan_running:
            self.status.set_label("Choose an available library and finish its scan first.")
            return
        self.status.set_label("Preparing organization preview…")
        self.organize_button.set_sensitive(False)
        root, kind, location = self.library_root, self.library_type, self.location_id
        threading.Thread(target=self._organization_plan_worker, args=(root, kind, location), daemon=True).start()

    def _organization_plan_worker(self, root: Path, kind: str, location: str) -> None:
        try:
            repository = LibraryRepository(self.database_path)
            try: plan = build_plan(repository, root, kind, location)
            finally: repository.close()
            GLib.idle_add(self._show_organization_plan, plan, root, None)
        except Exception as error:
            GLib.idle_add(self._show_organization_plan, None, root, str(error))

    def _show_organization_plan(self, plan: OrganizationPlan | None, root: Path, error: str | None) -> bool:
        self.organize_button.set_sensitive(True)
        if error or plan is None:
            self.status.set_label("Could not prepare organization preview")
            self.status.set_tooltip_text(error or "Unknown error")
            return GLib.SOURCE_REMOVE
        if not plan.actions:
            self.status.set_label("No confident organization changes found")
            self.status.set_tooltip_text("Uncertain files remain unchanged.")
            return GLib.SOURCE_REMOVE
        dialog = Adw.Window(transient_for=self, modal=True, title="Review file organization",
                            default_width=820, default_height=680)
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12,
                          margin_top=18, margin_bottom=18, margin_start=18, margin_end=18)
        content.append(Gtk.Label(label=f"Review {len(plan.actions)} proposed file changes. Nothing has been changed yet.", xalign=0, wrap=True))
        preview = Gtk.TextView(editable=False, cursor_visible=False, monospace=True, wrap_mode=Gtk.WrapMode.NONE)
        lines = [f"{action.source.relative_to(root)}\n    → {action.destination.relative_to(root)}" for action in plan.actions]
        if plan.skipped:
            lines.extend(["", f"Left unchanged for review ({len(plan.skipped)}):"])
            lines.extend(plan.skipped[:80])
            if len(plan.skipped) > 80:
                lines.append(f"…and {len(plan.skipped) - 80} more")
        preview.get_buffer().set_text("\n".join(lines))
        scroll = Gtk.ScrolledWindow(vexpand=True, hexpand=True)
        scroll.set_child(preview)
        content.append(scroll)
        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8, halign=Gtk.Align.END)
        cancel = Gtk.Button(label="Cancel")
        cancel.connect("clicked", lambda _button: dialog.close())
        apply_button = Gtk.Button(label=f"Apply {len(plan.actions)} changes")
        apply_button.add_css_class("destructive-action")
        apply_button.connect("clicked", self._apply_organization, dialog, plan, root)
        actions.append(cancel)
        actions.append(apply_button)
        content.append(actions)
        dialog.set_content(content)
        dialog.present()
        return GLib.SOURCE_REMOVE

    def _apply_organization(self, _button: Gtk.Button, dialog: Adw.Window,
                            plan: OrganizationPlan, root: Path) -> None:
        dialog.close()
        self._rescan_running = True
        self.organize_button.set_sensitive(False)
        self.rescan_button.set_sensitive(False)
        self.status.set_label("Organizing files…")
        threading.Thread(target=self._organization_apply_worker, args=(plan, root), daemon=True).start()

    def _organization_apply_worker(self, plan: OrganizationPlan, root: Path) -> None:
        try:
            manifest, errors = apply_plan(plan, root)
            GLib.idle_add(self._organization_applied, manifest, errors, None)
        except Exception as error:
            GLib.idle_add(self._organization_applied, None, [], str(error))

    def _organization_applied(self, manifest: Path | None, errors: list[str], error: str | None) -> bool:
        self._rescan_running = False
        self.organize_button.set_sensitive(True)
        self.rescan_button.set_sensitive(True)
        if error:
            self.status.set_label("Organization failed")
            self.status.set_tooltip_text(error)
        else:
            if manifest:
                self.settings.data["last_organization_manifest"] = str(manifest)
                self.settings.save()
                self.undo_button.set_visible(True)
            label = f"Organization complete · {manifest.name if manifest else ''}"
            if errors:
                label = f"Partially complete · {len(errors)} changes failed"
                self.status.set_tooltip_text("\n".join(errors[:20]))
            self.status.set_label(label)
            self._start_rescan(None)
        return GLib.SOURCE_REMOVE

    def _undo_organization(self, _button: Gtk.Button) -> None:
        value = self.settings.data.get("last_organization_manifest")
        manifest = Path(value) if value else None
        if not manifest or not manifest.is_file() or self._rescan_running:
            self.status.set_label("No available organization operation to undo.")
            return
        dialog = Adw.MessageDialog(transient_for=self, heading="Undo file organization?",
                                   body="Seru will move the files back to their recorded locations if those locations are still available.")
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("undo", "Undo")
        dialog.set_response_appearance("undo", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.connect("response", self._undo_response, manifest)
        dialog.present()

    def _undo_response(self, _dialog: Adw.MessageDialog, response: str, manifest: Path) -> None:
        if response != "undo":
            return
        self._rescan_running = True
        self.undo_button.set_sensitive(False)
        self.status.set_label("Undoing file organization…")
        threading.Thread(target=self._undo_worker, args=(manifest,), daemon=True).start()

    def _undo_worker(self, manifest: Path) -> None:
        try:
            errors = undo_manifest(manifest)
            GLib.idle_add(self._undo_finished, errors, None)
        except Exception as error:
            GLib.idle_add(self._undo_finished, [], str(error))

    def _undo_finished(self, errors: list[str], error: str | None) -> bool:
        self._rescan_running = False
        self.undo_button.set_sensitive(True)
        if error or errors:
            self.status.set_label("Undo could not finish" if errors else "Undo failed")
            self.status.set_tooltip_text(error or "\n".join(errors[:20]))
        else:
            self.settings.data.pop("last_organization_manifest", None)
            self.settings.save()
            self.undo_button.set_visible(False)
            self.status.set_label("Organization undone")
            self._start_rescan(None)
        return GLib.SOURCE_REMOVE

    def do_close_request(self) -> bool:
        for watcher in self._watchers.values():
            watcher.close()
        self._watchers.clear()
        return False
