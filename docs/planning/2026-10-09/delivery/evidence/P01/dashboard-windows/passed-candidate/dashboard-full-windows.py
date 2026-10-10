import hashlib,json,os,signal,subprocess,threading,time,shutil,re,tempfile
from pathlib import Path
cache=Path('/home/ryan/.cache/agentmux-governance');oldroot=cache/'p01-dashboard-full-vkqiqkjv';repo=Path('/mnt/c/Users/RyanHelms/GitHub/agentmux');w=Path(tempfile.mkdtemp(prefix='p01-dashboard-windows-',dir=cache));out=w/'evidence';out.mkdir();checkout=oldroot/'checkout';candidate='09fe9c749ff674c0dd5ca4fa7c53abfbe23cadcd'
# This checkout is owned entirely by the disposable qualification harness.
subprocess.run(['git','fetch',str(repo),candidate],cwd=checkout,check=True,capture_output=True);subprocess.run(['git','checkout','--force','--detach',candidate],cwd=checkout,check=True,capture_output=True)
env={'PATH':'/usr/local/bin:/usr/bin:/bin','LANG':'C.UTF-8','PYTHONDONTWRITEBYTECODE':'1','GIT_CONFIG_NOSYSTEM':'1','AGENTMUX_NO_COURIER':'1','AGENTMUX_NO_TOAST':'1','PLAYWRIGHT_DIR':str(oldroot/'dependencies/node_modules/playwright'),'PLAYWRIGHT_BROWSERS_PATH':str(oldroot/'browsers')}
for key,name in [('HOME','home'),('TMPDIR','tmp'),('TMUX_TMPDIR','tmux'),('AGENTMUX_HOME','state'),('CODEX_HOME','codex'),('CLAUDE_CONFIG_DIR','claude')]:env[key]=str(w/name);Path(env[key]).mkdir(mode=0o700)
env['TMPDIR']=tempfile.mkdtemp(prefix='amx-',dir='/tmp')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
names=[n for n in subprocess.check_output(['git','ls-files','-z'],cwd=checkout).decode().split('\0') if n and not n.startswith(('docs/planning/','.context/','.bytedesk/'))]
report={'candidateCommit':candidate,'workRoot':str(w),'environment':env,'sourceHashes':{n:sha(checkout/n) for n in names},'windowsCodexVersion':subprocess.check_output(['codex','--version'],env=env,text=True,stderr=subprocess.STDOUT).strip(),'wrapperSha256':sha(Path('/home/ryan/.local/share/agentmux/windows-clients/forward.py')),'limits':['External orchestration plugin absent:16+4tests remain missing coverage.','Python3.14 archivedgateway differential requires separate3.12report.','WindowsCodex privateconfig/profile routing qualified separately; state initialization over LinuxUNC is not runtimequalified.','No providerinference or realcredentials authorized; originalauth test uses missingcustomkey and loopbackgateway.']}
focused=subprocess.run(['python3','dashboard/test_hub_panel.py'],cwd=checkout,env=env,capture_output=True,text=True,timeout=60)
(out/'focused-hub-panel.log').write_text(focused.stdout+focused.stderr);report['shortTempRoot']=env['TMPDIR'];report['focusedHubPanelExitCode']=focused.returncode
assert focused.returncode==0,focused.stderr
stop=threading.Event()
def monitor():
 handles={}
 with (out/'dashboard-full-runner.log').open('wb') as dest:
  while not stop.is_set():
   for path in Path(env['TMPDIR']).glob('*/suite.log'):
    if path not in handles:
     try:handles[path]=path.open('rb')
     except OSError:continue
   for src in handles.values():dest.write(src.read());dest.flush()
   for f in Path(env['TMPDIR']).glob('agentmux-gate-fail-*.out'):shutil.copyfile(f,out/f.name)
   time.sleep(.1)
  for src in handles.values():dest.write(src.read());src.close()
thread=threading.Thread(target=monitor);thread.start();print(str(w),flush=True);started=time.monotonic()
with (out/'dashboard-full-wrapper.log').open('w') as stream:
 child=subprocess.Popen(['bash','dashboard/check_test_residue.sh','--root',env['AGENTMUX_HOME'],'--','bash','dashboard/run_tests.sh'],cwd=checkout,env=env,stdout=stream,stderr=subprocess.STDOUT,start_new_session=True)
 try:rc=child.wait(timeout=2700)
 except subprocess.TimeoutExpired:
  os.killpg(child.pid,signal.SIGTERM)
  try:child.wait(timeout=15)
  except subprocess.TimeoutExpired:os.killpg(child.pid,signal.SIGKILL);child.wait()
  rc=124
stop.set();thread.join();report['exitCode']=rc;report['seconds']=round(time.monotonic()-started,3);report['sourceUnchanged']=all(sha(checkout/n)==v for n,v in report['sourceHashes'].items());report['trackedStatus']=subprocess.check_output(['git','status','--porcelain','--untracked-files=no'],cwd=checkout,text=True)
report['suiteResults']=[x for x in (out/'dashboard-full-runner.log').read_text().splitlines() if re.match(r'^(test_|check_test_|smoke\.sh)',x)];report['actualSuiteCount']=len(report['suiteResults']);report['zeroCheckSuites']=[x for x in report['suiteResults'] if 'passed 0,' in x]
remaining=[]
for entry in Path('/proc').iterdir():
 if not entry.name.isdigit() or int(entry.name)==os.getpid():continue
 try:
  if str(w).encode() in (entry/'environ').read_bytes():remaining.append(int(entry.name))
 except OSError:pass
report['ownedProcessesBeforeCleanup']=remaining
for pid in remaining:
 try:os.kill(pid,signal.SIGTERM)
 except ProcessLookupError:pass
report['logs']={p.name:sha(p) for p in out.glob('*.log')};report['harnessSha256']=sha(Path(__file__));(out/'dashboard-full-windows-result.json').write_text(json.dumps(report,indent=2)+'\n');shutil.copyfile(__file__,out/'dashboard-full-windows.py');print(json.dumps({'exitCode':rc,'seconds':report['seconds'],'actualSuites':report['actualSuiteCount'],'out':str(out)}))
