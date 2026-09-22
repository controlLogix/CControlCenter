"""Always-on-top transcript overlay. It never takes keyboard focus, so typed text
keeps going to the terminal you were using."""

from __future__ import annotations

import ctypes
import queue
import tkinter as tk
from tkinter import font as tkfont
from typing import Callable

user32 = ctypes.windll.user32
GWL_EXSTYLE = -20
WS_EX_TOPMOST = 0x00000008
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000

BG = "#111418"
FG = "#e9edf1"
DIM = "#8b96a3"
STATE_COLORS = {"listening": "#3ccf6e", "speech": "#ff5c5c", "paused": "#d9a21b",
                "loading": "#5aa0ff", "ready": "#5aa0ff", "error": "#ff5c5c"}


class Overlay:
    def __init__(
        self,
        opacity: float,
        devices: Callable[[], list],
        on_device: Callable[[str], None],
        on_toggle_listen: Callable[[], None],
        options: dict[str, tk.BooleanVar] | None = None,
        on_option: Callable[[str, bool], None] | None = None,
        on_move: Callable[[int, int], None] | None = None,
        on_opacity: Callable[[float], None] | None = None,
        on_quit: Callable[[], None] | None = None,
        position: tuple[int | None, int | None] = (None, None),
        hotkey: str = "",
    ):
        self.events: queue.Queue[dict] = queue.Queue()
        self._devices = devices
        self._on_device = on_device
        self._on_toggle = on_toggle_listen
        self._on_option = on_option
        self._on_move = on_move
        self._on_opacity = on_opacity
        self._on_quit = on_quit
        self._state = "loading"
        self._device_name = ""

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
        root.attributes("-alpha", max(0.2, min(1.0, opacity)))
        self._opacity = opacity
        self.options = {k: tk.BooleanVar(root, v) for k, v in (options or {}).items()}

        base = tkfont.nametofont("TkDefaultFont").actual("family")
        self._f_small = (base, 9)
        self._f_text = (base, 14)

        top = tk.Frame(root, bg=BG)
        top.pack(fill="x", padx=12, pady=(8, 2))
        self.dot = tk.Canvas(top, width=12, height=12, bg=BG, highlightthickness=0)
        self.dot_id = self.dot.create_oval(2, 2, 11, 11, fill=STATE_COLORS["loading"], outline="")
        self.dot.pack(side="left")
        self.status = tk.Label(top, text="loading model…", fg=DIM, bg=BG, font=self._f_small, anchor="w")
        self.status.pack(side="left", padx=(6, 0))
        self.meter = tk.Canvas(top, width=80, height=6, bg="#1f252c", highlightthickness=0)
        self.meter_bar = self.meter.create_rectangle(0, 0, 0, 6, fill="#3ccf6e", outline="")
        self.meter.pack(side="right", pady=3)
        tk.Label(top, text=f"{hotkey}  ·  right-click for options", fg="#5c6773", bg=BG,
                 font=self._f_small).pack(side="right", padx=8)

        self.final = tk.Label(root, text="", fg=FG, bg=BG, font=self._f_text, anchor="w",
                              justify="left", wraplength=int(700 * scale))
        self.final.pack(fill="x", padx=12)
        self.partial = tk.Label(root, text="Say something…", fg=DIM, bg=BG,
                                font=(self._f_text[0], self._f_text[1], "italic"),
                                anchor="w", justify="left", wraplength=int(700 * scale))
        self.partial.pack(fill="x", padx=12)
        self.target = tk.Label(root, text="", fg="#5c6773", bg=BG, font=self._f_small, anchor="w")
        self.target.pack(fill="x", padx=12, pady=(2, 8))

        root.update_idletasks()
        w, h = int(740 * scale), int(150 * scale)
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        x, y = position
        if x is None or y is None or not (0 <= x < sw - 40 and 0 <= y < sh - 40):
            x = (sw - w) // 2
            y = sh - h - int(90 * scale)  # just above the taskbar
        root.geometry(f"{w}x{h}+{x}+{y}")

        for widget in (root, top, self.status, self.final, self.partial, self.target):
            widget.bind("<ButtonPress-1>", self._drag_start)
            widget.bind("<B1-Motion>", self._drag)
            widget.bind("<ButtonRelease-1>", self._drag_end)
            widget.bind("<Button-3>", self._menu)
            widget.bind("<Double-Button-1>", lambda e: self._on_toggle())

        root.after(50, self._no_activate)
        root.after(40, self._pump)

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
        if self._on_move:
            self._on_move(self.root.winfo_x(), self.root.winfo_y())

    def _menu(self, e):
        # Tk menus need a foreground window; hand focus back to whatever had it afterwards.
        prev = user32.GetForegroundWindow()
        m = tk.Menu(self.root, tearoff=0)
        mics = tk.Menu(m, tearoff=0)
        choice = tk.StringVar(self.root, self._device_name)
        for d in self._devices():
            mics.add_radiobutton(label=d["name"], value=d["name"], variable=choice,
                                 command=lambda n=d["name"]: self._switch_device(n))
        m.add_cascade(label="Microphone", menu=mics)
        op = tk.Menu(m, tearoff=0)
        for pct in (100, 90, 80, 70, 55, 40):
            op.add_command(label=f"{pct}%", command=lambda p=pct: self.set_opacity(p / 100))
        m.add_cascade(label="Opacity", menu=op)
        m.add_separator()
        labels = {"type_text": "Type into focused window", "auto_enter": "Press Enter after each phrase"}
        for key, var in self.options.items():
            m.add_checkbutton(label=labels.get(key, key), variable=var,
                              command=lambda k=key, v=var: self._on_option and self._on_option(k, v.get()))
        m.add_command(label="Pause / resume listening", command=self._on_toggle)
        m.add_separator()
        m.add_command(label="Quit", command=self._on_quit or self.root.destroy)
        try:
            m.tk_popup(e.x_root, e.y_root)
        finally:
            m.grab_release()
            if prev:
                user32.SetForegroundWindow(prev)

    def _switch_device(self, name: str) -> None:
        try:
            self._on_device(name)
        except (OSError, ValueError) as err:
            self._handle({"type": "error", "message": str(err)})

    def set_opacity(self, value: float) -> None:
        self._opacity = value
        self.root.attributes("-alpha", value)
        if self._on_opacity:
            self._on_opacity(value)

    # -- events ------------------------------------------------------------

    def _pump(self) -> None:
        try:
            while True:
                self._handle(self.events.get_nowait())
        except queue.Empty:
            pass
        self.root.after(40, self._pump)

    def _set_state(self, state: str, label: str | None = None) -> None:
        self._state = state
        self.dot.itemconfigure(self.dot_id, fill=STATE_COLORS.get(state, DIM))
        name = self._device_name or "no mic"
        self.status.configure(text=f"{label or state}  ·  {name}")

    def _handle(self, ev: dict) -> None:
        t = ev.get("type")
        if t == "state":
            label = {"loading": f"loading {ev.get('model', '')}…"}.get(ev["state"])
            self._set_state(ev["state"], label)
            if ev["state"] == "paused":
                self.partial.configure(text="Paused. Press the hotkey or double-click to resume.")
            elif ev["state"] == "listening":
                self.partial.configure(text="Say something…")
        elif t == "device":
            self._device_name = ev["device"]["name"]
            self._set_state(self._state)
        elif t == "speech_start":
            self._set_state("speech", "hearing you")
            self.target.configure(text="")
        elif t == "partial":
            self.partial.configure(text=ev["text"])
        elif t == "final":
            self.final.configure(text=ev["text"])
            self.partial.configure(text="")
            self._set_state("listening")
        elif t == "discard":
            self._set_state("listening")
            self.partial.configure(text="")
        elif t == "typed":
            self.target.configure(text=f"→ {ev.get('action', 'typed')} into: {ev.get('window') or '(unknown window)'}")
        elif t == "hint":
            self.target.configure(text=f"⚠ {ev['message']}")
        elif t == "error":
            self._set_state("error", "error")
            self.target.configure(text=ev.get("message", ""))
        elif t == "level":
            if self._state != "paused":
                width = min(80, int(80 * (ev["rms"] / 0.08) ** 0.5))
                self.meter.coords(self.meter_bar, 0, 0, width, 6)

    def run(self) -> None:
        self.root.mainloop()

    def close(self) -> None:
        try:
            self.root.after(0, self.root.destroy)
        except tk.TclError:
            pass
