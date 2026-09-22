"""Command line entry point: `voicecli [run] [options]` and `voicecli devices`."""

from __future__ import annotations

import argparse
import json
import sys

from .config import Config, config_path


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


def _run(args) -> int:
    from .app import App

    cfg = Config.load()
    for key in ("device", "model", "partial_model", "language", "opacity", "silence_ms", "port", "hotkey"):
        value = getattr(args, key)
        if value is not None:
            setattr(cfg, key, value)
    if cfg.partial_model == "same":
        cfg.partial_model = None
    if args.enter is not None:
        cfg.auto_enter = args.enter
    if args.type is not None:
        cfg.type_text = args.type
    cfg.save()  # flags stick, so the next run starts the same way
    return App(cfg, overlay=not args.no_overlay, verbose=args.verbose).run()


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)

    p = argparse.ArgumentParser(prog="voicecli", description="Talk to any CLI: live local transcription typed into the focused window.")
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
        add("--language", help="language code for multilingual models, e.g. en, de")
        add("--opacity", type=float, help="overlay opacity 0.2–1.0")
        add("--silence-ms", dest="silence_ms", type=int, help="silence that ends a phrase (ms)")
        add("--port", type=int, help="local API port")
        add("--hotkey", help="toggle listening, e.g. ctrl+alt+space")
        add("--enter", action=argparse.BooleanOptionalAction, help="press Enter after each phrase")
        add("--type", action=argparse.BooleanOptionalAction, help="type text into the focused window")
        add("--no-overlay", action="store_true", help="headless: JSONL on stdout + HTTP API only")
        add("--verbose", "-v", action="store_true", help="also emit mic level events")
    r.set_defaults(func=_run)
    p.set_defaults(func=_run)
    p.epilog = f"config: {config_path()}"

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
