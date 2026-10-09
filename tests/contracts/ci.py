"""Run portable P01 checks with locked dependencies and fresh, source-bound evidence."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import signal
import subprocess
import sys
import tarfile
import tempfile
import time
import unittest
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
RELEASE = 'https://github.com/nats-io/nats-server/releases/download/v2.15.0'
# Reviewed against that release's SHA256SUMS on October 9, 2026.
ARCHIVE_SHA256 = {
    'darwin-amd64': '5bd8b59ca5bf93fab3da2c5843cf564cd6e2e291e22ae3b861746e7ebe259b95',
    'darwin-arm64': 'e1c4e22d70bd44abfa0bcb3c16f7cf0c66f648c2e728c58924e8a1ce88913cc8',
    'linux-amd64': '5d2c51caca950333aba84911df7d377f826f3a59ec36061c6539105084f65c92',
    'linux-arm64': 'cdc208f5a3f42963a52b6ab06ef65626bb870315dc936e26ba571780c6351112',
}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_hashes():
    paths = []
    for name in ('contracts/v1', 'sdk', 'tests/contracts', 'tests/storage', 'tests/leaf'):
        paths.extend(p for p in (ROOT / name).rglob('*') if p.is_file()
                     and not set(p.parts) & {'node_modules', 'dist', '__pycache__'}
                     and p.suffix != '.pyc')
    paths += [ROOT / 'hub/requirements.lock', ROOT / '.github/workflows/contracts.yml']
    for name in ('docs/planning/2026-10-09', '.bytedesk/design-patterns', '.context'):
        paths.extend(p for p in (ROOT / name).rglob('*') if p.is_file()
                     and not set(p.parts) & {'evidence', '__pycache__', 'node_modules'}
                     and p.suffix in ('.py', '.json', '.md', '.mjs'))
    return {p.relative_to(ROOT).as_posix(): digest(p) for p in sorted(paths)}


def download(url):
    # Only fixed official release URLs are used; no token or user-supplied URL.
    with urllib.request.urlopen(url, timeout=60) as response:
        return response.read()


def broker(workspace, report):
    system = {'Linux': 'linux', 'Darwin': 'darwin'}[platform.system()]
    arch = {'x86_64': 'amd64', 'AMD64': 'amd64', 'arm64': 'arm64', 'aarch64': 'arm64'}[platform.machine()]
    asset = f'nats-server-v2.15.0-{system}-{arch}.tar.gz'
    sums = download(f'{RELEASE}/SHA256SUMS').decode('ascii')
    matches = [line.split()[0] for line in sums.splitlines() if line.split()[-1].lstrip('*') == asset]
    if len(matches) != 1 or matches[0] != ARCHIVE_SHA256[f'{system}-{arch}']:
        raise ValueError('Release checksum missing or ambiguous')
    archive = workspace / asset
    archive.write_bytes(download(f'{RELEASE}/{asset}'))
    if digest(archive) != matches[0]:
        raise ValueError('Release checksum mismatch')
    target = workspace / 'nats-server'
    with tarfile.open(archive, 'r:gz') as package:
        members = [m for m in package.getmembers() if m.name == asset[:-7] + '/nats-server' and m.isfile()]
        if len(members) != 1:
            raise ValueError('Release binary missing or ambiguous')
        with package.extractfile(members[0]) as source:
            target.write_bytes(source.read())
    target.chmod(0o700)
    version = subprocess.check_output([str(target), '--version'], text=True, timeout=15).strip()
    if version != 'nats-server: v2.15.0':
        raise ValueError('Unexpected broker version')
    report['broker'] = {'version': version, 'archiveUrl': f'{RELEASE}/{asset}',
                        'checksumUrl': f'{RELEASE}/SHA256SUMS', 'archiveSha256': matches[0],
                        'binarySha256': digest(target), 'checksumVerified': True}
    return target


def negative_fixture(evidence):
    """Prove a malformed positive fixture fails the real cross-language test."""
    import test_conformance as conformance
    original = conformance.VECTORS
    before = digest(original)
    fixture = json.loads(original.read_text(encoding='utf-8'))['plugin-manifest']
    del fixture['packageId']
    with tempfile.TemporaryDirectory(prefix='agentmux-negative-fixture-') as directory:
        mutant = Path(directory) / 'invalid-positive.json'
        mutant.write_text(json.dumps({'plugin-manifest': fixture}), encoding='utf-8')
        conformance.VECTORS = mutant
        try:
            suite = unittest.TestSuite([conformance.Conformance('test_all_schema_examples')])
            result = unittest.TestResult()
            suite.run(result)
        finally:
            conformance.VECTORS = original
    observed = [dict(getattr(test, 'params', {})) for test, _ in result.failures]
    expected = [{'client':'python','schema':'plugin-manifest'}, {'client':'typescript','schema':'plugin-manifest'}]
    ok = (result.testsRun == 1 and observed == expected and not result.errors and not result.skipped
          and not result.expectedFailures and before == digest(original))
    record = {'status':'passed' if ok else 'failed', 'mutation':'Removed packageId from a copied positive plugin-manifest fixture.',
              'expectedAssertionFailures':expected, 'observedAssertionFailures':observed,
              'errorCount':len(result.errors), 'skipCount':len(result.skipped),
              'originalFixtureSha256':before, 'originalFixtureUnchanged':before==digest(original),
              'sourceHashes':source_hashes(), 'limits':['Isolated negative check; no fixture or SDK source was changed.']}
    evidence.mkdir(parents=True, exist_ok=True)
    (evidence/'negative-fixture.json').write_text(json.dumps(record,indent=2)+'\n',encoding='utf-8')
    return 0 if ok else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--negative-fixture', action='store_true')
    args = parser.parse_args()
    if args.negative_fixture:
        return negative_fixture(args.evidence.resolve())
    if args.workspace is None:
        parser.error('--workspace is required for the full run')
    args.workspace = args.workspace.resolve()
    args.evidence = args.evidence.resolve()
    args.workspace.mkdir(parents=True, exist_ok=True)
    args.evidence.mkdir(parents=True, exist_ok=True)
    if any(args.workspace.iterdir()):
        parser.error('Build workspace must be empty to prevent stale compiled files')
    if any(args.evidence.iterdir()):
        parser.error('Evidence directory must be empty to prevent stale results')
    report = {'recordedAt': datetime.now(timezone.utc).isoformat(), 'checks': [],
              'platform': platform.platform(), 'python': platform.python_version(),
              'sourceHashes': source_hashes(), 'exitCode': 1,
              'limits': ['Native host execution only; this is not WSL proof or phase approval.',
                         'Broker fixtures do not establish production enrollment or final bilateral release acceptance.']}
    env = os.environ.copy()

    def run(name, command, cwd=ROOT, timeout=300):
        started = time.monotonic()
        item = {'name': name, 'command': command, 'exitCode': 1}
        report['checks'].append(item)
        process = None
        try:
            process = subprocess.Popen(command, cwd=cwd, env=env, start_new_session=True)
            item['exitCode'] = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
            item['failure'] = 'timeout'
        item['seconds'] = round(time.monotonic() - started, 3)
        return item['exitCode'] == 0

    try:
        report['sourceCommit'] = subprocess.check_output(['git','rev-parse','HEAD'], cwd=ROOT, text=True, timeout=15).strip()
        report['node'] = subprocess.check_output(['node','--version'], text=True, timeout=15).strip()
        report['npm'] = subprocess.check_output(['npm','--version'], text=True, timeout=15).strip()
        if not run('locked-python-dependencies', [sys.executable,'-m','pip','install','-r',str(ROOT/'sdk/python/requirements.lock'),'-r',str(ROOT/'hub/requirements.lock')]):
            raise RuntimeError('Python setup failed')
        builds = {}
        for name, relative in (('contracts','sdk/typescript'),('storage','tests/storage/typescript')):
            build = args.workspace / name
            shutil.copytree(ROOT / relative, build, dirs_exist_ok=True, ignore=shutil.ignore_patterns('node_modules','dist','__pycache__'))
            if not run(name+'-dependencies',['npm','ci','--ignore-scripts','--no-audit','--no-fund'],build) or not run(name+'-build',['npm','run','build'],build):
                raise RuntimeError('TypeScript setup failed')
            builds[name] = build
        server = broker(args.workspace, report)
        env.update(PYTHONPATH=str(ROOT/'sdk/python'), AGENTMUX_CONTRACT_PYTHON=sys.executable,
                   AGENTMUX_CONTRACT_TS_CLI=str(builds['contracts']/'dist/cli.js'),
                   AGENTMUX_SCHEMA_DIR=str(ROOT/'contracts/v1/schemas'),
                   AGENTMUX_CONTRACT_EXAMPLES=str(ROOT/'tests/contracts/vectors/valid-examples.json'),
                   AGENTMUX_STORAGE_TS_CLIENT=str(builds['storage']/'dist/client.js'),
                   AGENTMUX_STORAGE_SERVER=str(server), AGENTMUX_LEAF_SERVER=str(server),
                   AGENTMUX_EVIDENCE_DIR=str(args.evidence))
        run('python-sdk-units',[sys.executable,'-m','unittest','discover','-s','sdk/python/tests','-v'])
        run('typescript-sdk-units',['npm','test'],builds['contracts'])
        run('cross-language-contracts',[sys.executable,'tests/contracts/run.py','--evidence',str(args.evidence/'contracts.json')])
        run('negative-contract-fixture',[sys.executable,'tests/contracts/ci.py','--negative-fixture','--evidence',str(args.evidence)])
        for suite, output in (('storage','storage-result.json'),('leaf','leaf-result.json'),('leaf/signed','signed-leaf-result.json')):
            source = args.evidence / output
            if source.exists():
                raise RuntimeError('Fixture evidence already exists before execution')
            script = 'tests/leaf/signed_run.py' if suite == 'leaf/signed' else f'tests/{suite}/run.py'
            run(suite,[sys.executable,script])
            if not source.is_file():
                report['checks'].append({'name':suite+'-fresh-evidence','exitCode':1})
        delivery = 'docs/planning/2026-10-09/delivery'
        run('tracker-tests',[sys.executable,'-m','unittest','discover','-s',delivery,'-p','test_track.py','-v'])
        run('regression-preservation',[sys.executable,delivery+'/check_regressions.py','--self-test'])
        run('component-preservation',[sys.executable,'docs/planning/2026-10-09/verify-component-coverage.py'])
        run('pattern-review',['node','.bytedesk/design-patterns/check.mjs','check','--root','.'])
        report['sourceUnchangedDuringRun'] = report['sourceHashes'] == source_hashes()
        report['exitCode'] = 0 if report['sourceUnchangedDuringRun'] and all(c['exitCode']==0 for c in report['checks']) else 1
    except Exception as exc:
        report['failureType'] = type(exc).__name__
    finally:
        (args.evidence/'ci-result.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    return report['exitCode']


if __name__ == '__main__':
    sys.exit(main())
