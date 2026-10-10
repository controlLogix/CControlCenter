from pathlib import Path
import os,sys,json,hashlib,shutil,tempfile,time,subprocess,unittest
source=Path('/mnt/c/Users/RyanHelms/GitHub/agentmux');base=Path(tempfile.mkdtemp(prefix='server-api-diagnostics-',dir='/home/ryan/.cache/agentmux-governance'));repo=base/'repo';repo.mkdir()
for p in source.iterdir():
 if p.is_file():shutil.copyfile(p,repo/p.name)
shutil.copytree(source/'hub',repo/'hub',ignore=shutil.ignore_patterns('__pycache__'))
original=json.loads(Path('/home/ryan/.cache/agentmux-governance/p01-hub-callback-qualified/hub-full-result.json').read_text())['sourceSha256']
hashes={n:hashlib.sha256((repo/n).read_bytes()).hexdigest() for n in original};assert hashes==original,'source drift'
home=base/'home';home.mkdir();os.environ['HOME']=str(home);os.environ['TMUX_TMPDIR']=str(base)
for key in list(os.environ):
 if key.startswith('AGENTMUX_'):os.environ.pop(key)
sys.path.insert(0,str(repo));from hub.tests.test_hub_offline import ServerAPI
real_popen=subprocess.Popen;processes=[];handles=[];events=[]
def logged_popen(cmd,*a,**kw):
 if isinstance(cmd,list) and any(str(x).endswith('/hub/server.py') for x in cmd):
  f=open(base/'server.log','a');handles.append(f);kw.update(stdout=f,stderr=f);started=time.monotonic();p=real_popen(cmd,*a,**kw);processes.append(p);events.append({'pid':p.pid,'command':cmd,'home':kw['env'].get('HOME'),'agentmuxHome':kw['env'].get('AGENTMUX_HOME'),'startedMonotonic':started});return p
 return real_popen(cmd,*a,**kw)
subprocess.Popen=logged_popen
try:
 with open(base/'tests.log','w') as log:
  started=time.monotonic();result=unittest.TextTestRunner(stream=log,verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(ServerAPI));elapsed=time.monotonic()-started
finally:
 subprocess.Popen=real_popen
 for p in processes:
  if p.poll() is None:p.terminate();p.wait(timeout=10)
 for f in handles:f.close()
report={'tests':result.testsRun,'successful':result.wasSuccessful(),'errors':[(str(t),e) for t,e in result.errors],'failures':[(str(t),e) for t,e in result.failures],'skipped':result.skipped,'seconds':elapsed,'events':events,'sourceSha256':hashes,'sourceMatchesFailedFullRun':True,'sourceUnchangedAfter':all(hashlib.sha256((repo/n).read_bytes()).hexdigest()==v for n,v in hashes.items()),'instrumentation':'Original test methods/setup/polls/assertions unchanged; only server Popen stdout/stderr redirected from DEVNULL into server.log. Private copied checkout and HOME/TMUX_TMPDIR.','processExitCodes':[p.returncode for p in processes]}
(base/'result.json').write_text(json.dumps(report,indent=2));print(str(base));print(json.dumps({k:report[k] for k in ['tests','successful','seconds','processExitCodes']}))
