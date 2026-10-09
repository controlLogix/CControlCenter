"""FAIL-54: genuine archived evidence and deliberately invalid in-memory copies."""
from copy import deepcopy
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import unittest
import sys

import check_conformance_evidence as gate

HERE = Path(__file__).resolve().parent
CANDIDATE = 'a2e9ee6d84a44a0b2f5783c3c0a3a613d50d0e41'
NATIVE = HERE / 'evidence/P01/native/a2e9ee6/linux/contracts.json'
WORKING = HERE / 'evidence/P01/controlled-execution-result.json'


class ConformanceEvidence(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = json.loads(NATIVE.read_text(encoding='utf-8'))
        cls.original = hashlib.sha256(NATIVE.read_bytes()).hexdigest()

    def tearDown(self):
        self.assertEqual(hashlib.sha256(NATIVE.read_bytes()).hexdigest(), self.original)

    def test_accepts_archived_native_report_against_actual_git_candidate(self):
        self.assertEqual(gate.validate(self.report,CANDIDATE,'linux'), [])

    def test_stale_hash_rejects_even_with_success_exit_code(self):
        changed = deepcopy(self.report)
        changed['sourceHashes']['tests/contracts/run.py'] = '0'*64
        self.assertEqual(changed['exitCode'], 0)
        self.assertIn('source inventory or hashes differ from committed candidate',gate.validate(changed,CANDIDATE,'linux'))

    def test_missing_required_source_cannot_reduce_the_scope(self):
        changed = deepcopy(self.report)
        del changed['sourceHashes']['tests/contracts/run.py']
        self.assertIn('source inventory or hashes differ from committed candidate',gate.validate(changed,CANDIDATE,'linux'))

    def test_skipped_test_rejects_even_with_success_summary(self):
        changed = deepcopy(self.report)
        changed['results'][0]['status'] = 'skipped'
        self.assertEqual((changed['exitCode'],changed['skips']), (0,0))
        self.assertIn('every test and subtest must pass',gate.validate(changed,CANDIDATE,'linux'))

    def test_skipped_environment_rejects_even_with_success_exit_code(self):
        changed = deepcopy(self.report)
        changed['environment']['status'] = 'skipped'
        self.assertEqual(changed['exitCode'], 0)
        self.assertTrue(any('skipped environments' in error for error in gate.validate(changed,CANDIDATE,'linux')))

    def test_linux_cannot_count_as_wsl_or_macos_evidence(self):
        for environment in ('wsl','macos'):
            with self.subTest(environment=environment):
                self.assertIn('report does not cover requested environment: '+environment,
                              gate.validate(self.report,CANDIDATE,environment))

    def test_build_and_mirror_claims_need_actual_hash_equality(self):
        for section,key in (('typescriptBuild','sourceComparison'),('sourceMirror','inputSha256')):
            changed = deepcopy(self.report)
            changed[section][key] = {}
            with self.subTest(section=section):
                self.assertTrue(gate.validate(changed,CANDIDATE,'linux'))

    def test_working_selection_and_uncommitted_inputs_cannot_qualify_old_candidate(self):
        raw = WORKING.read_bytes()
        working = json.loads(raw)
        errors = gate.validate(working,CANDIDATE,'wsl')
        self.assertIn('full conformance suite is required',errors)
        self.assertIn('source inventory or hashes differ from committed candidate',errors)
        self.assertEqual(WORKING.read_bytes(),raw)

    def test_skips_failures_and_mutable_build_flags_each_reject(self):
        for field,value in (('skips',1),('failures',1),('errors',1),('expectedFailures',1),
                            ('sourceUnchangedDuringRun',False),('typescriptBuildUnchangedDuringRun',False)):
            changed = deepcopy(self.report); changed[field] = value
            with self.subTest(field=field):
                self.assertTrue(gate.validate(changed,CANDIDATE,'linux'))

    def test_missing_compiled_output_and_repeated_test_id_reject(self):
        changed = deepcopy(self.report)
        del changed['typescriptBuild']['compiledJavaScriptHashes']['cli.js']
        self.assertTrue(gate.validate(changed,CANDIDATE,'linux'))
        changed = deepcopy(self.report)
        complete = [row for row in changed['results'] if not row.get('subtest',False)]
        complete[-1]['test'] = complete[0]['test']
        self.assertIn('test count or unique result identities do not match',gate.validate(changed,CANDIDATE,'linux'))

    def test_omitted_method_rejects_even_when_test_count_is_adjusted(self):
        changed = deepcopy(self.report)
        removed = next(row['test'] for row in changed['results'] if not row.get('subtest',False))
        changed['results'] = [row for row in changed['results'] if not row['test'].startswith(removed)]
        changed['testsRun'] -= 1
        self.assertEqual((changed['exitCode'],changed['selection']['fullSuite']), (0,True))
        errors = gate.validate(changed,CANDIDATE,'linux')
        self.assertIn('completed test methods differ from committed candidate suite',errors)
        self.assertNotIn('test count or unique result identities do not match',errors)

    def test_rejects_unsupported_dynamic_discovery(self):
        examples = [
            'def load_tests(loader, tests, pattern): return tests',
            'import unittest\nclass Base(unittest.TestCase):\n def test_one(self): pass\nclass Child(Base): pass',
            'import unittest\nclass Tests(unittest.TestCase):\n @generated\n def test_one(self): pass',
            'import unittest\nfor name in names: setattr(Tests, name, generated)',
            'from elsewhere import ImportedTests',
        ]
        for example in examples:
            with self.subTest(source=example), self.assertRaisesRegex(ValueError,'unsupported dynamic'):
                gate.test_methods('tests/contracts/test_example.py',example)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence',type=Path)
    args = parser.parse_args()
    inputs = (NATIVE,WORKING,Path(__file__),Path(gate.__file__))
    before = {str(p.relative_to(gate.ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs}
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(ConformanceEvidence)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    after = {str(p.relative_to(gate.ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs}
    passed = result.wasSuccessful() and result.testsRun > 0 and not result.skipped and before == after
    record = {'recordedAt':datetime.now(timezone.utc).isoformat(),'candidateCommit':CANDIDATE,
        'command':[sys.executable,*sys.argv],'testsRun':result.testsRun,'failures':len(result.failures),
        'errors':len(result.errors),'skips':len(result.skipped),'exitCode':0 if passed else 1,
        'inputHashes':before,'inputsUnchangedDuringRun':before==after,
        'limits':['Deliberate in-memory evidence mutations against archived native and working reports.',
                  'This proves conformance evidence rejection, not other suite acceptance or phase approval.']}
    if args.evidence:
        if args.evidence.resolve() in [p.resolve() for p in inputs]:
            parser.error('evidence output must not overwrite inputs')
        args.evidence.parent.mkdir(parents=True,exist_ok=True)
        args.evidence.write_text(json.dumps(record,indent=2)+'\n',encoding='utf-8')
    sys.exit(record['exitCode'])
