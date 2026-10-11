"""First-run library configuration."""
from __future__ import annotations

from pathlib import Path
import gi
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk

from ..config.settings import LIBRARY_LABELS, LIBRARY_TYPES, Settings


class SetupPage(Gtk.Box):
    def __init__(self, settings: Settings, on_complete: object) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, vexpand=True)
        self.settings, self.on_complete = settings, on_complete
        self.entries: dict[str, Gtk.EntryRow] = {}
        self.structure_preview = Gtk.Label(label="", wrap=True, xalign=0)
        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16,
                       margin_top=28, margin_bottom=28, margin_start=24, margin_end=24)
        clamp = Adw.Clamp(maximum_size=720, tightening_threshold=560)
        clamp.set_child(body)
        self.append(clamp)
        body.append(Adw.StatusPage(icon_name="video-x-generic-symbolic", title="Welcome to Seru",
                                   description="Set up your local libraries. You can change these locations later."))
        profile = Adw.PreferencesGroup(title="Your profile")
        self.name_entry = Adw.EntryRow(title="Display name")
        self.name_entry.set_text(settings.data.get("display_name", ""))
        profile.add(self.name_entry)
        body.append(profile)
        libraries = Adw.PreferencesGroup(title="Library folders",
                                         description="Choose existing folders, or leave a library empty and configure it later.")
        for kind in LIBRARY_TYPES:
            row = Adw.EntryRow(title=LIBRARY_LABELS[kind])
            selected = settings.library_path(kind)
            if selected:
                row.set_text(str(selected))
            row.set_show_apply_button(False)
            row.connect("changed", self._update_structure_preview)
            choose = Gtk.Button(label="Choose…", valign=Gtk.Align.CENTER)
            choose.connect("clicked", self._choose_folder, kind)
            row.add_suffix(choose)
            libraries.add(row)
            self.entries[kind] = row
        body.append(libraries)
        self.create_layout = Gtk.CheckButton(label="I agree to create the shown empty starter folders")
        body.append(Gtk.Label(label="If selected, Seru will create Series/ in empty Anime, TV Shows, and Cartoons folders, and Movies/ in an empty Movies folder.", wrap=True, xalign=0))
        body.append(self.structure_preview)
        body.append(self.create_layout)
        self.error = Gtk.Label(label="", xalign=0, wrap=True)
        self.error.add_css_class("error")
        body.append(self.error)
        finish = Gtk.Button(label="Continue", halign=Gtk.Align.END)
        finish.add_css_class("suggested-action")
        finish.connect("clicked", self._finish)
        body.append(finish)
        self._update_structure_preview()

    def _update_structure_preview(self, *_args: object) -> None:
        targets = []
        for kind, entry in self.entries.items():
            value = entry.get_text().strip()
            if not value:
                continue
            root = Path(value).expanduser()
            try:
                is_empty = not root.exists() or (root.is_dir() and not any(root.iterdir()))
            except OSError:
                is_empty = False
            if is_empty:
                targets.append(str(root / ("Movies" if kind == "movies" else "Series")))
        self.structure_preview.set_label("Seru will create:\n" + "\n".join(targets) if targets else "No empty starter folders are proposed for the selected locations.")

    def _choose_folder(self, _button: Gtk.Button, kind: str) -> None:
        dialog = Gtk.FileChooserNative(title=f"Choose {LIBRARY_LABELS[kind]} folder", action=Gtk.FileChooserAction.SELECT_FOLDER)
        dialog.set_transient_for(self.get_root())
        def response(native: Gtk.FileChooserNative, response_id: int) -> None:
            if response_id == Gtk.ResponseType.ACCEPT:
                file = native.get_file()
                if file and file.get_path():
                    self.entries[kind].set_text(file.get_path())
            native.destroy()
        dialog.connect("response", response)
        dialog.show()

    def _finish(self, _button: Gtk.Button) -> None:
        display_name = self.name_entry.get_text().strip()
        if not display_name:
            self.error.set_label("Enter a display name to continue.")
            return
        try:
            roots: dict[str, Path] = {}
            for kind, entry in self.entries.items():
                value = entry.get_text().strip()
                if not value:
                    continue
                path = Path(value).expanduser()
                if path.exists() and not path.is_dir():
                    raise ValueError(f"{path} is not a folder.")
                roots[kind] = path
            if self.create_layout.get_active():
                for kind, path in roots.items():
                    if not path.exists() or (path.is_dir() and not any(path.iterdir())):
                        (path / ("Movies" if kind == "movies" else "Series")).mkdir(parents=True, exist_ok=True)
            self.settings.data["display_name"] = display_name
            for kind in LIBRARY_TYPES:
                self.settings.set_library_path(kind, roots.get(kind))
            self.settings.save()
        except (OSError, ValueError) as error:
            self.error.set_label(f"Setup could not be saved: {error}")
            return
        self.on_complete()
