"""Entry point for VoiceCLI.exe and `voicecli [run] [options]` / `voicecli devices`.

Keep the imports here light: a second launch (clicking the pinned taskbar icon while voicecli
is running) should hand over to the running instance before numpy or Whisper load."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys

from . import __version__, singleton
from .config import MODES, Config, config_path, frozen, models_dir

log = logging.getLogger("voicecli")

# Must match AppUserModelID on the Start menu shortcut the installer creates.
APP_ID = "VoiceCLI.App"


def _has_console() -> bool:
    return sys.stdout is not None and os.path.basename(sys.executable).lower() != "pythonw.exe"


def _set_app_id() -> None:
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except (AttributeError, OSError):
        pass


def _devices(args) -> int:
    from .audio import list_inputs

    devs = list_inputs(all_apis=args.all)
    if args.json:
        print(json.dumps([d.to_dict() for d in devs], indent=2))
        return 0
    saved = Config.load().device
    for d in devs:
        mark = "*" if d.is_default else " "
        pick = "  <- selected" if saved and saved.lower() in d.name.lower() else ""
        print(f"{mark} [{d.index:>3}] {d.name}  ({d.hostapi}, {d.rate} Hz){pick}")
    print("\n* = Windows default.  Select with:  voicecli --device <index or part of the name>")
    return 0


def _quit_running() -> int:
    """Used by the installer and uninstaller: ask a running voicecli to exit and wait for it."""
    if not singleton.signal("quit"):
        return 0
    return 0 if singleton.wait_gone(15) else 1


def _self_test(console: bool) -> int:
    """Load the default models with downloads off and transcribe a short synthetic clip, to prove
    a build or an install is complete. Exit code 0 means OK; details go to the log."""
    os.environ["HF_HUB_OFFLINE"] = "1"
    try:
        import numpy as np

        from .audio import TARGET_RATE, list_inputs
        from .engine import load_model, model_source

        t = np.arange(TARGET_RATE) / TARGET_RATE
        clip = (0.1 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
        defaults = Config()
        for name in dict.fromkeys((defaults.model, defaults.partial_model)):
            if frozen() and model_source(name) == name:
                raise RuntimeError(f"model {name} is not bundled in {models_dir()}")
            model = load_model(name, cpu_threads=2, allow_download=False)
            list(model.transcribe(clip, beam_size=1, without_timestamps=True)[0])
            log.info("self-test: %s ok (%s)", name, model_source(name))
        log.info("self-test: %d input device(s)", len(list_inputs()))
    except Exception:
        log.exception("self-test failed")
        if console:
            print("self-test FAILED; see the log", file=sys.stderr)
        return 1
    if console:
        print("self-test ok")
    return 0


def _run(args, console: bool) -> int:
    instance = singleton.acquire()
    if instance is None:
        singleton.signal("show")
        log.info("already running; asked it to show its overlay")
        if console:
            print("voicecli is already running; brought its overlay forward.", file=sys.stderr)
        return 0
    try:
        from .app import App

        cfg = Config.load()
        for key in ("device", "model", "partial_model", "language", "mode", "ptt_key", "opacity", "silence_ms", "port", "hotkey"):
            value = getattr(args, key)
            if value is not None:
                setattr(cfg, key, value)
        if cfg.partial_model == "same":
            cfg.partial_model = None
        if args.enter is not None:
            cfg.auto_enter = args.enter
        if args.type is not None:
            cfg.type_text = args.type
        cfg = Config.from_dict(cfg.__dict__)  # command-line values get the same checks as the file
        cfg.save()  # flags stick, so the next run starts the same way
        if not cfg.allow_download:
            os.environ["HF_HUB_OFFLINE"] = "1"
        _set_app_id()
        log.info("voicecli %s starting%s (%s)", __version__, " at sign-in" if args.startup else "",
                 sys.executable)
        return App(cfg, overlay=not args.no_overlay, verbose=args.verbose, console=console).run(instance)
    finally:
        instance.stop_listening()  # the mutex goes with the process, see Instance.stop_listening


def main(argv: list[str] | None = None) -> int:
    console = _has_console()
    if not console:
        # VoiceCLI.exe and pythonw have no stdout/stderr; libraries that print must not crash.
        sys.stdout = sys.stderr = open(os.devnull, "w", encoding="utf-8")
    elif hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

    p = argparse.ArgumentParser(prog="voicecli", description="Talk to any CLI: live local transcription typed into the window you choose.")
    p.add_argument("--version", action="version", version=f"voicecli {__version__}")
    sub = p.add_subparsers(dest="cmd")

    d = sub.add_parser("devices", help="list microphones")
    d.add_argument("--all", action="store_true", help="include every host API, not just WASAPI")
    d.add_argument("--json", action="store_true")
    d.set_defaults(func=_devices)

    r = sub.add_parser("run", help="start listening (default)")
    for parser, default in ((p, None), (r, argparse.SUPPRESS)):
        # SUPPRESS on the subcommand keeps `voicecli -d 3 run` from resetting -d to None.
        add = lambda *a, **kw: parser.add_argument(*a, **{"default": default, **kw})
        add("--device", "-d", help="mic index or part of its name (saved)")
        add("--model", "-m", help="whisper model: tiny.en, base.en, small.en, medium.en, large-v3, distil-large-v3 …")
        add("--partial-model", dest="partial_model", help="smaller model for live partials (default base.en; 'same' reuses --model)")
        add("--mode", choices=MODES, help="ptt = hold --ptt-key to talk (default), open = always listening")
        add("--ptt-key", dest="ptt_key", help="push-to-talk key or combo: rctrl, ralt, capslock, f13, mouse4, ctrl+win …")
        add("--language", help="language code for multilingual models, e.g. en, de")
        add("--opacity", type=float, help="overlay opacity 0.2–1.0")
        add("--silence-ms", dest="silence_ms", type=int, help="silence that ends a phrase (ms)")
        add("--port", type=int, help="local API port")
        add("--hotkey", help="open mic: pause/resume, e.g. ctrl+alt+space")
        add("--enter", action=argparse.BooleanOptionalAction, help="press Enter after each phrase")
        add("--type", action=argparse.BooleanOptionalAction, help="type text into the focused window")
        add("--no-overlay", action="store_true", help="headless: JSONL on stdout + HTTP API only")
        add("--verbose", "-v", action="store_true", help="also emit mic level events")
        add("--startup", action="store_true", help=argparse.SUPPRESS)  # started by the Run key at sign-in
        add("--quit", action="store_true", help="ask a running voicecli to exit, then return")
        add("--self-test", dest="self_test", action="store_true", help="check the installation (models load offline), then exit")
    r.set_defaults(func=_run)
    p.set_defaults(func=_run)
    p.epilog = f"config: {config_path()}"

    args = p.parse_args(argv)
    if args.func is _devices:
        return _devices(args)
    if args.quit:
        return _quit_running()

    from . import logs

    logs.setup(console)
    if args.self_test:
        return _self_test(console)
    logs.install_crash_hooks(show_dialog=not console)
    return _run(args, console)


if __name__ == "__main__":
    raise SystemExit(main())
