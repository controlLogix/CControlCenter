"""The shared field-write journal.

These are the properties the two journals this replaces were tested for, plus
the ones only a shared journal needs: that a row says which transport it came
from, that an intent can be paired back to its outcome, and that the migration
off the old files loses nothing.

The ordering and fail-closed tests are the load-bearing ones. If either can be
made to pass against a journal that writes after transmission, the module is
wrong however tidy it looks.
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    import writejournal
except ImportError as exc:      # a tree without the module - see _NeedsJournal
    writejournal, IMPORT_ERROR = None, exc
else:
    IMPORT_ERROR = None


class _NeedsJournal(unittest.TestCase):
    """The absence of the module under test must FAIL, never crash the suite.

    A suite that dies at import proves nothing, and the failability gate cannot
    tell "this test would have caught the regression" from "this file could not
    be loaded" - both produce no assertions. So the import is guarded and every
    property reports itself as failing instead.
    """

    def setUp(self):
        if writejournal is None:
            self.fail(f'writejournal is missing, so nothing here is guaranteed: {IMPORT_ERROR}')


class ClassifyTests(_NeedsJournal):
    def test_rejected_means_the_device_said_no(self):
        self.assertEqual(writejournal.classify(True), 'rejected')

    def test_anything_else_is_unknown_not_a_failure(self):
        # A dropped connection is not the device refusing. We do not know what
        # happened at the far end, and that is a different fact to act on.
        self.assertEqual(writejournal.classify(False), 'unknown')

    def test_completed_fragments_outrank_the_reason(self):
        # Some fragments landed, so the controller holds a value neither side
        # asked for. That is worse to know than either word alone, and must not
        # be folded into 'unknown'.
        self.assertEqual(writejournal.classify(True, 1), 'partial')
        self.assertEqual(writejournal.classify(False, 3), 'partial')


class JournalTests(_NeedsJournal):
    def setUp(self):
        super().setUp()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'sub' / 'field-writes.jsonl'
        self.journal = writejournal.WriteJournal(self.path, transport='enip')

    def rows(self):
        return [json.loads(line) for line in
                self.path.read_text(encoding='utf-8').splitlines() if line.strip()]

    def test_constructing_a_journal_writes_nothing(self):
        # A client that is built and then refuses to write - a bad actor, an
        # unconfirmed call - must leave no trace at all.
        self.assertFalse(self.path.exists())
        self.assertFalse(self.path.parent.exists())

    def test_a_transport_is_required_and_must_be_named(self):
        for bad in (None, '', '   ', 7):
            with self.subTest(transport=bad), self.assertRaises(ValueError):
                writejournal.WriteJournal(self.path, transport=bad)

    def test_intent_is_on_disk_before_it_returns(self):
        # Checked from INSIDE fsync, so this is the ordering guarantee itself and
        # not a re-read after the fact, which would pass either way.
        seen = []
        real = writejournal.os.fsync

        def checked(fd):
            real(fd)
            seen.append(self.path.read_text(encoding='utf-8'))

        with patch('writejournal.os.fsync', side_effect=checked) as sync:
            self.journal.intent({'tag': 'Count', 'value': 10})
            sync.assert_called_once()
        self.assertIn('"outcome": "intent"', seen[0])
        self.assertIn('"value": 10', seen[0])

    def test_every_row_names_its_transport_and_pairs_to_its_intent(self):
        handle = self.journal.intent({'tag': 'Count', 'value': 10})
        handle.settle('success')
        rows = self.rows()
        self.assertEqual([r['outcome'] for r in rows], ['intent', 'success'])
        self.assertEqual({r['transport'] for r in rows}, {'enip'})
        # One id across both rows: that is how a reader pairs an outcome back to
        # the intent it settles, in a file now holding several transports.
        self.assertEqual(len({r['id'] for r in rows}), 1)
        self.assertEqual(rows[0]['id'], handle.id)
        self.assertTrue(all(isinstance(r['time'], float) for r in rows))

    def test_a_write_cannot_be_settled_twice(self):
        # Two outcomes for one write makes the journal ambiguous at exactly the
        # moment it is being read to find out what happened.
        handle = self.journal.intent({'tag': 'Count'})
        handle.settle('success')
        with self.assertRaises(RuntimeError):
            handle.settle('rejected')
        self.assertEqual([r['outcome'] for r in self.rows()], ['intent', 'success'])

    def test_an_unrecognised_outcome_is_refused(self):
        handle = self.journal.intent({'tag': 'Count'})
        for bad in ('ok', 'failed', 'intent', '', None):
            with self.subTest(outcome=bad), self.assertRaises(ValueError):
                handle.settle(bad)
        # And refusing left the write open, so it can still be settled properly.
        self.assertIsNone(handle.outcome)
        handle.settle('unknown')
        self.assertEqual(handle.outcome, 'unknown')

    def test_intent_fails_closed(self):
        # The caller must not transmit, so the error has to reach it. A journal
        # that swallowed this would leave writes happening with no record.
        with patch.object(self.journal, 'append', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                self.journal.intent({'tag': 'Count'})

    def test_raw_bytes_survive_as_hex(self):
        # Bytes preserve NaN/Inf and packed BOOL bits, which JSON numbers do not.
        handle = self.journal.intent({'old_value': b'\x00\xff', 'new_value': b'\xc2\x00'})
        handle.settle('success')
        self.assertEqual(self.rows()[0]['old_value'], {'hex': '00ff'})

    def test_a_value_json_cannot_represent_is_refused_rather_than_mangled(self):
        with self.assertRaises(ValueError):
            self.journal.intent({'value': float('nan')})

    def test_the_default_path_follows_home(self):
        # Resolved per call, not captured at import: the tests and the sidecar
        # both relocate HOME, and a module constant would freeze whichever home
        # happened to be set first.
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop('AGENTMUX_HOME', None)
            with patch.object(Path, 'home', return_value=Path(self.temp.name) / 'elsewhere'):
                self.assertEqual(writejournal.default_path(),
                                 Path(self.temp.name) / 'elsewhere' / '.agentmux' / 'field-writes.jsonl')

    def test_agentmux_home_wins_because_that_is_what_every_suite_relocates(self):
        # The residue bug ccstore.py:17-21 already records once: two files
        # hardcoded ~/.agentmux, and the moment AGENTMUX_HOME was set - which
        # every suite does - they wrote to the operator's real directory. For an
        # audit trail that is worse than untidy: a test run leaves rows in the
        # record of what was actually sent to equipment. Found again here when a
        # suite run created ~/.agentmux/field-writes.jsonl with 'test-operator'
        # rows in it.
        elsewhere = Path(self.temp.name) / 'relocated'
        with patch.dict(os.environ, {'AGENTMUX_HOME': str(elsewhere)}):
            self.assertEqual(writejournal.default_path(), elsewhere / 'field-writes.jsonl')
            self.assertTrue(all(p.parent == elsewhere for p in writejournal.legacy_paths()),
                            'the legacy journals do not follow AGENTMUX_HOME either')


class MigrationTests(_NeedsJournal):
    def setUp(self):
        super().setUp()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.target = self.root / 'field-writes.jsonl'
        self.enip = self.root / 'enip-writes.jsonl'
        self.logix = self.root / 'logix-writes.jsonl'

    def write(self, path, records):
        path.write_text(''.join(json.dumps(r) + '\n' for r in records), encoding='utf-8')

    def rows(self):
        return [json.loads(line) for line in
                self.target.read_text(encoding='utf-8').splitlines() if line.strip()]

    def test_merges_both_files_in_timestamp_order(self):
        # Interleaved on purpose: concatenating the files would put every enip
        # row before every logix one and misrepresent what happened when.
        self.write(self.enip, [{'time': 10, 'tag': 'A'}, {'time': 30, 'tag': 'C'}])
        self.write(self.logix, [{'time': 20, 'tag': 'B'}, {'time': 40, 'tag': 'D'}])
        result = writejournal.migrate_legacy(self.target, [self.enip, self.logix])
        self.assertEqual(result['merged'], 4)
        self.assertEqual([r['tag'] for r in self.rows()], ['A', 'B', 'C', 'D'])

    def test_rows_gain_the_transport_their_file_implied(self):
        self.write(self.enip, [{'time': 1, 'tag': 'A'}])
        self.write(self.logix, [{'time': 2, 'tag': 'B'}])
        writejournal.migrate_legacy(self.target, [self.enip, self.logix])
        self.assertEqual([r['transport'] for r in self.rows()], ['enip', 'logix'])

    def test_sources_are_renamed_not_deleted_and_a_rerun_is_a_no_op(self):
        # The original bytes stay available to anyone auditing the migration.
        self.write(self.enip, [{'time': 1, 'tag': 'A'}])
        writejournal.migrate_legacy(self.target, [self.enip, self.logix])
        self.assertFalse(self.enip.exists())
        self.assertTrue(self.enip.with_suffix('.jsonl.migrated').exists())

        again = writejournal.migrate_legacy(self.target, [self.enip, self.logix])
        self.assertEqual(again['merged'], 0)
        self.assertEqual(len(self.rows()), 1, 'a second run duplicated the records')

    def test_an_unparseable_line_is_kept_rather_than_dropped(self):
        # A line we cannot read is still something that happened. Discarding it
        # is the one choice that cannot be undone.
        self.enip.write_text('{"time": 1, "tag": "A"}\nnot json at all\n', encoding='utf-8')
        result = writejournal.migrate_legacy(self.target, [self.enip])
        self.assertEqual(result['merged'], 2)
        text = self.target.read_text(encoding='utf-8')
        self.assertIn('not json at all', text)
        # ...and it sorts last rather than pretending to a position in time.
        self.assertTrue(text.rstrip().endswith('not json at all'))

    def test_a_missing_source_is_reported_not_an_error(self):
        result = writejournal.migrate_legacy(self.target, [self.enip, self.logix])
        self.assertEqual(result['merged'], 0)
        self.assertEqual(len(result['skipped']), 2)
        self.assertFalse(self.target.exists())


class SoleJournalTests(_NeedsJournal):
    """Nothing may write the two files this module replaced."""

    def test_legacy_paths_covers_every_file_that_was_replaced(self):
        names = {p.name for p in writejournal.legacy_paths()}
        self.assertEqual(names, {'enip-writes.jsonl', 'logix-writes.jsonl', 'ads-writes.jsonl'})
        # The migration infers each row's transport from the stem, so the shape
        # of these names is load-bearing, not cosmetic.
        for path in writejournal.legacy_paths():
            self.assertTrue(path.name.endswith('-writes.jsonl'), path.name)

    def test_no_module_still_names_a_legacy_journal(self):
        # writejournal.py names them on purpose - that is what the migration
        # reads - so it is the one file exempt.
        here = Path(__file__).resolve().parent
        offenders = []
        for source in sorted(here.glob('*.py')):
            if source.name in ('writejournal.py', Path(__file__).name):
                continue
            text = source.read_text(encoding='utf-8', errors='replace')
            for legacy in ('enip-writes.jsonl', 'logix-writes.jsonl', 'ads-writes.jsonl'):
                if legacy in text:
                    offenders.append(f'{source.name} still names {legacy}')
        self.assertEqual(offenders, [], '; '.join(offenders))

    def test_every_client_that_writes_to_equipment_journals_through_this_module(self):
        # ads.py is here because the plan said there were TWO journals and there
        # were three: it kept ~/.agentmux/ads-writes.jsonl with the same shape
        # and the same guarantees, and nothing pointed at it. That is the exact
        # failure a shared journal exists to prevent, so the census is a test
        # rather than a sentence in a docstring - a fourth client added later
        # fails here until someone classifies it.
        import ads
        import enip
        import logix
        clients = [(enip.LogixClient('unused'), 'enip'),
                   (logix.LogixClient('unused'), 'logix'),
                   (ads.ADSClient('unused', '1.2.3.4.1.1', '5.6.7.8.1.1'), 'ads')]
        for client, transport in clients:
            with self.subTest(transport=transport):
                self.assertIsInstance(client.journal, writejournal.WriteJournal)
                self.assertEqual(client.journal.transport, transport)
                # The path property is what callers and the panels read.
                self.assertEqual(client.journal_path, client.journal.path)
                self.assertEqual(client.journal.path.name, 'field-writes.jsonl')

    def test_no_client_keeps_a_private_journal_writer_any_more(self):
        # A module that reintroduces its own _journal has reintroduced its own
        # file, and the durability guarantee stops being checked in one place.
        import ads
        import enip
        import logix
        for module in (enip, logix, ads):
            for name in dir(module):
                attr = getattr(module, name)
                if isinstance(attr, type) and hasattr(attr, '_journal'):
                    self.fail(f'{module.__name__}.{name} still has a private _journal')


def main():
    runner = unittest.TextTestRunner(verbosity=2)
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    result = runner.run(suite)
    failed = len(result.failures) + len(result.errors)
    print(f'passed {result.testsRun - failed - len(result.skipped)}, failed {failed}')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
