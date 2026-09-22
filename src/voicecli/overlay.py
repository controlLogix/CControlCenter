"""Always-on-top transcript overlay. It never takes keyboard focus, so typed text
keeps going to the terminal you were using."""

from __future__ import annotations

import ctypes
import queue
import tkinter as tk
from tkinter import font as tkfont
from typing import TYPE_CHECKING

from . import inject

if TYPE_CHECKING:
    from .app import App

user32 = ctypes.windll.user32
GWL_EXSTYLE = -20
WS_EX_TOPMOST = 0x00000008
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000

BG = "#111418"
FG = "#e9edf1"
DIM = "#8b96a3"
FAINT = "#5c6773"
STATE_COLORS = {"listening": "#3ccf6e", "speech": "#ff5c5c", "recording": "#ff5c5c", "paused": "#d9a21b",
                "ptt_idle": "#8b96a3", "loading": "#5aa0ff", "ready": "#5aa0ff", "error": "#ff5c5c"}


def _virtual_screen() -> tuple[int, int, int, int]:
    """Bounding box of all monitors (SM_XVIRTUALSCREEN .. SM_CYVIRTUALSCREEN)."""
    m = user32.GetSystemMetrics
    x, y = m(76), m(77)
    return x, y, x + m(78), y + m(79)


class Overlay:
    def __init__(self, app: "App", position: tuple[int | None, int | None] = (None, None)):
        self.app = app
        self.cfg = app.cfg
        self.events: queue.Queue[dict] = queue.Queue()
        self._state = "loading"
        self._device_name = ""
        self._closing = False

        try:  # per-monitor DPI aware, so geometry and fonts use real pixels on scaled displays
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except OSError:
            pass
        root = self.root = tk.Tk()
        scale = root.winfo_fpixels("1i") / 96
        root.title("voicecli")
        root.overrideredirect(True)
        root.configure(bg=BG)
        root.attributes("-topmost", True)
        root.attributes("-alpha", max(0.2, min(1.0, self.cfg.opacity)))

        base = tkfont.nametofont("TkDefaultFont").actual("family")
        f_small = (base, 9)
        f_text = (base, 14)

        top = tk.Frame(root, bg=BG)
        top.pack(fill="x", padx=12, pady=(8, 2))
        self.dot = tk.Canvas(top, width=12, height=12, bg=BG, highlightthickness=0)
        self.dot_id = self.dot.create_oval(2, 2, 11, 11, fill=STATE_COLORS["loading"], outline="")
        self.dot.pack(side="left")
        self.status = tk.Label(top, text="loading model…", fg=DIM, bg=BG, font=f_small, anchor="w")
        self.status.pack(side="left", padx=(6, 0))
        self.meter = tk.Canvas(top, width=80, height=6, bg="#1f252c", highlightthickness=0)
        self.meter_bar = self.meter.create_rectangle(0, 0, 0, 6, fill="#3ccf6e", outline="")
        self.meter.pack(side="right", pady=3)
        tk.Label(top, text="right-click for options", fg=FAINT, bg=BG, font=f_small).pack(side="right", padx=8)

        wrap = int(700 * scale)
        self.final = tk.Label(root, text="", fg=FG, bg=BG, font=f_text, anchor="w", justify="left", wraplength=wrap)
        self.final.pack(fill="x", padx=12)
        self.partial = tk.Label(root, text="", fg=DIM, bg=BG, font=(f_text[0], f_text[1], "italic"),
                                anchor="w", justify="left", wraplength=wrap)
        self.partial.pack(fill="x", padx=12)
        bottom = tk.Frame(root, bg=BG)
        bottom.pack(fill="x", padx=12, pady=(2, 8), side="bottom")
        self.dest = tk.Label(bottom, text="", fg=DIM, bg=BG, font=f_small, anchor="w")
        self.dest.pack(side="left")
        self.note = tk.Label(bottom, text="", fg=FAINT, bg=BG, font=f_small, anchor="e")
        self.note.pack(side="right")
        self._show_dest()

        root.update_idletasks()
        w, h = int(740 * scale), int(160 * scale)
        vx0, vy0, vx1, vy1 = _virtual_screen()
        x, y = position
        if x is None or y is None or not (vx0 <= x < vx1 - 40 and vy0 <= y < vy1 - 40):
            x = (root.winfo_screenwidth() - w) // 2
            y = root.winfo_screenheight() - h - int(90 * scale)  # just above the taskbar
        root.geometry(f"{w}x{h}+{x}+{y}")

        for widget in (root, top, self.status, self.final, self.partial, bottom, self.dest, self.note):
            widget.bind("<ButtonPress-1>", self._drag_start)
            widget.bind("<B1-Motion>", self._drag)
            widget.bind("<ButtonRelease-1>", self._drag_end)
            widget.bind("<Button-3>", self._menu)

        root.after(50, self._no_activate)
        root.after(40, self._pump)

    # -- thread-safe requests ---------------------------------------------------

    def request(self, cmd: str) -> None:
        self.events.put({"type": "_cmd", "cmd": cmd})

    # -- window plumbing ------------------------------------------------------

    def _hwnd(self) -> int:
        return user32.GetParent(self.root.winfo_id()) or self.root.winfo_id()

    def _no_activate(self) -> None:
        hwnd = self._hwnd()
        style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW | WS_EX_TOPMOST)

    def _drag_start(self, e):
        self._dx, self._dy = e.x_root - self.root.winfo_x(), e.y_root - self.root.winfo_y()

    def _drag(self, e):
        self.root.geometry(f"+{e.x_root - self._dx}+{e.y_root - self._dy}")

    def _drag_end(self, e):
        self.app.save_position(self.root.winfo_x(), self.root.winfo_y())

    def _show(self) -> None:
        self.root.deiconify()
        self.root.attributes("-topmost", True)
        self.root.lift()
        self._no_activate()
        self.note.configure(text="")

    def _toggle(self) -> None:
        if self.root.state() == "withdrawn":
            self._show()
        else:
            self.root.withdraw()

    def _quit(self) -> None:
        if not self._closing:
            self._closing = True
            self.root.after(0, self.root.destroy)

    # -- menu ------------------------------------------------------------------

    def _menu(self, e):
        app, cfg = self.app, self.cfg
        # Tk menus need a foreground window; hand focus back to whatever had it afterwards.
        prev = user32.GetForegroundWindow()
        m = tk.Menu(self.root, tearoff=0)

        mode = tk.StringVar(self.root, cfg.mode)
        modes = tk.Menu(m, tearoff=0)
        modes.add_radiobutton(label=f"Push-to-talk (hold {inject.key_label(cfg.ptt_key)})", value="ptt",
                              variable=mode, command=lambda: self._safe(app.set_mode, "ptt"))
        modes.add_radiobutton(label=f"Open mic ({inject.key_label(cfg.hotkey)} pauses)", value="open",
                              variable=mode, command=lambda: self._safe(app.set_mode, "open"))
        m.add_cascade(label="Listening mode", menu=modes)

        mics = tk.Menu(m, tearoff=0)
        mic = tk.StringVar(self.root, self._device_name)
        for d in app.devices():
            mics.add_radiobutton(label=d["name"], value=d["name"], variable=mic,
                                 command=lambda n=d["name"]: self._safe(app.set_device, n))
        m.add_cascade(label="Microphone", menu=mics)

        targets = tk.Menu(m, tearoff=0)
        current = tk.IntVar(self.root, app.target.hwnd if app.target else 0)
        targets.add_radiobutton(label="Whatever window has focus", value=0, variable=current,
                                command=lambda: self._safe(app.set_target, None))
        targets.add_separator()
        for w in inject.list_windows():
            targets.add_radiobutton(label=w.label, value=w.hwnd, variable=current,
                                    command=lambda h=w.hwnd: self._safe(app.set_target, h))
        m.add_cascade(label=f"Send text to   ({inject.key_label(cfg.lock_hotkey)} locks the focused window)", menu=targets)

        m.add_separator()
        opts = {"type_text": tk.BooleanVar(self.root, cfg.type_text),
                "auto_enter": tk.BooleanVar(self.root, cfg.auto_enter)}
        m.add_checkbutton(label="Type text into the window", variable=opts["type_text"],
                          command=lambda: app.set_option("type_text", opts["type_text"].get()))
        m.add_checkbutton(label="Press Enter after each phrase", variable=opts["auto_enter"],
                          command=lambda: app.set_option("auto_enter", opts["auto_enter"].get()))
        op = tk.Menu(m, tearoff=0)
        for pct in (100, 90, 80, 70, 55, 40):
            op.add_command(label=f"{pct}%", command=lambda p=pct: self._set_opacity(p / 100))
        m.add_cascade(label="Opacity", menu=op)
        if cfg.mode == "open":
            m.add_command(label="Pause / resume listening", command=app.toggle_listening)
        m.add_separator()
        m.add_command(label=f"Hide overlay   ({inject.key_label(cfg.show_hotkey)} shows it)", command=self.root.withdraw)
        m.add_command(label="Quit voicecli", command=self._quit)
        try:
            m.tk_popup(e.x_root, e.y_root)
        except tk.TclError:
            return
        finally:
            try:
                m.grab_release()
            except tk.TclError:
                pass
            if prev:
                user32.SetForegroundWindow(prev)

    def _safe(self, fn, *args) -> None:
        try:
            fn(*args)
        except (OSError, ValueError) as err:
            self._handle({"type": "error", "message": str(err)})

    def _set_opacity(self, value: float) -> None:
        self.root.attributes("-alpha", value)
        self.app.save_opacity(value)

    # -- events ------------------------------------------------------------

    def _pump(self) -> None:
        if self._closing:
            return
        try:
            while True:
                self._handle(self.events.get_nowait())
        except queue.Empty:
            pass
        except tk.TclError:
            return
        self.root.after(40, self._pump)

    def _idle_text(self) -> str:
        if self.cfg.mode == "ptt":
            return f"hold {inject.key_label(self.cfg.ptt_key)} to talk"
        return "listening"

    def _set_state(self, state: str, label: str | None = None) -> None:
        self._state = state
        self.dot.itemconfigure(self.dot_id, fill=STATE_COLORS.get(state, DIM))
        name = self._device_name or "no mic"
        self.status.configure(text=f"{label or state}  ·  {name}")

    def _show_dest(self) -> None:
        t = self.app.target
        if t is not None:
            self.dest.configure(text=f"🔒 sending to: {t.label}", fg="#e0b84c")
        else:
            self.dest.configure(text="→ sending to: whatever window has focus", fg=DIM)

    def _handle(self, ev: dict) -> None:
        t = ev.get("type")
        if t == "_cmd":
            {"show": self._show, "toggle": self._toggle, "quit": self._quit}[ev["cmd"]]()
        elif t == "state":
            s = ev["state"]
            label = {"loading": f"loading {ev.get('model', '')}…", "ptt_idle": self._idle_text(),
                     "recording": "recording…", "paused": "paused", "listening": "listening"}.get(s)
            self._set_state(s, label)
            if s == "paused":
                self.partial.configure(text=f"Paused. {inject.key_label(self.cfg.hotkey)} resumes.")
            elif s in ("recording",):
                self.partial.configure(text="")
        elif t == "mode":
            self.partial.configure(text="")
        elif t == "device":
            self._device_name = ev["device"]["name"]
            self._set_state(self._state, self.status.cget("text").split("  ·  ")[0])
        elif t == "target":
            self._show_dest()
        elif t == "speech_start":
            if self._state != "recording":
                self._set_state("speech", "hearing you")
            self.note.configure(text="")
        elif t == "partial":
            self.partial.configure(text=ev["text"])
        elif t == "final":
            self.final.configure(text=ev["text"])
            self.partial.configure(text="")
        elif t == "discard":
            self.partial.configure(text="")
        elif t == "typed":
            if ev.get("action") == "skipped":
                self.note.configure(text=f"not typed: {ev.get('reason', '')}", fg="#e0b84c")
            else:
                self.note.configure(text=f"{ev.get('action')} → {ev.get('window', '')[:40]}", fg=FAINT)
        elif t == "hint":
            self.note.configure(text=f"⚠ {ev['message']}", fg="#e0b84c")
        elif t == "error":
            self._set_state("error", "error")
            self.note.configure(text=ev.get("message", "")[:90], fg="#ff7b7b")
        elif t == "level":
            width = min(80, int(80 * (ev["rms"] / 0.08) ** 0.5))
            self.meter.coords(self.meter_bar, 0, 0, width, 6)

    def run(self) -> None:
        self.root.mainloop()
