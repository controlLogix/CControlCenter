"""An unprivileged Ethernet/IP-segment scanner for the local plant network.

WHAT IT DOES. Sweeps a private IPv4 range the operator names with ordinary TCP
connects on a small set of industrial service ports, then reads the host's own
ARP/neighbour table to attach a MAC address and an OUI vendor to anything that
answered. The result is "what is on this segment, and what does it speak" - the
question you ask before pointing the Modbus or PROFINET panel at anything.

WHY TCP CONNECT AND NOT ARP OR ICMP. Raw frames and raw ICMP need root. This
server runs unprivileged and the project does not pretend otherwise (the same
reason the BOOTP panel was only ever a notice). A TCP connect needs no privilege,
tells you more than a ping does - it names the service - and a device that
answers on 502 is more useful than one that merely replies to ICMP. The ARP
lookup afterwards is free: the sweep itself populates the neighbour table for
every on-link address, so a MAC comes back for hosts on the same segment without
a single privileged operation.

THE RANGE GUARD IS NOT COSMETIC. Only RFC1918, CGNAT, link-local and loopback
ranges may be scanned, and never more than MAX_HOSTS addresses. A plant segment
is private by definition, so this costs the operator nothing, and it means a
mistyped prefix cannot turn an operator's own dashboard into a scanner pointed at
the public internet. The bound is checked before a single socket opens.

EVERY SCAN IS JOURNALLED - range, ports, actor and result count - because a scan
is a visible event on someone else's network and an operator should be able to
answer "what was that" a week later.

IT IS A SNAPSHOT, NOT A MONITOR. A scan runs once, in a bounded thread pool, and
ends. Nothing here re-scans on a timer: a background process quietly touching
every address on a plant segment forever is not a thing this dashboard should do
without being asked each time.
"""

import gzip
import ipaddress
import json
import os
import re
import socket
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

MAX_HOSTS = 1024
MAX_PORTS = 16
CONNECT_TIMEOUT = 0.4
WORKERS = 64
SCAN_DEADLINE = 300.0            # a whole scan, not a single connect

# Ports worth asking about on a controls network, with what an answer means. The
# name is what the UI shows next to the port, so it must say the protocol rather
# than the vendor - two vendors' PLCs both answer on 44818.
SERVICES = {
    22: "SSH",
    80: "HTTP",
    102: "S7comm / ISO-TSAP",
    443: "HTTPS",
    502: "Modbus TCP",
    1883: "MQTT",
    1962: "PCWorx",
    2222: "EtherNet/IP I/O",
    4840: "OPC UA",
    8883: "MQTT over TLS",
    9600: "Omron FINS",
    11740: "SINEC / PROFINET context",
    20000: "DNP3",
    44818: "EtherNet/IP explicit",
    48898: "Beckhoff ADS",
}
DEFAULT_PORTS = [22, 80, 102, 443, 502, 1883, 4840, 44818, 48898]

# The full IEEE registry, vendored as a gzipped OUI->organisation table (see
# vendor/README.md). 40k assignments, 351 KiB on disk, no runtime download - the
# machines this runs on are plant-side and frequently have no route to the
# internet, so looking a vendor up over HTTP the way most tools do would mean the
# column is empty exactly where it is most useful.
#
# Loaded on the first lookup rather than at import, because a dashboard that never
# opens the scanner should not pay for it.
_OUI_PATH = Path(__file__).resolve().parent / "vendor" / "oui.tsv.gz"
_oui_table = None
_oui_lock = threading.Lock()


def _oui_registry():
    global _oui_table
    with _oui_lock:
        if _oui_table is None:
            table = {}
            try:
                with gzip.open(_OUI_PATH, "rt", encoding="utf-8") as handle:
                    for line in handle:
                        prefix, _, org = line.rstrip("\n").partition("\t")
                        if org:
                            table[prefix] = org
            except OSError:
                # Missing or unreadable: fall back to the curated table below
                # rather than failing a scan over a lookup table.
                table = {}
            _oui_table = table
        return _oui_table


# Kept as an override for the prefixes worth naming in controls terms. The IEEE
# registry says "Rockwell Automation" for some and a subsidiary's legal name for
# others; on a plant network the name on the cabinet is the useful one.
VENDORS = {
    "00:0c:29": "VMware", "00:50:56": "VMware", "00:1c:06": "Siemens",
    "00:1b:1b": "Siemens", "08:00:06": "Siemens", "00:0e:8c": "Siemens",
    "20:87:56": "Siemens", "00:00:bc": "Rockwell Automation",
    "00:1d:9c": "Rockwell Automation", "5c:88:16": "Rockwell Automation",
    "f4:54:33": "Rockwell Automation", "00:30:de": "WAGO",
    "00:0a:dc": "WAGO", "00:07:7c": "Beckhoff", "00:01:05": "Beckhoff",
    "00:80:f4": "Telemecanique / Schneider", "00:00:54": "Schneider Electric",
    "00:60:35": "Schneider Electric", "00:20:4a": "Lantronix",
    "00:90:e8": "Moxa", "00:0b:ad": "Moxa", "00:0f:8f": "Phoenix Contact",
    "00:a0:45": "Phoenix Contact", "00:1e:c0": "Microchip",
    "00:04:17": "Hilscher", "00:02:a2": "Hilscher", "00:1e:cd": "Turck",
    "00:11:6b": "Digital Data / Turck", "00:23:c1": "Advantech",
    "00:d0:c9": "Advantech", "00:0d:81": "Pepperl+Fuchs",
    "b8:27:eb": "Raspberry Pi", "dc:a6:32": "Raspberry Pi",
    "e4:5f:01": "Raspberry Pi", "00:15:5d": "Microsoft Hyper-V",
}

# Private space only - RFC1918, CGNAT, link-local, loopback. See the module note.
ALLOWED = [ipaddress.ip_network(cidr) for cidr in (
    "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",
    "100.64.0.0/10", "169.254.0.0/16", "127.0.0.0/8")]

MAC_RE = re.compile(r"(?:[0-9a-f]{2}:){5}[0-9a-f]{2}", re.I)


class Invalid(ValueError):
    """Operator input the scanner refuses. Maps to HTTP 400."""


def check_range(text):
    """Parse a CIDR or a single address, and refuse anything out of bounds."""
    if not isinstance(text, str) or len(text) > 64:
        raise Invalid("range must be a CIDR such as 192.168.1.0/24")
    try:
        network = ipaddress.ip_network(text.strip(), strict=False)
    except ValueError as err:
        raise Invalid(f"not a network: {err}") from None
    if network.version != 4:
        raise Invalid("IPv4 only in this pass")
    if not any(network.subnet_of(allowed) for allowed in ALLOWED):
        raise Invalid("only private ranges may be scanned "
                      "(10/8, 172.16/12, 192.168/16, 100.64/10, 169.254/16, 127/8)")
    hosts = list(network.hosts()) or [network.network_address]
    if len(hosts) > MAX_HOSTS:
        raise Invalid(f"{len(hosts)} addresses exceeds the {MAX_HOSTS} address cap; "
                      f"scan a smaller prefix")
    return network, hosts


def check_ports(values):
    if values is None:
        return list(DEFAULT_PORTS)
    if not isinstance(values, list) or not 1 <= len(values) <= MAX_PORTS:
        raise Invalid(f"ports must be a list of 1 to {MAX_PORTS} port numbers")
    ports = []
    for value in values:
        if type(value) is not int or not 1 <= value <= 65535:
            raise Invalid("each port must be an integer 1-65535")
        if value not in ports:
            ports.append(value)
    return ports


def vendor_for(mac):
    """Curated name first, then the IEEE registry, then honestly nothing."""
    if not mac or len(mac) < 8:
        return None
    curated = VENDORS.get(mac[:8].lower())
    if curated:
        return curated
    return _oui_registry().get(mac[:8].replace(":", "").upper()) or None


# -- where the MAC addresses actually live ------------------------------------
#
# A TCP connect scan learns which addresses answer. It cannot learn a MAC: that is
# layer 2, and the only record of it is the scanning host's own ARP/neighbour cache,
# populated as a side effect of the sweep.
#
# WHICH BREAKS COMPLETELY UNDER WSL2, and this dashboard usually runs under WSL2.
# WSL2 puts Linux behind a NAT on a Hyper-V virtual switch: eth0 is 172.30.x, the
# default route is the Windows host, and the plant LAN is reached by NAT. Outbound
# TCP works fine - the scan finds every host - but the Linux ARP table only ever
# contains ONE entry, the virtual gateway, because Linux is not on the plant segment
# at all. Every MAC and every vendor came back empty, and the panel said nothing
# about why.
#
# The MACs do exist; they are in the WINDOWS host's ARP table, one NAT hop away. WSL
# can run Windows binaries directly, so that table is readable. This tries the Linux
# caches first (correct on a native Linux box, and on WSL in mirrored networking
# mode) and falls back to the Windows one when Linux only knows its own gateway.

def running_under_wsl():
    if os.name == "nt":
        return False
    try:
        return "microsoft" in Path("/proc/version").read_text(encoding="utf-8").lower()
    except OSError:
        return False


def _parse_arp(text):
    table = {}
    for line in text.splitlines():
        addresses = re.findall(r"\b\d{1,3}(?:\.\d{1,3}){3}\b", line)
        mac = MAC_RE.search(line.replace("-", ":"))
        if addresses and mac:
            candidate = mac.group(0).lower()
            # Broadcast and multicast rows are not devices.
            if candidate == "ff:ff:ff:ff:ff:ff" or candidate.startswith("01:00:5e"):
                continue
            table.setdefault(addresses[0], candidate)
    return table


def _run_table(argv, timeout=8):
    try:
        done = subprocess.run(argv, stdin=subprocess.DEVNULL,
                              capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return {}
    if done.returncode != 0 or not done.stdout:
        return {}
    return _parse_arp(done.stdout)


WINDOWS_ARP = ("/mnt/c/Windows/System32/ARP.EXE", "/mnt/c/Windows/System32/arp.exe",
               "arp.exe")


def neighbour_table():
    """Every ARP/neighbour cache this host can see, merged. Never fatal.

    Returns (table, source) where source names where the addresses came from, so
    the panel can say "these MACs are the Windows host's, not this machine's"
    rather than presenting them as something it observed directly.
    """
    native = _run_table(["ip", "-4", "neigh", "show"]) or _run_table(["arp", "-a"])
    if os.name == "nt":
        return native or _run_table(["arp", "-a"]), "this host"

    # More than one entry means Linux is genuinely on the segment - a native box,
    # or WSL in mirrored networking mode. One entry is the NAT gateway and nothing
    # else, which is indistinguishable from useless.
    if len(native) > 1 or not running_under_wsl():
        return native, "this host"

    for candidate in WINDOWS_ARP:
        if candidate.startswith("/") and not Path(candidate).exists():
            continue
        windows = _run_table([candidate, "-a"])
        if windows:
            merged = dict(windows)
            merged.update(native)
            return merged, "the Windows host (WSL is behind a NAT)"
    return native, "this host"


def probe(address, ports, deadline):
    """TCP-connect to each port on one address. Returns open ports, or []."""
    found = []
    for port in ports:
        if time.monotonic() > deadline:
            break
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(CONNECT_TIMEOUT)
        try:
            if sock.connect_ex((address, port)) == 0:
                found.append(port)
        except OSError:
            pass
        finally:
            sock.close()
    return found


class Scanner:
    """At most one scan at a time, readable while it runs."""

    def __init__(self, journal=None):
        self.journal = journal
        self.lock = threading.Lock()
        self.thread = None
        self.cancel = threading.Event()
        self.state = "idle"            # idle | running | done | cancelled | error
        self.error = None
        self.started_at = None
        self.finished_at = None
        self.scanned = 0
        self.total = 0
        self.hosts = []
        self.request = None
        self.mac_source = None
        self.resolved = 0

    def start(self, body):
        if not isinstance(body, dict):
            raise Invalid("body must be a JSON object")
        unknown = body.keys() - {"range", "ports", "actor"}
        if unknown:
            raise Invalid(f"unknown fields: {', '.join(sorted(unknown))}")
        actor = str(body.get("actor") or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", actor):
            raise Invalid("an operator name is required before scanning a network")
        network, hosts = check_range(body.get("range"))
        ports = check_ports(body.get("ports"))
        with self.lock:
            if self.state == "running":
                raise Invalid("a scan is already running; stop it first")
            self.cancel = threading.Event()
            self.state = "running"
            self.error = None
            self.started_at = time.time()
            self.finished_at = None
            self.scanned = 0
            self.total = len(hosts)
            self.hosts = []
            self.mac_source = None
            self.resolved = 0
            self.request = {"range": str(network), "ports": ports, "actor": actor}
        cancel = self.cancel
        self.thread = threading.Thread(target=self._run, args=(hosts, ports, cancel),
                                       name="netscan", daemon=True)
        self.thread.start()
        self._journal("started", 0)
        return self.snapshot()

    def stop(self):
        self.cancel.set()
        with self.lock:
            if self.state == "running":
                self.state = "cancelled"
        return self.snapshot()

    def _journal(self, outcome, found):
        if not self.journal or not self.request:
            return
        try:
            self.journal({"kind": "netscan", "outcome": outcome,
                          "actor": self.request["actor"], "range": self.request["range"],
                          "ports": self.request["ports"], "found": found,
                          "at": time.time()})
        except Exception:
            # A journal that is unavailable must not abort a scan the operator is
            # watching; the scan result itself is still on screen and truthful.
            pass

    def _run(self, hosts, ports, cancel):
        deadline = time.monotonic() + SCAN_DEADLINE
        results = {}
        try:
            with ThreadPoolExecutor(max_workers=WORKERS) as pool:
                futures = {pool.submit(probe, str(host), ports, deadline): str(host)
                           for host in hosts}
                for future, address in futures.items():
                    if cancel.is_set():
                        future.cancel()
                        continue
                    try:
                        open_ports = future.result()
                    except Exception:
                        open_ports = []
                    with self.lock:
                        self.scanned += 1
                    if open_ports:
                        results[address] = open_ports
            table, mac_source = neighbour_table()
            rows = []
            for address, open_ports in results.items():
                mac = table.get(address)
                try:
                    hostname = socket.gethostbyaddr(address)[0][:120]
                except (OSError, UnicodeError):
                    hostname = None
                rows.append({
                    "address": address, "hostname": hostname, "mac": mac,
                    "vendor": vendor_for(mac),
                    "ports": [{"port": port, "service": SERVICES.get(port, "unknown")}
                              for port in open_ports],
                })
            rows.sort(key=lambda row: tuple(int(p) for p in row["address"].split(".")))
            with self.lock:
                self.hosts = rows
                self.mac_source = mac_source
                self.resolved = sum(1 for row in rows if row["mac"])
                self.finished_at = time.time()
                if self.state == "running":
                    self.state = "done"
            self._journal("cancelled" if cancel.is_set() else "completed", len(rows))
        except Exception as err:
            with self.lock:
                self.state = "error"
                self.error = f"{type(err).__name__}"
                self.finished_at = time.time()
            self._journal("error", 0)

    def snapshot(self):
        with self.lock:
            return {
                "state": self.state, "error": self.error, "request": self.request,
                "started_at": self.started_at, "finished_at": self.finished_at,
                "scanned": self.scanned, "total": self.total,
                "mac_source": self.mac_source, "resolved": self.resolved,
                "under_wsl": running_under_wsl(),
                "hosts": [dict(row) for row in self.hosts],
                "services": {str(port): name for port, name in SERVICES.items()},
                "default_ports": list(DEFAULT_PORTS),
                "max_hosts": MAX_HOSTS,
            }


def export_csv(rows):
    """Flatten a result set for download. One line per open port, not per host."""
    out = ["address,hostname,mac,vendor,port,service"]
    for row in rows:
        for port in row.get("ports", []):
            out.append(",".join(json.dumps(str(value if value is not None else ""))
                                for value in (row["address"], row.get("hostname"),
                                              row.get("mac"), row.get("vendor"),
                                              port["port"], port["service"])))
    return "\n".join(out) + "\n"
