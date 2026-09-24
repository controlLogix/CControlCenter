"""TwinCAT EtherCAT diagnostics through TM-075 ADSClient.

Wire contract: Beckhoff System Manager, ADS Interface:
https://infosys.beckhoff.com/content/1033/tcsystemmanager/1089026187.html
Use the EtherCAT DEVICE NetId (InfoData.AmsNetId), not the PLC runtime NetId.
This partial implementation deliberately does not invent undocumented services
for actual addresses, AL status codes or working-counter error counts.
Read snapshots are sequential, not atomic. No scans or counter resets are sent.
"""
import argparse
import struct

try:
    from .ads import ADSClient, ProtocolError, ADSError
except ImportError:
    from ads import ADSClient, ProtocolError, ADSError

LIMITATION = ('Requires a TwinCAT master reachable over ADS. Reads diagnostics '
              'from that master; without one there is nothing to read. '
              'This is not an EtherCAT master.')
MISSING = 'unavailable: ADS mapping not verified'
STATES = {1: 'INIT', 2: 'PREOP', 3: 'BOOT', 4: 'SAFEOP', 8: 'OP'}


def state_name(value):
    parts = [STATES.get(value & 15, f'Unknown state ({value & 15})')]
    for mask, meaning in ((16, 'error'), (32, 'identity mismatch'),
                          (64, 'initialization command error')):
        if value & mask:
            parts.append(meaning)
    if value & ~127:
        parts.append(f'unknown flags 0x{value & ~127:x}')
    return '; '.join(parts)


def link_name(value):
    if not value:
        return 'Link OK'
    parts = [meaning for mask, meaning in
             ((1, 'link not present'), (2, 'no communication'),
              (4, 'missing link'), (8, 'additional link')) if value & mask]
    ports = [p for bit, p in enumerate('ABCD', 4) if value & (1 << bit)]
    if ports:
        parts.append('ports ' + ', '.join(ports))
    return '; '.join(parts)


class EtherCATDiagnostics:
    def __init__(self, client):
        if client.target_port != 65535:
            raise ValueError('EtherCAT master diagnostics require ADS port 65535')
        self.client = client

    def _read(self, group, offset, fmt):
        size = struct.calcsize(fmt)
        data = self.client.read(group, offset, size)
        if len(data) != size:
            raise ProtocolError(f'EtherCAT group 0x{group:x}: expected {size} bytes, got {len(data)}')
        return struct.unpack(fmt, data)

    def _addresses(self):
        count, = self._read(6, 0, '<H')
        addresses = self._read(7, 0, f'<{count}H') if count else ()
        if any(not 1 <= a <= 65534 for a in addresses) or len(set(addresses)) != count:
            raise ProtocolError('invalid or duplicate EtherCAT slave addresses')
        return addresses

    def snapshot(self):
        master, = self._read(3, 0x100, '<H')
        addresses = self._addresses()
        slaves = []
        for address in addresses:
            row = dict(configured_address=address, actual_address=None,
                       al_status_code=None, working_counter_errors=None,
                       state=None, crc_per_port=None, errors=[])
            # Unsupported/unreachable slave fields never become healthy zeros.
            try:
                state, link = self._read(9, address, '<BB')
                row.update(state=state_name(state), link=link_name(link))
            except ADSError as exc:
                row['errors'].append('state: ' + str(exc))
            try:
                crc = self._read(0x12, address, '<4I')
                row['crc_per_port'] = dict(zip('ABCD', crc))
            except ADSError as exc:
                row['errors'].append('CRC: ' + str(exc))
            slaves.append(row)
        if addresses != self._addresses():
            raise ProtocolError('slave configuration changed during snapshot; read again')
        return dict(master_state=state_name(master), slaves=slaves)

    def request_state(self, address, state, *, confirm=False, actor=None):
        # Authorize before even opening a connection or reading topology.
        self.client._authorize(confirm, actor)
        if type(address) is not int or not 1 <= address <= 65534:
            raise ValueError('slave address must be an integer from 1 to 65534')
        codes = {name: code for code, name in STATES.items()}
        if state not in codes:
            raise ValueError('state must be INIT, PREOP, BOOT, SAFEOP or OP')
        if address not in self._addresses():
            raise ValueError('slave address is not in the configured slave list')
        # ADSClient durably journals intent before transmission and the outcome.
        # Group 9 + address + UINT16 state are retained in its payload_hex field.
        self.client.write(9, address, struct.pack('<H', codes[state]),
                          confirm=confirm, actor=actor)


def render(snapshot):
    lines = [LIMITATION, 'Master: ' + snapshot['master_state'],
             f"Configured slaves: {len(snapshot['slaves'])}",
             'Actual addresses, AL status codes and working-counter error counts: ' + MISSING,
             'CRC counters are cumulative master values; this tool does not reset them.']
    for slave in snapshot['slaves']:
        lines.append(f"Slave configured={slave['configured_address']} actual={MISSING}")
        lines.append('  State: ' + (slave['state'] or 'unavailable') +
                     '; ' + slave.get('link', 'link unavailable'))
        crc = slave['crc_per_port']
        lines.append('  CRC: ' + ('; '.join(f'port {p}={crc[p]}' for p in 'ABCD')
                                  if crc is not None else 'unavailable'))
        lines.extend('  ' + e for e in slave['errors'])
    return '\n'.join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=LIMITATION,
                                     epilog='Use the EtherCAT device NetId from its EtherCAT tab / InfoData.AmsNetId.')
    parser.add_argument('host')
    parser.add_argument('--target-net-id', required=True)
    parser.add_argument('--source-net-id', required=True)
    parser.add_argument('--tcp-port', type=int, default=48898)
    parser.add_argument('--source-port', type=int, default=32905)
    parser.add_argument('--journal-path')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('show')
    change = sub.add_parser('request-state')
    change.add_argument('address', type=int)
    change.add_argument('state', choices=tuple(STATES.values()))
    change.add_argument('--confirm', action='store_true')
    change.add_argument('--actor', required=True)
    args = vars(parser.parse_args(argv))
    command = args.pop('command')
    options = {key: args.pop(key) for key in ('address', 'state', 'confirm', 'actor') if key in args}
    print(LIMITATION)
    try:
        with ADSClient(**args, target_port=65535) as client:
            diag = EtherCATDiagnostics(client)
            if command == 'show':
                print(render(diag.snapshot()))
            else:
                diag.request_state(**options)
                print('State request accepted by ADS; transition completion has not been verified.')
    except (ProtocolError, OSError, ValueError) as exc:
        print('EtherCAT: ' + str(exc))
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
