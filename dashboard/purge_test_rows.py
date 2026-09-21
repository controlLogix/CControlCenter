#!/usr/bin/env python3
"""Remove rows left in cc.db by test runs. Idempotent; asks before deleting.

    python3 dashboard/purge_test_rows.py [--yes]

Only touches rows whose names/titles match the fixtures the test suites create, so
real project data is never a candidate. Journal entries are NOT deleted - that table
is append-only by design and has no delete endpoint.

Needed because earlier runs predated /api/delete and each one left a row behind.
"""

import json
import sys
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8787"
# Exact matches only. A prefix match would be a footgun the day someone names a real
# epic "smoke test rig".
TEST_EPIC_TITLES = {"smoke epic"}
TEST_DEVICE_NAMES = {"smoke-plc"}


def get(path):
    with urllib.request.urlopen(f"{BASE}/{path}", timeout=15) as response:
        return json.load(response)


def delete(kind, row_id):
    request = urllib.request.Request(
        f"{BASE}/api/delete", method="POST",
        data=json.dumps({"kind": kind, "id": row_id}).encode(),
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return json.load(response)
    except urllib.error.HTTPError as err:
        return {"error": err.read().decode("utf-8", "replace")}


def main():
    epics = [e for e in get("api/epics")["epics"] if e["title"] in TEST_EPIC_TITLES]
    devices = [d for d in get("api/devices")["devices"] if d["name"] in TEST_DEVICE_NAMES]

    if not epics and not devices:
        print("nothing to purge")
        return 0

    for epic in epics:
        print(f"  epic   id={epic['id']:<4} {epic['title']!r} "
              f"({len(epic.get('tasks', []))} task(s) would cascade)")
    for device in devices:
        print(f"  device id={device['id']:<4} {device['name']!r}")

    if "--yes" not in sys.argv:
        if input(f"\ndelete {len(epics)} epic(s) and {len(devices)} device(s)? [y/N] "
                 ).strip().lower() not in ("y", "yes"):
            print("left alone")
            return 0

    removed = cascaded = 0
    for epic in epics:
        result = delete("epic", epic["id"])
        if result.get("ok"):
            removed += 1
            cascaded += result.get("cascaded_tasks", 0)
        else:
            print(f"  failed on epic {epic['id']}: {result}")
    for device in devices:
        if delete("device", device["id"]).get("ok"):
            removed += 1
    print(f"deleted {removed} row(s), cascading {cascaded} task(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
