"""Retain accepted regression files or require an explicit reviewed replacement."""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[4]
HERE = Path(__file__).resolve().parent


def regression_path(name):
    path = Path(name)
    return ('tests' in path.parts or path.name.startswith('test_') or
            path.name.endswith(('_test.py', '_test.sh')) or '.test.' in path.name or
            path.name in ('test.sh', 'run_tests.sh', 'syntax_check.sh'))


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT)


def read_manifest():
    manifest = json.loads((HERE / 'regression-baseline.json').read_text(encoding='utf-8'))
    assert manifest['schemaVersion'] == '1.0.0'
    commit = manifest['acceptedCommit']
    entries = []
    for entry in git('ls-tree', '-rz', commit).split(b'\0'):
        if not entry:
            continue
        metadata, name = entry.split(b'\t', 1)
        path = name.decode('utf-8')
        if regression_path(path):
            mode, kind, object_id = metadata.split()
            assert kind == b'blob', 'Regression path is not a Git blob'
            entries.append((path, object_id))
    # One batch avoids starting a Git process for every retained test file.
    contents = subprocess.check_output(['git', 'cat-file', '--batch'], cwd=ROOT,
                                       input=b''.join(oid + b'\n' for _, oid in entries))
    expected, offset = {}, 0
    for path, object_id in entries:
        end = contents.index(b'\n', offset)
        actual_id, kind, size = contents[offset:end].split()
        assert actual_id == object_id and kind == b'blob', 'Unexpected Git batch response'
        start, length = end + 1, int(size)
        data = contents[start:start + length]
        assert len(data) == length and contents[start + length:start + length + 1] == b'\n'
        expected[path] = hashlib.sha256(data).hexdigest()
        offset = start + length + 1
    assert offset == len(contents), 'Unexpected trailing Git batch output'
    assert manifest['files'] == expected, 'Regression inventory no longer matches the accepted Git snapshot'
    return manifest


def verify(manifest, overrides=None):
    overrides = overrides or {}
    errors = []
    replacements = manifest['reviewedReplacements']
    assert set(replacements) <= set(manifest['files']), 'Unknown replacement source'
    for name, original in manifest['files'].items():
        path = ROOT / name
        data = overrides[name] if name in overrides else path.read_bytes() if path.is_file() else None
        digest = hashlib.sha256(data).hexdigest() if data is not None else None
        if digest == original:
            continue
        replacement = replacements.get(name)
        if not replacement:
            errors.append(name + ': accepted regression file changed or missing without reviewed replacement')
            continue
        target = (ROOT / replacement['path']).resolve()
        evidence = (ROOT / replacement['evidence']).resolve()
        target_name = target.relative_to(ROOT).as_posix() if target.is_relative_to(ROOT) else None
        target_data = overrides.get(target_name, target.read_bytes() if target.is_file() else b'')
        valid = (target.is_relative_to(ROOT) and evidence.is_relative_to(ROOT) and target.is_file() and evidence.is_file()
                 and replacement.get('reviewer') == 'Codex' and bool(replacement.get('reviewedAt'))
                 and bool(replacement.get('reason')) and replacement.get('originalSha256') == original
                 and hashlib.sha256(target_data).hexdigest() == replacement.get('replacementSha256'))
        if not valid:
            errors.append(name + ': invalid or stale reviewed replacement')
    return errors


def removal_mutation(manifest):
    for name in manifest['files']:
        if not name.endswith('.py'):
            continue
        text = (ROOT / name).read_text(encoding='utf-8')
        for node in ast.walk(ast.parse(text)):
            call = node.value if isinstance(node, ast.Expr) else None
            is_call = isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute) and call.func.attr.startswith('assert')
            if isinstance(node, ast.Assert) or is_call:
                lines = text.splitlines(keepends=True)
                lines[node.lineno - 1:node.end_lineno] = [' ' * node.col_offset + 'pass  # deliberately removed regression assertion\n']
                mutated = ''.join(lines)
                ast.parse(mutated)
                return name, mutated.encode()
    raise AssertionError('No actual Python assertion found for the negative test')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--self-test', action='store_true')
    parser.add_argument('--evidence', type=Path)
    args = parser.parse_args()
    manifest = read_manifest()
    errors = verify(manifest)
    negative = None
    if args.self_test:
        name, data = removal_mutation(manifest)
        detected = verify(manifest, {name: data})
        assert any(error.startswith(name + ':') for error in detected), 'Removed assertion escaped the regression gate'
        negative = {'path': name, 'assertionRemovalDetected': True,
                    'mutation': 'One actual Python assertion replaced with pass in an in-memory candidate; repository unchanged.'}
    result = {'ok': not errors, 'acceptedCommit': manifest['acceptedCommit'], 'files': len(manifest['files']),
              'errors': errors, 'negativeTest': negative,
              'assurance': 'Exact regression-file retention or recorded Codex-reviewed replacement. It does not prove assertion quality or semantic equivalence of a replacement.'}
    if args.evidence:
        result['sourceHashes'] = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                                  for p in (Path(__file__), HERE / 'regression-baseline.json')}
        args.evidence.parent.mkdir(parents=True, exist_ok=True)
        args.evidence.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8', newline='\n')
    print(json.dumps(result, indent=2))
    return 0 if not errors else 1


if __name__ == '__main__':
    raise SystemExit(main())
