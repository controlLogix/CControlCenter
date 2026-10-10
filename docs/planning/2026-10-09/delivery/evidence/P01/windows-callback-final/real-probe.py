import os,sys,json,tempfile,subprocess,socket,time,hashlib,shutil
from pathlib import Path
source=Path('/mnt/c/Users/RyanHelms/GitHub/agentmux');repo=source;sys.path.insert(0,str(repo))
from hub.store import Store
base=Path(tempfile.mkdtemp(prefix='callback-real-',dir='/home/ryan/.cache/agentmux-governance'))
home=base/'home';home.mkdir();state=home/'.agentmux';(state/'hub').mkdir(parents=True)
s=socket.socket();s.bind(('127.0.0.1',0));port=s.getsockname()[1];s.close()
(state/'hub/config.toml').write_text(f'tcp_port = {port}\npoll_s = 10000\n')
st=Store(str(state/'hub/hub.db'));st.repo_add('alpha',paths=[str(base)])
tokens={}
for name in ('one','two'):
 token=os.urandom(32).hex();session=st.register('alpha','worker',name,'shell',{'capabilities':[],'max_active':1,'lease_s':900},token_sha=hashlib.sha256(token.encode()).hexdigest());st.set_state(session,'ready');p=base/(name+'.token');p.write_text(token);p.chmod(0o600);tokens[name]=p
st.db.close()
wrapper=base/'agentmux';wrapper.write_text('#!/bin/sh\nexec '+sys.executable+' '+str(repo/'hub/cli.py')+' "${@:2}"\n'.replace('${@:2}','${@:2}'))
# POSIX shift, avoiding shell argument reconstruction.
wrapper.write_text('#!/bin/sh\n[ "$1" = hub ] || exit 2\nshift\nexec '+sys.executable+' '+str(repo/'hub/cli.py')+' "$@"\n');wrapper.chmod(0o700)
native=base/'checkout';native.mkdir()
for src in source.iterdir():
 if src.is_file():
  dst=native/src.name;shutil.copy2(src,dst)
  if src.suffix=='.sh':dst.write_bytes(dst.read_bytes().replace(b'\r\n',b'\n'))
shutil.copytree(source/'hub',native/'hub',ignore=shutil.ignore_patterns('__pycache__'))
(repo_script:=native/'agentmux.sh').chmod(0o700)
repo=native
env={k:v for k,v in os.environ.items() if not k.startswith('AGENTMUX_')};env.update(HOME=str(home),AGENTMUX_HOME=str(state),AGENTMUX_SOCKET='agentmux',TMUX_TMPDIR=str(base),AGENTMUX_BIN=str(repo_script),AGENTMUX_WINDOWS_CALLBACKS='1',AGENTMUX_WSL_DISTRO='Ubuntu-26.04')
log=open(base/'hub.log','w');p=subprocess.Popen([sys.executable,str(repo/'hub/server.py')],env=env,stdout=log,stderr=log)
node='/mnt/c/nvm4w/nodejs/node.exe';py='C:/Users/RyanHelms/AppData/Local/Programs/Python/Python314/python.exe';helper='C:/Users/RyanHelms/GitHub/agentmux/agentmux_windows.py'
results=[]
def callback(name,args,changes={}):
 e=dict(env);e.update(AGENTMUX_WINDOWS_CALLBACK='1',AGENTMUX_HUB_URL=f'tcp://127.0.0.1:{port}',AGENTMUX_HUB_TOKEN_FILE=str(tokens[name]),AGENTMUX_AGENT='spoofed',AGENTMUX_WSL_DISTRO='Ubuntu-26.04',AGENTMUX_WSL_BIN=str(wrapper),AGENTMUX_WSL_CWD=str(base));e.update(changes)
 keys=['AGENTMUX_WINDOWS_CALLBACK','AGENTMUX_HUB_URL','AGENTMUX_AGENT','AGENTMUX_WSL_DISTRO','AGENTMUX_WSL_BIN','AGENTMUX_WSL_CWD'];paths=['AGENTMUX_HUB_TOKEN_FILE','AGENTMUX_HOME','TMUX_TMPDIR']
 e['WSLENV']=':'.join(keys+[x+'/p' for x in paths])
 js='const c=require("child_process").spawnSync('+json.dumps(py)+','+json.dumps([helper,'hub',*args])+',{encoding:"utf8",env:process.env});process.stdout.write(JSON.stringify({code:c.status,out:c.stdout,err:c.stderr}));'
 r=subprocess.run([node,'-e',js],env=e,capture_output=True,text=True,timeout=20);return json.loads(r.stdout)
try:
 for _ in range(100):
  try:
   c=socket.create_connection(('127.0.0.1',port),timeout=.1);c.close();break
  except OSError:time.sleep(.1)
 def operator(*args):
  r=subprocess.run([sys.executable,str(repo/'hub/cli.py'),*args],env=env,capture_output=True,text=True,timeout=120)
  assert r.returncode==0,(args,r.stdout,r.stderr)
  return r
 for agent in ('paneone','panetwo'):
  operator('spawn','alpha','worker',agent,'--cli','shell')
  session='alpha-worker-'+agent
  outfile=base/(agent+'.json')
  code='import os,json;open('+repr(str(outfile))+',"w").write(json.dumps({k:v for k,v in os.environ.items() if k in ["AGENTMUX_SPAWN_WINDOWS_CALLBACK","AGENTMUX_WINDOWS_CALLBACK","AGENTMUX_HUB_URL","AGENTMUX_HUB_TOKEN_FILE","AGENTMUX_HUB_TOKEN"]}))'
  import shlex
  subprocess.run(['tmux','-L','agentmux','send-keys','-t',session,shlex.join(['python3','-c',code]),'Enter'],env=env,check=True)
  for _ in range(100):
   if outfile.exists():break
   time.sleep(.1)
  actual=json.loads(outfile.read_text());assert actual['AGENTMUX_HUB_TOKEN_FILE'].endswith('/worker-'+agent+'/run/token'),actual;assert 'AGENTMUX_HUB_TOKEN' not in actual,actual;assert 'AGENTMUX_SPAWN_WINDOWS_CALLBACK' not in actual,actual
  results.append({'case':'real-pane-'+agent,'env':actual})
  tokens[agent]=Path(actual['AGENTMUX_HUB_TOKEN_FILE'])
 native_env={k:v for k,v in env.items() if k not in ('AGENTMUX_WINDOWS_CALLBACK','AGENTMUX_SPAWN_WINDOWS_CALLBACK','AGENTMUX_HUB_URL','AGENTMUX_HUB_TOKEN_FILE')}
 r=subprocess.run([str(repo_script),'spawn','native_after','--cli','shell','--cwd',str(base)],env=native_env,capture_output=True,text=True,timeout=120);assert r.returncode==0,(r.stdout,r.stderr)
 outfile=base/'native_after.json'
 code='import os,json;open('+repr(str(outfile))+',"w").write(json.dumps({k:v for k,v in os.environ.items() if k in ["AGENTMUX_SPAWN_WINDOWS_CALLBACK","AGENTMUX_WINDOWS_CALLBACK","AGENTMUX_HUB_TOKEN_FILE"]}))'
 subprocess.run(['tmux','-L','agentmux','send-keys','-t','native_after',shlex.join(['python3','-c',code]),'Enter'],env=env,check=True)
 for _ in range(100):
  if outfile.exists():break
  time.sleep(.1)
 actual=json.loads(outfile.read_text());assert actual=={},actual;results.append({'case':'native-after-callback-no-markers-or-token','env':actual})
 for name in tokens:
  r=callback(name,['whoami']);assert r['code']==0 and r['out'].startswith('alpha-worker-'+name),r;results.append({'case':'identity-'+name,**r})
 work=json.loads(operator('--json','work','add','--to','agent:alpha-worker-paneone','--title','safe callback proof').stdout)['id']
 r=callback('paneone',['--json','claim',work]);assert r['code']==0,r;results.append({'case':'claim-own-work',**r})
 r=callback('panetwo',['done',work,'--result','wrong owner']);assert r['code']!=0,r;results.append({'case':'reject-other-agent-completion',**r})
 r=callback('paneone',['done',work,'--result','safe callback proof complete']);assert r['code']==0,r;results.append({'case':'complete-own-work',**r})
 operator('kill','alpha-worker-panetwo')
 r=callback('panetwo',['whoami']);assert r['code']!=0 and 'invalid or revoked' in r['err'],r;results.append({'case':'revoked-agent',**r})
 r=callback('one',['--as','alpha-worker-two','whoami']);assert r['code']==0 and r['out'].startswith('alpha-worker-one'),r;results.append({'case':'spoof-as-ignored',**r})
 for changes in ({'AGENTMUX_HUB_URL':''},{'AGENTMUX_HUB_URL':'unix:///tmp/wrong'},{'AGENTMUX_HUB_TOKEN_FILE':str(base/'missing.token')}):
  r=callback('one',['whoami'],changes);assert r['code']!=0,r;results.append({'case':'invalid-context',**r})
 r=callback('one',['start']);assert r['code']!=0,r;results.append({'case':'no-daemon',**r})
 tokens['one'].write_text('wrong-token');r=callback('one',['whoami']);assert r['code']!=0 and 'invalid or revoked' in r['err'],r;results.append({'case':'wrong-token',**r})
finally:
 subprocess.run(['tmux','-L','agentmux','kill-server'],env=env,capture_output=True)
 p.terminate();p.wait(timeout=10);log.close()
 (base/'result.json').write_text(json.dumps({'results':results,'hubExited':p.poll() is not None,'sourceHashes':{f:hashlib.sha256((repo/f).read_bytes()).hexdigest() for f in ['agentmux.cmd','agentmux_windows.py','hub/cli.py','hub/server.py','agentmux.sh']},'limitations':['Two real shell panes and two pre-registered identities; no provider execution.','Windows Python helper used; batch shell parser not tested.']},indent=2))
 for path in tokens.values():path.unlink(missing_ok=True)
 shutil.rmtree(home)
 print(base)
