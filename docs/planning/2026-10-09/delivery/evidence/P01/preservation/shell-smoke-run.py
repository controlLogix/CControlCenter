"""Run the original shell smoke against an isolated committed native snapshot."""
import hashlib,io,json,os,platform,shlex,shutil,signal,sqlite3,subprocess,sys,tarfile,tempfile,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[7];OUT=Path(__file__).resolve().parent

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def owned_processes(root):
 found=[]
 for p in Path('/proc').glob('[0-9]*'):
  try:
   if str(root).encode() in (p/'environ').read_bytes():found.append(int(p.name))
  except (PermissionError,FileNotFoundError,ProcessLookupError):pass
 return found

def main():
 commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
 work=Path(tempfile.mkdtemp(prefix='shell-smoke-',dir='/home/ryan/.cache/agentmux-governance'))
 tree=work/'checkout';tree.mkdir();home=work/'home';state=work/'state';binpath=home/'.local/bin'
 for p in (binpath,state,work/'tmp',work/'tmux',work/'codex',work/'claude'):p.mkdir(parents=True,mode=0o700)
 env={'PATH':str(binpath)+':/home/ryan/.cache/agentmux-governance/venv/bin:/usr/bin:/bin','LANG':'C.UTF-8','TERM':'xterm-256color','HOME':str(home),'TMPDIR':str(work/'tmp'),'TMUX_TMPDIR':str(work/'tmux'),'AGENTMUX_HOME':str(state),'CODEX_HOME':str(work/'codex'),'CLAUDE_CONFIG_DIR':str(work/'claude'),'AGENTMUX_REPO':str(tree),'AGENTMUX_NO_COURIER':'1','AGENTMUX_NO_TOAST':'1','AGENTMUX_IDLE_MINUTES':'0','AGENTMUX_PYTHON':'/home/ryan/.cache/agentmux-governance/venv/bin/python','PYTHONDONTWRITEBYTECODE':'1','GIT_CONFIG_NOSYSTEM':'1'}
 am=binpath/'agentmux';am.write_text('#!/bin/bash\nexec /bin/bash '+shlex.quote(str(tree/'agentmux.sh'))+' "$@"\n');am.chmod(0o700);env['AGENTMUX_BIN']=str(am)
 shell=binpath/'fixture-shell';shell.write_text('#!/bin/bash\nexec /bin/bash --noprofile --norc "$@"\n');shell.chmod(0o700);env['SHELL']=str(shell)
 (state/'hub').mkdir();config=state/'hub/config.toml';config.write_text('node = "local"\nnats_url = ""\ntcp_port = 0\n')
 report={'candidateCommit':commit,'recordedAtUnix':time.time(),'executionHarnessSha256':sha(Path(__file__)),'environment':{'platform':platform.platform(),'python':sys.version},'isolation':{'ownedRoot':str(work),'HOME':str(home),'AGENTMUX_HOME':str(state),'AGENTMUX_BIN':str(am),'AGENTMUX_REPO':str(tree),'TMUX_TMPDIR':str(work/'tmux'),'shellStartupFilesDisabled':True,'cleanEnvironmentNoProviderCredentials':True,'tcpDisabled':True,'natsDisabled':True},'limits':['One real local hub and shell pane only; no model provider, NATS federation, dashboard parity or phase acceptance.']}
 def call(args,timeout=30):return subprocess.run([str(am),'hub',*args],cwd=tree,env=env,stdin=subprocess.DEVNULL,capture_output=True,text=True,timeout=timeout)
 started=time.monotonic();code=1
 try:
  archive=subprocess.check_output(['git','archive',commit],cwd=ROOT)
  with tarfile.open(fileobj=io.BytesIO(archive)) as package:package.extractall(tree,filter='data')
  report['archiveSha256']=hashlib.sha256(archive).hexdigest()
  report['sourceHashes']={p.relative_to(tree).as_posix():sha(p) for p in tree.rglob('*') if p.is_file() and not p.relative_to(tree).as_posix().startswith(('docs/planning/','.context/','.bytedesk/'))}
  report['fixtureHashes']={'agentmuxWrapper':sha(am),'shellWrapper':sha(shell),'hubConfig':sha(config)}
  with (OUT/'shell-smoke-output.log').open('wb') as log:
   process=subprocess.Popen(['bash','hub/demo/smoke_shell.sh'],cwd=tree,env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
   try:code=process.wait(timeout=150)
   except subprocess.TimeoutExpired:os.killpg(process.pid,signal.SIGKILL);process.wait();code=124
  report['command']='bash hub/demo/smoke_shell.sh';report['exitCode']=code
  report['logSha256']=sha(OUT/'shell-smoke-output.log')
  report['privateAgentSidecars']=[p.name for p in (state/'run').glob('calc-worker-smoke_sh.*')]
  report['hubShutdown']={'exitCode':call(['stop']).returncode}
  database=state/'hub/hub.db'
  if database.exists():
   con=sqlite3.connect('file:'+str(database)+'?mode=ro',uri=True);con.row_factory=sqlite3.Row
   report['observations']={
    'agents':[dict(r) for r in con.execute('select session,cli,state,state_note from agents')],
    'deliveries':[dict(r) for r in con.execute('select message_id,recipient,state,attempts from deliveries')],
    'work':[dict(r) for r in con.execute('select id,target,title,state,claimed_by,result from work_items')],
    'events':[dict(r) for r in con.execute('select seq,entity,entity_id,event,actor from events')],
    'repoPaths':[dict(r) for r in con.execute('select repo,path from repo_paths')]}
   con.close()
  report['sourceUnchanged']=all(sha(tree/n)==v for n,v in report['sourceHashes'].items())
 except Exception as error:
  report['failureType']=type(error).__name__;report['failure']=str(error)
 finally:
  if (tree/'agentmux.sh').exists():
   try:call(['kill','calc-worker-smoke_sh'],10)
   except Exception:pass
   try:call(['stop'],10)
   except Exception:pass
  for sock in (work/'tmux').rglob('*'):
   if sock.is_socket():subprocess.run(['tmux','-S',str(sock),'kill-server'],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
  deadline=time.monotonic()+8
  while owned_processes(work) and time.monotonic()<deadline:time.sleep(.1)
  report['ownedProcessesBeforeFallback']=owned_processes(work)
  for pid in report['ownedProcessesBeforeFallback']:
   try:os.kill(pid,signal.SIGTERM)
   except ProcessLookupError:pass
  time.sleep(.2)
  for pid in owned_processes(work):
   try:os.kill(pid,signal.SIGKILL)
   except ProcessLookupError:pass
  report['remainingOwnedProcessIds']=owned_processes(work)
  shutil.rmtree(work);report['cleanupComplete']=not work.exists() and not report['remainingOwnedProcessIds']
 report['durationSeconds']=round(time.monotonic()-started,3)
 text=(OUT/'shell-smoke-output.log').read_text() if (OUT/'shell-smoke-output.log').exists() else ''
 required=['welcome acked by the pane itself','direct message acked','role claim + done ok','sidecars cleaned','SMOKE PASS']
 report['assertionMarkers']={m:m in text for m in required}
 report['ok']=code==0 and all(report['assertionMarkers'].values()) and report.get('sourceUnchanged',False) and report['cleanupComplete'] and not report.get('failureType')
 (OUT/'shell-smoke-result.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8');print(json.dumps({'ok':report['ok'],'exitCode':code,'failure':report.get('failure')}))
if __name__=='__main__':main()
