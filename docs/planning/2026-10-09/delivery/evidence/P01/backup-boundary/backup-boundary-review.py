import ast,hashlib,json,os,subprocess,sys
from pathlib import Path
from datetime import datetime,timezone
root=Path('/mnt/c/Users/RyanHelms/GitHub/agentmux');os.chdir(root)
out=Path.home()/'.cache/agentmux-governance/p01-backup-boundary';out.mkdir(parents=True,exist_ok=True)
old=subprocess.check_output(['git','show','09fe9c7:hub/store.py'],text=True)
method=next(n for n in ast.walk(ast.parse(old)) if isinstance(n,ast.FunctionDef) and n.name=='backup_to')
function=ast.get_source_segment(old,method)
code="import unittest\nfrom hub import store\nexec("+repr(function)+",store.__dict__)\nstore.Store.backup_to=store.backup_to\ns=unittest.defaultTestLoader.loadTestsFromName('hub.tests.test_governance.BackupIdentity.test_second_boundary_uses_one_timestamp_for_backup_rotation')\nr=unittest.TextTestRunner(verbosity=2).run(s)\nraise SystemExit(0 if r.wasSuccessful() else 1)\n"
runs=[]
for name,args in [('positive',[sys.executable,'-m','unittest','hub.tests.test_governance.BackupIdentity','hub.tests.test_hub_offline.BackupsAndRetention','-v']),('original-negative',[sys.executable,'-c',code])]:
 r=subprocess.run(args,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
 (out/(name+'.log')).write_bytes(r.stdout.encode())
 runs.append({'id':name,'command':args[:2]+(['original backup_to injected into current module; new boundary test only'] if name=='original-negative' else args[2:]),'exitCode':r.returncode,'logSha256':hashlib.sha256(r.stdout.encode()).hexdigest()})
assert runs[0]['exitCode']==0 and runs[1]['exitCode']==1
assert 'AssertionError: True is not false' in (out/'original-negative.log').read_text()
# Every original test method is unchanged; the new regression is additive.
old_tests=ast.parse(subprocess.check_output(['git','show','09fe9c7:hub/tests/test_governance.py'],text=True))
new_tests=ast.parse((root/'hub/tests/test_governance.py').read_text())
def tests(tree):return {c.name+'.'+f.name:ast.dump(f,include_attributes=False) for c in tree.body if isinstance(c,ast.ClassDef) for f in c.body if isinstance(f,(ast.FunctionDef,ast.AsyncFunctionDef)) and f.name.startswith('test_')}
a,b=tests(old_tests),tests(new_tests);assert all(b.get(k)==v for k,v in a.items())
report={'recordedAt':datetime.now(timezone.utc).isoformat(),'baseCommit':subprocess.check_output(['git','rev-parse','09fe9c7'],text=True).strip(),'scope':'Backup filename timestamp sampled once; existing rotation and snapshot assertions retained','runs':runs,'unchangedOriginalMethods':len(a),'sourceSha256':{p:hashlib.sha256((root/p).read_bytes()).hexdigest() for p in ['hub/store.py','hub/tests/test_governance.py']},'limits':['Deterministic second-boundary reproduction and focused real SQLite backups; native/full candidate evidence remains required.']}
(out/'result.json').write_bytes((json.dumps(report,indent=2)+'\n').encode());print(json.dumps(report,indent=2))
