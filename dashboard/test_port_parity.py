"""Nothing is lost in the port, enforced rather than promised.

THE REQUIREMENT. The React rewrite is 1:1 - every view, panel, module, stored
preference, endpoint and board operation that exists today exists afterwards,
plus the new work. That is a hard scope constraint, and the way a rewrite
breaks it is never a decision. It is a list somebody wrote from memory, and the
missing line is found by an operator weeks later when the thing they use every
day is simply gone.

So the list is DERIVED from the source on every run (see portparity.py) and
every item must be accounted for in docs/port-parity.json. Three failures are
possible and each is a real way a port goes wrong:

  1. UNCLASSIFIED - present in the source, absent from the manifest. This is
     the dangerous one: a feature nobody decided about. It also catches the
     reverse direction, where a feature is added to the OLD dashboard during
     the migration and quietly never ports.
  2. UNBACKED - the manifest says `ported` and names a React file that is not
     on disk. A manifest that can claim work nobody did is a worse lie than no
     manifest, because it reads as evidence.
  3. A DROP WITH NO REASON. Deliberately not porting something is a legitimate
     decision; not saying why is not. `why` is required and is checked for
     being an actual sentence rather than a placeholder.

WHAT THIS DELIBERATELY DOES NOT DO. It does not check that a ported view is
CORRECT - that is what the view's own tests and the differ are for. It checks
that nothing fell off the list. Those are different jobs and conflating them
would make this suite fail for reasons it cannot explain.
"""
import re
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import portparity


class TheInventoryIsDerivedAndPlausible(unittest.TestCase):
    """If the derivation breaks, everything below passes vacuously."""

    @classmethod
    def setUpClass(cls):
        cls.inv = portparity.inventory()

    def test_every_kind_found_something(self):
        # A regex that stops matching returns an empty list, and an empty list
        # satisfies every "is it classified" check below without complaint.
        # That is the failure mode this suite is least able to notice, so it is
        # asserted first and directly.
        for kind, names in self.inv.items():
            self.assertTrue(names, f'{kind} derived nothing - the extractor is broken')

    def test_the_eight_known_views_are_all_found(self):
        # Named explicitly. If the rail markup changes shape and the regex
        # silently matches fewer, this says so instead of shrinking quietly.
        expected = {'board', 'github', 'iiot', 'organization',
                    'runs', 'settings', 'status', 'terminals'}
        self.assertEqual(set(self.inv['views']), expected)

    def test_the_stored_preferences_are_found_by_constant(self):
        # These are the keys a careless rename silently wipes - themes, board
        # layout, collapse and view state. The plan records this as R3.
        storage = set(self.inv['storage'])
        self.assertGreaterEqual(len(storage), 10,
                                f'only found {len(storage)} stored keys; the '
                                'constant extractor has probably stopped matching')
        for key in ('agentmux.theme', 'agentmux.view'):
            self.assertIn(key, storage, f'{key} is not being inventoried')

    def test_the_board_operation_count_matches_the_independent_survey(self):
        # The plan counted 40 board ops by hand, from BOARD_READS (15) plus
        # BOARD_WRITES (25). Two independent methods agreeing is worth more
        # than either alone, and a drift here means one of them is now wrong.
        self.assertEqual(len(self.inv['board_ops']), 40,
                         'the board op count no longer matches the surveyed 40')


class EverythingIsAccountedFor(unittest.TestCase):
    """The three ways the manifest and the source can disagree."""

    @classmethod
    def setUpClass(cls):
        cls.unclassified, cls.unbacked, cls.dropped = portparity.audit()

    def test_nothing_in_the_source_is_missing_from_the_manifest(self):
        listed = '\n'.join(f'    {kind}: {name}' for kind, name in self.unclassified)
        self.assertEqual(
            self.unclassified, [],
            'these exist in the dashboard and nobody has decided whether they '
            'port. Add each to docs/port-parity.json as vanilla, ported or '
            f'dropped:\n{listed}')

    def test_nothing_claims_to_be_ported_without_the_file_existing(self):
        listed = '\n'.join(f'    {kind}: {name} -> {path}' for kind, name, path in self.unbacked)
        self.assertEqual(
            self.unbacked, [],
            'the manifest claims these are ported but the named React file is '
            f'not on disk:\n{listed}')

    def test_every_drop_carries_a_real_reason(self):
        bad = []
        for kind, name, why in self.dropped:
            text = (why or '').strip()
            # A placeholder is worse than a blank, because it reads as answered.
            if len(text) < 20 or re.match(r'^(n/?a|tbd|todo|-+|\.+)$', text, re.I):
                bad.append(f'    {kind}: {name} -> {why!r}')
        self.assertEqual(bad, [],
                         'a deliberate drop is a decision somebody signs. These '
                         'have no usable reason:\n' + '\n'.join(bad))


class TheManifestIsHonestAboutProgress(unittest.TestCase):
    """A progress number that overstates is worse than none."""

    def test_the_manifest_exists_and_parses(self):
        self.assertTrue(portparity.MANIFEST.is_file(),
                        f'{portparity.MANIFEST} is missing')
        self.assertTrue(portparity.load_manifest(),
                        'the manifest is empty or is not valid JSON')

    def test_a_ported_entry_must_name_its_react_file(self):
        man = portparity.load_manifest()
        nameless = []
        for kind, entries in man.items():
            for name, entry in (entries or {}).items():
                if (entry or {}).get('status') == 'ported' and not (entry or {}).get('react'):
                    nameless.append(f'{kind}: {name}')
        self.assertEqual(nameless, [],
                         'ported with no React file named: ' + ', '.join(nameless))

    def test_the_status_values_are_from_the_closed_set(self):
        # A typo'd status silently reads as `vanilla` through .get's default,
        # which means a ported view could quietly stop being checked.
        allowed = {'vanilla', 'ported', 'dropped'}
        bad = []
        for kind, entries in portparity.load_manifest().items():
            for name, entry in (entries or {}).items():
                status = (entry or {}).get('status', 'vanilla')
                if status not in allowed:
                    bad.append(f'{kind}: {name} = {status!r}')
        self.assertEqual(bad, [], 'unknown status values: ' + ', '.join(bad))

    def test_progress_is_reported_and_is_not_overstated(self):
        # Prints the real number on every gate run, so "how much is ported" is
        # never a thing anybody has to estimate.
        summary = portparity.summary()
        total = sum(c['total'] for c in summary.values())
        ported = sum(c.get('ported', 0) for c in summary.values())
        dropped = sum(c.get('dropped', 0) for c in summary.values())
        print(f'  port parity: {ported}/{total} ported, {dropped} dropped, '
              f'{total - ported - dropped} still vanilla')
        self.assertLessEqual(ported, total)
        for kind, counts in summary.items():
            self.assertEqual(
                counts['total'],
                counts['ported'] + counts['vanilla'] + counts['dropped'] + counts['unclassified'],
                f'{kind} counts do not add up to its total')


def main():
    runner = unittest.TextTestRunner(verbosity=2)
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    result = runner.run(suite)
    failed = len(result.failures) + len(result.errors)
    print(f'passed {result.testsRun - failed - len(result.skipped)}, failed {failed}')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
