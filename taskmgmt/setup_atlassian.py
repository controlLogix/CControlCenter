#!/usr/bin/env python3
"""Interactive, non-echoing setup for ~/.agentmux/atlassian.json.

Run this IN YOUR OWN TERMINAL, not through an agent:

    python3 taskmgmt/setup_atlassian.py

The API token is read with getpass, so it is never echoed, never becomes a
command argument (so it cannot land in shell history or `ps`), and the file is
written 0600 under a 077 umask so it is never briefly world-readable.

Cloud needs an API token from https://id.atlassian.com/manage-profile/security/api-tokens
Server/DC needs a Personal Access Token instead, and no email.
"""

from __future__ import annotations

import getpass
import json
import os
import pathlib
import re
import stat
import sys

CONFIG = pathlib.Path.home() / ".agentmux" / "atlassian.json"


def ask(label: str, default: str = "", required: bool = True) -> str:
    suffix = f" [{default}]" if default else ""
    while True:
        value = input(f"  {label}{suffix}: ").strip() or default
        if value or not required:
            return value
        print("    required.")


def main() -> int:
    print(__doc__)

    if CONFIG.exists():
        print(f"  {CONFIG} already exists.")
        if ask("overwrite? (yes/no)", "no").lower() not in ("y", "yes"):
            print("  left unchanged.")
            return 0

    deployment = ""
    while deployment not in ("cloud", "server"):
        deployment = ask("deployment (cloud|server)", "cloud").lower()

    base_url = ""
    while not re.match(r"^https://[^\s/]+", base_url):
        base_url = ask("base_url (e.g. https://yourorg.atlassian.net)").rstrip("/")
        if not base_url.startswith("https://"):
            print("    must start with https://")

    email = ask("email (Atlassian account)") if deployment == "cloud" else ""

    token = ""
    while not token:
        token = getpass.getpass("  api_token (not echoed): ").strip()
        if not token:
            print("    required.")

    jira_project = ask("jira_project key (e.g. AGENT)", required=False).upper()
    confluence_space = ask("confluence_space key (e.g. AGENTMUX)", required=False).upper()
    done_transition = ask("done transition name/regex", "done|closed|complete|resolve",
                          required=False)

    cfg = {"deployment": deployment, "base_url": base_url, "api_token": token}
    if email:
        cfg["email"] = email
    if jira_project:
        cfg["jira_project"] = jira_project
    if confluence_space:
        cfg["confluence_space"] = confluence_space
    if done_transition:
        cfg["done_transition"] = done_transition

    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    old_umask = os.umask(0o077)
    try:
        # Write via a temp file in the same directory, then rename: a reader can
        # never see a partial credential file, and the mode is right from creation.
        tmp = CONFIG.with_name(CONFIG.name + f".tmp.{os.getpid()}")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(cfg, fh, indent=2)
            fh.write("\n")
        os.chmod(tmp, 0o600)
        os.replace(tmp, CONFIG)
    finally:
        os.umask(old_umask)

    mode = stat.S_IMODE(CONFIG.stat().st_mode)
    print(f"\n  wrote {CONFIG} (mode {mode:o})")
    if mode != 0o600:
        print(f"  WARNING: expected 600. Run: chmod 600 {CONFIG}")

    print("\n  Verify with:")
    print(f"    python3 {pathlib.Path(__file__).parent / 'task.py'} whoami")
    print("  Dry-run anything first, e.g.:")
    print(f"    python3 {pathlib.Path(__file__).parent / 'task.py'} --dry-run "
          f"create --summary 'test'")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\n  aborted; nothing written.")
        raise SystemExit(130)
