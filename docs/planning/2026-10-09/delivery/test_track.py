"""Coverage and dependency checks must reject incomplete delivery records."""
import unittest
import track


class TrackingTests(unittest.TestCase):
    def setUp(self):
        self.data = track.read(track.STATE)

    def test_complete_inventory_is_consistent(self):
        self.assertTrue(track.validate(self.data))

    def test_missing_work_is_rejected(self):
        self.data['tasks'] = [t for t in self.data['tasks'] if t['id'] != 'P02-T01']
        with self.assertRaisesRegex(AssertionError, 'work coverage'):
            track.validate(self.data)

    def test_removed_phase_criterion_is_rejected(self):
        self.data['epics'][0]['acceptanceCriteria'].pop()
        with self.assertRaisesRegex(AssertionError, 'criteria'):
            track.validate(self.data)

    def test_missing_catalog_record_is_rejected(self):
        task = next(t for t in self.data['tasks'] if t.get('catalogRecordIds'))
        task['catalogRecordIds'] = []
        with self.assertRaisesRegex(AssertionError, 'catalog coverage'):
            track.validate(self.data)

    def test_predecessor_cannot_be_bypassed(self):
        task = next(t for t in self.data['tasks'] if t['id'] == 'P02-T01')
        task['status'] = 'in_progress'
        with self.assertRaisesRegex(AssertionError, 'predecessor'):
            track.validate(self.data)

    def test_cycle_is_rejected(self):
        # Isolate dependency-cycle validation from the live board's progress.
        for row in self.data['tasks']:
            row['status'] = 'planned'
        task = next(t for t in self.data['tasks'] if t['id'] == 'P00-T06')
        task['dependsOn'] = ['P00-T01']
        with self.assertRaisesRegex(AssertionError, 'cycle'):
            track.validate(self.data)

    def test_duplicate_behavior_owner_is_rejected(self):
        source = next(t for t in self.data['tasks'] if t.get('behaviorCheckIds'))
        target = next(t for t in self.data['tasks'] if t['id'] == 'P00-T02')
        target['behaviorCheckIds'].append(source['behaviorCheckIds'][0])
        with self.assertRaisesRegex(AssertionError, 'duplicate component behavior owner'):
            track.validate(self.data)

    def test_host_qualification_cannot_be_moved_before_host_implementation(self):
        owner = next(t for t in self.data['tasks'] if 'REPO-01-C01' in t.get('behaviorCheckIds', []))
        owner['behaviorCheckIds'].remove('REPO-01-C01')
        earlier = next(t for t in self.data['tasks'] if t['id'] == 'P00-T06')
        earlier['behaviorCheckIds'].append('REPO-01-C01')
        with self.assertRaisesRegex(AssertionError, 'qualification phase mismatch'):
            track.validate(self.data)
