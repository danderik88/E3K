# E3K home screen: commands | temperatures + graph | print and power.
# KlipperScreen add-on (addons/ is gitignored): swaps the stock main_menu panel
# for this one and hides the action-bar shutdown button (it only powers off the Pi).
# Rollback: enable_addons: False in KlipperScreen.conf, or delete this file.
import json
import logging
import sys
import threading
import urllib.request

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk

from panels.main_menu import Panel as StockMainMenu

MOONRAKER = "http://127.0.0.1:7125"
SPOOLMAN = "http://127.0.0.1:7912"
ARM_SECONDS = 4


def init(screen):
    stock_load = screen._load_panel

    def load_panel(panel):
        return sys.modules[__name__] if panel == "main_menu" else stock_load(panel)

    screen._load_panel = load_panel
    logging.info("e3k_home: main_menu replaced")


def _get(path, base=MOONRAKER):
    with urllib.request.urlopen(base + path, timeout=3) as r:
        return json.load(r)


class Panel(StockMainMenu):
    def __init__(self, screen, title, items=None):
        super().__init__(screen, title, items)
        self._hide_pi_shutdown()
        self.poll = None
        self.armed = None
        self.light_on = False
        self.auto_off = False

        # Rebuild the layout around the stock left panel (device list + graph),
        # keeping main_menu/menu_scroll so the stock numpad show/hide still works:
        # col 0 = commands + temperatures, col 1 = right column (numpad goes there).
        self.content.remove(self.main_menu)
        self.main_menu.remove(self.left_panel)
        w = self._gtk.content_width

        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, homogeneous=True)
        left.set_size_request(int(w * 0.17), -1)
        left.set_hexpand(False)  # stop KS buttons (hexpand=True) from widening the column
        for icon, label, cb in (
            ("move", "Movimenti", lambda b: self._screen.show_panel("move", "Movimenti")),
            ("heat-up", "Temperature", lambda b: self._screen.show_panel("temperature", "Temperature")),
            ("extrude", "Estrusione", lambda b: self._screen.show_panel("extrude", "Estrusione")),
            ("settings", "Altro", lambda b: self._screen._go_to_submenu(b, "more")),
        ):
            left.add(self._tile(icon, label, cb))

        self.spool = Gtk.Label(label="", xalign=0)
        self.spool.get_style_context().add_class("e3k_spool")
        self.left_panel.pack_end(self.spool, False, False, 0)
        self.left_panel.set_hexpand(True)

        top = Gtk.Box(spacing=0)
        top.pack_start(left, False, False, 0)
        top.pack_start(self.left_panel, True, True, 0)

        right = Gtk.Grid(row_homogeneous=True, column_homogeneous=True)
        right.set_size_request(int(w * 0.22), -1)
        right.set_hexpand(False)
        self.b_print = self._tile("printer", "Stampa", lambda b: self._screen.show_panel("gcodes", "Stampa"), "e3k_print")
        self.b_light = self._tile("light", "Luce", self.toggle_light)
        self.b_auto = self._tile("clock", "Auto-off", self.toggle_auto_off)
        self.b_off = self._tile("shutdown", "Spegni", self.off_clicked, "e3k_off")
        right.attach(self.b_print, 0, 0, 1, 2)
        right.attach(self.b_light, 0, 2, 1, 1)
        right.attach(self.b_auto, 0, 3, 1, 1)
        right.attach(self.b_off, 0, 4, 1, 1)

        self.main_menu = Gtk.Grid(hexpand=True, vexpand=True)
        self.main_menu.attach(top, 0, 0, 1, 1)
        self.menu_scroll = right
        self.main_menu.attach(self.menu_scroll, 1, 0, 1, 1)
        self.content.add(self.main_menu)

    def _tile(self, icon, label, cb, style="e3k_tile"):
        # one label line + smaller icon: 4-5 stacked tiles must fit the ~445 px content height
        b = self._gtk.Button(icon, label, style, scale=self._gtk.button_image_scale * 0.55, lines=1)
        b.connect("clicked", cb)
        return b

    def _hide_pi_shutdown(self):
        bp = self._screen.base_panel
        if getattr(bp, "_e3k_patched", False):
            return
        stock_update = bp.update_action_bar

        def update_action_bar():
            stock_update()
            bp.control["shutdown"].set_visible(False)

        bp.update_action_bar = update_action_bar
        bp._e3k_patched = True
        bp.control["shutdown"].set_visible(False)

    # --- lifecycle: poll light / auto-off / spool only while visible ---
    def activate(self):
        super().activate()
        self.refresh()
        if self.poll is None:
            self.poll = GLib.timeout_add_seconds(10, self.refresh)

    def deactivate(self):
        super().deactivate()
        if self.poll is not None:
            GLib.source_remove(self.poll)
            self.poll = None
        self.disarm()

    def refresh(self):
        threading.Thread(target=self._fetch, daemon=True).start()
        return True

    def _fetch(self):
        state = {}
        try:
            q = _get("/printer/objects/query?gcode_macro%20_AUTO_OFF")
            state["auto"] = bool(int(q["result"]["status"]["gcode_macro _AUTO_OFF"]["enabled"]))
        except Exception as e:
            logging.debug(f"e3k_home auto-off: {e}")
        try:
            strip = _get("/machine/wled/strips")["result"]["strips"]["light"]
            # LIGHT_ON = preset 1, LIGHT_OFF = preset 2 (dim), see Wled.cfg
            state["light"] = strip.get("status") == "on" and strip.get("preset") == 1
        except Exception as e:
            logging.debug(f"e3k_home wled: {e}")
        try:
            sid = _get("/server/spoolman/spool_id")["result"]["spool_id"]
            if sid:
                s = _get(f"/api/v1/spool/{sid}", SPOOLMAN)
                state["spool"] = f"{s['filament'].get('name', '')} · {round(s.get('remaining_weight') or 0)} g"
        except Exception as e:
            logging.debug(f"e3k_home spoolman: {e}")
        GLib.idle_add(self._apply, state)

    def _apply(self, state):
        if "auto" in state:
            self.auto_off = state["auto"]
            self._style(self.b_auto, "e3k_on", self.auto_off)
            self.b_auto.set_label("Auto-off attivo" if self.auto_off else "Auto-off")
        if "light" in state:
            self.light_on = state["light"]
            self._style(self.b_light, "e3k_on", self.light_on)
            self.b_light.set_label("Luce accesa" if self.light_on else "Luce spenta")
        if "spool" in state:
            self.spool.set_label(state["spool"])
        return False

    @staticmethod
    def _style(widget, cls, on):
        ctx = widget.get_style_context()
        (ctx.add_class if on else ctx.remove_class)(cls)

    def _gcode(self, script):
        self._screen._send_action(None, "printer.gcode.script", {"script": script})

    # --- toggles (optimistic, the next poll confirms) ---
    def toggle_light(self, widget):
        self._gcode("LIGHT_OFF" if self.light_on else "LIGHT_ON")
        self._apply({"light": not self.light_on})

    def toggle_auto_off(self, widget):
        self._gcode("AUTO_OFF_OFF" if self.auto_off else "AUTO_OFF_ON")
        self._apply({"auto": not self.auto_off})

    # --- power off: first tap arms for ARM_SECONDS, second tap runs SHUTDOWN ---
    def off_clicked(self, widget):
        if self.armed is None:
            self.armed = [ARM_SECONDS, GLib.timeout_add_seconds(1, self._tick)]
            self._style(self.b_off, "e3k_off_armed", True)
            self._show_countdown()
            return
        self.disarm()
        self.b_off.set_label("Spegnimento…")
        self._gcode("SHUTDOWN")

    def _show_countdown(self):
        self.b_off.set_label(f"Tocca per spegnere ({self.armed[0]})")

    def _tick(self):
        self.armed[0] -= 1
        if self.armed[0] <= 0:
            self.armed = None  # this timeout ends itself by returning False
            self.disarm()
            return False
        self._show_countdown()
        return True

    def disarm(self):
        if self.armed is not None:
            GLib.source_remove(self.armed[1])
            self.armed = None
        self._style(self.b_off, "e3k_off_armed", False)
        self.b_off.set_label("Spegni")
