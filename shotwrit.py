#!/usr/bin/env python3
"""Shotwrit - screenshot tool with region select, pen, box and arrow marking.

Copyright (C) 2026 mishajib
SPDX-License-Identifier: GPL-3.0-or-later

Usage: shotwrit.py [--quick] [--setup] [--update] [--version] [--uninstall-user] [image.png]
(no image: capture via the portal; --quick shows GNOME's screenshot selector, then opens the editor)
"""
import datetime
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: E402
import cairo  # noqa: E402

COLORS = {"Red": (0.93, 0.15, 0.15), "Yellow": (1.0, 0.82, 0.0),
          "Green": (0.1, 0.7, 0.3), "Blue": (0.15, 0.4, 0.95), "Black": (0, 0, 0)}
SAVE_DIR = os.path.expanduser("~/Pictures/shotwrit")
APP_ID = "io.github.mishajib.Shotwrit"
VERSION = "0.1.1"
REPO = "mishajib/shotwrit"
KEYS_SCHEMA = "org.gnome.settings-daemon.plugins.media-keys"
KEY_PATH = "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/shotwrit/"
SETUP_MARK = os.path.join(GLib.get_user_config_dir(), "shotwrit", "shortcut-set")


def discard(path):
    """The portal leaves its raw capture in ~/Pictures; shotwrit keeps its own copy."""
    try:
        os.remove(path)
    except OSError:
        pass


def grant_portal_access():
    """Let the portal capture without a system dialog (it can't prompt an unfocused app)."""
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION)
        for app in ("", APP_ID, "shotwrit"):
            bus.call_sync("org.freedesktop.impl.portal.PermissionStore",
                          "/org/freedesktop/impl/portal/PermissionStore",
                          "org.freedesktop.impl.portal.PermissionStore", "SetPermission",
                          GLib.Variant("(sbssas)", ("screenshot", True, "screenshot", app, ["yes"])),
                          None, Gio.DBusCallFlags.NONE, -1, None)
    except GLib.Error as e:
        print("could not grant screenshot access:", e.message, file=sys.stderr)


def set_shortcut():
    """Bind Ctrl+Alt+S to `shotwrit --quick` in GNOME. Returns True if it was set."""
    src = Gio.SettingsSchemaSource.get_default()
    if not src or not src.lookup(KEYS_SCHEMA, True):
        return False
    exe = shutil.which("shotwrit") or "python3 " + os.path.abspath(__file__)
    keys = Gio.Settings.new_with_path(KEYS_SCHEMA + ".custom-keybinding", KEY_PATH)
    keys.set_string("name", "Shotwrit")
    keys.set_string("command", exe + " --quick")
    keys.set_string("binding", "<Control><Alt>s")
    media = Gio.Settings.new(KEYS_SCHEMA)
    paths = media.get_strv("custom-keybindings")
    if KEY_PATH not in paths:
        media.set_strv("custom-keybindings", paths + [KEY_PATH])
    Gio.Settings.sync()
    return True


def first_run_setup(force=False):
    """Grant portal access every launch; set the shortcut once (or when forced)."""
    grant_portal_access()
    if force or not os.path.exists(SETUP_MARK):
        if set_shortcut():
            os.makedirs(os.path.dirname(SETUP_MARK), exist_ok=True)
            open(SETUP_MARK, "w").close()
            return True
    return False


def monitor_rects():
    """[(label, x, y, w, h)] in logical coordinates, one per connected monitor."""
    mons = Gdk.Display.get_default().get_monitors()
    out = []
    for i in range(mons.get_n_items()):
        m = mons.get_item(i)
        g = m.get_geometry()
        name = " ".join(t for t in (m.get_model(), m.get_connector()) if t) or "Monitor"
        out.append(("%d: %s  (%d\u00d7%d)" % (i + 1, name, g.width, g.height), g.x, g.y, g.width, g.height))
    return out


def crop_to_monitor(path, mon, mons):
    """Crop the portal's all-monitors capture to one monitor; returns a new png path."""
    bx, by = min(m[1] for m in mons), min(m[2] for m in mons)
    bw = max(m[1] + m[3] for m in mons) - bx
    bh = max(m[2] + m[4] for m in mons) - by
    img = cairo.ImageSurface.create_from_png(path)
    sx, sy = img.get_width() / bw, img.get_height() / bh
    out = cairo.ImageSurface(cairo.FORMAT_ARGB32, round(mon[3] * sx), round(mon[4] * sy))
    cr = cairo.Context(out)
    cr.set_source_surface(img, -round((mon[1] - bx) * sx), -round((mon[2] - by) * sy))
    cr.paint()
    dest = GLib.build_filenamev([GLib.get_tmp_dir(), "shotwrit-monitor-%d.png" % os.getpid()])
    out.write_to_png(dest)
    return dest


def choose_monitor(app, path, callback):
    """With several monitors ask which one to keep; with one, pass the capture straight through.
    callback(path or None)."""
    mons = monitor_rects()
    if path is None or len(mons) < 2:
        callback(path)
        return
    win = Gtk.Window(application=app, title="Shotwrit", resizable=False, modal=True)
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin_top=16,
                  margin_bottom=16, margin_start=20, margin_end=20)
    box.append(Gtk.Label(label="Which monitor do you want to capture?", margin_bottom=4))
    state = {"done": False}

    def finish(mon):
        if state["done"]:
            return
        state["done"] = True
        if mon is None:
            discard(path)
            callback(None)
        elif mon == "all":
            callback(path)
        else:
            new = crop_to_monitor(path, mon, mons)
            discard(path)
            callback(new)
        win.destroy()

    for m in mons:
        b = Gtk.Button(label=m[0])
        b.connect("clicked", lambda _b, m=m: finish(m))
        box.append(b)
    b = Gtk.Button(label="All monitors")
    b.connect("clicked", lambda _b: finish("all"))
    box.append(b)
    win.connect("close-request", lambda _w: finish(None) or False)
    keys = Gtk.EventControllerKey()
    keys.connect("key-pressed", lambda _c, k, *_: finish(None) if k == Gdk.KEY_Escape else None)
    win.add_controller(keys)
    win.set_child(box)
    win.present()


def _fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "shotwrit/" + VERSION})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def update():
    """Install the latest GitHub release over this one. Returns a process exit code."""
    try:
        rel = json.loads(_fetch("https://api.github.com/repos/%s/releases/latest" % REPO))
    except Exception as e:  # network, rate limit, bad json
        print("could not check for updates:", e, file=sys.stderr)
        return 1
    tag = rel["tag_name"]
    ver = lambda v: tuple(int(x) for x in v.lstrip("v").split(".") if x.isdigit())
    if ver(tag) <= ver(VERSION):
        print("Shotwrit %s is already the latest version." % VERSION)
        return 0
    print("Updating Shotwrit %s -> %s" % (VERSION, tag.lstrip("v")))
    me = os.path.abspath(__file__)
    try:
        if me.startswith("/usr/"):  # installed from the .deb
            deb = next(a for a in rel["assets"] if a["name"].endswith(".deb"))
            with tempfile.TemporaryDirectory() as d:
                path = os.path.join(d, deb["name"])
                with open(path, "wb") as f:
                    f.write(_fetch(deb["browser_download_url"]))
                return subprocess.call(["sudo", "apt", "install", "-y", path])
        code = _fetch("https://raw.githubusercontent.com/%s/%s/shotwrit.py" % (REPO, tag))
        compile(code, me, "exec")  # don't overwrite ourselves with something broken
        with open(me + ".new", "wb") as f:
            f.write(code)
        os.replace(me + ".new", me)
    except Exception as e:
        print("update failed:", e, file=sys.stderr)
        return 1
    print("Updated to %s." % tag.lstrip("v"))
    return 0


def uninstall_user():
    """Undo first_run_setup for this user: shortcut, portal access, config. Screenshots are kept."""
    src = Gio.SettingsSchemaSource.get_default()
    if src and src.lookup(KEYS_SCHEMA, True):
        media = Gio.Settings.new(KEYS_SCHEMA)
        media.set_strv("custom-keybindings", [p for p in media.get_strv("custom-keybindings") if p != KEY_PATH])
        keys = Gio.Settings.new_with_path(KEYS_SCHEMA + ".custom-keybinding", KEY_PATH)
        for k in ("name", "command", "binding"):
            keys.reset(k)
        Gio.Settings.sync()
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION)
        for app in ("", APP_ID, "shotwrit"):
            bus.call_sync("org.freedesktop.impl.portal.PermissionStore",
                          "/org/freedesktop/impl/portal/PermissionStore",
                          "org.freedesktop.impl.portal.PermissionStore", "DeletePermission",
                          GLib.Variant("(sss)", ("screenshot", "screenshot", app)),
                          None, Gio.DBusCallFlags.NONE, -1, None)
    except GLib.Error:
        pass
    shutil.rmtree(os.path.dirname(SETUP_MARK), ignore_errors=True)


def portal_screenshot(callback, interactive=False):
    """Take a full-screen shot via xdg-desktop-portal; callback(path or None)."""
    bus = Gio.bus_get_sync(Gio.BusType.SESSION)
    token = "shotwrit%d_%d" % (os.getpid(), GLib.get_monotonic_time())
    sender = bus.get_unique_name().lstrip(":").replace(".", "_")
    path = "/org/freedesktop/portal/desktop/request/%s/%s" % (sender, token)

    def on_response(_c, _s, _p, _i, _sig, params):
        code, results = params.unpack()
        uri = results.get("uri") if code == 0 else None
        callback(Gio.File.new_for_uri(uri).get_path() if uri else None)

    bus.signal_subscribe("org.freedesktop.portal.Desktop",
                         "org.freedesktop.portal.Request", "Response", path,
                         None, Gio.DBusSignalFlags.NONE, on_response)
    bus.call_sync("org.freedesktop.portal.Desktop", "/org/freedesktop/portal/desktop",
                  "org.freedesktop.portal.Screenshot", "Screenshot",
                  GLib.Variant("(sa{sv})", ("", {"handle_token": GLib.Variant("s", token),
                                                 "interactive": GLib.Variant("b", interactive)})),
                  None, Gio.DBusCallFlags.NONE, -1, None)


class Editor(Gtk.ApplicationWindow):
    def __init__(self, app, image_path, quick=False, autoclose=False):
        super().__init__(application=app, title="Shotwrit")
        self.quick = quick
        self.autoclose = quick or autoclose  # close after Copy/Save
        self.load_image(image_path)
        self.tool = "select"
        self.color = COLORS["Red"]
        self.width = 4
        self.shapes = []      # (tool, color, width, points)
        self.current = None
        self.moving = None    # (index, original points) while dragging a mark
        self.crop = None      # (x0, y0, x1, y1) in image coords
        self.capture_mode = 0  # 0 = full screen, 1 = pick area/window with GNOME
        self.delay = 0
        self.scale, self.ox, self.oy = 1.0, 0, 0

        self.area = Gtk.DrawingArea(hexpand=True, vexpand=True)
        self.area.set_draw_func(self.draw)
        drag = Gtk.GestureDrag()
        drag.connect("drag-begin", self.on_begin)
        drag.connect("drag-update", self.on_update)
        drag.connect("drag-end", self.on_end)
        self.area.add_controller(drag)

        panel = self.build_toolbar()
        css = Gtk.CssProvider()
        css.load_from_string(
            ".floating { background: rgba(32,32,32,0.94); border-radius: 14px; "
            "box-shadow: 0 4px 16px rgba(0,0,0,.5); padding: 4px; }"
            ".toast { background: rgba(20,20,20,0.92); color: white; border-radius: 10px; "
            "padding: 10px 18px; font-weight: bold; }")
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.toast = Gtk.Label(visible=False, halign=Gtk.Align.CENTER, valign=Gtk.Align.START,
                               margin_top=24)
        self.toast.add_css_class("toast")
        overlay = Gtk.Overlay()
        overlay.set_child(self.area)
        overlay.add_overlay(self.toast)
        if quick:
            panel.add_css_class("floating")
            panel.set_halign(Gtk.Align.CENTER)
            panel.set_valign(Gtk.Align.END)
            panel.set_margin_bottom(28)
            overlay.add_overlay(panel)
            self.set_child(overlay)
            self.area.set_cursor_from_name("crosshair")
        else:
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            box.append(panel)
            box.append(overlay)
            self.set_child(box)
        self.redo_stack = []
        self.copied = False
        self.connect("close-request", self.on_close)
        if quick:
            self.fullscreen()
        else:
            self.set_default_size(min(self.iw + 40, 1200), min(self.ih + 90, 700))

        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self.on_key)
        self.add_controller(keys)

    def load_image(self, path):
        self.img = cairo.ImageSurface.create_from_png(path)
        self.iw, self.ih = self.img.get_width(), self.img.get_height()
        self.shapes, self.current, self.crop = [], None, None
        self.redo_stack = []
        if hasattr(self, "area"):
            self.area.queue_draw()

    def recapture(self):
        self.set_visible(False)

        def go():
            def loaded(path):
                if path:
                    self.load_image(path)
                    discard(path)
                self.set_visible(True)
                self.present()

            def done(path):
                if self.capture_mode == 1:
                    loaded(path)
                else:
                    choose_monitor(self.get_application(), path, loaded)
            portal_screenshot(done, interactive=self.capture_mode == 1)
            return False
        GLib.timeout_add(int(self.delay * 1000) + 400, go)

    # --- UI -------------------------------------------------------------
    def build_toolbar(self):
        mk = lambda: Gtk.Box(spacing=6, margin_top=3, margin_bottom=3, margin_start=6,
                             margin_end=6, halign=Gtk.Align.CENTER)
        tools, actions = mk(), mk()
        first = None
        for name, label in (("select", "Select"), ("pen", "Draw"), ("box", "Box"),
                            ("arrow", "Arrow"), ("text", "Text"), ("hl", "Marker"),
                            ("blur", "Blur"), ("move", "Move")):
            b = Gtk.ToggleButton(label=label)
            if first:
                b.set_group(first)
            else:
                first = b
                b.set_active(True)
            b.set_tooltip_text("Shortcut: " + {"select": "S", "pen": "D", "box": "B", "arrow": "A",
                               "text": "T", "hl": "H", "blur": "U", "move": "M"}[name])
            b.connect("toggled", lambda w, n=name: w.get_active() and setattr(self, "tool", n))
            setattr(self, "btn_" + name, b)
            tools.append(b)
        colors = Gtk.DropDown.new_from_strings(list(COLORS))
        colors.connect("notify::selected", lambda w, _p: setattr(
            self, "color", list(COLORS.values())[w.get_selected()]))
        tools.append(colors)
        size = Gtk.SpinButton.new_with_range(1, 24, 1)
        size.set_value(self.width)
        size.connect("value-changed", lambda w: setattr(self, "width", w.get_value()))
        tools.append(size)
        if not self.quick:
            mode = Gtk.DropDown.new_from_strings(["Full screen", "Pick area/window"])
            mode.connect("notify::selected",
                         lambda w, _p: setattr(self, "capture_mode", w.get_selected()))
            actions.append(mode)
            delay = Gtk.SpinButton.new_with_range(0, 10, 1)
            delay.set_tooltip_text("Capture delay (seconds)")
            delay.connect("value-changed", lambda w: setattr(self, "delay", w.get_value()))
            actions.append(delay)
        for label, fn in (("New shot", self.recapture), ("Undo", self.undo),
                          ("Redo", self.redo), ("Copy", self.copy), ("Save", self.save)):
            b = Gtk.Button(label=label)
            b.connect("clicked", lambda _w, f=fn: f())
            actions.append(b)
        panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        panel.append(tools)
        panel.append(actions)
        return panel

    def show_toast(self, text, ms=1500):
        self.toast.set_text(text)
        self.toast.set_visible(True)
        GLib.timeout_add(ms, lambda: self.toast.set_visible(False) or False)

    def on_key(self, _c, keyval, _code, state):
        ctrl = state & Gdk.ModifierType.CONTROL_MASK
        k = Gdk.keyval_name(keyval).lower()
        if ctrl and k == "z" and state & Gdk.ModifierType.SHIFT_MASK:
            self.redo()
        elif ctrl and k == "y":
            self.redo()
        elif ctrl and k == "z":
            self.undo()
        elif ctrl and k == "c":
            self.copy()
        elif ctrl and k == "s":
            self.save()
        elif k in ("return", "kp_enter") and self.quick:
            self.copy()
        elif k == "escape":
            self.close()
        elif k in ("s", "d", "b", "a", "t", "h", "u", "m") and not ctrl:
            tool = {"s": "select", "d": "pen", "b": "box", "a": "arrow",
                    "t": "text", "h": "hl", "u": "blur", "m": "move"}[k]
            getattr(self, "btn_" + tool).set_active(True)
        else:
            return False
        return True

    # --- coordinates & drawing -------------------------------------------
    def to_img(self, x, y):
        return ((x - self.ox) / self.scale, (y - self.oy) / self.scale)

    def paint_shape(self, cr, shape):
        tool, color, width, pts, text = shape
        cr.set_source_rgb(*color)
        cr.set_line_width(width)
        cr.set_line_cap(cairo.LINE_CAP_ROUND)
        cr.set_line_join(cairo.LINE_JOIN_ROUND)
        (x0, y0), (x1, y1) = pts[0], pts[-1]
        if tool == "text":
            cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
            cr.set_font_size(max(14, width * 5))
            for i, line in enumerate(text.split("\n")):
                cr.move_to(x0, y0 + (i + 1) * max(14, width * 5) * 1.2)
                cr.show_text(line)
        elif tool == "blur":
            bx, by = min(x0, x1), min(y0, y1)
            bw, bh = abs(x1 - x0), abs(y1 - y0)
            if bw >= 1 and bh >= 1:
                blk = 10
                small = cairo.ImageSurface(cairo.FORMAT_ARGB32, int(bw / blk) + 1, int(bh / blk) + 1)
                sc = cairo.Context(small)
                sc.scale(1 / blk, 1 / blk)
                sc.set_source_surface(self.img, -bx, -by)
                sc.paint()
                cr.save()
                cr.rectangle(bx, by, bw, bh)
                cr.clip()
                cr.translate(bx, by)
                cr.scale(blk, blk)
                cr.set_source_surface(small, 0, 0)
                cr.get_source().set_filter(cairo.FILTER_NEAREST)
                cr.paint()
                cr.restore()
        elif tool in ("pen", "hl"):
            if tool == "hl":
                cr.set_source_rgba(*color, 0.4)
                cr.set_line_width(width * 4)
                cr.set_line_cap(cairo.LINE_CAP_BUTT)
            cr.move_to(x0, y0)
            for x, y in pts[1:]:
                cr.line_to(x, y)
            cr.stroke()
        elif tool == "box":
            cr.rectangle(x0, y0, x1 - x0, y1 - y0)
            cr.stroke()
        elif tool == "arrow":
            cr.move_to(x0, y0)
            cr.line_to(x1, y1)
            cr.stroke()
            ang = math.atan2(y1 - y0, x1 - x0)
            head = max(12, width * 4)
            cr.move_to(x1, y1)
            for d in (2.6, -2.6):
                cr.line_to(x1 + head * math.cos(ang + d), y1 + head * math.sin(ang + d))
                cr.move_to(x1, y1)
            cr.stroke()

    def render(self, cr):
        cr.set_source_surface(self.img, 0, 0)
        cr.paint()
        for s in self.shapes + ([self.current] if self.current else []):
            self.paint_shape(cr, s)

    def draw(self, _a, cr, w, h):
        self.scale = min(w / self.iw, h / self.ih, 1.0)
        self.ox, self.oy = (w - self.iw * self.scale) / 2, (h - self.ih * self.scale) / 2
        cr.translate(self.ox, self.oy)
        cr.scale(self.scale, self.scale)
        self.render(cr)
        if self.quick and not self.crop:
            cr.set_source_rgba(0, 0, 0, 0.4)
            cr.rectangle(0, 0, self.iw, self.ih)
            cr.fill()
        if self.crop:
            x0, y0, x1, y1 = self.norm_crop()
            cr.set_source_rgba(0, 0, 0, 0.5)
            cr.set_fill_rule(cairo.FILL_RULE_EVEN_ODD)
            cr.rectangle(0, 0, self.iw, self.ih)
            cr.rectangle(x0, y0, x1 - x0, y1 - y0)
            cr.fill()
            cr.set_source_rgb(1, 1, 1)
            cr.set_line_width(1 / self.scale)
            cr.set_dash([6 / self.scale, 4 / self.scale])
            cr.rectangle(x0, y0, x1 - x0, y1 - y0)
            cr.stroke()

    def norm_crop(self):
        x0, y0, x1, y1 = self.crop
        clamp = lambda v, m: max(0, min(m, v))
        return (clamp(min(x0, x1), self.iw), clamp(min(y0, y1), self.ih),
                clamp(max(x0, x1), self.iw), clamp(max(y0, y1), self.ih))

    # --- gestures -------------------------------------------------------
    def shape_bbox(self, shape):
        tool, _c, width, pts, text = shape
        if tool == "text":
            size = max(14, width * 5)
            cr = cairo.Context(cairo.ImageSurface(cairo.FORMAT_ARGB32, 1, 1))
            cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
            cr.set_font_size(size)
            lines = text.split("\n")
            w = max(cr.text_extents(line).x_advance for line in lines)
            x, y = pts[0]
            return x, y, x + w, y + size * 1.2 * (len(lines) + 0.3)
        pad = max(width, 6) + 4
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        return min(xs) - pad, min(ys) - pad, max(xs) + pad, max(ys) + pad

    def hit(self, p):
        for i in range(len(self.shapes) - 1, -1, -1):
            x0, y0, x1, y1 = self.shape_bbox(self.shapes[i])
            if x0 <= p[0] <= x1 and y0 <= p[1] <= y1:
                return i
        return None

    def on_begin(self, _g, x, y):
        self.start = self.to_img(x, y)
        if self.tool in ("move", "text"):
            i = self.hit(self.start)
            if i is not None:
                self.moving = (i, list(self.shapes[i][3]))
                return
            if self.tool == "move":
                return
        if self.tool == "select":
            self.crop = (*self.start, *self.start)
        else:
            if self.tool == "text":
                self.ask_text(x, y, self.start)
                return
            self.current = (self.tool, self.color, self.width, [self.start], "")
        self.area.queue_draw()

    def on_update(self, _g, dx, dy):
        if self.moving:
            i, orig = self.moving
            sh = self.shapes[i]
            self.shapes[i] = (*sh[:3], [(px + dx / self.scale, py + dy / self.scale)
                                        for px, py in orig], sh[4])
            self.area.queue_draw()
            return
        if self.tool == "move":
            return
        p = (self.start[0] + dx / self.scale, self.start[1] + dy / self.scale)
        if self.tool == "select":
            self.crop = (*self.start, *p)
        elif self.tool == "text":
            return
        elif self.tool in ("pen", "hl"):
            self.current[3].append(p)
        else:
            self.current = (*self.current[:3], [self.start, p], "")
        self.area.queue_draw()

    def on_end(self, *_a):
        if self.moving:
            self.moving = None
            return
        if self.current and len(self.current[3]) > 1:
            self.shapes.append(self.current); self.redo_stack.clear()
        self.current = None
        if self.crop:
            x0, y0, x1, y1 = self.norm_crop()
            if x1 - x0 < 3 or y1 - y0 < 3:
                self.crop = None
        self.area.queue_draw()

    def ask_text(self, x, y, pos):
        pop = Gtk.Popover(has_arrow=False)
        pop.set_parent(self.area)
        pop.set_pointing_to(Gdk.Rectangle(int(x), int(y), 1, 1))
        entry = Gtk.Entry(placeholder_text="Type text, Enter to add")

        def commit(_e):
            if entry.get_text():
                self.shapes.append(("text", self.color, self.width, [pos], entry.get_text()))
                self.redo_stack.clear()
            pop.popdown()
            self.area.queue_draw()
        entry.connect("activate", commit)
        pop.connect("closed", lambda p: GLib.idle_add(p.unparent))
        pop.set_child(entry)
        pop.popup()
        entry.grab_focus()

    # --- actions --------------------------------------------------------
    def undo(self):
        if self.shapes:
            self.redo_stack.append(self.shapes.pop())
            self.area.queue_draw()

    def redo(self):
        if self.redo_stack:
            self.shapes.append(self.redo_stack.pop())
            self.area.queue_draw()

    def export(self):
        x0, y0, x1, y1 = self.norm_crop() if self.crop else (0, 0, self.iw, self.ih)
        w, h = int(x1 - x0), int(y1 - y0)
        out = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
        cr = cairo.Context(out)
        cr.translate(-x0, -y0)
        self.render(cr)
        return out

    def copy(self):
        path = GLib.build_filenamev([GLib.get_tmp_dir(), "shotwrit-clip.png"])
        self.export().write_to_png(path)
        with open(path, "rb") as f:
            data = GLib.Bytes.new(f.read())
        provider = Gdk.ContentProvider.new_union([
            Gdk.ContentProvider.new_for_bytes("image/png", data),
            Gdk.ContentProvider.new_for_value(Gdk.Texture.new_from_bytes(data))])
        self.get_clipboard().set_content(provider)
        self.copied = True
        self.save(toast=False)
        self.show_toast("Copied and saved to Pictures/shotwrit")

    def on_close(self, _w):
        """Wayland drops clipboard data when its owner exits; stay alive, hidden,
        until something else is copied."""
        clip = self.get_clipboard()
        if not (self.copied and clip.is_local()):
            return False
        self.set_visible(False)
        app = self.get_application()
        app.hold()
        clip.connect("changed", lambda c: None if c.is_local() else app.quit())
        GLib.timeout_add_seconds(1800, app.quit)
        return True

    def save(self, toast=True):
        os.makedirs(SAVE_DIR, exist_ok=True)
        path = os.path.join(SAVE_DIR, "Screenshot %s.png" %
                            datetime.datetime.now().strftime("%Y-%m-%d %H-%M-%S"))
        self.export().write_to_png(path)
        self.set_title("Shotwrit - saved " + path)
        if toast:
            self.show_toast("Saved to Pictures/shotwrit")
        if self.autoclose:
            GLib.timeout_add(1200, lambda: self.close() or False)


class App(Gtk.Application):
    def __init__(self, image=None, quick=False):
        super().__init__(application_id="io.github.mishajib.Shotwrit",
                         flags=Gio.ApplicationFlags.NON_UNIQUE)
        self.image, self.quick = image, quick

    def do_activate(self):
        if self.image:
            Editor(self, self.image, self.quick).present()
        else:
            self.hold()
            portal_screenshot(self.on_shot, interactive=self.quick)

    def on_shot(self, path):
        if path is None:
            self.release()
            print("screenshot cancelled or denied", file=sys.stderr)
            return
        if self.quick:  # GNOME's own selector already cropped it
            self.open_shot(path)
        else:
            choose_monitor(self, path, self.open_shot)

    def open_shot(self, path):
        self.release()
        if path:
            Editor(self, path, self.quick and bool(self.image), autoclose=self.quick).present()
            discard(path)


if __name__ == "__main__":
    if "--uninstall-user" in sys.argv:
        uninstall_user()
        print("Shotwrit shortcut, permission and settings removed. Screenshots in %s were kept." % SAVE_DIR)
        sys.exit(0)
    if "--version" in sys.argv:
        print("Shotwrit " + VERSION)
        sys.exit(0)
    if "--update" in sys.argv:
        sys.exit(update())
    if "--setup" in sys.argv:
        print("Shortcut set: Ctrl+Alt+S" if first_run_setup(force=True) else "Shortcut not set (GNOME only)")
        sys.exit(0)
    first_run_setup()
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    sys.exit(App(args[0] if args else None, "--quick" in sys.argv).run([sys.argv[0]]))
