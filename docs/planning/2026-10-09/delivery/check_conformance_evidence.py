"""Admit only full conformance reports bound to an explicit committed candidate."""
import argparse
import ast
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[4]
HEX = re.compile(r'[0-9a-f]{64}\Z')
SOURCE_ROOTS = ('contracts/v1/', 'sdk/python/', 'sdk/typescript/', 'tests/contracts/')
DRAFT_ROOT = 'docs/planning/2026-10-09/delivery/contracts/'


def test_methods(path, content):
    """Support the current explicit TestCase classes, not generated discovery."""
    tree = ast.parse(content, filename=path)
    prefix = PurePosixPath(path).stem
    ids = set()
    known_classes = {node.name for node in tree.body if isinstance(node,ast.ClassDef)}
    unsupported = 'unsupported dynamic test discovery in ' + path
    main_guard = ast.dump(ast.parse("if __name__ == '__main__':\n unittest.main()\n").body[0])
    for node in ast.walk(tree):
        if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)) and node.name == 'load_tests':
            raise ValueError(unsupported)
        if isinstance(node,ast.Call) and isinstance(node.func,ast.Name) and node.func.id in ('exec','eval','setattr','__import__'):
            raise ValueError(unsupported)
    for node in tree.body:
        if isinstance(node,ast.If) and ast.dump(node) == main_guard:
            continue
        if isinstance(node,(ast.Import,ast.ImportFrom)):
            # Imported TestCase classes could be collected alongside local classes.
            if isinstance(node,ast.ImportFrom):
                allowed = {'pathlib':{'Path'}, 'datetime':{'datetime'},
                           'test_state_models':{'request'},
                           'fake_execution':{'ResponsePlan','FakeProvider','FakeWorker'}}
                if node.level or node.module not in allowed or any(alias.asname or alias.name not in allowed[node.module] for alias in node.names):
                    raise ValueError(unsupported)
            continue
        if isinstance(node,ast.Assign):
            if not all(isinstance(target,ast.Name) and target.id.isupper() for target in node.targets):
                raise ValueError(unsupported)
            if any(isinstance(value,ast.Name) and value.id in known_classes for value in ast.walk(node.value)):
                raise ValueError(unsupported)
            continue
        if isinstance(node,ast.Expr) and isinstance(node.value,ast.Constant) and isinstance(node.value.value,str):
            continue
        if isinstance(node,ast.FunctionDef):
            if node.decorator_list or node.name.startswith('test'):
                raise ValueError(unsupported)
            continue
        if not isinstance(node,ast.ClassDef):
            raise ValueError(unsupported)
        is_case = len(node.bases) == 1 and ast.dump(node.bases[0]) == ast.dump(ast.Attribute(value=ast.Name(id='unittest',ctx=ast.Load()),attr='TestCase',ctx=ast.Load()))
        if not is_case:
            if node.decorator_list or node.keywords or any(not isinstance(base,ast.Name) or base.id != 'Exception' for base in node.bases):
                raise ValueError(unsupported)
            if any(isinstance(child,(ast.FunctionDef,ast.AsyncFunctionDef)) and child.name.startswith('test') for child in node.body):
                raise ValueError(unsupported)
            continue
        if node.decorator_list or node.keywords:
            raise ValueError(unsupported)
        methods = set()
        for child in node.body:
            if isinstance(child,ast.Expr) and isinstance(child.value,ast.Constant):
                continue
            if not isinstance(child,ast.FunctionDef):
                raise ValueError(unsupported)
            if child.name.startswith('test'):
                if child.decorator_list or child.name in methods:
                    raise ValueError(unsupported)
                methods.add(child.name)
                identity = prefix+'.'+node.name+'.'+child.name
                if identity in ids:
                    raise ValueError(unsupported)
                ids.add(identity)
        if not methods:
            raise ValueError(unsupported)
    if not ids:
        raise ValueError('no supported concrete test methods in ' + path)
    return ids


def git(*args, input=None):
    return subprocess.check_output(['git', *args], cwd=ROOT, input=input, timeout=30)


def inventories(candidate):
    """Derive required files from Git, independently of the report's claims."""
    if not re.fullmatch(r'[0-9a-f]{40}', candidate):
        raise ValueError('candidate must be a complete lowercase Git commit ID')
    resolved = git('rev-parse', '--verify', candidate + '^{commit}').decode().strip()
    if resolved != candidate:
        raise ValueError('candidate does not identify a commit')
    tree = {}
    for row in git('ls-tree', '-rz', '--full-tree', candidate).split(b'\0'):
        if not row:
            continue
        header, path = row.split(b'\t', 1)
        mode, kind, oid = header.decode().split()
        path = path.decode('utf-8')
        if path.startswith(SOURCE_ROOTS) or path in (DRAFT_ROOT+'state-machines.json', DRAFT_ROOT+'model-examples.json'):
            if mode not in ('100644', '100755') or kind != 'blob':
                raise ValueError('contract input must be a regular committed file: ' + path)
            if set(PurePosixPath(path).parts) & {'node_modules', 'dist', '__pycache__'} or path.endswith('.pyc'):
                continue
            tree[path] = oid
    source = {p for p in tree if PurePosixPath(p).suffix in ('.py','.ts','.json','.toml','.lock')}
    mirror = {p for p in tree if p.startswith(('contracts/v1/','sdk/python/'))}
    build = {p for p in tree if p in ('sdk/typescript/package.json', 'sdk/typescript/package-lock.json',
                                    'sdk/typescript/tsconfig.json') or p.startswith('sdk/typescript/src/') and p.endswith('.ts')}
    paths = sorted(source | mirror | build)
    if not paths or 'tests/contracts/run.py' not in source:
        raise ValueError('candidate lacks the supported conformance runner')
    # One batch reads exact Git bytes, including files absent from the worktree.
    raw = git('cat-file', '--batch', input=('\n'.join(tree[p] for p in paths)+'\n').encode())
    offset, hashes, expected_tests = 0, {}, set()
    for path in paths:
        end = raw.index(b'\n', offset)
        oid, kind, size = raw[offset:end].decode().split()
        size = int(size); offset = end + 1
        if oid != tree[path] or kind != 'blob':
            raise ValueError('unexpected Git batch response')
        content = raw[offset:offset+size]; offset += size
        if len(content) != size or raw[offset:offset+1] != b'\n':
            raise ValueError('incomplete Git batch response')
        offset += 1
        hashes[path] = hashlib.sha256(content).hexdigest()
        if path.startswith('tests/contracts/') and PurePosixPath(path).name.startswith('test_') and path.endswith('.py'):
            if len(PurePosixPath(path).parts) != 3:
                raise ValueError('nested test discovery is not supported')
            expected_tests.update(test_methods(path,content))
    if offset != len(raw):
        raise ValueError('extra Git batch response')
    return ({p:hashes[p] for p in sorted(source)},
            {p:hashes[p] for p in sorted(mirror)},
            {p.removeprefix('sdk/typescript/'):hashes[p] for p in sorted(build)}, expected_tests)


def validate(report, candidate, environment):
    """Return review findings; passing is scoped to this one report format."""
    source, mirror, build, expected_tests = inventories(candidate)
    errors = []
    def check(ok, message):
        if not ok: errors.append(message)
    if not isinstance(report, dict):
        return ['conformance report must be an object']
    for field in ('exitCode','failures','errors','skips','expectedFailures'):
        check(type(report.get(field)) is int and report[field] == 0, field + ' must be integer zero')
    check(type(report.get('testsRun')) is int and report['testsRun'] > 0, 'testsRun must be positive')
    check(report.get('selection') == {'pattern':'test_*.py','match':None,'fullSuite':True}, 'full conformance suite is required')
    check(report.get('sourceHashes') == source, 'source inventory or hashes differ from committed candidate')
    for field in ('sourceUnchangedDuringRun','typescriptBuildUnchangedDuringRun'):
        check(report.get(field) is True, field + ' must be true')
    base = report.get('sourceCommit')
    if isinstance(base, str) and re.fullmatch(r'[0-9a-f]{40}', base):
        result = subprocess.run(['git','merge-base','--is-ancestor',base,candidate],cwd=ROOT,
                                stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=30)
        check(result.returncode == 0, 'recorded checkout base is not an ancestor of candidate')
    else:
        errors.append('recorded checkout base is invalid')
    env = report.get('environment')
    if not isinstance(env, dict) or set(env) != {'platform','harnessPython','clientPython','node'}:
        errors.append('environment fields are missing or unsupported; skipped environments cannot qualify')
    else:
        check(all(isinstance(v,str) and v.strip() for v in env.values()), 'environment values must be recorded')
        platform = str(env['platform']).lower()
        observed = ('wsl' if 'linux' in platform and ('microsoft' in platform or 'wsl' in platform)
                    else 'linux' if platform.startswith('linux-') else 'macos' if platform.startswith('macos-') else 'unsupported')
        check(observed == environment, 'report does not cover requested environment: ' + environment)
    rows = report.get('results')
    if not isinstance(rows,list) or not rows:
        errors.append('individual test results are required')
    else:
        check(all(isinstance(row,dict) and row.get('status') == 'passed'
                  and isinstance(row.get('test'),str) and row['test'].strip() for row in rows), 'every test and subtest must pass')
        complete = [row.get('test') for row in rows if isinstance(row,dict) and not row.get('subtest',False)]
        check(len(complete) == report.get('testsRun') and len(set(complete)) == len(complete), 'test count or unique result identities do not match')
        check(set(complete) == expected_tests, 'completed test methods differ from committed candidate suite')
    native = report.get('sourceMirror',{})
    if not isinstance(native,dict): native = {}
    check(native.get('inputSha256') == mirror, 'native mirror inventory or hashes differ from committed candidate')
    for field in ('matchesRepositoryBefore','matchesRepositoryAfter','unchangedDuringRun'):
        check(native.get(field) is True, 'native mirror ' + field + ' must be true')
    compiled = report.get('typescriptBuild',{})
    if not isinstance(compiled,dict): compiled = {}
    check(compiled.get('sourceComparison') == {p:{'repository':h,'buildSource':h} for p,h in build.items()},
          'build source inventory or hashes differ from committed candidate')
    for field in ('allSourcesMatch','cliPresent'):
        check(compiled.get(field) is True, 'TypeScript ' + field + ' must be true')
    outputs = compiled.get('compiledJavaScriptHashes')
    expected_js = {str(PurePosixPath(p.removeprefix('src/')).with_suffix('.js')) for p in build if p.startswith('src/')}
    check(isinstance(outputs,dict) and set(outputs) == expected_js
          and all(isinstance(v,str) and HEX.fullmatch(v) for v in outputs.values()), 'compiled JavaScript inventory and SHA256 hashes are required')
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report',required=True,type=Path)
    parser.add_argument('--candidate',required=True)
    parser.add_argument('--environment',choices=('linux','macos','wsl'),required=True)
    parser.add_argument('--evidence',type=Path)
    args = parser.parse_args()
    raw = args.report.read_bytes()
    try:
        errors = validate(json.loads(raw),args.candidate,args.environment)
    except (ValueError,KeyError,TypeError,subprocess.SubprocessError) as exc:
        errors = ['evidence admission failed: ' + str(exc)]
    record = {'recordedAt':datetime.now(timezone.utc).isoformat(),'candidateCommit':args.candidate,
              'command':[sys.executable,*sys.argv], 'environmentRequired':args.environment,
              'report':str(args.report),'reportSha256':hashlib.sha256(raw).hexdigest(),
              'checkerSha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'exitCode':int(bool(errors)), 'errors':errors,
              'limits':['Conformance-format evidence admission only; not authenticity proof, other suite acceptance or phase approval.',
                        'Compiled hashes record tested output identity; this tool does not rebuild or authenticate binaries.',
                        'Candidate comparison reads committed Git blobs, never working-tree files.']}
    if args.evidence:
        if args.evidence.resolve() == args.report.resolve():
            parser.error('evidence output must not replace the input report')
        args.evidence.parent.mkdir(parents=True,exist_ok=True)
        args.evidence.write_text(json.dumps(record,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(record,indent=2))
    return record['exitCode']


if __name__ == '__main__':
    sys.exit(main())
