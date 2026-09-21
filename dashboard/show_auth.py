#!/usr/bin/env python3
"""Print the /api/auth payload as a tree. A debugging aid for the auth grouping.

    python3 dashboard/show_auth.py

Exists because the nested quoting needed to do this in a one-liner through
wsl.exe -> bash -> python is unreadable and kept breaking.
"""
import json
import sys
import urllib.request

with urllib.request.urlopen("http://127.0.0.1:8787/api/auth", timeout=15) as response:
    data = json.load(response)

if data.get("error"):
    sys.exit(f"api/auth error: {data['error']}")

print("active:", data.get("active") or "(none selected)")
files = data.get("files", {})
for key in ("settings", "env"):
    info = files.get(key) or {}
    print(f"  {info.get('path')}: mode {info.get('mode') or 'absent'}"
          + (f", {info['count']} vars" if info.get("count") else ""))
print()

for provider in data["providers"]:
    state = "ready" if provider["configured"] else "needs " + ", ".join(provider["missing"])
    print(f"{provider['id']:<20} [{provider['kind']:<11}] "
          f"{' + '.join(provider['clis']) or '-':<22} {state}")
    for row in provider.get("settings", []):
        print(f"    shared setting  {row['key']:<18} "
              f"{row['value'] if row['set'] else '(not set)'}")
    for secret in provider.get("secrets", []):
        print(f"    shared secret   {secret['name']:<18} "
              f"{'set' if secret['set'] else '(not set)'}")
    for method in provider["methods"]:
        marks = []
        if method["active"]:
            marks.append("ACTIVE")
        if method["default"]:
            marks.append("cli default")
        marks.append("ready" if method["configured"] else "needs setup")
        own = ", ".join(s["key"] for s in method["settings"]) or "-"
        print(f"    {method['id']:<20} {method['cli']:<7} own: {own:<32} "
              f"[{', '.join(marks)}]")
    print()
