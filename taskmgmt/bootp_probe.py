#!/usr/bin/env python3
"""Passive BOOTP/DHCP listener. Reports requests; never answers one.

    sudo python3 taskmgmt/bootp_probe.py --iface eth0 [--timeout 60]

WHY THIS IS A SEPARATE, PRIVILEGED SCRIPT
-----------------------------------------
Receiving BOOTP means binding UDP 67 (server) and 68 (client), both privileged
ports. The agentmux dashboard runs unprivileged (uid 1000) and must stay that way, so
it cannot do this and does not pretend to - its IIOT view names this command
instead. Run it yourself, under sudo, and paste or pipe the output.

THIS TOOL IS READ-ONLY ON THE WIRE. It listens and prints; it never sends a
BOOTREPLY, never offers a lease, never ACKs. That restriction is deliberate and
must not be relaxed: this is meant to run on live plant networks, where a second
DHCP responder hands out addresses that conflict with the real server and takes
machines off the network. Commissioning a device by BOOTP is a job for a tool the
operator has consciously pointed at one MAC address, not for a probe.

Output is one JSON object per line on stdout (so it pipes into jq), diagnostics
on stderr.
"""

import argparse
import datetime as dt
import json
import socket
import struct
import sys

BOOTP_SERVER_PORT = 67
BOOTP_CLIENT_PORT = 68
MAX_DATAGRAM = 2048          # a BOOTP/DHCP packet is 300-576 bytes; this is slack
DHCP_MAGIC = b"\x63\x82\x53\x63"

OPCODES = {1: "BOOTREQUEST", 2: "BOOTREPLY"}

# DHCP message types (option 53). A BOOTP-only client sends none of these.
MESSAGE_TYPES = {
    1: "DISCOVER", 2: "OFFER", 3: "REQUEST", 4: "DECLINE",
    5: "ACK", 6: "NAK", 7: "RELEASE", 8: "INFORM",
}

OPT_REQUESTED_IP = 50
OPT_MESSAGE_TYPE = 53
OPT_HOSTNAME = 12
OPT_VENDOR_CLASS = 60
OPT_END = 255
OPT_PAD = 0


def parse_options(blob):
    """Walk the DHCP option field. Bounded and tolerant of truncation."""
    out = {}
    if not blob.startswith(DHCP_MAGIC):
        return out                      # plain BOOTP, no options
    index = len(DHCP_MAGIC)
    while index < len(blob):
        code = blob[index]
        if code == OPT_END:
            break
        if code == OPT_PAD:
            index += 1
            continue
        if index + 2 > len(blob):
            break                       # truncated option header
        length = blob[index + 1]
        start = index + 2
        if start + length > len(blob):
            break                       # truncated option body
        out[code] = blob[start:start + length]
        index = start + length
    return out


def text(raw):
    """Decode an option that is supposed to be text, safely for a terminal."""
    if raw is None:
        return None
    decoded = raw.rstrip(b"\x00").decode("utf-8", "replace")
    return "".join(c for c in decoded if c.isprintable()) or None


def parse_packet(data):
    """Return a dict for one BOOTP packet, or None if it is not one."""
    if len(data) < 236:
        return None
    op, htype, hlen = data[0], data[1], data[2]
    xid = struct.unpack("!I", data[4:8])[0]
    ciaddr, yiaddr, siaddr, giaddr = (
        socket.inet_ntoa(data[offset:offset + 4]) for offset in (12, 16, 20, 24))
    mac = ":".join(f"{byte:02x}" for byte in data[28:28 + min(hlen, 16)])

    options = parse_options(data[236:])
    requested = options.get(OPT_REQUESTED_IP)
    msg_type = options.get(OPT_MESSAGE_TYPE)

    return {
        "at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "op": OPCODES.get(op, f"op:{op}"),
        "htype": htype,
        "xid": f"0x{xid:08x}",
        "mac": mac,
        "client_ip": ciaddr if ciaddr != "0.0.0.0" else None,
        "offered_ip": yiaddr if yiaddr != "0.0.0.0" else None,
        "server_ip": siaddr if siaddr != "0.0.0.0" else None,
        "relay_ip": giaddr if giaddr != "0.0.0.0" else None,
        "requested_ip": socket.inet_ntoa(requested) if requested and len(requested) == 4 else None,
        "dhcp_type": MESSAGE_TYPES.get(msg_type[0]) if msg_type else None,
        "hostname": text(options.get(OPT_HOSTNAME)),
        "vendor_class": text(options.get(OPT_VENDOR_CLASS)),
    }


def bind(port, iface):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    except OSError:
        pass
    if iface:
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BINDTODEVICE,
                            iface.encode() + b"\x00")
        except (AttributeError, OSError) as err:
            # Not fatal: without SO_BINDTODEVICE we simply listen on every
            # interface. Say so rather than silently widening the scope.
            print(f"note: could not bind to {iface} ({err}); listening on all "
                  f"interfaces", file=sys.stderr)
    try:
        sock.bind(("", port))
    except PermissionError:
        sock.close()
        sys.exit(f"cannot bind UDP {port}: this needs root (or CAP_NET_BIND_SERVICE). "
                 f"Re-run with sudo. This script will not try to escalate.")
    except OSError as err:
        sock.close()
        sys.exit(f"cannot bind UDP {port}: {err}")
    return sock


def main():
    parser = argparse.ArgumentParser(
        description="Passive BOOTP/DHCP listener. Reports requests; never replies.")
    parser.add_argument("--iface", help="interface to listen on (default: all)")
    parser.add_argument("--timeout", type=float, default=0,
                        help="seconds to listen, 0 = until Ctrl-C")
    parser.add_argument("--port", type=int, choices=(BOOTP_SERVER_PORT, BOOTP_CLIENT_PORT),
                        default=BOOTP_SERVER_PORT,
                        help="67 to see client requests (default), 68 to see server replies")
    args = parser.parse_args()

    sock = bind(args.port, args.iface)
    if args.timeout:
        sock.settimeout(args.timeout)
    print(f"listening on UDP {args.port}"
          + (f" via {args.iface}" if args.iface else " (all interfaces)")
          + "; read-only, no replies are sent", file=sys.stderr)

    seen = 0
    try:
        while True:
            try:
                data, addr = sock.recvfrom(MAX_DATAGRAM)
            except socket.timeout:
                break
            record = parse_packet(data)
            if record is None:
                print(f"note: ignored a {len(data)}-byte datagram from {addr[0]} "
                      f"that is not BOOTP", file=sys.stderr)
                continue
            record["from"] = addr[0]
            print(json.dumps(record), flush=True)
            seen += 1
    except KeyboardInterrupt:
        pass
    finally:
        sock.close()
    print(f"{seen} BOOTP packet(s) seen", file=sys.stderr)


if __name__ == "__main__":
    main()
