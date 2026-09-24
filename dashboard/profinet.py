"""A shared PROFINET station schema, and a diff against an imported DCP snapshot.

WHY A SCHEMA AND NOT JUST AN IMPORT. The DCP panel could already import the output
of `pn_dcp.py identify` and print it in a table. That tells you what IS on the
segment; it does not tell you whether that is what SHOULD be. The station name and
IP a PROFINET controller looks for are configured in the engineering project, so
the useful question on a commissioning day is "which device does not match the
project" - and a table of forty stations does not answer it by eye.

So this mirrors the Modbus panel exactly: one server-side JSON document the whole
team shares (the expected stations), a snapshot of what was actually observed, and
a computed status per row. Modbus's editor saves a tag table and shows live values
against it; this saves a station table and shows imported values against it.

THE SNAPSHOT IS STILL AN IMPORT, AND THAT IS STATED EVERYWHERE. Nothing here
touches the plant network. DCP Identify needs a raw socket on a real NIC, which
this unprivileged server does not have and WSL NAT could not carry anyway. The
operator runs the privileged helper and pastes or uploads the result. What is
stored is therefore always "what was true when that scan ran", and the schema
carries the observation timestamp so an hour-old snapshot cannot be mistaken for
live device status.

WRITING TO A DEVICE IS NOT HERE AND WILL NOT BE. `pn_dcp.py set` renames or
re-addresses a running station permanently, and a wrong station name disconnects a
machine from its controller. That stays a deliberate, typed, terminal action.
"""

import json
import os
import re
import tempfile
import threading
import time
from pathlib import Path

MAX_STATIONS = 512
MAC_RE = re.compile(r"(?:[0-9a-f]{2}:){5}[0-9a-f]{2}\Z", re.I)
IPV4_RE = re.compile(r"\d{1,3}(?:\.\d{1,3}){3}\Z")
# IEC 61158-6-10 station names: lower-case letters, digits, hyphen and dot, not
# starting or ending with a separator, and not shaped like an IP address.
NAME_RE = re.compile(r"[a-z0-9]([a-z0-9.-]{0,238}[a-z0-9])?\Z")

FIELDS = ("mac", "name", "ip", "subnet", "gateway", "vendor", "role", "note")


class Invalid(ValueError):
    """Operator input the panel refuses. Maps to HTTP 400."""


def _text(value, limit, label):
    if value is None:
        return None
    if not isinstance(value, str):
        raise Invalid(f"{label} must be a string")
    value = value.strip()
    if not value:
        return None
    if len(value) > limit:
        raise Invalid(f"{label} exceeds {limit} characters")
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in value):
        raise Invalid(f"{label} contains control characters")
    return value


def _ipv4(value, label):
    value = _text(value, 15, label)
    if value is None:
        return None
    if not IPV4_RE.match(value) or any(not part.isdigit() or int(part) > 255
                                       for part in value.split(".")):
        raise Invalid(f"{label} is not an IPv4 address")
    return value


def check_station(row, index):
    if not isinstance(row, dict):
        raise Invalid(f"station {index + 1}: must be an object")
    unknown = row.keys() - set(FIELDS)
    if unknown:
        raise Invalid(f"station {index + 1}: unknown fields {', '.join(sorted(unknown))}")
    mac = _text(row.get("mac"), 17, f"station {index + 1} mac")
    if mac is None or not MAC_RE.match(mac):
        raise Invalid(f"station {index + 1}: a MAC address like 00:1b:1b:00:00:01 is required")
    name = _text(row.get("name"), 240, f"station {index + 1} name")
    if name is not None and not NAME_RE.match(name):
        raise Invalid(f"station {index + 1}: '{name}' is not a valid PROFINET station "
                      f"name (lower case, digits, dot and hyphen)")
    return {
        "mac": mac.lower(), "name": name,
        "ip": _ipv4(row.get("ip"), f"station {index + 1} ip"),
        "subnet": _ipv4(row.get("subnet"), f"station {index + 1} subnet"),
        "gateway": _ipv4(row.get("gateway"), f"station {index + 1} gateway"),
        "vendor": _text(row.get("vendor"), 80, f"station {index + 1} vendor"),
        "role": _text(row.get("role"), 40, f"station {index + 1} role"),
        "note": _text(row.get("note"), 200, f"station {index + 1} note"),
    }


def validate(config):
    """Check a schema document without writing it."""
    if not isinstance(config, dict):
        raise Invalid("schema must be a JSON object")
    unknown = config.keys() - {"segment", "controller", "stations"}
    if unknown:
        raise Invalid(f"unknown fields: {', '.join(sorted(unknown))}")
    stations = config.get("stations")
    if not isinstance(stations, list):
        raise Invalid("stations must be a list")
    if len(stations) > MAX_STATIONS:
        raise Invalid(f"at most {MAX_STATIONS} stations")
    checked = [check_station(row, index) for index, row in enumerate(stations)]
    seen = set()
    for row in checked:
        if row["mac"] in seen:
            raise Invalid(f"duplicate MAC {row['mac']}")
        seen.add(row["mac"])
    names = [row["name"] for row in checked if row["name"]]
    if len(set(names)) != len(names):
        # Two stations with one name is the failure this panel exists to catch, so
        # it must not be possible to WRITE it into the schema either.
        raise Invalid("two stations share a station name; PROFINET names are unique "
                      "per segment")
    return {"segment": _text(config.get("segment"), 80, "segment"),
            "controller": _text(config.get("controller"), 80, "controller"),
            "stations": checked}


def check_snapshot(records):
    """Validate imported DCP Identify records - the same shape pn_dcp.py emits."""
    if not isinstance(records, list):
        raise Invalid("snapshot must be a list of DCP records")
    if len(records) > MAX_STATIONS * 4:
        raise Invalid("snapshot is too large")
    out = []
    for index, row in enumerate(records):
        if not isinstance(row, dict):
            raise Invalid(f"record {index + 1}: must be an object")
        if row.get("kind") != "dcp-identify":
            raise Invalid(f"record {index + 1}: expected DCP Identify output")
        mac = _text(row.get("mac"), 17, f"record {index + 1} mac")
        if mac is None or not MAC_RE.match(mac):
            raise Invalid(f"record {index + 1}: invalid MAC")
        out.append({
            # `kind` is KEPT, not stripped. These records are persisted and read
            # back on the next server start, and check_snapshot is the same
            # function that validates them then - dropping the discriminator made
            # every saved snapshot unloadable, which presented as an import that
            # vanished on restart.
            "kind": "dcp-identify",
            "mac": mac.lower(),
            "name": _text(row.get("name"), 240, f"record {index + 1} name"),
            "ip": _ipv4(row.get("ip"), f"record {index + 1} ip"),
            "subnet": _ipv4(row.get("subnet"), f"record {index + 1} subnet"),
            "gateway": _ipv4(row.get("gateway"), f"record {index + 1} gateway"),
            "vendor": _text(row.get("vendor"), 80, f"record {index + 1} vendor"),
            "vendor_id": _text(str(row.get("vendor_id") or "") or None, 20,
                               f"record {index + 1} vendor_id"),
            "device_id": _text(str(row.get("device_id") or "") or None, 20,
                               f"record {index + 1} device_id"),
            "at": _text(str(row.get("at") or "") or None, 40, f"record {index + 1} at"),
        })
    return out


COMPARED = ("name", "ip", "subnet", "gateway")


def reconcile(schema, snapshot):
    """Join the expected stations to the observed ones on MAC.

    MAC is the join key and not the station name, because the name is exactly the
    field most likely to be wrong - joining on it would quietly pair an unnamed
    replacement device with nothing and report both sides as missing.
    """
    observed = {row["mac"]: row for row in snapshot}
    rows = []
    for expected in schema.get("stations", []):
        actual = observed.pop(expected["mac"], None)
        if actual is None:
            rows.append({"status": "missing", "mac": expected["mac"],
                         "expected": expected, "actual": None, "differences": []})
            continue
        differences = [field for field in COMPARED
                       if expected.get(field) and expected[field] != actual.get(field)]
        rows.append({"status": "mismatch" if differences else "match",
                     "mac": expected["mac"], "expected": expected, "actual": actual,
                     "differences": differences})
    for mac, actual in observed.items():
        rows.append({"status": "unexpected", "mac": mac, "expected": None,
                     "actual": actual, "differences": []})
    order = {"mismatch": 0, "missing": 1, "unexpected": 2, "match": 3}
    rows.sort(key=lambda row: (order[row["status"]], row["mac"]))
    counts = {status: 0 for status in order}
    for row in rows:
        counts[row["status"]] += 1
    return {"rows": rows, "counts": counts}


class Schema:
    """The persisted schema plus the last imported snapshot, shared server-side."""

    EMPTY = {"segment": None, "controller": None, "stations": []}

    def __init__(self, path):
        self.path = Path(path)
        self.lock = threading.Lock()
        self.schema = dict(self.EMPTY)
        self.snapshot = []
        self.imported_at = None
        self.imported_by = None
        try:
            saved = json.loads(self.path.read_text(encoding="utf-8"))
            self.schema = validate(saved.get("schema") or self.EMPTY)
            self.snapshot = check_snapshot(saved.get("snapshot") or [])
            self.imported_at = saved.get("imported_at")
            self.imported_by = saved.get("imported_by")
        except (OSError, ValueError, AttributeError):
            # A corrupt file is replaced on the next save rather than crashing the
            # server; the operator sees an empty schema, which is honest.
            pass

    def _persist_locked(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"schema": self.schema, "snapshot": self.snapshot,
                   "imported_at": self.imported_at, "imported_by": self.imported_by}
        handle, temp = tempfile.mkstemp(dir=str(self.path.parent), suffix=".tmp")
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as out:
                json.dump(payload, out, indent=2)
            os.replace(temp, self.path)
        except BaseException:
            try:
                os.unlink(temp)
            except OSError:
                pass
            raise

    def save_schema(self, config):
        checked = validate(config)
        with self.lock:
            self.schema = checked
            self._persist_locked()
        return self.state()

    def save_snapshot(self, records, actor=None):
        checked = check_snapshot(records)
        actor = _text(actor, 64, "actor")
        with self.lock:
            self.snapshot = checked
            self.imported_at = time.time()
            self.imported_by = actor
            self._persist_locked()
        return self.state()

    def state(self):
        with self.lock:
            schema = json.loads(json.dumps(self.schema))
            snapshot = json.loads(json.dumps(self.snapshot))
            imported_at, imported_by = self.imported_at, self.imported_by
        return {"schema": schema, "snapshot": snapshot,
                "imported_at": imported_at, "imported_by": imported_by,
                "max_stations": MAX_STATIONS,
                "reconciliation": reconcile(schema, snapshot)}
