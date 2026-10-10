import ast,hashlib,json,os,shutil,subprocess,tempfile
from pathlib import Path
root=Path('/mnt/c/Users/RyanHelms/GitHub/agentmux')
out=Path('/home/ryan/.cache/agentmux-governance/legacy-step-negative');out.mkdir(exist_ok=True)
names=[p.relative_to(root).as_posix() for folder in ('dashboard','taskmgmt') for p in (root/folder).rglob('*.py') if '__pycache__' not in p.parts]+['dashboard/auth.json','.github/workflows/tests.yml']
hashes={n:hashlib.sha256((root/n).read_bytes()).hexdigest()for n in names}
with tempfile.TemporaryDirectory(prefix='legacy-step-negative-') as d:
    base=Path(d);dash=base/'dashboard';shutil.copytree(root/'dashboard',dash,ignore=shutil.ignore_patterns('__pycache__','node_modules','*.db','*.log'))
    shutil.copytree(root/'taskmgmt',base/'taskmgmt',ignore=shutil.ignore_patterns('__pycache__','*.db','*.log'))
    test=dash/'test_host_guard.py';text=test.read_text(encoding='utf-8');tree=ast.parse(text)
    method=next(n for n in ast.walk(tree)if isinstance(n,ast.FunctionDef)and n.name.startswith('test_'))
    calls=[n for n in ast.walk(method)if isinstance(n,ast.Expr)and isinstance(n.value,ast.Call)and isinstance(n.value.func,ast.Attribute)and n.value.func.attr.startswith('assert')]
    assert calls
    node=min(calls,key=lambda n:n.lineno);lines=text.splitlines(keepends=True)
    original=''.join(lines[node.lineno-1:node.end_lineno]);lines[node.lineno-1:node.end_lineno]=[' '*node.col_offset+'self.fail("intentional workflow-step assertion fixture")\n']
    test.write_text(''.join(lines),encoding='utf-8')
    env={'PATH':os.defpath,'HOME':str(base/'home'),'TMPDIR':str(base/'tmp'),'PYTHONDONTWRITEBYTECODE':'1','LANG':'C.UTF-8'}
    Path(env['HOME']).mkdir();Path(env['TMPDIR']).mkdir()
    cmd=['python3','dashboard/test_host_guard.py'];r=subprocess.run(cmd,cwd=base,env=env,capture_output=True,text=True,timeout=40)
    log=r.stdout+r.stderr
    if (out/'negative.log').exists() and not (out/'setup-failure.log').exists(): shutil.copyfile(out/'negative.log',out/'setup-failure.log')
    (out/'negative.log').write_text(log,encoding='utf-8')
    assert r.returncode!=0 and 'intentional workflow-step assertion fixture'in log and 'FAILED'in log
    report={'candidate':subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip(),'sourceHashes':hashes,'command':cmd,'exitCode':r.returncode,'mutation':{'method':method.name,'line':node.lineno,'originalAssertion':original,'replacement':'self.fail("intentional workflow-step assertion fixture")'},'logSha256':hashlib.sha256((out/'negative.log').read_bytes()).hexdigest(),'repositorySourceUnchanged':all(hashlib.sha256((root/n).read_bytes()).hexdigest()==h for n,h in hashes.items()),'limits':['Deliberate existing assertion failure executes exact dashboard workflow command on a disposable source copy; no CI failure run or runtime fault simulation claimed.','Workflow uses ordinary fail-fast run step, no continue-on-error or suppressed exit code; command nonzero blocks that step. Existing native CI tests qualify live suites separately; skipped legacy broker cases are not passes.','Actual private HTTP server fixture, no providers or operator state.']}
    assert report['repositorySourceUnchanged'];(out/'result.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'exitCode':r.returncode,'expectedFailureDetected':True,'method':method.name,'result':str(out/'result.json')}))
