"""Serial RTU transport for modbus_poll's shared protocol and tag table.

Requires pyserial and an RS-485 adapter with automatic direction control.
Only one master may be wired to the bus. A canonical-port lock serializes all
clients in this process; pyserial's exclusive POSIX open excludes cooperating
processes. USB/OS buffering limits observable timing: this is not a real-time
UART implementation. No serial URLs (including loop:// echo) are accepted.
"""
import os
import struct
import threading
import time

from modbus_poll import (Client as ProtocolClient, ModbusError, ModbusException,
                         finite, integer)


def crc16(data):
    """CRC-16/MODBUS, initial FFFF, reflected polynomial A001."""
    crc = 0xffff
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ (0xa001 if crc & 1 else 0)
    return crc


def frame(data):
    return data + struct.pack('<H', crc16(data))


def serial_config(config):
    device = config.get('device')
    if (not isinstance(device, str) or not device.strip() or len(device) > 256
            or '\x00' in device or '://' in device):
        raise ValueError('device must be a local serial port path')
    baud = integer(config.get('baud', 9600), 300, 4000000)
    parity = config.get('parity', 'E')
    if parity not in ('N', 'E', 'O'):
        raise ValueError('parity must be N, E or O')
    stopbits = integer(config.get('stopbits', 1), 1, 2)
    return dict(device=device, baud=baud, parity=parity, stopbits=stopbits)


def timing(baud, parity, stopbits):
    character = (1 + 8 + (parity != 'N') + stopbits) / baud
    # Serial Line V1.02 section 2.5.1.1 recommends fixed timers above 19200.
    return character, (1.5 * character if baud <= 19200 else .00075), (
        3.5 * character if baud <= 19200 else .00175)


_locks = {}
_locks_guard = threading.Lock()


class Client(ProtocolClient):
    def __init__(self, device, *, baud=9600, parity='E', stopbits=1, timeout=1,
                 journal_path=None):
        self.config = serial_config(dict(device=device, baud=baud, parity=parity, stopbits=stopbits))
        # This does not call super().__init__ - it has no host or port - so the
        # journal attributes the inherited write() needs are set here. Missing
        # them would fail at the moment of a write to equipment, which is the
        # worst possible time to discover an attribute is not there.
        self._journal_path = journal_path
        self._journal = None
        self.timeout = finite(timeout)
        if self.timeout <= 0:
            raise ValueError('timeout must be positive')
        self.character_time, self.inter_character, self.inter_frame = timing(baud, parity, stopbits)
        with _locks_guard:
            self.bus_lock = _locks.setdefault(os.path.realpath(device), threading.Lock())

    def target(self):
        return dict(transport='rtu', **self.config)

    def exchange(self, unit, function, data):
        integer(unit, 1, 247)  # Broadcasts cannot acknowledge writes.
        integer(function, 1, 127)
        request = frame(bytes([unit, function]) + data)
        if len(request) > 256:
            raise ValueError('RTU frame exceeds 256 bytes')
        deadline = time.monotonic() + self.timeout

        def remaining():
            seconds = deadline - time.monotonic()
            if seconds <= 0:
                raise TimeoutError('Modbus RTU response deadline')
            return seconds

        if not self.bus_lock.acquire(timeout=remaining()):
            raise TimeoutError('Modbus RTU bus busy')
        try:
            try:
                import serial
            except ImportError as err:
                raise ModbusError('RTU requires pyserial; install it in the dashboard Python environment') from err
            try:
                port = serial.Serial(self.config['device'], baudrate=self.config['baud'],
                                     bytesize=8, parity=self.config['parity'],
                                     stopbits=self.config['stopbits'], timeout=remaining(),
                                     write_timeout=remaining(), exclusive=True)
            except (OSError, ValueError) as err:
                raise ModbusError(f"Cannot open serial port {self.config['device']}: {err}. "
                                  'Check port permissions, settings and whether another master owns it. '
                                  'On WSL2, USB serial/RS-485 adapters need usbipd attachment; '
                                  'a Windows COM mapping may not be usable.') from err
            with port:
                # Flush every request, then require an idle bus. Drain late replies
                # and noise until t3.5 has elapsed; never send into an active frame.
                port.reset_input_buffer()
                while True:
                    port.timeout = min(self.inter_frame, remaining())
                    if not port.read(1):
                        remaining()
                        break
                port.reset_input_buffer()
                port.write_timeout = remaining()
                if port.write(request) != len(request):
                    raise ModbusError('incomplete RTU transmission')
                # Read immediately: a slave responds only after receiving TX.
                # Sleeping here could hide gaps in already-buffered replies.
                # The automatic-direction adapter handles TX completion; avoid
                # an unbounded tcdrain/flush call under this response deadline.
                response = bytearray()
                while True:
                    port.timeout = min(self.inter_character, remaining()) if response else remaining()
                    part = port.read(1)
                    if not part:
                        if not response:
                            raise TimeoutError('Modbus RTU response deadline')
                        # A t1.5 gap invalidates a frame if more bytes arrive
                        # before the full t3.5 frame delimiter.
                        port.timeout = min(self.inter_frame - self.inter_character, remaining())
                        if port.read(1):
                            raise ModbusError('RTU inter-character gap')
                        remaining()
                        break
                    response += part
                    if len(response) > 256:
                        raise ModbusError('RTU frame exceeds 256 bytes')
                if len(response) < 5 or crc16(response) != 0:
                    raise ModbusError('invalid RTU frame length or CRC')
                if response[0] != unit:
                    raise ModbusError('wrong RTU response unit')
                pdu = response[1:-2]
                if pdu[0] == function | 128 and len(pdu) == 2:
                    raise ModbusException(pdu[1])
                if pdu[0] != function:
                    raise ModbusError('wrong response function')
                return bytes(pdu[1:])
        finally:
            self.bus_lock.release()
