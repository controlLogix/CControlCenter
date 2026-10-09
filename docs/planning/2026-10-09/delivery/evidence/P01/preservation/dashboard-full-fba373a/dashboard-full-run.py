import json, hashlib, os, pathlib, platform, shutil, signal, subprocess, sys, tempfile, time
P=pathlib.Path
ROOT=P('/mnt/c/Users/RyanHelms/GitHub/agentmux')
BASE=P('/home/ryan/.cache/agentmux-governance')
WORK=P(tempfile.mkdtemp(prefix='p01-dashboard-full-',dir=BASE))
OUT=WORK/'evidence';OUT.mkdir()
ENV={'PATH':'/usr/local/bin:/usr/bin:/bin','LANG':'C.UTF-8','PYTHONDONTWRITEBYTECODE':'1','GIT_CONFIG_NOSYSTEM':'1','AGENTMUX_NO_COURIER':'1','AGENTMUX_NO_TOAST':'1'}
for key,name in [('HOME','home'),('TMPDIR','tmp'),('TMUX_TMPDIR','tmux'),('AGENTMUX_HOME','state'),('CODEX_HOME','codex'),('CLAUDE_CONFIG_DIR','claude'),('PLAYWRIGHT_BROWSERS_PATH','browsers')]:
 ENV[key]=str(WORK/name);P(ENV[key]).mkdir(mode=0o700)
report={'candidate':'fba373a06a7b356b49fc778b96be5d6e5ae387b6','workRoot':str(WORK),'checks':[],'python':sys.version,'platform':platform.platform(),'isolation':ENV.copy()}
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(): (OUT/'dashboard-full-result.json').write_text(json.dumps(report,indent=2)+'\n')
def run(label,cmd,cwd,limit=600):
 path=OUT/(label+'.log');started=time.monotonic()
 with path.open('w') as log:
  proc=subprocess.Popen(cmd,cwd=cwd,env=ENV,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
  try: rc=proc.wait(timeout=limit)
  except subprocess.TimeoutExpired:
   os.killpg(proc.pid,signal.SIGTERM)
   try:proc.wait(timeout=15)
   except subprocess.TimeoutExpired:os.killpg(proc.pid,signal.SIGKILL);proc.wait()
   rc=124
 text=path.read_text(errors='replace');r={'name':label,'command':cmd,'exitCode':rc,'seconds':round(time.monotonic()-started,3),'logSha256':sha(path),'skipLines':[x for x in text.splitlines() if 'SKIP' in x or 'skipped' in x.lower()],'tail':text.splitlines()[-8:]};report['checks'].append(r);save();print(json.dumps(r),flush=True);return rc
print(str(WORK),flush=True);save()
checkout=WORK/'checkout';deps=WORK/'dependencies';deps.mkdir()
try:
 assert run('clone',['git','clone','--no-hardlinks','--no-checkout','-c','core.autocrlf=false',str(ROOT),str(checkout)],WORK)==0
 assert run('checkout',['git','checkout','--detach',report['candidate']],checkout)==0
 names=subprocess.check_output(['git','ls-files','-z'],cwd=checkout,env=ENV).decode().split('\0')
 names=[n for n in names if n and not n.startswith(('docs/planning/','.context/','.bytedesk/'))]
 report['sourceHashes']={n:sha(checkout/n) for n in names};save()
 (deps/'package.json').write_text(json.dumps({'name':'agentmux-dashboard-qualification','private':True,'version':'1.0.0','dependencies':{'playwright':'1.64.0'}}))
 assert run('npm-install',['npm','install','--ignore-scripts','--no-audit','--no-fund','--cache',str(WORK/'npm-cache')],deps)==0
 report['lockSha256']=sha(deps/'package-lock.json')
 ENV['PLAYWRIGHT_DIR']=str(deps/'node_modules/playwright')
 assert run('firefox-install',['node',str(deps/'node_modules/playwright/cli.js'),'install','firefox'],deps)==0
 # Capture installed package/browser manifests without exposing credentials.
 shutil.copyfile(deps/'package-lock.json',OUT/'dashboard-full-package-lock.json')
 shutil.copyfile(deps/'node_modules/playwright-core/browsers.json',OUT/'dashboard-full-browsers.json')
 report['declaredSuites']=[line.split()[1] for line in (checkout/'dashboard/run_tests.sh').read_text().splitlines() if line.startswith('run ')]
 run('full-suite',['bash','dashboard/check_test_residue.sh','--root',ENV['AGENTMUX_HOME'],'--','bash','dashboard/run_tests.sh'],checkout,2700)
 report['sourceUnchanged']=all(sha(checkout/n)==v for n,v in report['sourceHashes'].items())
 report['trackedStatus']=subprocess.check_output(['git','status','--porcelain','--untracked-files=no'],cwd=checkout,env=ENV,text=True)
except Exception as exc:report['error']=str(exc)
finally:
 report['socketCleanup']=[]
 for sock in P(ENV['TMUX_TMPDIR']).rglob('*'):
  if sock.is_socket():
   r=subprocess.run(['tmux','-S',str(sock),'kill-server'],env=ENV,capture_output=True);report['socketCleanup'].append({'socket':str(sock),'exitCode':r.returncode})
 # Identify only processes which contain this owned root in their environment.
 owned=[]
 for entry in P('/proc').iterdir():
  if not entry.name.isdigit() or int(entry.name)==os.getpid():continue
  try:
   if str(WORK).encode() in (entry/'environ').read_bytes():owned.append(int(entry.name))
  except (OSError,PermissionError):pass
 report['remainingOwnedProcessesBeforeCleanup']=owned
 for pid in owned:
  try:os.kill(pid,signal.SIGTERM)
  except ProcessLookupError:pass
 report['limits']=['Full original dashboard suite; skips and failures retained, not a phase pass.','No production credentials inherited; provider validation uses the suite synthetic credential.','Gateway archived-bytecode differential under Python3.14 may skip; separate Python3.12 evidence remains required.']
 save();print('FINAL '+str(OUT/'dashboard-full-result.json'),flush=True)
