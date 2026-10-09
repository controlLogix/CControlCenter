"""Compare unchanged name tests and added refusal cases against both source versions."""
import ast
import hashlib
import io
import json
from pathlib import Path
import platform
import subprocess
import sys
import types
import unittest

ROOT = next(p for p in Path(__file__).resolve().parents if (p / 'hub/names.py').is_file())
OUT = Path(__file__).resolve().parent
BASE = '37e0d8cd7439d31a491ac673e73438f7885cd04e'
PATHS = ['hub/names.py', 'hub/tests/test_hub_offline.py']

def sha(raw):
    return hashlib.sha256(raw).hexdigest()

def methods(raw):
    tree = ast.parse(raw)
    return {(c.name, m.name): ast.dump(m, include_attributes=False)
            for c in tree.body if isinstance(c, ast.ClassDef)
            for m in c.body if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))
            and m.name.startswith('test_')}

current = {p: (ROOT / p).read_bytes() for p in PATHS}
original = {p: subprocess.check_output(['git', '-C', str(ROOT), 'show', BASE + ':' + p]) for p in PATHS}
old_methods, new_methods = methods(original[PATHS[1]]), methods(current[PATHS[1]])
retained = all(new_methods.get(k) == body for k, body in old_methods.items())
assert retained, 'Original test method changed or removed'
names_class = next(n for n in ast.parse(current[PATHS[1]]).body if isinstance(n, ast.ClassDef) and n.name == 'Names')
runs = []
for label, source in [('original', original[PATHS[0]]), ('current', current[PATHS[0]])]:
    module_name = '_names_review_' + label
    module = types.ModuleType(module_name)
    sys.modules[module_name] = module
    try:
        exec(compile(source, 'hub/names.py (' + label + ')', 'exec'), module.__dict__)
        scope = {'names': module, 'unittest': unittest, '__name__': 'names_preservation_review'}
        exec(compile(ast.Module(body=[names_class], type_ignores=[]), PATHS[1], 'exec'), scope)
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(scope['Names'])
        text = io.StringIO()
        result = unittest.TextTestRunner(stream=text, verbosity=2).run(suite)
        log = text.getvalue().encode()
        (OUT / (label + '.log')).write_bytes(log)
        runs.append({'source': label, 'testsRun': result.testsRun, 'failures': len(result.failures),
                     'errors': len(result.errors), 'skips': len(result.skipped),
                     'successful': result.wasSuccessful(), 'log': label + '.log',
                     'logSha256': sha(log), 'failedSubtests': [str(t) for t, _ in result.failures]})
    finally:
        del sys.modules[module_name]
assert runs[0]['testsRun'] == 6 and runs[0]['failures'] == 10 and not runs[0]['errors']
assert runs[1]['testsRun'] == 6 and runs[1]['successful'] and not runs[1]['skips']
unchanged = all((ROOT / p).read_bytes() == raw for p, raw in current.items())
assert unchanged
report = {'candidateBase': BASE, 'workingChangesIncluded': True,
          'command': 'python ' + Path(__file__).relative_to(ROOT).as_posix(),
          'environment': {'python': sys.version, 'platform': platform.platform()},
          'sourceHashes': {p: sha(raw) for p, raw in current.items()},
          'originalSourceHashes': {p: sha(raw) for p, raw in original.items()},
          'harnessSha256': sha(Path(__file__).read_bytes()),
          'originalTestMethodsRetainedAST': retained, 'originalTestMethodCount': len(old_methods),
          'originalNamesMethods': sorted(k[1] for k in old_methods if k[0] == 'Names'),
          'runs': runs, 'sourceUnchanged': unchanged,
          'limits': ['Only the extracted six Names unittest methods execute; no store, network or host state is used.',
                     'Original source is a Git blob executed in a separate temporary Python module; repository files are not replaced.',
                     'This focused evidence does not qualify full legacy suites, native macOS/Linux or a phase.']}
(OUT / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps({'originalMethodsRetained': retained, 'runs': runs, 'sourceUnchanged': unchanged}, indent=2))
