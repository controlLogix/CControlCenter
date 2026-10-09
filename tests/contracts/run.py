"""Run conformance and optionally save source-bound evidence without request bodies."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


class Result(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.records = []

    def addSuccess(self, test):
        super().addSuccess(test)
        self.records.append({'test': test.id(), 'status': 'passed'})

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self.records.append({'test': test.id(), 'status': 'failed'})

    def addError(self, test, err):
        super().addError(test, err)
        self.records.append({'test': test.id(), 'status': 'error'})

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self.records.append({'test': test.id(), 'status': 'skipped'})

    def addSubTest(self, test, subtest, err):
        super().addSubTest(test, subtest, err)
        self.records.append({'test': subtest.id(), 'status': 'failed' if err else 'passed', 'subtest': True})


def version(command):
    return subprocess.check_output(command, cwd=ROOT, text=True, stderr=subprocess.STDOUT, timeout=15).strip()


def hashes():
    paths = []
    for directory in ('contracts/v1', 'sdk/python', 'sdk/typescript', 'tests/contracts'):
        paths.extend(p for p in (ROOT / directory).rglob('*') if p.is_file() and p.suffix in ('.py', '.ts', '.json', '.toml', '.lock')
                     and not set(p.relative_to(ROOT).parts) & {'node_modules', 'dist', '__pycache__'})
    return {str(p.relative_to(ROOT)).replace('\\', '/'): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths)}


def typescript_build():
    cli = Path(os.environ.get('AGENTMUX_CONTRACT_TS_CLI', str(ROOT / 'sdk/typescript/dist/cli.js')))
    cache = cli.parent.parent
    repo = ROOT / 'sdk/typescript'
    names = ['package.json', 'package-lock.json', 'tsconfig.json']
    names += [str(p.relative_to(repo)).replace('\\', '/') for p in sorted((repo / 'src').rglob('*.ts'))]
    pairs = {}
    for name in names:
        actual = cache / name
        pairs[name] = {'repository': hashlib.sha256((repo / name).read_bytes()).hexdigest(),
                       'buildSource': hashlib.sha256(actual.read_bytes()).hexdigest() if actual.is_file() else None}
    compiled = {str(p.relative_to(cli.parent)).replace('\\', '/'): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted(cli.parent.rglob('*.js'))}
    return {'sourceComparison': pairs, 'allSourcesMatch': all(v['repository'] == v['buildSource'] for v in pairs.values()),
            'compiledJavaScriptHashes': compiled, 'cliPresent': cli.is_file()}


def mirror_hashes(root):
    paths = []
    for directory in ('contracts/v1', 'sdk/python'):
        paths.extend(p for p in (root / directory).rglob('*') if p.is_file()
                     and '__pycache__' not in p.parts and p.suffix != '.pyc')
    return {str(p.relative_to(root)).replace('\\', '/'): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths)}


def run(args, mirror, mirror_before):
    before = hashes()
    build_before = typescript_build()
    mirror_matches_before = mirror_before == mirror_hashes(ROOT)
    started = time.monotonic()
    loader = unittest.TestLoader()
    if args.match:
        loader.testNamePatterns = ['*' + args.match + '*']
    suite = loader.discover(str(HERE), pattern='test_*.py')
    result = unittest.TextTestRunner(verbosity=2, resultclass=Result).run(suite)
    unchanged = before == hashes()
    build_unchanged = build_before == typescript_build()
    mirror_unchanged = mirror_before == mirror_hashes(mirror)
    mirror_matches_after = mirror_before == mirror_hashes(ROOT)
    ok = (result.wasSuccessful() and result.testsRun > 0 and not result.skipped and not result.expectedFailures and unchanged
          and build_unchanged and build_before['allSourcesMatch'] and build_before['cliPresent']
          and mirror_matches_before and mirror_matches_after and mirror_unchanged)
    if args.evidence:
        python = os.environ.get('AGENTMUX_CONTRACT_PYTHON', sys.executable)
        node = os.environ.get('AGENTMUX_CONTRACT_NODE', 'node')
        record = {
            'recordedAt': datetime.now(timezone.utc).isoformat(),
            'sourceCommit': version(['git', 'rev-parse', 'HEAD']),
            'sourceBinding': 'Commit is the checkout base; sourceHashes identify exact working files. Compiled CLI has a separate digest.',
            'sourceHashes': before, 'sourceUnchangedDuringRun': unchanged,
            'typescriptBuild': build_before, 'typescriptBuildUnchangedDuringRun': build_unchanged,
            'sourceMirror': {'root': str(mirror), 'inputSha256': mirror_before,
                             'matchesRepositoryBefore': mirror_matches_before,
                             'matchesRepositoryAfter': mirror_matches_after, 'unchangedDuringRun': mirror_unchanged,
                             'lifetime': 'Owned TemporaryDirectory; removed after the report is saved.'},
            'environment': {'platform': platform.platform(), 'harnessPython': platform.python_version(),
                            'clientPython': version([python, '--version']), 'node': version([node, '--version'])},
            'command': 'python tests/contracts/run.py --evidence <output>',
            'selection': {'pattern': 'test_*.py', 'match': args.match, 'fullSuite': args.match is None},
            'durationSeconds': round(time.monotonic() - started, 3), 'exitCode': 0 if ok else 1,
            'testsRun': result.testsRun, 'failures': len(result.failures), 'errors': len(result.errors),
            'skips': len(result.skipped), 'expectedFailures': len(result.expectedFailures), 'results': result.records,
            'limitations': [
                'Local subprocess protocol, schema, canonical-byte and signature fixtures only; no live NATS, enrollment, current-grant lookup or production authorization qualification.',
                'Ephemeral test signing seeds and request bodies are not stored in this record.',
                'Strict raw UTF-8 is tested at the CLI byte boundary. Payload-size unit checks belong to each SDK because nested JSON escaping changes outer CLI frame size.',
                'A passing local environment does not qualify unexecuted macOS, CI, provider or terminal environments.'
            ]}
        args.evidence.parent.mkdir(parents=True, exist_ok=True)
        args.evidence.write_text(json.dumps(record, indent=2) + '\n', encoding='utf-8', newline='\n')
    return 0 if ok else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence', type=Path)
    parser.add_argument('--match', help='Run test names containing this text; partial evidence stays labeled.')
    args = parser.parse_args()
    saved = {key: os.environ.get(key) for key in ('AGENTMUX_CONTRACT_SOURCE_ROOT', 'AGENTMUX_SCHEMA_DIR')}
    try:
        with tempfile.TemporaryDirectory(prefix='agentmux-contract-inputs-') as directory:
            mirror = Path(directory)
            for relative in ('contracts/v1', 'sdk/python'):
                shutil.copytree(ROOT / relative, mirror / relative, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
            copied = mirror_hashes(mirror)
            if copied != mirror_hashes(ROOT):
                raise RuntimeError('Native fixture source copy does not match the repository')
            os.environ['AGENTMUX_CONTRACT_SOURCE_ROOT'] = str(mirror)
            os.environ['AGENTMUX_SCHEMA_DIR'] = str(mirror / 'contracts/v1/schemas')
            return run(args, mirror, copied)
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


if __name__ == '__main__':
    sys.exit(main())
