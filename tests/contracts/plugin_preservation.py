"""Run the maintained plugin's original and added tests in private local state."""
import argparse
import ast
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import signal
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / 'plugins/agentmux-orchestration'
SUITES = {
    'dashboard/test_orchestration_plugin.py': 16,
    'dashboard/test_plugin_skills.py': 4,
    'plugins/agentmux-orchestration/tests/test_hook_mcp.py': 13,
    'plugins/agentmux-orchestration/tests/test_packaging.py': 3,
}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_hashes():
    paths = [p for p in PACKAGE.rglob('*') if p.is_file()
             and '__pycache__' not in p.parts and p.suffix != '.pyc']
    if len(paths) != 22:
        raise ValueError('Expected exactly 22 maintained package files')
    paths += list((ROOT / 'taskmgmt').rglob('*.py'))
    paths += [ROOT / p for p in SUITES]
    paths += [ROOT / 'dashboard/auth.json', Path(__file__), ROOT / 'tests/contracts/ci.py']
    return {p.relative_to(ROOT).as_posix(): digest(p) for p in sorted(set(paths))}


def expected_method_ids(index, path):
    """These four suites declare their methods directly; do not accept invented IDs."""
    tree = ast.parse((ROOT / path).read_text(encoding='utf-8'))
    methods = {f'plugin_preservation_{index}.{node.name}.{method.name}'
               for node in tree.body if isinstance(node, ast.ClassDef)
               for method in node.body if isinstance(method, ast.FunctionDef)
               and method.name.startswith('test_')}
    if len(methods) != SUITES[path]:
        raise ValueError('Unsupported or changed test discovery: ' + path)
    return methods


class RecordedResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.methods = []
        self.bad = set()

    def addSuccess(self, test):
        super().addSuccess(test)
        if test.id() not in self.bad:
            self.methods.append({'id': test.id(), 'status': 'passed'})

    def record(self, test, status):
        self.bad.add(test.id())
        self.methods.append({'id': test.id(), 'status': status})

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self.record(test, 'failed')

    def addError(self, test, err):
        super().addError(test, err)
        self.record(test, 'error')

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self.record(test, 'skipped')

    def addExpectedFailure(self, test, err):
        super().addExpectedFailure(test, err)
        self.record(test, 'expected-failure')

    def addUnexpectedSuccess(self, test):
        super().addUnexpectedSuccess(test)
        self.record(test, 'unexpected-success')

    def addSubTest(self, test, subtest, err):
        super().addSubTest(test, subtest, err)
        if err is not None:
            self.record(test, 'failed-subtest')


def worker(evidence):
    before = source_hashes()
    report = {'recordedAt': datetime.now(timezone.utc).isoformat(),
              'platform': platform.platform(), 'python': platform.python_version(),
              'sourceHashes': before, 'suites': [], 'exitCode': 1,
              'limits': ['Offline plugin compatibility, not provider inference or native Windows hook qualification.']}
    for index, (path, count) in enumerate(SUITES.items()):
        spec = importlib.util.spec_from_file_location(f'plugin_preservation_{index}', ROOT / path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        suite = unittest.defaultTestLoader.loadTestsFromModule(module)
        result = unittest.TextTestRunner(stream=sys.stdout, verbosity=2,
                                        resultclass=RecordedResult).run(suite)
        methods = result.methods
        passed = (result.testsRun == count and len(methods) == count
                  and {m['id'] for m in methods} == expected_method_ids(index, path)
                  and all(m['status'] == 'passed' for m in methods)
                  and result.wasSuccessful() and not result.skipped
                  and not result.expectedFailures and not result.unexpectedSuccesses)
        report['suites'].append({'path': path, 'expectedTests': count,
                                'tests': result.testsRun, 'passed': passed, 'methods': methods})
    after = source_hashes()
    report['sourceHashesAfter'] = after
    report['sourceUnchangedDuringRun'] = before == after
    report['tests'] = sum(s['tests'] for s in report['suites'])
    report['exitCode'] = 0 if before == after and all(s['passed'] for s in report['suites']) else 1
    evidence.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    return report['exitCode']


def admitted(report, expected):
    try:
        return (report.get('exitCode') == 0 and report.get('tests') == 36
            and report.get('sourceHashes') == report.get('sourceHashesAfter') == expected
            and report.get('sourceUnchangedDuringRun') is True
            and [(s.get('path'), s.get('tests')) for s in report.get('suites', [])] == list(SUITES.items())
            and all(s.get('passed') is True and len(s.get('methods', [])) == count
                    and {m['id'] for m in s['methods']} == expected_method_ids(index, s['path'])
                    and all(m.get('status') == 'passed' for m in s['methods'])
                    for index, (s, count) in enumerate(zip(report.get('suites', []), SUITES.values()))))
    except (AttributeError, KeyError, TypeError, ValueError):
        return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--worker', action='store_true')
    args = parser.parse_args()
    evidence = args.evidence.resolve()
    log = evidence.with_suffix('.log')
    if evidence.is_relative_to(ROOT) or evidence.exists() or (not args.worker and log.exists()):
        parser.error('Evidence must be a fresh path outside the repository')
    evidence.parent.mkdir(parents=True, exist_ok=True)
    if args.worker:
        return worker(evidence)
    before = source_hashes()
    with tempfile.TemporaryDirectory(prefix='agentmux-plugin-preservation-') as directory:
        home = Path(directory)
        env = {'PATH': os.defpath, 'HOME': str(home), 'TMPDIR': str(home),
               'AGENTMUX_HOME': str(home/'state'), 'CODEX_HOME': str(home/'codex'),
               'CLAUDE_CONFIG_DIR': str(home/'claude'), 'XDG_CONFIG_HOME': str(home/'config'),
               'XDG_CACHE_HOME': str(home/'cache'), 'XDG_DATA_HOME': str(home/'data'),
               'AGENTMUX_PLUGIN_ROOT': str(PACKAGE), 'PYTHONDONTWRITEBYTECODE': '1',
               'PYTHONNOUSERSITE': '1', 'GIT_CONFIG_NOSYSTEM': '1',
               'GIT_CONFIG_GLOBAL': str(home/'gitconfig')}
        with log.open('x', encoding='utf-8') as output:
            process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()),
                                        '--worker', '--evidence', str(evidence)],
                                       cwd=ROOT, env=env, stdout=output, stderr=subprocess.STDOUT,
                                       start_new_session=True)
            try:
                code = process.wait(timeout=180)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
                code = 1
    if not evidence.is_file():
        evidence.write_text(json.dumps({'exitCode': 1, 'failure': 'Worker did not produce evidence',
                                       'sourceHashes': before}) + '\n', encoding='utf-8')
    report = json.loads(evidence.read_text(encoding='utf-8'))
    accepted = code == 0 and admitted(report, before) and before == source_hashes()
    report.update(logSha256=digest(log), isolatedHomeRemoved=not home.exists(),
                  exitCode=0 if accepted else 1)
    evidence.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'tests': report.get('tests', 0), 'exitCode': report['exitCode'], 'report': str(evidence)}))
    return report['exitCode']


if __name__ == '__main__':
    sys.exit(main())
