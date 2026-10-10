import os,sys,tempfile,subprocess,json,hashlib
from pathlib import Path
repo=Path(sys.argv[1]).resolve();out=Path(sys.argv[2]).resolve();source=repo/'dashboard/test_dispatch.py';before=hashlib.sha256(source.read_bytes()).hexdigest()
with tempfile.TemporaryDirectory(prefix='original-dispatch-review-') as td:
 env={k:v for k,v in os.environ.items() if not k.startswith('AGENTMUX_') and k not in ('CODEX_HOME','CLAUDE_CONFIG_DIR','CC_ENFORCE','TM_ENFORCE','GIT_DIR','GIT_WORK_TREE')};env.update(HOME=td,TMPDIR=td,PYTHONDONTWRITEBYTECODE='1',GIT_CONFIG_NOSYSTEM='1',GIT_CONFIG_GLOBAL='/dev/null')
 r=subprocess.run([sys.executable,str(source)],cwd=td,env=env,capture_output=True,text=True,timeout=150)
 out.with_suffix('.log').write_text(r.stdout+r.stderr);report={'command':[sys.executable,str(source)],'exitCode':r.returncode,'sourceHash':before,'sourceUnchanged':before==hashlib.sha256(source.read_bytes()).hexdigest(),'summary':r.stdout.splitlines()[-8:],'limits':['Unchanged original runtime suite, independent of new package launcher. Uses original mocked transport seams and actual disposable Git lifecycle assertions.']};out.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report));sys.exit(r.returncode)
