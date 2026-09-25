"""One durable journal for every write this project makes to field equipment.

WHY ONE. There were three. enip.py, logix.py and ads.py each kept their own
JSONL file with their own field names and their own idea of what an outcome is.
Three journals answer "what did we last send to that controller?" only for
someone who remembers all three exist - and the project plan that called for
unifying them knew about two, which is the point: ads.py had been quietly
keeping its own audit trail that nothing pointed at. None of the three files had
ever been created on this machine, so "every write is audited" was a plan rather
than a fact. One file, one format, and a `transport` field saying which client
sent it.

THE ORDER IS THE GUARANTEE. intent() writes the record, flushes it and fsyncs it
BEFORE it returns. The intent reaches the disk before a byte reaches the wire,
so a process that dies mid-write still leaves a record of what it was trying to
do. That ordering is the whole point of the module; a journal written after
transmission would be a log, not an audit trail.

IT FAILS CLOSED. Any error writing the intent propagates to the caller, which
must not then transmit. That is why intent() hands back a Handle instead of
taking the write as a callback: the exception surfaces in the caller's own
control flow, where the decision not to send is visible in the code rather than
buried in a helper.

'REJECTED' AND 'UNKNOWN' ARE DIFFERENT ANSWERS AND ARE RECORDED SEPARATELY.
Rejected means the device said no and nothing changed. Unknown means we do not
know whether it changed - the connection dropped, or the reply never arrived.
They are acted on differently, and that is the reason to distinguish them: an
unknown outcome is investigated at the equipment and NEVER automatically
retried. 'partial' is an unknown with a known boundary - some fragments were
accepted and the rest were not, so the device is in a state neither side chose.
"""

import json
import os
import time
import uuid
from pathlib import Path

# 'intent' is written by intent(); the rest settle it. A settled record repeats
# the intent's fields so one line is readable without joining it to another.
OUTCOMES = ('success', 'rejected', 'unknown', 'partial')


def default_path():
    """Where the journal lives unless a caller says otherwise.

    Resolved on each call rather than at import: the tests and the sidecar both
    relocate HOME, and a module-level constant would capture whichever home
    happened to be set when the module was first imported.
    """
    return Path.home() / '.agentmux' / 'field-writes.jsonl'


def legacy_paths():
    """The three journals this one replaces. See migrate_legacy().

    The transport each row gets during migration is inferred from the filename
    stem, so a name here must keep the '<transport>-writes.jsonl' shape.
    """
    root = Path.home() / '.agentmux'
    return (root / 'enip-writes.jsonl',
            root / 'logix-writes.jsonl',
            root / 'ads-writes.jsonl')


def classify(rejected, completed=0):
    """Map a failed transmission to an outcome.

    `rejected` is true only when the DEVICE refused - a CIP error status came
    back. Anything else (a dropped connection, a timeout, a malformed reply)
    means we do not know what happened at the far end, which is a different
    fact and gets a different word.

    `completed` outranks it: if some fragments were accepted the write is
    partial however the rest failed, because the controller now holds a value
    that neither side asked for.

    One definition, because enip.py and logix.py each had their own and a pair
    of subtly different answers to "did that write land" is worse than either.
    """
    if completed:
        return 'partial'
    return 'rejected' if rejected else 'unknown'


def _encode(value):
    # Raw bytes preserve NaN/Inf and packed BOOL bits without JSON ambiguity.
    if isinstance(value, (bytes, bytearray)):
        return {'hex': bytes(value).hex()}
    raise TypeError('unsupported journal value')


class Handle:
    """One write, from its durable intent to its settled outcome.

    Settling twice is refused. A second outcome for one write would make the
    journal ambiguous at exactly the moment it is being read to find out what
    happened, which is the only moment it matters.
    """

    __slots__ = ('_journal', '_record', '_settled')

    def __init__(self, journal, record):
        self._journal, self._record, self._settled = journal, record, None

    @property
    def id(self):
        return self._record['id']

    @property
    def outcome(self):
        return self._settled

    def settle(self, outcome, **extra):
        if self._settled is not None:
            raise RuntimeError(f'write {self.id} already settled as {self._settled}')
        if outcome not in OUTCOMES:
            raise ValueError(f'unknown outcome {outcome!r}; expected one of {OUTCOMES}')
        self._journal.append(dict(self._record, outcome=outcome, **extra))
        self._settled = outcome


class WriteJournal:
    """An append-only, fsync'd record of writes attempted against equipment."""

    def __init__(self, path=None, *, transport):
        if not isinstance(transport, str) or not transport.strip():
            raise ValueError('a journal must name its transport')
        self.transport = transport
        self.path = Path(path) if path is not None else default_path()

    def append(self, record):
        """Write one record and return only once it is on the disk.

        The directory is created here rather than in __init__ so that a client
        which is constructed and then refuses to write - a bad actor, an
        unconfirmed call - leaves no trace at all. test_logix asserts exactly
        that by checking the journal does not exist after the guards fire.
        """
        line = json.dumps(dict(record, time=time.time()),
                          default=_encode, allow_nan=False) + '\n'
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open('a', encoding='utf-8') as stream:
            stream.write(line)
            stream.flush()
            os.fsync(stream.fileno())

    def intent(self, record):
        """Record the intent to write, durably, and return its Handle.

        Raises if the record cannot be made durable - and the caller must then
        NOT transmit. Every write path in this repo relies on that, which is why
        the exception is left to propagate rather than being logged here.
        """
        entry = dict(record, id=uuid.uuid4().hex, transport=self.transport)
        self.append(dict(entry, outcome='intent'))
        return Handle(self, entry)


def migrate_legacy(target=None, sources=None):
    """Fold the legacy journals into the unified one, in timestamp order.

    Never deletes: each source is renamed to <name>.migrated once folded, so a
    second run finds nothing and the original bytes remain for anyone auditing
    the migration itself. Records with no usable `time` sort last rather than
    being dropped - an unparseable audit record is still evidence.

    Returns {'merged': n, 'sources': [...], 'skipped': [...]}.
    """
    target = Path(target) if target is not None else default_path()
    sources = [Path(p) for p in (sources if sources is not None else legacy_paths())]

    rows, moved, skipped = [], [], []
    for source in sources:
        if not source.exists():
            skipped.append(str(source))
            continue
        for line in source.read_text(encoding='utf-8').splitlines():
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except ValueError:
                # Keep it. A line we cannot parse is still something that
                # happened, and discarding it is the one unrecoverable choice.
                rows.append((float('inf'), line))
                continue
            if isinstance(record, dict):
                record.setdefault('transport', source.stem.split('-')[0])
                line = json.dumps(record, allow_nan=False)
            when = record.get('time') if isinstance(record, dict) else None
            rows.append((when if isinstance(when, (int, float)) else float('inf'), line))
        moved.append(source)

    if rows:
        rows.sort(key=lambda row: row[0])
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open('a', encoding='utf-8') as stream:
            for _, line in rows:
                stream.write(line + '\n')
            stream.flush()
            os.fsync(stream.fileno())

    for source in moved:
        source.rename(source.with_suffix(source.suffix + '.migrated'))

    return {'merged': len(rows), 'sources': [str(p) for p in moved], 'skipped': skipped}
