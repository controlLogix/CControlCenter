#!/usr/bin/env python3
"""Claude Code PreToolUse hook: remote work never triggers privileged tools (FEDERATION.md 7.2).

If the calling agent holds work that came from ANOTHER PERSON (work_items.origin_peer)
and the operator has not approved that item with --privileged, privileged tool calls
are denied. Privileged = the repo's existing privileged surfaces (assumption A13):
PCM600 imports into a project, CODESYS runtime writes/forces, PROFINET DCP and BOOTP.

Fails closed only when federation is enabled on this hub and the hub cannot answer
(assumption A20): without federation there is no remote work to guard against.
"""
from __future__ import annotations

import json
import os
import re
import sys
import tomllib

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

PRIVILEGED_TOOLS = re.compile(
    r"^mcp__[^_].*?__(pcm_import_\w+|write_runtime_values|force_runtime_values|execute_script)$")
PRIVILEGED_BASH = re.compile(r"(pn_dcp\.py|bootp_probe\.py|PCM600Cmd|\bprofinet\b.*\b(set|write|flash)\b)", re.I)


def privileged(tool, tin):
    if PRIVILEGED_TOOLS.match(tool or ""):
        return f"tool {tool}"
    if tool == "Bash":
        m = PRIVILEGED_BASH.search(str((tin or {}).get("command", "")))
        if m:
            return f"command matching {m.group(0)!r}"
    return None


def federation_on():
    root = os.environ.get("AGENTMUX_HOME") or os.path.expanduser("~/.agentmux")
    try:
        with open(os.path.join(root, "hub", "federation.toml"), "rb") as f:
            return bool(tomllib.load(f).get("federation", {}).get("enabled"))
    except (OSError, ValueError):
        return False


def decide(event, gate=None):
    """Returns (allow, reason). gate() -> the hub's fed_gate result (injected in tests)."""
    what = privileged(event.get("tool_name"), event.get("tool_input"))
    if not what:
        return True, ""
    if gate is None:
        from hub import cli

        def gate():
            return cli.call("fed_gate", {}, timeout=5)["result"]
    try:
        g = gate()
    except Exception as e:  # noqa: BLE001
        if federation_on():
            return False, f"privileged {what} refused: the hub cannot confirm you hold no remote work ({e})"
        return True, ""
    remote = [w for w in g.get("remote_work", []) if not w.get("privileged_ok")]
    if remote:
        items = ", ".join(f"{w['id']} from {w['peer']}" for w in remote)
        return False, (f"privileged {what} refused: you hold work from another person ({items}). Remote work never "
                       f"triggers privileged tools unless your operator approves it: "
                       f"agentmux hub fed approve <quarantine id> --privileged")
    return True, ""


def main():
    try:
        event = json.load(sys.stdin)
    except ValueError:
        return 0
    allow, reason = decide(event)
    if not allow:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                                 "permissionDecisionReason": reason}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
