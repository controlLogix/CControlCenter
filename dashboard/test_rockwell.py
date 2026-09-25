"""The audited pycomm3 wrapper.

No network and no controller: a recorded fake driver stands in, shaped like
pycomm3's own return values. The point of these is not that pycomm3 works - it
has its own tests - but that OUR write path cannot be taken without leaving a
record, and that the read path closes the gaps logix.py names.

The whitelist test is the one written for future authors rather than for today:
a new write-capable method fails it until somebody classifies it. Everything
else here can be satisfied by a careful person; that one is satisfied by the
gate noticing.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'field'))
try:
    import rockwell
    import writejournal
except ImportError as exc:      # a tree without the module - see _NeedsRockwell
    rockwell = writejournal = None
    IMPORT_ERROR = exc
else:
    IMPORT_ERROR = None


# ── a recorded controller ────────────────────────────────────────────────────
# Shaped like pycomm3's own values: driver.tags is a dict of specs, read/write
# return Tag-alikes whose truthiness is "did this work".

class FakeTag:
    def __init__(self, tag, value=None, type_=None, error=None):
        self.tag, self.value, self.type, self.error = tag, value, type_, error

    def __bool__(self):
        return self.error is None


TAGS = {
    'CartonCount': {
        'tag_type': 'atomic', 'data_type': 'DINT', 'instance_id': 1841,
        'dim': 0, 'dimensions': [0, 0, 0], 'alias': False,
        'external_access': 'Read/Write',
    },
    'Tank': {
        'tag_type': 'struct', 'instance_id': 1902, 'dim': 0,
        'dimensions': [0, 0, 0], 'alias': False, 'external_access': 'Read/Write',
        'data_type': {
            'name': 'UDT_Tank',
            'template': {'structure_handle': 0x2A1B, 'structure_size': 24,
                         'member_count': 3},
            'internal_tags': {
                'Level':   {'tag_type': 'atomic', 'data_type': 'REAL', 'offset': 0},
                'Filling': {'tag_type': 'atomic', 'data_type': 'BOOL', 'offset': 4, 'bit': 2},
                'Name':    {'tag_type': 'atomic', 'data_type': 'SINT', 'offset': 8, 'array': 16},
            },
        },
    },
}

PLC_INFO = {
    'name': 'LineOne', 'product_name': '1756-L83E/B', 'product_code': 168,
    'vendor': 'Rockwell Automation/Allen-Bradley', 'serial': 'a1b2c3d4',
    'keyswitch': 'REMOTE RUN', 'revision': {'major': 32, 'minor': 11},
}


class FakeDriver:
    """Stands in for pycomm3.LogixDriver. Records everything it is asked to do."""

    def __init__(self, path, *, write_error=None, write_raises=None, read_raises=False):
        self.path = path
        self.tags = TAGS
        self.opened = self.closed = False
        self.writes = []
        self.reads = []
        self._write_error = write_error
        self._write_raises = write_raises
        self._read_raises = read_raises
        self.values = {'CartonCount': 41, 'Tank.Level': 3.5}

    def open(self):
        self.opened = True

    def close(self):
        self.closed = True

    def get_plc_info(self):
        return PLC_INFO

    def read(self, *names):
        if self._read_raises:
            raise ConnectionError('link lost')
        self.reads.append(names)
        out = [FakeTag(n, self.values.get(n), 'DINT') for n in names]
        return out[0] if len(out) == 1 else out

    def write(self, *pairs):
        if self._write_raises is not None:
            raise self._write_raises
        self.writes.append(pairs)
        tag = pairs[0][0] if pairs and isinstance(pairs[0], tuple) else None
        return FakeTag(tag, pairs[0][1] if pairs else None, 'DINT',
                       error=self._write_error)


class _NeedsRockwell(unittest.TestCase):
    """The absence of the module under test must FAIL, never crash the suite.

    A suite that dies at import proves nothing, and the failability gate cannot
    tell "this would have caught the regression" from "this file would not
    load" - both produce no assertions.
    """

    def setUp(self):
        if rockwell is None:
            self.fail(f'field/rockwell.py is missing, so nothing here holds: {IMPORT_ERROR}')
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.journal_path = Path(self.temp.name) / 'field-writes.jsonl'
        self.journal = writejournal.WriteJournal(self.journal_path, transport='pycomm3')

    def session(self, **kwargs):
        made = {}

        def factory(path):
            made['driver'] = FakeDriver(path, **kwargs)
            return made['driver']

        s = rockwell.AuditedLogixSession('10.1.2.3/bp/1', journal=self.journal,
                                         driver_factory=factory)
        s.open()
        self.addCleanup(s.close)
        return s, made['driver']

    def rows(self):
        if not self.journal_path.exists():
            return []
        return [json.loads(line) for line in
                self.journal_path.read_text(encoding='utf-8').splitlines() if line.strip()]


# ── the capability surface ───────────────────────────────────────────────────

class SurfaceTests(_NeedsRockwell):
    def test_the_write_capable_set_is_exactly_what_is_declared(self):
        # Written for whoever adds the next method, not for today. A new public
        # callable on the session that can change a controller fails here until
        # somebody classifies it - which is the check that survives us.
        public = {name for name in dir(rockwell.AuditedLogixSession)
                  if not name.startswith('_')}
        callables = {name for name in public
                     if callable(getattr(rockwell.AuditedLogixSession, name, None))}
        declared = set(rockwell.WRITE_CAPABLE)
        self.assertTrue(declared <= callables,
                        f'WRITE_CAPABLE names methods that do not exist: {declared - callables}')
        writers = {name for name in callables if name.startswith('write')}
        self.assertEqual(writers, declared,
                         'a write-capable method is not declared in WRITE_CAPABLE; '
                         'classify it, do not widen the set to make this pass')
        # And the readers stay readers: nothing else may reach the wire to write.
        self.assertEqual(callables - declared,
                         {'open', 'close', 'read', 'tags', 'describe', 'plc_info'})

    def test_the_driver_is_never_handed_out(self):
        session, driver = self.session()
        exposed = [name for name in dir(session)
                   if not name.startswith('_') and getattr(session, name, None) is driver]
        self.assertEqual(exposed, [], f'the driver is reachable as {exposed}')

    def test_the_audit_bypassing_methods_are_defanged_on_the_instance(self):
        # Defence in depth, NOT a fence - Python has no private, and the module
        # says so. This asserts the layer exists, not that it is sufficient.
        _session, driver = self.session()
        for name in ('write', 'generic_message'):
            with self.subTest(method=name):
                with self.assertRaises(rockwell.WriteRefused) as caught:
                    getattr(driver, name)(('CartonCount', 1))
                # The message has to point at the audited path, because whoever
                # reads this traceback needs to know where to go instead.
                self.assertIn('write_tag', str(caught.exception))

    def test_a_refused_bypass_writes_nothing_and_journals_nothing(self):
        _session, driver = self.session()
        with self.assertRaises(rockwell.WriteRefused):
            driver.write(('CartonCount', 99))
        self.assertEqual(driver.writes, [])
        self.assertEqual(self.rows(), [])


# ── the gates in front of a write ────────────────────────────────────────────

class WriteGateTests(_NeedsRockwell):
    def test_confirm_and_actor_gate_before_anything_happens(self):
        session, driver = self.session()
        for confirm in (False, 1, 'true', None):
            with self.subTest(confirm=confirm), self.assertRaises(rockwell.WriteRefused):
                session.write_tag('CartonCount', 7, confirm=confirm, actor='operator')
        for actor in (None, '', '   ', 7):
            with self.subTest(actor=actor), self.assertRaises(ValueError):
                session.write_tag('CartonCount', 7, confirm=True, actor=actor)
        # Nothing reached the wire and nothing was recorded - a refused write is
        # not an attempted one, and a journal full of them would be noise.
        self.assertEqual(driver.writes, [])
        self.assertEqual(self.rows(), [])
        self.assertFalse(self.journal_path.exists())

    def test_the_intent_is_on_disk_before_the_write_is_sent(self):
        # Checked from inside the write itself, which is the only place the
        # ordering can actually be observed.
        seen = {}
        session, _driver = self.session()

        # Patch the CLASS method, because that is the one the session reaches
        # for deliberately - the instance attribute is the refusal.
        original = FakeDriver.write

        def watched(drv, *pairs):
            seen['rows'] = self.rows()      # read off disk, mid-write
            return original(drv, *pairs)

        FakeDriver.write = watched
        try:
            session.write_tag('CartonCount', 7, confirm=True, actor='operator')
        finally:
            FakeDriver.write = original

        # If the journal were written after transmission this would be empty,
        # which is what makes the assertion worth making.
        self.assertEqual([r['outcome'] for r in seen['rows']], ['intent'],
                         'the intent was not durable before transmission')
        self.assertEqual(seen['rows'][0]['new_value'], 7)

    def test_a_journal_that_cannot_record_stops_the_write(self):
        from unittest.mock import patch
        session, driver = self.session()
        with patch.object(self.journal, 'append', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                session.write_tag('CartonCount', 7, confirm=True, actor='operator')
        self.assertEqual(driver.writes, [], 'a write reached the controller with no record')


# ── outcomes ─────────────────────────────────────────────────────────────────

class OutcomeTests(_NeedsRockwell):
    def test_success_records_what_was_overwritten(self):
        session, driver = self.session()
        result = session.write_tag('CartonCount', 7, confirm=True, actor='operator')
        rows = self.rows()
        self.assertEqual([r['outcome'] for r in rows], ['intent', 'success'])
        self.assertEqual(rows[0]['transport'], 'pycomm3')
        self.assertEqual(rows[0]['actor'], 'operator')
        # The value that was there, recorded as an OBSERVATION: controller logic
        # can change a tag between the read and the write, so it is not a
        # snapshot and the field name must not claim it is.
        self.assertEqual(rows[0]['observed_value'], 41)
        self.assertIn('observed_value', rows[0])
        self.assertNotIn('before', rows[0])
        self.assertEqual(result['journal_id'], rows[0]['id'])
        self.assertEqual(driver.writes, [(('CartonCount', 7),)])

    def test_the_controller_saying_no_is_rejected_and_changes_nothing(self):
        session, _driver = self.session(write_error='Path destination unknown')
        with self.assertRaises(rockwell.WriteRefused):
            session.write_tag('CartonCount', 7, confirm=True, actor='operator')
        rows = self.rows()
        self.assertEqual([r['outcome'] for r in rows], ['intent', 'rejected'])
        self.assertIn('Path destination unknown', rows[1]['error'])

    def test_a_transport_failure_is_unknown_not_rejected(self):
        # The difference is the whole point: rejected means nothing changed,
        # unknown means we do not know. They are acted on differently.
        session, _driver = self.session(write_raises=ConnectionError('link lost'))
        with self.assertRaises(ConnectionError):
            session.write_tag('CartonCount', 7, confirm=True, actor='operator')
        rows = self.rows()
        self.assertEqual([r['outcome'] for r in rows], ['intent', 'unknown'])

    def test_no_retry_path_is_exposed(self):
        # An unknown outcome is investigated at the equipment, never retried by
        # software - so there must be nothing here that offers to.
        source = (Path(__file__).resolve().parents[1] / 'field' / 'rockwell.py').read_text(encoding='utf-8')
        import ast
        tree = ast.parse(source)
        names = {n.name for n in ast.walk(tree)
                 if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
        offenders = sorted(n for n in names if 'retry' in n.lower())
        self.assertEqual(offenders, [], f'a retry path is exposed: {offenders}')

    def test_an_unreadable_current_value_does_not_block_the_write_but_is_recorded(self):
        # The read-back is best effort. Failing the write because we could not
        # see the old value would be worse: it makes the audit read-back a
        # precondition for control, which it is not.
        session, driver = self.session(read_raises=True)
        session.write_tag('CartonCount', 7, confirm=True, actor='operator')
        rows = self.rows()
        self.assertEqual([r['outcome'] for r in rows], ['intent', 'success'])
        self.assertIsNone(rows[0]['observed_value'])
        self.assertIn('link lost', rows[0]['observed_error'])


# ── what pycomm3 closes in logix.py ──────────────────────────────────────────

class DecodingTests(_NeedsRockwell):
    def test_instance_ids_come_from_the_controller(self):
        # logix.py:6-7: "callers supply an instance ID obtained from the
        # controller". Now nobody supplies it.
        session, _driver = self.session()
        self.assertEqual(session.tags()['CartonCount']['instance_id'], 1841)
        self.assertEqual(session.tags()['Tank']['instance_id'], 1902)

    def test_a_udt_reports_its_template_rather_than_the_caller_guessing(self):
        # logix.py:11-12: "the caller must supply the handle and element size
        # from a known template, not guess a UDT layout".
        session, _driver = self.session()
        template = session.tags()['Tank']['template']
        self.assertEqual(template['structure_handle'], 0x2A1B)
        self.assertEqual(template['structure_size'], 24)
        self.assertEqual(template['member_count'], 3)

    def test_members_decode_with_offsets_and_bit_positions(self):
        # logix.py:10-11: "template discovery/member layout decoding is not
        # included". It is now.
        session, _driver = self.session()
        members = session.tags()['Tank']['members']
        self.assertEqual(set(members), {'Level', 'Filling', 'Name'})
        self.assertEqual(members['Level'], {'data_type': 'REAL', 'tag_type': 'atomic',
                                            'offset': 0, 'bit': None, 'array': 0,
                                            'template': None})
        # A packed BOOL needs its bit position, or it is written to the wrong bit.
        self.assertEqual(members['Filling']['bit'], 2)
        self.assertEqual(members['Name']['array'], 16)

    def test_a_member_path_describes_the_member(self):
        session, _driver = self.session()
        described = session.describe('Tank.Level')
        self.assertEqual(described['data_type'], 'REAL')
        self.assertEqual(described['parent'], 'Tank')
        self.assertIsNone(session.describe('Tank.Nope'))
        self.assertIsNone(session.describe('NoSuchTag'))

    def test_the_revision_is_read_not_typed(self):
        # logix.py: "version 21 or later... callers supply". Read it once.
        session, _driver = self.session()
        info = session.plc_info()
        self.assertEqual(info['revision_major'], 32)
        self.assertTrue(info['supports_instance_addressing'])

    def test_a_member_write_carries_the_layout_it_did_not_guess(self):
        session, _driver = self.session()
        session.write_member('Tank.Level', 4.25, confirm=True, actor='operator')
        row = self.rows()[0]
        self.assertEqual(row['member_of'], 'Tank')
        self.assertEqual(row['member_offset'], 0)
        self.assertEqual(row['member_type'], 'REAL')

    def test_a_struct_write_refuses_a_member_name_that_does_not_exist(self):
        # A typo that reaches a controller is how the wrong thing gets written,
        # so this is refused here rather than left for the driver to interpret.
        session, driver = self.session()
        with self.assertRaises(ValueError) as caught:
            session.write_struct('Tank', {'Level': 1.0, 'Levle': 2.0},
                                 confirm=True, actor='operator')
        self.assertIn('Levle', str(caught.exception))
        self.assertEqual(driver.writes, [])
        self.assertEqual(self.rows(), [])

    def test_write_member_needs_a_member_path(self):
        session, _driver = self.session()
        with self.assertRaises(ValueError):
            session.write_member('CartonCount', 1, confirm=True, actor='operator')


def main():
    runner = unittest.TextTestRunner(verbosity=2)
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    result = runner.run(suite)
    failed = len(result.failures) + len(result.errors)
    print(f'passed {result.testsRun - failed - len(result.skipped)}, failed {failed}')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
