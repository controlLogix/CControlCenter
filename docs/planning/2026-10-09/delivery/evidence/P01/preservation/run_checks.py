"""Execute unchanged preservation checks in owned disposable environments."""
import argparse, hashlib, io, json, os, platform, re, shutil, signal, subprocess, sys, tempfile, time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[7]
OUT=Path(__file__).resolve().parent

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def run(command,cwd,env,log,timeout=600):
 started=time.monotonic()
 with log.open('w',encoding='utf-8') as stream:
  child=subprocess.Popen(command,cwd=cwd,env=env,stdout=stream,stderr=subprocess.STDOUT,start_new_session=True)
  try:code=child.wait(timeout=timeout)
  except subprocess.TimeoutExpired:
   os.killpg(child.pid,signal.SIGKILL);child.wait();code=124
 text=log.read_text(encoding='utf-8',errors='replace')
 return {'command':command,'exitCode':code,'seconds':round(time.monotonic()-started,3),'log':log.name,'logSha256':sha(log),'summary':text.splitlines()[-4:],'skipLines':[s for s in text.splitlines() if s.startswith('SKIP ') or 'baseline(s) skipped' in s]}
def committed_hashes(root,commit,names):
 request=''.join(commit+':'+n+'\n' for n in names).encode()
 result=subprocess.check_output(['git','cat-file','--batch'],input=request,cwd=root)
 stream=io.BytesIO(result);hashes={}
 for name in names:
  header=stream.readline().decode().split();assert header[1]=='blob',header
  data=stream.read(int(header[2]));assert stream.read(1)==b'\n'
  hashes[name]=hashlib.sha256(data).hexdigest()
 return hashes

def main():
 parser=argparse.ArgumentParser();parser.add_argument('--gateway',action='store_true');args=parser.parse_args()
 commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
 report={'executionHarnessSha256':sha(Path(__file__)),'recordedAtUnix':time.time(),'candidateCommit':commit,'environment':{'platform':platform.platform(),'python':sys.version},'checks':[],'limits':[]}
 if args.gateway:
  paths=['dashboard/test_gateway.py','taskmgmt/bedrock_gateway.py','taskmgmt/recovered/bedrock_gateway.cpython-312.pyc.bin']
  report['sourceHashes']={n:sha(ROOT/n) for n in paths}
  with tempfile.TemporaryDirectory(prefix='agentmux-p01-gateway-') as directory:
   work=Path(directory)
   for n in paths:(work/n).parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(ROOT/n,work/n)
   env={k:v for k,v in os.environ.items() if k in ('SYSTEMROOT','WINDIR','PATH','TEMP','TMP')}
   env.update(PYTHONIOENCODING='utf-8',PYTHONDONTWRITEBYTECODE='1')
   report['copiedSourceMatches']=all(sha(ROOT/n)==sha(work/n) for n in paths)
   report['checks'].append(run([sys.executable,'dashboard/test_gateway.py'],work,env,OUT/'gateway.log'))
  report['cleanupComplete']=not work.exists();report['sourceUnchanged']=report['sourceHashes']=={n:sha(ROOT/n) for n in paths}
  report['limits']=['Windows CPython 3.12 pure translation and archived-bytecode comparison only; no Bedrock service or credential used.']
  target=OUT/'gateway-result.json'
 else:
  cache=Path('/home/ryan/.cache/agentmux-governance');work=Path(tempfile.mkdtemp(prefix='p01-preservation-',dir=cache));checkout=work/'checkout'
  env={'PATH':'/usr/local/bin:/usr/bin:/bin','LANG':'C.UTF-8','HOME':str(work/'home'),'TMPDIR':str(work/'tmp'),'TMUX_TMPDIR':str(work/'tmux'),'AGENTMUX_HOME':str(work/'state'),'CODEX_HOME':str(work/'codex'),'CLAUDE_CONFIG_DIR':str(work/'claude'),'AGENTMUX_NO_COURIER':'1','AGENTMUX_NO_TOAST':'1','PYTHONDONTWRITEBYTECODE':'1','GIT_CONFIG_NOSYSTEM':'1'}
  for key in ('HOME','TMPDIR','TMUX_TMPDIR','AGENTMUX_HOME','CODEX_HOME','CLAUDE_CONFIG_DIR'):Path(env[key]).mkdir(mode=0o700)
  try:
   setup=run(['git','clone','--no-hardlinks','--no-checkout','-c','core.autocrlf=false',str(ROOT),str(checkout)],work,env,OUT/'clone.log');report['checks'].append(setup)
   if setup['exitCode']:raise RuntimeError('Disposable clone failed')
   subprocess.run(['git','checkout','--detach',commit],cwd=checkout,env=env,check=True,capture_output=True)
   names=subprocess.check_output(['git','ls-files','-z'],cwd=checkout,env=env).decode().split('\0')
   paths=[n for n in names if n and not n.startswith(('docs/planning/','.context/','.bytedesk/'))]
   report['sourceHashes']={n:sha(checkout/n) for n in paths}
   report['committedSourceHashes']=committed_hashes(checkout,commit,paths)
   report['copiedSourceMatches']=report['sourceHashes']==report['committedSourceHashes']
   report['workingTreeDifferences']=[n for n,v in report['sourceHashes'].items() if sha(ROOT/n)!=v]
   report['tmuxVersion']=subprocess.check_output(['tmux','-V'],env=env,text=True).strip()
   report['isolation']={'nativeCheckout':str(checkout),'fullGitHistory':True,'privateHome':env['HOME'],'privateState':env['AGENTMUX_HOME'],'privateTmuxDirectory':env['TMUX_TMPDIR'],'noProviderCredentials':True}
   for label,command in [('testlib',['bash','dashboard/test_testlib.sh']),('failability',['bash','dashboard/check_test_failability.sh']),('residue',['bash','dashboard/test_residue.sh']),('orchtest',[sys.executable,'-m','unittest','discover','-s','orchtest','-p','test_*.py','-v']),('residue-gate',['bash','dashboard/check_test_residue.sh','--root',env['AGENTMUX_HOME'],'--','bash','dashboard/test_residue.sh'])]:
    item=run(command,checkout,env,OUT/(label+'.log'));item['name']=label;report['checks'].append(item)
    (OUT/'running-result.json').write_text(json.dumps(report,indent=2)+'\n')
   report['sourceUnchanged']=all(sha(checkout/n)==v for n,v in report['sourceHashes'].items())
   report['finalGitStatus']=subprocess.check_output(['git','status','--porcelain','--untracked-files=no'],cwd=checkout,env=env,text=True)
   report['residualFiles']=[p.relative_to(work).as_posix() for p in (work/'tmp').iterdir()]
  finally:
   sockets=list((work/'tmux').rglob('*'))
   report['ownedSocketCleanup']=[]
   for sock in sockets:
    if sock.is_socket():
     result=subprocess.run(['tmux','-S',str(sock),'kill-server'],env=env,capture_output=True,text=True)
     report['ownedSocketCleanup'].append({'socket':str(sock.relative_to(work)),'exitCode':result.returncode})
   shutil.rmtree(work)
   report['cleanupComplete']=not work.exists()
  report['limits']=['WSL Linux checks; this does not qualify native macOS.','Residue fixtures intentionally stub dashboard discovery/server and test subjects while executing real runner/gate scripts.','The residue gate wraps the selected residue suite, not the full dashboard suite.','Passing digest8 tests retain the documented collision; no collision-free claim.']
  target=OUT/'local-result.json'
 report['ok']=all(c['exitCode']==0 for c in report['checks']) and report.get('sourceUnchanged',False) and report.get('copiedSourceMatches',False) and report['cleanupComplete']
 target.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8');print(json.dumps({'report':str(target),'ok':report['ok']}))
if __name__=='__main__':main()
