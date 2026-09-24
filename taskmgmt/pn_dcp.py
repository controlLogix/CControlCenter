#!/usr/bin/env python3
"""Privileged PROFINET DCP helper; JSON lines on stdout, diagnostics on stderr.

    sudo python3 taskmgmt/pn_dcp.py --iface eth0 identify
    sudo python3 taskmgmt/pn_dcp.py --iface eth0 set --mac 00:11:22:33:44:55 --name station-1
    sudo python3 taskmgmt/pn_dcp.py --iface eth0 set --mac 00:11:22:33:44:55 \
        --ip 192.168.1.10 --subnet 255.255.255.0 --gateway 192.168.1.1

MEASURED CONSTRAINT: uid 1000 socket(AF_PACKET, SOCK_RAW) raises PermissionError
in the dispatch environment. WSL2 eth0 is NAT'd: even root cannot reach a plant
segment with these layer-2 frames. Run under sudo on Linux with a real NIC on
that segment. The dashboard stays unprivileged and only imports this output.

Identify All is read-only discovery (multicast 01:0e:cf:00:00:00, EtherType
0x8892). Set WRITES A RUNNING DEVICE. Renaming the wrong station can take a
machine off its controller. Each invocation writes ONE explicit unicast MAC
and ONE setting (name OR full IP suite), permanently. It reads current values,
requires typing that MAC at /dev/tty, and fsyncs an intent before transmission.
There is no automatic retry; a timeout has unknown outcome. Inspect equipment
before retrying. Acknowledgement is not verification of controller operation.
Reset-to-factory is absent by decision: no diagnostic value or safe default.

Wire layout reference: https://github.com/secdev/scapy/blob/master/scapy/contrib/pnio_dcp.py
No third-party runtime dependencies. Journals default to /var/log/pn-dcp.jsonl.
"""
import argparse
import datetime as dt
import ipaddress
import json
import math
import os
from pathlib import Path
import re
import secrets
import socket
import stat
import struct
import sys
import time

ETHERTYPE = 0x8892
MULTICAST = '01:0e:cf:00:00:00'
IDENTIFY_REQ, IDENTIFY_RES, GET_SET = 0xfefe, 0xfeff, 0xfefd
NAME, IP = (2, 2), (1, 2)


class DCPError(Exception):
    pass


class Rejected(DCPError):
    pass


def mac_bytes(value):
    if not isinstance(value, str) or not re.fullmatch(r'(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}', value):
        raise ValueError('MAC must be six explicit colon-separated octets')
    return bytes.fromhex(value.replace(':', ''))


def target_mac(value):
    raw = mac_bytes(value)
    if raw[0] & 1 or raw == bytes(6):
        raise ValueError('Set requires one nonzero unicast MAC; multicast/broadcast refused')
    return raw.hex(':')


def block(option, suboption, data):
    return struct.pack('!BBH', option, suboption, len(data)) + data + b'\0' * (len(data) % 2)


def frame(dst, src, frame_id, service, xid, payload, response=0, delay=0):
    packet = (mac_bytes(dst) + mac_bytes(src) + struct.pack('!HHBBIHH', ETHERTYPE,
              frame_id, service, response, xid, delay, len(payload)) + payload)
    return packet.ljust(60, b'\0')


def parse_frame(data):
    """Strict lengths; ignore Ethernet padding and unrelated/malformed packets."""
    if len(data) < 26:
        return None
    ether = struct.unpack_from('!H', data, 12)[0]
    offset = 14
    # Accept one/two VLAN tags in offline captures as well as untagged packets.
    for _ in range(2):
        if ether not in (0x8100, 0x88a8):
            break
        if len(data) < offset + 4:
            return None
        ether = struct.unpack_from('!H', data, offset + 2)[0]
        offset += 4
    if ether != ETHERTYPE or len(data) < offset + 12:
        return None
    fid, service, response, xid, _, length = struct.unpack_from('!HBBIHH', data, offset)
    offset += 12
    end = offset + length
    if end > len(data) or fid not in (IDENTIFY_RES, GET_SET):
        return None
    blocks = {}
    while offset < end:
        if offset + 4 > end:
            return None
        opt, sub, size = struct.unpack_from('!BBH', data, offset)
        offset += 4
        if offset + size + size % 2 > end or (opt, sub) in blocks:
            return None
        blocks[opt, sub] = data[offset:offset + size]
        offset += size + size % 2
    return dict(mac=data[6:12].hex(':'), dst=data[:6].hex(':'), frame_id=fid,
                service=service, response=response, xid=xid, blocks=blocks)


def station(packet):
    blocks = packet['blocks']
    out = dict(kind='dcp-identify', at=dt.datetime.now(dt.timezone.utc).isoformat(),
               mac=packet['mac'], name=None, ip=None, subnet=None, gateway=None,
               vendor=None, vendor_id=None, device_id=None)
    for key, field in ((NAME, 'name'), ((2, 1), 'vendor')):
        raw = blocks.get(key)
        if raw is not None:
            if len(raw) < 2:
                raise DCPError('truncated text block')
            out[field] = raw[2:].decode('utf-8', 'replace')
    raw = blocks.get(IP)
    if raw is not None:
        if len(raw) != 14:
            raise DCPError('invalid IP block')
        out.update(zip(('ip', 'subnet', 'gateway'),
                       (socket.inet_ntoa(raw[i:i + 4]) for i in (2, 6, 10))))
        out['ip_block_info'] = int.from_bytes(raw[:2], 'big')
    raw = blocks.get((2, 3))
    if raw is not None:
        if len(raw) != 6:
            raise DCPError('invalid identity block')
        out['vendor_id'], out['device_id'] = struct.unpack('!HH', raw[2:])
    return out


def setting(name=None, ip=None, subnet=None, gateway=None):
    if name is not None:
        if any(v is not None for v in (ip, subnet, gateway)):
            raise ValueError('change name OR IP suite in one invocation')
        labels = name.split('.')
        if (len(name) > 240 or not all(re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', x) for x in labels)
                or re.fullmatch(r'\d+\.\d+\.\d+\.\d+', name)
                or re.match(r'^port-\d{3}', labels[0])):
            raise ValueError('invalid PROFINET station name (lowercase DNS labels, max 240 bytes)')
        return NAME, {'name': name}, name.encode('ascii')
    if any(v is None for v in (ip, subnet, gateway)):
        raise ValueError('supply --name OR all of --ip --subnet --gateway')
    addr, gw = ipaddress.IPv4Address(ip), ipaddress.IPv4Address(gateway)
    if not re.fullmatch(r'\d+\.\d+\.\d+\.\d+', subnet):
        raise ValueError('subnet must be a dotted contiguous netmask')
    network = ipaddress.IPv4Network(f'{ip}/{subnet}', strict=False)
    if str(network.netmask) != subnet or network.prefixlen not in range(1, 31):
        raise ValueError('subnet must be a contiguous /1 through /30 netmask')
    if (addr.is_multicast or addr.is_loopback or addr.is_unspecified or int(addr) >= 0xe0000000
            or addr in (network.network_address, network.broadcast_address)):
        raise ValueError('IP must be a unicast host address')
    if int(gw) and (gw not in network or gw in (addr, network.network_address, network.broadcast_address)
                    or gw.is_multicast or gw.is_loopback):
        raise ValueError('gateway must be zero or another host in the same subnet')
    return IP, dict(ip=str(addr), subnet=subnet, gateway=str(gw)), addr.packed + network.netmask.packed + gw.packed


class Client:
    def __init__(self, iface, timeout=3):
        if not math.isfinite(timeout) or timeout <= 0 or timeout > 60:
            raise ValueError('timeout must be > 0 and <= 60 seconds')
        self.timeout, self.iface = timeout, iface
        self.sock = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(ETHERTYPE))
        try:
            self.sock.bind((iface, 0))
            address = self.sock.getsockname()
            if address[3] != 1 or len(address[4]) != 6:
                raise DCPError('requires an Ethernet interface')
            self.mac = target_mac(address[4].hex(':'))
        except BaseException:
            self.sock.close()
            raise

    def close(self):
        self.sock.close()

    def replies(self, xid, service, target=None):
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            self.sock.settimeout(max(.001, deadline - time.monotonic()))
            try:
                data = self.sock.recv(65535)
            except socket.timeout:
                return
            p = parse_frame(data)
            if (p and p['xid'] == xid and p['service'] == service and p['dst'] == self.mac
                    and p['frame_id'] == (IDENTIFY_RES if service == 5 else GET_SET)
                    and (target is None or p['mac'] == target) and p['response'] in (1, 5)):
                yield p

    def identify(self):
        xid = secrets.randbits(32)
        self.sock.send(frame(MULTICAST, self.mac, IDENTIFY_REQ, 5, xid, block(255, 255, b''), delay=128))
        seen = set()
        for p in self.replies(xid, 5):
            if p['response'] == 1 and p['mac'] not in seen:
                try:
                    record = station(p)
                except DCPError:
                    continue
                seen.add(p['mac'])
                yield record

    def read(self, mac, key):
        mac = target_mac(mac)
        if key not in (NAME, IP):
            raise ValueError('only station name and IP suite are supported')
        xid = secrets.randbits(32)
        # Get carries only the requested option/suboption selector, no block length.
        self.sock.send(frame(mac, self.mac, GET_SET, 3, xid, bytes(key)))
        for p in self.replies(xid, 3, mac):
            if p['response'] != 1 or key not in p['blocks']:
                raise DCPError('device did not supply current value; refusing Set')
            values = station(p)
            fields = ('name',) if key == NAME else ('ip', 'subnet', 'gateway')
            if any(values[f] is None for f in fields):
                raise DCPError('missing old value; refusing Set')
            return {f: values[f] for f in fields}
        raise DCPError('current-value read timed out; no Set sent')

    def write(self, mac, key, raw):
        mac = target_mac(mac)
        if key not in (NAME, IP):
            raise ValueError('only station name and IP suite are supported')
        xid = secrets.randbits(32)
        self.sock.send(frame(mac, self.mac, GET_SET, 4, xid, block(*key, b'\0\1' + raw)))
        for p in self.replies(xid, 4, mac):
            if p['response'] != 1:
                raise Rejected('device rejected Set service')
            status = p['blocks'].get((5, 4))
            if status is None or len(status) != 3 or status[:2] != bytes(key):
                raise DCPError('invalid Set acknowledgement; outcome unknown')
            if status[2]:
                raise Rejected(f'device rejected Set: block error {status[2]}')
            return
        raise DCPError('Set acknowledgement timed out; outcome unknown; inspect device before retrying')


def journal(path, record):
    """Fail closed; durable append before a write, with symlink/non-file refusal."""
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise OSError('journal must be a regular file')
        import fcntl
        fcntl.flock(fd, fcntl.LOCK_EX)
        data = (json.dumps(dict(record, at=dt.datetime.now(dt.timezone.utc).isoformat())) + '\n').encode()
        while data:
            count = os.write(fd, data)
            if count <= 0:
                raise OSError('journal write failed')
            data = data[count:]
        os.fsync(fd)
        parent = os.open(str(Path(path).absolute().parent), os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(parent)
        finally:
            os.close(parent)
    finally:
        os.close(fd)


def confirm(mac):
    with open('/dev/tty', 'r+') as tty:
        tty.write(f'Type {mac} to permanently WRITE this device (anything else cancels): ')
        tty.flush()
        return tty.readline().strip() == mac


def perform_set(client, mac, change, journal_path, confirmer=confirm):
    mac = target_mac(mac)
    key, new, raw = change
    # Do not expose arbitrary option writes, including resets, through this helper.
    if setting(**new) != change:
        raise ValueError('invalid setting')
    old = client.read(mac, key)
    event = dict(kind='dcp-set', operation_id=secrets.token_hex(16), mac=mac,
                 iface=client.iface, actor=os.environ.get('SUDO_USER') or str(os.getuid()),
                 old=old, new=new, permanent=True)
    print('WARNING: WRITE to a running device; may disconnect its controller.\n' + json.dumps(event, indent=2), file=sys.stderr)
    if not confirmer(mac):
        raise DCPError('confirmation cancelled; no Set sent')
    if client.read(mac, key) != old:
        raise DCPError('current value changed during confirmation; no Set sent')
    journal(journal_path, dict(event, outcome='intent'))
    try:
        client.write(mac, key, raw)
    except BaseException as exc:
        journal(journal_path, dict(event, outcome='rejected' if isinstance(exc, Rejected) else 'unknown', error=str(exc)))
        raise
    result = dict(event, outcome='acknowledged')
    journal(journal_path, result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--iface', required=True)
    parser.add_argument('--timeout', type=float, default=3)
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('identify', help='read-only Identify All')
    write = sub.add_parser('set', help='permanent single-device write; typed MAC confirmation')
    write.add_argument('--mac', required=True)
    write.add_argument('--name')
    write.add_argument('--ip')
    write.add_argument('--subnet')
    write.add_argument('--gateway')
    write.add_argument('--journal', default='/var/log/pn-dcp.jsonl')
    args = parser.parse_args(argv)
    client = None
    try:
        if args.command == 'set':
            mac = target_mac(args.mac)
            change = setting(args.name, args.ip, args.subnet, args.gateway)
        client = Client(args.iface, args.timeout)
        if args.command == 'identify':
            for record in client.identify():
                print(json.dumps(record), flush=True)
        else:
            print(json.dumps(perform_set(client, mac, change, args.journal)), flush=True)
        return 0
    except (OSError, ValueError, DCPError) as exc:
        print(f'DCP: {exc}. Requires sudo/CAP_NET_RAW and a real plant NIC; WSL NAT cannot carry DCP.', file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print('DCP interrupted; inspect journal before retrying a Set.', file=sys.stderr)
        return 130
    finally:
        if client is not None:
            client.close()


if __name__ == '__main__':
    sys.exit(main())
