"""The only module in this repo permitted to import pycomm3.

WHY A SINGLE IMPORT SITE. pycomm3 can write anything to a Logix controller,
including arbitrary CIP services through `generic_message`. Scattering its
import would scatter that capability, and "every write is audited" would become
a claim about developer discipline rather than about the code. `import pycomm3`
appearing anywhere else is a test failure - see dashboard/check_field_writes.sh.

WHAT ACTUALLY HOLDS, STATED HONESTLY. There are layers here and they are not
equally strong:

  1. This module is the only importer.          - a tripwire, checked by CI
  2. AuditedLogixSession never hands out the driver, and defangs the two
     methods that bypass the audit on the instance it holds.
                                                - defence in depth, NOT a fence
  3. The sidecar exposes no route taking a raw CIP service, class, instance or
     attribute, and no generic_message.         - THIS is the real boundary

**Python has no private.** A caller inside this process that wants the driver
can reach it; the mangled attribute is one `getattr` away and nothing here
pretends otherwise. Layer 2 exists to catch OUR OWN future mistakes, which is
the actual threat model - nobody is attacking a loopback sidecar from inside
itself. What stops an unaudited write from the outside is that there is no route
for one, and that is a property of field/app.py, not of this file.

WHAT THIS CLOSES. logix.py names its own gaps and pycomm3 fills exactly those:
instance IDs sourced from the controller rather than supplied by the caller
(`logix.py:6-7`); template discovery and member layout decoding (`:10-11`); the
handle and element size for a UDT write read from the cached template rather
than guessed (`:11-12`); the controller revision read once on connect rather
than typed by a caller; and routing through a chassis backplane, which
`enip.py:4` rules out.

logix.py is NOT retired by this. It stays as a second, independent decoder and
is worth keeping as a verification oracle: two decoders agreeing about a value
is stronger evidence than either alone, and it turns a sunk cost into a
regression asset.
"""

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
# The vendored, hash-pinned copy (field/vendor/README.md) comes first, so this
# imports the reviewed bytes even on a machine that happens to have pycomm3
# pip-installed. A sidecar that silently used a different version than the one
# in the manifest would make the manifest a decoration.
sys.path.insert(0, str(_HERE / 'vendor'))
sys.path.insert(0, str(_HERE.parent / 'dashboard'))

import writejournal                                    # noqa: E402

try:
    import pycomm3                                     # noqa: E402
    from pycomm3 import CIPDriver, LogixDriver         # noqa: E402
    IMPORT_ERROR = None
except Exception as _exc:                              # noqa: BLE001
    pycomm3 = CIPDriver = LogixDriver = None
    IMPORT_ERROR = f'{type(_exc).__name__}: {_exc}'


class RockwellUnavailable(RuntimeError):
    """pycomm3 could not be imported; the Rockwell features are off."""


class WriteRefused(PermissionError):
    """A write was refused before anything reached the wire."""


def available():
    """True when the Rockwell features can run at all. Never raises."""
    return LogixDriver is not None


def _require():
    if not available():
        raise RockwellUnavailable(f'pycomm3 is unavailable: {IMPORT_ERROR}')


def _refuse(name):
    """Replace a driver method with something that explains itself.

    Bound onto the INSTANCE, so the class is untouched and the session can still
    reach the real method deliberately, in one visible place. Anyone who ends up
    reading this traceback is being told where the audited path is, which is
    more useful than a driver that silently did the write.
    """
    def refused(*_args, **_kwargs):
        raise WriteRefused(
            f'{name}() is not reachable through AuditedLogixSession. Every write '
            f'goes through write_tag/write_member/write_struct so that it is '
            f'journalled before transmission; a raw CIP service has no audit '
            f'record and no outcome, so there is deliberately no route to one.')
    return refused


# ── reads ────────────────────────────────────────────────────────────────────

def _template_of(data_type):
    """The structure_handle and element size a UDT write needs.

    This is the thing logix.py:11-12 says the caller must supply and must not
    guess. Read from the controller's own template, so it is sourced rather
    than assumed.
    """
    if not isinstance(data_type, dict):
        return None
    template = data_type.get('template') or {}
    if not template:
        return None
    return {
        'name': data_type.get('name'),
        'structure_handle': template.get('structure_handle'),
        'structure_size': template.get('structure_size'),
        'member_count': template.get('member_count'),
    }


def _members_of(data_type):
    """Each member's name, type, byte offset and bit position.

    `internal_tags` is what makes `read('UDT.Member')` possible without the
    caller knowing the layout - logix.py:10-11's second gap.
    """
    if not isinstance(data_type, dict):
        return {}
    members = {}
    for name, spec in (data_type.get('internal_tags') or {}).items():
        inner = spec.get('data_type')
        members[name] = {
            'data_type': inner.get('name') if isinstance(inner, dict) else inner,
            'tag_type': spec.get('tag_type'),
            'offset': spec.get('offset'),
            'bit': spec.get('bit'),
            'array': spec.get('array') or 0,
            # A member that is itself a structure carries its own template.
            'template': _template_of(inner),
        }
    return members


def describe_tag(name, spec):
    """Normalise one pycomm3 tag entry into the shape the panel renders.

    Kept separate from the session so it can be tested against recorded
    controller output with no driver and no network at all.
    """
    data_type = spec.get('data_type')
    structure = isinstance(data_type, dict)
    return {
        'name': name,
        'tag_type': spec.get('tag_type'),
        # Sourced from the controller (logix.py:6-7), never supplied by a caller.
        'instance_id': spec.get('instance_id'),
        'data_type': data_type.get('name') if structure else data_type,
        'dimensions': [d for d in (spec.get('dimensions') or []) if d],
        'dim': spec.get('dim', 0),
        'alias': bool(spec.get('alias')),
        'external_access': spec.get('external_access'),
        'template': _template_of(data_type),
        'members': _members_of(data_type),
    }


class AuditedLogixSession:
    """A Logix connection whose only write paths are journalled ones.

    Use as a context manager. The driver is never returned, never stored on a
    public attribute, and has its two audit-bypassing methods replaced on the
    instance. See the module docstring for what that is and is not worth.
    """

    def __init__(self, path, *, journal=None, driver_factory=None):
        _require()
        if not isinstance(path, str) or not path.strip():
            raise ValueError('a connection path is required, e.g. "10.1.2.3/bp/1"')
        self.path = path
        # A separate journal instance per session, but the same file: one
        # audit trail for every transport (writejournal.py).
        self.journal = journal if journal is not None else writejournal.WriteJournal(
            None, transport='pycomm3')
        # Injectable so the proof tests can drive a recorded controller with no
        # network. It is a seam, not a back door: it cannot reach a real
        # controller that the path does not already name.
        self._factory = driver_factory or LogixDriver
        self.__driver = None
        self._info = None

    # ── lifecycle ────────────────────────────────────────────────────────────
    def __enter__(self):
        self.open()
        return self

    def __exit__(self, *_exc):
        self.close()
        return False

    def open(self):
        if self.__driver is not None:
            return
        driver = self._factory(self.path)
        driver.open()
        # Defang the instance. Defence in depth only - see the module docstring.
        driver.write = _refuse('write')
        driver.generic_message = _refuse('generic_message')
        self.__driver = driver
        return self

    def close(self):
        driver, self.__driver = self.__driver, None
        if driver is not None:
            driver.close()

    def _driver(self):
        if self.__driver is None:
            raise RuntimeError('session is not open')
        return self.__driver

    # ── reads ────────────────────────────────────────────────────────────────
    def plc_info(self):
        """Identity and revision, read from the controller once per session.

        logix.py required callers to supply the major revision, which meant a
        number typed by a person could disagree with the controller. Read it.
        """
        if self._info is None:
            info = self._driver().get_plc_info()
            revision = info.get('revision') or {}
            self._info = {
                'name': info.get('name'),
                'product_name': info.get('product_name'),
                'product_code': info.get('product_code'),
                'vendor': info.get('vendor'),
                'serial': info.get('serial'),
                'keyswitch': info.get('keyswitch'),
                'revision_major': revision.get('major'),
                'revision_minor': revision.get('minor'),
                # Symbol instance addressing needs 21 or later (logix.py:7).
                'supports_instance_addressing': (revision.get('major') or 0) >= 21,
            }
        return dict(self._info)

    def tags(self):
        """Every controller-scope tag, with instance ids and UDT layouts."""
        return {name: describe_tag(name, spec)
                for name, spec in (self._driver().tags or {}).items()}

    def describe(self, name):
        """One tag, or None. Accepts 'UDT.Member' and describes the member."""
        tags = self._driver().tags or {}
        if name in tags:
            return describe_tag(name, tags[name])
        base, _, member = name.partition('.')
        if member and base in tags:
            described = describe_tag(base, tags[base])
            spec = described['members'].get(member)
            if spec is not None:
                return dict(spec, name=name, parent=base)
        return None

    def read(self, *names):
        """Read one or more tags. Reads are not gated; only writes are."""
        if not names:
            raise ValueError('read requires at least one tag name')
        results = self._driver().read(*names)
        if not isinstance(results, list):
            results = [results]
        return [{'tag': r.tag, 'value': r.value, 'type': r.type,
                 'error': r.error, 'ok': bool(r)} for r in results]

    # ── writes ───────────────────────────────────────────────────────────────
    @staticmethod
    def _authorize(confirm, actor):
        # Verbatim the posture enip.py:8-11 states and test_enip/test_logix
        # prove: confirm=True and a nonempty actor, checked before anything
        # else happens, so a guard failure cannot reach the wire.
        if confirm is not True:
            raise WriteRefused('write requires confirm=True')
        if not isinstance(actor, str) or not actor.strip():
            raise ValueError('write requires a named actor')

    def _write(self, kind, tag, value, *, confirm, actor, **extra):
        self._authorize(confirm, actor)
        driver = self._driver()

        # Read back what is about to be overwritten. Best effort and recorded as
        # such: an observation is not a snapshot, because controller logic can
        # change the tag between this read and the write. Recording it as
        # `observed` rather than `before` is the difference between an audit
        # record and a claim.
        observed, observed_error = None, None
        try:
            current = driver.read(tag)
            observed = getattr(current, 'value', None)
            observed_error = getattr(current, 'error', None)
        except Exception as exc:                        # noqa: BLE001
            observed_error = f'{type(exc).__name__}: {exc}'

        # Durable BEFORE transmission, and it raises if it cannot be - in which
        # case nothing below runs and nothing reaches the wire.
        handle = self.journal.intent(dict(
            actor=actor, kind=kind, path=self.path, tag=tag,
            new_value=_jsonable(value), observed_value=_jsonable(observed),
            observed_error=observed_error, **extra))

        try:
            # Reaching past the defanged instance attribute to the real class
            # method, deliberately and in exactly one place. This is the audited
            # path; everything else got _refuse().
            result = type(driver).write(driver, (tag, value))
        except Exception as exc:                        # noqa: BLE001
            # An exception is a transport failure: we do not know whether the
            # controller applied it. Different from a refusal, and never
            # retried automatically.
            handle.settle('unknown', error=f'{type(exc).__name__}: {exc}')
            raise

        if isinstance(result, list):
            result = result[0] if result else None
        error = getattr(result, 'error', None) if result is not None else 'no response'
        if error:
            # The controller answered and said no. Nothing changed.
            handle.settle('rejected', error=str(error))
            raise WriteRefused(f'controller refused the write to {tag}: {error}')

        handle.settle('success')
        return {'tag': tag, 'value': _jsonable(value), 'observed': _jsonable(observed),
                'observed_error': observed_error, 'journal_id': handle.id}

    def write_tag(self, tag, value, *, confirm=False, actor=None):
        """Write one atomic tag."""
        return self._write('write_tag', tag, value, confirm=confirm, actor=actor)

    def write_member(self, tag, value, *, confirm=False, actor=None):
        """Write one member of a structure, e.g. 'Tank.Level'.

        The handle and element size come from the controller's cached template,
        which is the gap logix.py:11-12 names: the caller no longer supplies
        them and therefore cannot guess them wrong.
        """
        if '.' not in tag:
            raise ValueError('write_member needs a member path, e.g. "Tank.Level"')
        described = self.describe(tag)
        if described is None:
            raise ValueError(f'{tag} is not a member of any known tag')
        return self._write('write_member', tag, value, confirm=confirm, actor=actor,
                           member_of=described.get('parent'),
                           member_offset=described.get('offset'),
                           member_type=described.get('data_type'))

    def write_struct(self, tag, value, *, confirm=False, actor=None):
        """Write a whole structure, as a dict keyed by member name."""
        if not isinstance(value, dict):
            raise ValueError('write_struct takes a dict keyed by member name')
        described = self.describe(tag)
        if described is None:
            raise ValueError(f'{tag} is not a known tag')
        template = described.get('template')
        if not template or template.get('structure_handle') is None:
            raise ValueError(f'{tag} has no structure template; it is not a UDT')
        unknown = sorted(set(value) - set(described.get('members') or {}))
        if unknown:
            # Refuse rather than let the driver decide. A member name that does
            # not exist is a typo, and a typo that reaches a controller is how
            # the wrong thing gets written.
            raise ValueError(f'{tag} has no member(s) {unknown}')
        return self._write('write_struct', tag, value, confirm=confirm, actor=actor,
                           structure_handle=template.get('structure_handle'),
                           structure_size=template.get('structure_size'))


def _jsonable(value):
    """Values reach the journal as JSON, so bytes become hex and the rest is checked."""
    if isinstance(value, (bytes, bytearray)):
        return {'hex': bytes(value).hex()}
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


def discover(timeout=1.0):
    """Broadcast ListIdentity and report what answers.

    UDP, so it finds devices a TCP sweep cannot, and it returns the device's own
    account of itself - vendor, product code, revision, serial and state - rather
    than an inference from an open port. Read-only by construction: ListIdentity
    has no write form.
    """
    _require()
    found = CIPDriver.discover(timeout) if timeout else CIPDriver.discover()
    return [{
        'ip_address': d.get('ip_address'),
        'product_name': d.get('product_name'),
        'product_code': d.get('product_code'),
        'vendor': d.get('vendor'),
        'device_type': d.get('device_type'),
        'revision': d.get('revision'),
        'serial': d.get('serial'),
        'state': d.get('state'),
        'status': d.get('status'),
        'origin': 'cip-listidentity',
    } for d in (found or [])]


# The set of public callables on the session that can change a controller. The
# proof test asserts this is EXACTLY right, so a new write method fails the gate
# until somebody classifies it - which is the check that survives future authors.
WRITE_CAPABLE = frozenset({'write_tag', 'write_member', 'write_struct'})
