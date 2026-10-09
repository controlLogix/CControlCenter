"""Exercise preservation guards on disposable planning copies, never live manifests."""
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import tempfile


HERE = Path(__file__).resolve().parent
PLAN = HERE.parents[2]
ROOT = PLAN.parents[2]


def main():
    checker = PLAN / 'verify-component-coverage.py'
    spec = importlib.util.spec_from_file_location('coverage_check', checker)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    inventory = json.loads((PLAN / 'component-inventory.json').read_text(encoding='utf-8'))
    names = ['component-inventory.json', 'phases.json', 'implementation-plan.md',
             'verification-matrix.json', 'verification-matrix.md', 'gate-record.template.json',
             'source-surface-index.json', *inventory['manifests']]
    hashes = {n: hashlib.sha256((PLAN / n).read_bytes()).hexdigest() for n in names}
    hashes['verify-component-coverage.py'] = hashlib.sha256(checker.read_bytes()).hexdigest()
    cases = []
    with tempfile.TemporaryDirectory(prefix='agentmux-preservation-') as directory:
        copied = Path(directory)
        for name in names:
            shutil.copyfile(PLAN / name, copied / name)
        baseline = module.check(root=ROOT, here=copied)
        assert baseline['ok'], baseline['errors']

        path = copied / 'component-inventory.json'
        original = path.read_bytes()
        mutated = json.loads(original)
        assert any(row['path'] == 'VERSION' for row in mutated['files'])
        mutated['files'] = [row for row in mutated['files'] if row['path'] != 'VERSION']
        path.write_text(json.dumps(mutated), encoding='utf-8')
        result = module.check(root=ROOT, here=copied)
        expected = "New/unmapped source or missing inventory file: ['VERSION']"
        assert not result['ok'] and expected in result['errors'], result
        cases.append({'scenarioId': 'FAIL-49', 'status': 'passed',
                      'mutation': 'Remove VERSION from copied inventory while leaving its source and component owner intact.',
                      'requiredRejection': expected, 'actualResult': result})
        path.write_bytes(original)

        path = copied / 'component-audit-harness.json'
        mutated = json.loads(path.read_text(encoding='utf-8'))
        component = next(c for c in mutated['components'] if c['id'] == 'HAR-01')
        component['disposition'] = 'replace'
        component['replacementReason'] = None
        path.write_text(json.dumps(mutated), encoding='utf-8')
        result = module.check(root=ROOT, here=copied)
        expected = 'HAR-01: replacement requires a reason'
        assert not result['ok'] and expected in result['errors'], result
        cases.append({'scenarioId': 'FAIL-53', 'status': 'passed',
                      'mutation': 'Change HAR-01 to replace in the copied manifest without a replacement reason.',
                      'requiredRejection': expected, 'actualResult': result})
    assert hashes == {n: hashlib.sha256((PLAN / n).read_bytes()).hexdigest() for n in hashes}, 'Source manifests changed during the check'
    record = {
        'recordedAt': datetime.now(timezone.utc).isoformat(),
        'sourceCommit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        'sourceBinding': 'Commit is the checkout base; sourceHashes identify the exact working files exercised, including uncommitted planning changes.',
        'sourceHashes': hashes,
        'harnessSha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'command': 'python docs/planning/2026-10-09/delivery/evidence/P00/check_preservation.py',
        'environment': {'platform': __import__('platform').platform(), 'python': __import__('sys').version},
        'exitCode': 0, 'baseline': baseline, 'cases': cases,
        'limitations': ['Static coverage guards only; these checks do not execute migration or prove runtime behavior preservation.',
                       'Codex must inspect behavior, alternatives and full authorized scope. A nonempty replacement reason alone cannot authorize a capability reduction.',
                       'Later-phase FAIL-49 and FAIL-53 runtime comparisons remain required; these are P00 structural negative checks.']}
    output = HERE / 'preservation-negative-results.json'
    output.write_text(json.dumps(record, indent=2) + '\n', encoding='utf-8', newline='\n')
    print(json.dumps({'ok': True, 'cases': [c['scenarioId'] for c in cases], 'output': str(output)}, indent=2))


if __name__ == '__main__':
    main()
