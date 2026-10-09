"""Exercise the actual pattern gate in an isolated, committed-source checkout."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[7]
HERE = Path(__file__).resolve().parent
STORE = '.bytedesk/design-patterns'


def command(args, cwd):
    result = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=120)
    return result.returncode, result.stdout, result.stderr


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    candidate = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    tracked = subprocess.check_output(['git', 'ls-tree', '-r', '--name-only', candidate,
                                      STORE, '.context'], cwd=ROOT, text=True).splitlines()
    original = {name: sha(ROOT / name) for name in tracked}
    report = {'recordedAt': datetime.now(timezone.utc).isoformat(), 'candidate': candidate,
              'platform': platform.platform(), 'python': platform.python_version(),
              'command': 'python ' + Path(__file__).relative_to(ROOT).as_posix(),
              'runnerSha256': sha(Path(__file__)), 'sourceHashes': original, 'cases': []}
    with tempfile.TemporaryDirectory(prefix='agentmux-pattern-negative-') as directory:
        fixture = Path(directory) / 'repo'
        rc, _, err = command(['git', '-c', 'core.autocrlf=false', 'clone', '--shared',
                              '--no-checkout', str(ROOT), str(fixture)], ROOT)
        if rc:
            raise RuntimeError('Isolated clone failed: ' + err)
        rc, _, err = command(['git', '-c', 'core.autocrlf=false', 'checkout', '--detach', candidate], fixture)
        if rc:
            raise RuntimeError('Isolated checkout failed: ' + err)
        review_path = fixture / STORE / 'review.json'
        registry_path = fixture / '.context/design-patterns.md'
        review_bytes = review_path.read_bytes()
        registry_bytes = registry_path.read_bytes()

        def run_case(name, expected=None):
            rc, out, err = command(['node', STORE + '/check.mjs', 'check', '--root', '.'], fixture)
            result = json.loads(out)
            passed = rc == 0 and result['ok'] if expected is None else (
                rc != 0 and not result['ok'] and any(expected in item for item in result['errors']))
            report['cases'].append({'name': name, 'exitCode': rc, 'expectedDiagnostic': expected,
                                    'result': result, 'stderr': err, 'passed': passed})

        run_case('unchanged committed candidate passes')
        review = json.loads(review_bytes)
        review['sourceDigest'] = '0' * 64
        review_path.write_text(json.dumps(review) + '\n', encoding='utf-8')
        run_case('stale review rejected', 'Review is stale or missing')
        review_path.write_bytes(review_bytes)

        text = registry_bytes.decode('utf-8')
        start = text.index('```json\n') + len('```json\n')
        end = text.index('\n```', start)
        registry = json.loads(text[start:end])
        entry = next(item for item in registry['entries'] if item['status'] == 'applied')
        entry['verificationEvidence'] = []
        registry_path.write_text(text[:start] + json.dumps(registry, indent=2) + text[end:], encoding='utf-8')
        # Refresh ONLY the disposable review so this case isolates missing evidence.
        rc, out, _ = command(['node', STORE + '/check.mjs', 'digest', '--root', '.'], fixture)
        if rc:
            raise RuntimeError('Fixture digest failed')
        review = json.loads(review_bytes)
        review['sourceDigest'] = json.loads(out)['sourceDigest']
        review_path.write_text(json.dumps(review) + '\n', encoding='utf-8')
        run_case('missing pattern evidence rejected', entry['id'] + ' verification: evidence files required')
        registry_path.write_bytes(registry_bytes)
        review = json.loads(review_bytes)
        review['findings'].append({'id': 'P01-NEGATIVE-FIXTURE', 'rule': 'DP001',
                                   'summary': 'Deliberate unresolved fixture finding.',
                                   'symbol': 'fixture', 'path': 'AGENTS.md'})
        review['rules']['DP001']['status'] = 'findings'
        review_path.write_text(json.dumps(review) + '\n', encoding='utf-8')
        run_case('unresolved finding rejected', 'P01-NEGATIVE-FIXTURE: violation needs repair')
        review_path.write_bytes(review_bytes)
        run_case('restored committed candidate passes')
    report['originalRecordsUnchanged'] = original == {name: sha(ROOT / name) for name in tracked}
    report['fixtureRemoved'] = not Path(directory).exists()
    report['status'] = 'passed' if all(case['passed'] for case in report['cases']) and report['originalRecordsUnchanged'] and report['fixtureRemoved'] else 'failed'
    report['limits'] = ['Tests structural rejection and history preservation; not semantic correctness of pattern review.',
                        'Mutations affect only a disposable checkout; no live review digest or findings were changed.']
    (HERE / 'pattern-negative-result.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'status': report['status'], 'cases': len(report['cases']), 'candidate': candidate}))
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
