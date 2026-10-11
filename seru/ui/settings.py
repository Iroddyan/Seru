"""Basic and PIN-gated advanced preferences."""
from __future__ import annotations

import hashlib
import hmac
import secrets
from pathlib import Path
import gi
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk

from ..config.settings import LIBRARY_LABELS, LIBRARY_TYPES, Settings


def _pin_hash(pin: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", pin.encode(), salt, 180_000)
    return f"{salt.hex()}:{digest.hex()}"


def _pin_matches(pin: str, stored: str) -> bool:
    try:
        salt_hex, digest_hex = stored.split(":", 1)
        return hmac.compare_digest(_pin_hash(pin, bytes.fromhex(salt_hex)).split(":", 1)[1], digest_hex)
    except (ValueError, TypeError):
        return False


class SettingsWindow(Adw.PreferencesWindow):
    def __init__(self, parent: Gtk.Window, settings: Settings, on_saved: object) -> None:
        super().__init__(transient_for=parent, modal=True, title="Settings", default_width=650, default_height=680)
        self.settings, self.on_saved = settings, on_saved
        self.rows: dict[str, Adw.EntryRow] = {}
        self.basic = Adw.PreferencesPage()
        self.basic.set_title("Basic")
        self.basic.set_icon_name("preferences-system-symbolic")
        self.advanced = Adw.PreferencesPage()
        self.advanced.set_title("Advanced")
        self.advanced.set_icon_name("applications-engineering-symbolic")
        self.add(self.basic)
        self.add(self.advanced)
        profile = Adw.PreferencesGroup(title="Profile")
        self.name = Adw.EntryRow(title="Display name")
        self.name.set_text(settings.data.get("display_name", ""))
        self.name.add_suffix(self._reset_button(lambda: self.name.set_text("")))
        profile.add(self.name)
        profile.add(self._action_row("Apply profile", self._apply_profile))
        profile.add(self._action_row("Reset profile", self._reset_profile))
        self.basic.add(profile)
        locations = Adw.PreferencesGroup(title="Library locations", description="Choose a folder for each library. Changes take effect after scanning.")
        for kind in LIBRARY_TYPES:
            row = Adw.EntryRow(title=LIBRARY_LABELS[kind])
            selected = settings.library_path(kind)
            if selected:
                row.set_text(str(selected))
            row.add_suffix(self._reset_button(lambda row=row: row.set_text("")))
            choose = Gtk.Button(label="Choose…", valign=Gtk.Align.CENTER)
            choose.connect("clicked", self._choose_folder, kind)
            row.add_suffix(choose)
            self.rows[kind] = row
            locations.add(row)
        locations.add(self._action_row("Apply library locations", self._apply_locations))
        locations.add(self._action_row("Reset library locations", self._reset_locations))
        self.basic.add(locations)
        behavior = Adw.PreferencesGroup(title="Behavior")
        self.watch = Adw.SwitchRow(title="Watch for changes while Seru is open")
        self.watch.set_active(bool(settings.data.get("watch_changes", True)))
        self.watch.add_suffix(self._reset_button(lambda: self.watch.set_active(True)))
        self.startup = Adw.SwitchRow(title="Reconcile libraries when Seru opens")
        self.startup.set_active(bool(settings.data.get("scan_on_startup", True)))
        self.startup.add_suffix(self._reset_button(lambda: self.startup.set_active(True)))
        behavior.add(self.watch)
        behavior.add(self.startup)
        behavior.add(self._action_row("Apply behavior", self._apply_behavior))
        behavior.add(self._action_row("Reset behavior", self._reset_behavior))
        self.basic.add(behavior)
        appearance = Adw.PreferencesGroup(title="Appearance")
        self.theme = Adw.ComboRow(title="Theme")
        self.theme.set_model(Gtk.StringList.new(["System", "Light", "Dark"]))
        self.theme.set_selected({"system": 0, "light": 1, "dark": 2}.get(settings.data.get("theme", "system"), 0))
        self.theme.add_suffix(self._reset_button(lambda: self.theme.set_selected(0)))
        appearance.add(self.theme)
        appearance.add(self._action_row("Apply appearance", self._apply_appearance))
        appearance.add(self._action_row("Reset appearance", self._reset_appearance))
        self.basic.add(appearance)
        self.basic_status = Gtk.Label(label="", xalign=0, wrap=True)
        feedback = Adw.PreferencesGroup(title="Changes")
        feedback.add(self.basic_status)
        self.basic.add(feedback)
        gate = Adw.PreferencesGroup(title="Advanced settings", description="Protected by a local six-digit PIN.")
        self.pin = Adw.PasswordEntryRow(title="Six-digit PIN")
        gate.add(self.pin)
        self.pin_status = Gtk.Label(label="", xalign=0, wrap=True)
        gate.add(self.pin_status)
        gate.add(self._action_row("Unlock advanced settings", self._unlock))
        self.advanced.add(gate)
        self.advanced_group = Adw.PreferencesGroup(title="Advanced")
        self.advanced_group.set_visible(False)
        self.probe_metadata = Adw.SwitchRow(title="Read technical media details with ffprobe")
        self.probe_metadata.set_active(bool(settings.data.get("probe_metadata", True)))
        self.probe_metadata.add_suffix(self._reset_button(lambda: self.probe_metadata.set_active(True)))
        self.advanced_group.add(self.probe_metadata)
        self.advanced_pin = Adw.PasswordEntryRow(title="Set a new six-digit PIN")
        self.advanced_group.add(self.advanced_pin)
        self.advanced_group.add(self._action_row("Apply advanced settings", self._apply_advanced))
        self.advanced_group.add(self._action_row("Reset advanced settings", self._reset_advanced))
        self.advanced.add(self.advanced_group)

    @staticmethod
    def _reset_button(callback: object) -> Gtk.Button:
        button = Gtk.Button(label="Reset", valign=Gtk.Align.CENTER)
        button.connect("clicked", lambda _button: callback())
        return button

    @staticmethod
    def _action_row(title: str, callback: object) -> Adw.ActionRow:
        row = Adw.ActionRow(title=title, activatable=True)
        row.add_suffix(Gtk.Image.new_from_icon_name("go-next-symbolic"))
        row.connect("activated", callback)
        return row

    def _apply_locations(self, *_args: object) -> None:
        try:
            for kind, row in self.rows.items():
                value = row.get_text().strip()
                path = Path(value).expanduser() if value else None
                if path is not None and path.exists() and not path.is_dir():
                    raise ValueError(f"{path} is not a folder")
                self.settings.set_library_path(kind, path)
            self.settings.save()
            self.on_saved()
            self.basic_status.set_label("Library locations applied.")
        except (OSError, ValueError) as error:
            self.basic_status.set_label(str(error))

    def _choose_folder(self, _button: Gtk.Button, kind: str) -> None:
        chooser = Gtk.FileChooserNative(title=f"Choose {LIBRARY_LABELS[kind]} folder",
                                        action=Gtk.FileChooserAction.SELECT_FOLDER)
        chooser.set_transient_for(self)
        def response(dialog: Gtk.FileChooserNative, response_id: int) -> None:
            if response_id == Gtk.ResponseType.ACCEPT:
                selected = dialog.get_file()
                if selected and selected.get_path():
                    self.rows[kind].set_text(selected.get_path())
            dialog.destroy()
        chooser.connect("response", response)
        chooser.show()

    def _apply_profile(self, *_args: object) -> None:
        self.settings.data["display_name"] = self.name.get_text().strip()
        self.settings.save()
        self.on_saved()

    def _reset_profile(self, *_args: object) -> None:
        self.name.set_text("")
        self.settings.data["display_name"] = ""
        self.settings.save()
        self.on_saved()

    def _reset_locations(self, *_args: object) -> None:
        for row in self.rows.values():
            row.set_text("")
        for kind in LIBRARY_TYPES:
            self.settings.set_library_path(kind, None)
        self.settings.save()
        self.on_saved()

    def _apply_behavior(self, *_args: object) -> None:
        self.settings.data["watch_changes"] = self.watch.get_active()
        self.settings.data["scan_on_startup"] = self.startup.get_active()
        self.settings.save()
        self.on_saved()

    def _reset_behavior(self, *_args: object) -> None:
        self.watch.set_active(True)
        self.startup.set_active(True)
        self._apply_behavior()

    def _apply_appearance(self, *_args: object) -> None:
        choice = self.theme.get_selected()
        value = ("system", "light", "dark")[min(choice, 2)]
        self.settings.data["theme"] = value
        manager = Adw.StyleManager.get_default()
        scheme = {"system": Adw.ColorScheme.DEFAULT, "light": Adw.ColorScheme.FORCE_LIGHT,
                  "dark": Adw.ColorScheme.FORCE_DARK}[value]
        manager.set_color_scheme(scheme)
        self.settings.save()

    def _reset_appearance(self, *_args: object) -> None:
        self.theme.set_selected(0)
        self._apply_appearance()

    def _unlock(self, *_args: object) -> None:
        pin = self.pin.get_text().strip()
        if not (pin.isascii() and pin.isdigit() and len(pin) == 6):
            self.pin_status.set_label("Enter exactly six digits.")
            return
        stored = self.settings.data.get("advanced_pin_hash", "")
        if stored and not _pin_matches(pin, stored):
            self.pin_status.set_label("That PIN did not match.")
            return
        if not stored:
            self.settings.data["advanced_pin_hash"] = _pin_hash(pin)
            self.settings.save()
        self.advanced_group.set_visible(True)
        self.pin_status.set_label("Advanced settings unlocked for this session.")

    def _apply_advanced(self, *_args: object) -> None:
        pin = self.advanced_pin.get_text().strip()
        if pin and not (pin.isascii() and pin.isdigit() and len(pin) == 6):
            self.pin_status.set_label("A new PIN must contain exactly six digits.")
            return
        if pin:
            self.settings.data["advanced_pin_hash"] = _pin_hash(pin)
        self.settings.data["probe_metadata"] = self.probe_metadata.get_active()
        self.settings.save()
        self.on_saved()
        self.advanced_pin.set_text("")
        self.pin_status.set_label("Advanced settings applied.")

    def _reset_advanced(self, *_args: object) -> None:
        self.settings.data["advanced_pin_hash"] = ""
        self.settings.data["probe_metadata"] = True
        self.probe_metadata.set_active(True)
        self.advanced_pin.set_text("")
        self.settings.save()
        self.on_saved()
        self.pin_status.set_label("Advanced settings reset. Choose a new PIN when you unlock them.")
