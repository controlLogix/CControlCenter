#!/usr/bin/env python3
"""Add the agentmux Bash allow rule to Claude Code user settings.

Run this yourself - Claude Code blocks an agent from editing its own permission
settings (reason: Self-Modification), which is correct. This script exists so the
change is one command rather than a hand-edit.

    python C:\\Dev\\agentmux\\add-allow-rule.py            # apply
    python C:\\Dev\\agentmux\\add-allow-rule.py --check     # report only

Idempotent. Preserves the file's existing formatting by doing a text insertion
rather than reserialising the JSON. Writes a timestamped backup first, and
refuses to write anything that does not parse as valid JSON.
"""

import datetime
import json
import pathlib
import shutil
import sys

SETTINGS = pathlib.Path.home() / ".claude" / "settings.json"
RULE = "Bash(wsl.exe -d Ubuntu -- /home/nick/.local/bin/agentmux:*)"
ANCHOR = '"Bash(git push)"'


def main() -> int:
    check_only = "--check" in sys.argv

    if not SETTINGS.is_file():
        print(f"error: not found: {SETTINGS}")
        return 1

    text = SETTINGS.read_text(encoding="utf-8")
    try:
        cfg = json.loads(text)
    except json.JSONDecodeError as exc:
        print(f"error: {SETTINGS} is not valid JSON ({exc}). Fix it first.")
        return 1

    allow = cfg.get("permissions", {}).get("allow", [])
    print(f"settings : {SETTINGS}")
    print(f"allow rules: {len(allow)}")

    if RULE in allow:
        print("result   : rule ALREADY PRESENT, nothing to do")
        return 0
    if check_only:
        print("result   : rule NOT present (run without --check to add it)")
        return 0

    # Text insertion after the anchor line, so surrounding formatting survives.
    idx = text.find(ANCHOR)
    if idx == -1:
        print(f"error: could not find anchor {ANCHOR} to insert after.")
        print("       Add this line to permissions.allow by hand instead:")
        print(f'         "{RULE}"')
        return 1
    line_end = text.find("\n", idx)
    if line_end == -1:
        print("error: anchor is on the final line; refusing to guess. Add by hand.")
        return 1

    indent = text[text.rfind("\n", 0, idx) + 1 : idx]
    updated = (
        text[:line_end] + ",\n" + indent + f'"{RULE}"' + text[line_end:]
    )

    # Never write something that does not parse, and never write something whose
    # only difference is not the one rule we intend to add.
    try:
        new_cfg = json.loads(updated)
    except json.JSONDecodeError as exc:
        print(f"error: insertion produced invalid JSON ({exc}). Nothing written.")
        return 1

    new_allow = new_cfg.get("permissions", {}).get("allow", [])
    if new_allow != allow + [RULE]:
        print("error: unexpected diff in the allow array. Nothing written.")
        return 1
    scrubbed = dict(new_cfg)
    scrubbed["permissions"] = {
        k: v for k, v in new_cfg["permissions"].items() if k != "allow"
    }
    original = dict(cfg)
    original["permissions"] = {
        k: v for k, v in cfg["permissions"].items() if k != "allow"
    }
    if scrubbed != original:
        print("error: something outside permissions.allow changed. Nothing written.")
        return 1

    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = SETTINGS.with_name(f"settings.json.bak-{stamp}")
    shutil.copy2(SETTINGS, backup)
    SETTINGS.write_text(updated, encoding="utf-8")

    print(f"backup   : {backup}")
    print(f"result   : ADDED -> {RULE}")
    print(f"allow rules now: {len(new_allow)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
