"""In-process Modbus TCP/RTU and a persisted, shared tag table.

Addresses are zero-based. Words use network byte order; word_order is high/low
for 32-bit values. Wire contract: modbus.org Modbus Application Protocol V1.1b3.
Writes never retry: an interrupted response has an unknown physical outcome.
"""
import copy
import json
import math
import os
from pathlib import Path
import socket
import struct
import tempfile
import threading
import time
import uuid

import writejournal


class ModbusError(Exception):
    pass


class ModbusException(ModbusError):
    """The DEVICE refused, and said so with an exception response.

    Its own class because the difference is the whole point of recording an
    outcome. A refusal means nothing changed. Every other failure here - a
    dropped connection, a bad CRC, a deadline - means we do not know whether it
    changed, which is what sends somebody to look at the equipment. Collapsing
    them made that instruction fire for writes the device had visibly rejected.
    """

    def __init__(self, code, detail=None):
        self.code = code
        super().__init__(detail or f'device exception {code}')


def integer(value, low, high):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f'expected integer {low}..{high}')
    return value


def finite(value):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError('expected finite number')
    return value


class Client:
    def __init__(self, host, port=502, timeout=1, *, journal_path=None):
        self.host, self.port, self.timeout = host, port, timeout
        self.transaction = 0
        self._journal_path = journal_path
        self._journal = None

    @property
    def journal(self):
        # Built on first use, so constructing a client that then refuses to
        # write leaves no trace at all.
        if self._journal is None:
            self._journal = writejournal.WriteJournal(self._journal_path, transport='modbus')
        return self._journal

    def target(self):
        return dict(host=self.host, port=self.port)

    def exchange(self, unit, function, data):
        integer(unit, 1, 247)
        self.transaction = (self.transaction + 1) & 65535
        deadline = time.monotonic() + self.timeout
        # Numeric addresses avoid unbounded platform DNS resolution in a poll.
        with socket.create_connection((self.host, self.port), self.timeout) as sock:
            def exact(size):
                result = b''
                while len(result) < size:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError('Modbus response deadline')
                    sock.settimeout(remaining)
                    part = sock.recv(size - len(result))
                    if not part:
                        raise ModbusError('connection closed')
                    result += part
                return result
            pdu = bytes([function]) + data
            sock.sendall(struct.pack('!HHHB', self.transaction, 0, len(pdu)+1, unit) + pdu)
            tx, protocol, length, peer = struct.unpack('!HHHB', exact(7))
            if (tx, protocol, peer) != (self.transaction, 0, unit) or not 2 <= length <= 254:
                raise ModbusError('invalid MBAP header')
            response = exact(length-1)
            if response[0] == function | 128 and len(response) == 2:
                raise ModbusException(response[1])
            if response[0] != function:
                raise ModbusError('wrong response function')
            return response[1:]

    def read(self, unit, function, address, count=1):
        integer(function, 1, 4)
        integer(count, 1, 2000 if function <= 2 else 125)
        integer(address, 0, 65536-count)
        raw = self.exchange(unit, function, struct.pack('!HH', address, count))
        size = (count+7)//8 if function <= 2 else count*2
        if len(raw) != size+1 or raw[0] != size:
            raise ModbusError('invalid read byte count')
        if function <= 2:
            return [bool(raw[1+i//8] & (1 << (i%8))) for i in range(count)]
        return list(struct.unpack('!'+'H'*count, raw[1:]))

    def write(self, unit, function, address, values, *, confirm=False, actor='', journal=None):
        if confirm is not True or not isinstance(actor, str) or not actor.strip() or len(actor) > 128:
            raise ValueError('explicit confirmation and actor required')
        if not callable(journal):
            raise ValueError('durable journal required')
        if function not in (5, 6, 15, 16):
            raise ValueError('unsupported write function')
        limit = {5: 1, 6: 1, 15: 1968, 16: 123}[function]
        if not isinstance(values, list):
            raise ValueError('values must be a list')
        integer(len(values), 1, limit)
        integer(address, 0, 65536-len(values))
        integer(unit, 1, 247)
        for v in values:
            if function in (5, 15):
                if type(v) is not bool:
                    raise ValueError('coil value must be boolean')
            else:
                integer(v, 0, 65535)
        if function in (5, 6):
            data = struct.pack('!HH', address, (0xff00 if values[0] else 0) if function == 5 else values[0])
            expected = data
        else:
            if function == 15:
                packed = bytearray((len(values)+7)//8)
                for i, value in enumerate(values):
                    packed[i//8] |= int(value) << (i%8)
                packed = bytes(packed)
            else:
                packed = struct.pack('!'+'H'*len(values), *values)
            expected = struct.pack('!HH', address, len(values))
            data = expected + bytes([len(packed)]) + packed
        event = dict(id=uuid.uuid4().hex, actor=actor, **self.target(),
                     unit=unit, function=function, address=address, value=values)
        # Two journals, both durable before transmission, and either failing
        # stops the write. The file is the audit shared with every other
        # transport (writejournal.py); the callback is the dashboard's own
        # journal in cc.db, which is what the page reads.
        handle = self.journal.intent(dict(event))
        journal(dict(event, outcome='intent'))  # Failure here prevents transmission.
        try:
            if self.exchange(unit, function, data) != expected:
                raise ModbusError('write acknowledgement mismatch')
        except ModbusException as exc:
            # The device said no. Nothing changed, so nobody needs to walk out
            # to the panel - and `unknown` stays meaning what it says.
            handle.settle('rejected', error=str(exc), exception_code=exc.code)
            journal(dict(event, outcome='rejected', exception_code=exc.code))
            raise
        except Exception as exc:
            handle.settle('unknown', error=f'{type(exc).__name__}: {exc}')
            journal(dict(event, outcome='unknown'))
            raise
        handle.settle('success')
        # Was 'acknowledged'. One word for one outcome: in a shared journal a
        # synonym means anyone grepping for successful writes misses these.
        journal(dict(event, outcome='success'))


FORMATS = {'int16': 'h', 'uint16': 'H', 'int32': 'i', 'uint32': 'I', 'float32': 'f'}


def decode(words, tag):
    if tag['type'] == 'bool':
        return bool(words[0])
    words = list(words)
    if tag['word_order'] == 'low':
        words.reverse()
    value = struct.unpack('!'+FORMATS[tag['type']], struct.pack('!'+'H'*len(words), *words))[0]
    return finite(value * tag['scale'] + tag['offset'])


def validate(config):
    import ipaddress
    if not isinstance(config, dict):
        raise ValueError('table must be an object')
    transport = config.get('transport', 'tcp')
    if transport == 'rtu':
        from modbus_rtu import serial_config
        endpoint = dict(transport='rtu', **serial_config(config))
    elif transport == 'tcp':
        endpoint = dict(host=str(ipaddress.ip_address(config.get('host', ''))),
                        port=integer(config.get('port', 502), 1, 65535))
    else:
        raise ValueError('transport must be tcp or rtu')
    interval = finite(config.get('interval', 2))
    if not 0.2 <= interval <= 3600:
        raise ValueError('interval must be 0.2..3600 seconds')
    tags = config.get('tags')
    if not isinstance(tags, list) or not 1 <= len(tags) <= 64:
        raise ValueError('provide 1..64 tags')
    result, names = [], set()
    for tag in tags:
        if not isinstance(tag, dict):
            raise ValueError('tag must be an object')
        name = tag.get('name')
        if not isinstance(name, str) or not name.strip() or len(name) > 80 or name in names:
            raise ValueError('tag names must be unique, nonempty, at most 80 characters')
        names.add(name)
        dtype = tag.get('type', 'uint16')
        if dtype not in (*FORMATS, 'bool'):
            raise ValueError('invalid data type')
        function = integer(tag.get('function', 3), 1, 4)
        if function <= 2 and dtype != 'bool':
            raise ValueError('bit reads require bool type')
        count = 2 if dtype in ('int32', 'uint32', 'float32') else 1
        order = tag.get('word_order', 'high')
        if order not in ('high', 'low'):
            raise ValueError('word_order must be high or low')
        unit_text = tag.get('engineering_unit', '')
        if not isinstance(unit_text, str) or len(unit_text) > 32:
            raise ValueError('invalid engineering unit')
        result.append(dict(name=name, unit=integer(tag.get('unit', 1), 1, 247),
                           address=integer(tag.get('address'), 0, 65536-count),
                           function=function, type=dtype, count=count, word_order=order,
                           scale=finite(tag.get('scale', 1)), offset=finite(tag.get('offset', 0)),
                           engineering_unit=unit_text))
    return dict(endpoint, interval=interval, tags=result)


def target(config):
    keys = ('transport', 'device', 'baud', 'parity', 'stopbits') if config.get('transport') == 'rtu' else ('host', 'port')
    return {key: config[key] for key in keys}


def client_for(config, timeout=1, journal_path=None):
    # journal_path travels through, so a test can point the shared audit file at
    # a temporary directory. Without it a test run appends to the operator's
    # real field-writes.jsonl, which is both residue and a polluted audit trail.
    if config.get('transport') == 'rtu':
        from modbus_rtu import Client as RTUClient
        return RTUClient(config['device'], baud=config['baud'], parity=config['parity'],
                         stopbits=config['stopbits'], timeout=timeout,
                         journal_path=journal_path)
    return Client(config['host'], config['port'], timeout, journal_path=journal_path)


class Poller:
    def __init__(self, path, journal, autostart=True, journal_path=None):
        self.path, self.journal = Path(path), journal
        # Where the SHARED field journal goes. None means the default; the tests
        # set it so a suite run never touches the real audit trail.
        self.journal_path = journal_path
        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        self.config = validate(json.loads(self.path.read_text())) if self.path.exists() else None
        self.values, self.last_good = {}, None
        self.error, self.failures, self.next_poll = '', 0, 0
        self.thread = None
        if autostart:
            self.thread = threading.Thread(target=self._run, daemon=True)
            self.thread.start()

    def save(self, config):
        config = validate(config)
        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, name = tempfile.mkstemp(dir=self.path.parent, prefix='.modbus-')
            try:
                with os.fdopen(fd, 'w') as out:
                    json.dump(config, out, allow_nan=False)
                    out.flush()
                    os.fsync(out.fileno())
                os.replace(name, self.path)
            finally:
                if os.path.exists(name):
                    os.unlink(name)
            self.config = config
            self.values, self.last_good = {}, None
            self.error, self.failures, self.next_poll = '', 0, 0
        return self.snapshot()

    def snapshot(self):
        with self.lock:
            now = time.time()
            config = copy.deepcopy(self.config)
            interval = config['interval'] if config else 0
            connected = self.last_good is not None and now-self.last_good < interval and not self.error
            rows = []
            for tag in config['tags'] if config else []:
                state = self.values.get(tag['name'], dict(value=None, last_good=None))
                stale = not connected or state['last_good'] is None or now-state['last_good'] >= interval
                # Age measured HERE, where the timestamp was taken. The browser
                # cannot compute it: subtracting our epoch from its own is two
                # different clocks, and iiot.js:11-14 is right that a wrong age is
                # worse than none because it still looks authoritative.
                age_ms = None if state['last_good'] is None else int((now - state['last_good']) * 1000)
                rows.append(dict(tag, **state, stale=stale, age_ms=age_ms))
            return dict(config=config, tags=rows, connected=connected, error=self.error,
                        retry_in=max(0, self.next_poll-time.monotonic()))

    def poll_once(self):
        with self.lock:
            config = self.config
            if config is None or time.monotonic() < self.next_poll:
                return
        started = time.monotonic()
        deadline = started + min(2, config['interval']/2)
        try:
            for tag in config['tags']:
                remaining = deadline-time.monotonic()
                if remaining <= 0:
                    raise TimeoutError('poll interval exhausted')
                client = client_for(config, remaining)
                value = decode(client.read(tag['unit'], tag['function'], tag['address'], tag['count']), tag)
                with self.lock:
                    if self.config is not config:
                        return
                    self.values[tag['name']] = dict(value=value, last_good=time.time())
            with self.lock:
                if self.config is not config:
                    return
                self.last_good, self.error, self.failures = time.time(), '', 0
                self.next_poll = started + config['interval']/2
        except (OSError, ModbusError, ValueError) as err:
            with self.lock:
                if self.config is not config:
                    return
                self.error = str(err)
                self.failures += 1
                self.next_poll = time.monotonic() + min(60, config['interval'] * 2**min(self.failures-1, 10))

    def write(self, body):
        # Serialize configuration replacement and writes so confirmation cannot
        # accidentally target a different device after a table edit.
        with self.lock:
            if not self.config:
                raise ValueError('configure a device first')
            if body.get('target') != target(self.config):
                raise ValueError('target changed; review and confirm again')
            client_for(self.config, journal_path=self.journal_path).write(
                body.get('unit'), body.get('function'), body.get('address'), body.get('values', []),
                confirm=body.get('confirm'), actor=body.get('actor'), journal=self.journal)
        return {'ok': True}

    def _run(self):
        while not self.stop_event.wait(0.02):
            self.poll_once()

    def close(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=2)
