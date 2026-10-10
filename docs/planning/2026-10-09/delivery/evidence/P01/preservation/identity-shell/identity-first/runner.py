import hashlib,io,json,os,pathlib,shlex,shutil,socket,subprocess,sys,tarfile,tempfile,time,traceback
P=pathlib.Path
repo=P('/mnt/c/Users/RyanHelms/GitHub/agentmux')
commit='a21f03a8a6792f4fa21099afe62804a56dfa7fc4'
root=P(tempfile.mkdtemp(prefix='identity-shell-',dir='/home/ryan/.cache/agentmux-governance'))
tree=root/'checkout'; tree.mkdir()
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
(root/'runner.py').write_bytes(P(__file__).read_bytes())
raw=subprocess.check_output(['git','archive',commit],cwd=repo)
with tarfile.open(fileobj=io.BytesIO(raw)) as archive:archive.extractall(tree,filter='data')
sources={str(p.relative_to(tree)):sha(p) for p in tree.rglob('*') if p.is_file()}
for n in ('home/.local/bin','state/hub','tmp','tmux','beta','codex','claude'): (root/n).mkdir(parents=True,exist_ok=True)
am=root/'home/.local/bin/agentmux';am.write_text('#!/bin/bash\nexec bash '+shlex.quote(str(tree/'agentmux.sh'))+' "$@"\n');am.chmod(0o700)
shell=root/'home/.local/bin/fixture-shell';shell.write_text('#!/bin/bash\nexec /bin/bash --noprofile --norc "$@"\n');shell.chmod(0o700)
env={'HOME':str(root/'home'),'AGENTMUX_HOME':str(root/'state'),'TMPDIR':str(root/'tmp'),'TMUX_TMPDIR':str(root/'tmux'),'CODEX_HOME':str(root/'codex'),'CLAUDE_CONFIG_DIR':str(root/'claude'),'PATH':str(am.parent)+':/home/ryan/.cache/agentmux-governance/venv/bin:/usr/bin:/bin','SHELL':str(shell),'LANG':'C.UTF-8','TERM':'xterm-256color','AGENTMUX_BIN':str(am),'AGENTMUX_REPO':str(tree),'AGENTMUX_NO_COURIER':'1','AGENTMUX_NO_TOAST':'1','AGENTMUX_IDLE_MINUTES':'0','PYTHONDONTWRITEBYTECODE':'1','GIT_CONFIG_NOSYSTEM':'1'}
(root/'state/hub/config.toml').write_text('node = "local"\nnats_url = ""\ntcp_port = 0\n')
report={'candidate':commit,'archiveSha256':hashlib.sha256(raw).hexdigest(),'sourceHashes':sources,'environment':env,'checks':[],'calls':[],'limits':['Real local hub and two shell tmux panes; no model providers, federation or native Windows execution.','Work result carries a JSON attachment descriptor with a local log path and SHA256; this is not a new artifact service.']}
def check(name,condition):
 report['checks'].append({'name':name,'passed':bool(condition)})
 assert condition,name
def call(verb,args=None,allow_error=False):
 with socket.socket(socket.AF_UNIX) as sock:
  sock.settimeout(15);sock.connect(str(root/'state/hub/hub.sock'));sock.sendall((json.dumps({'verb':verb,'args':args or {}})+'\n').encode());buf=b''
  while not buf.endswith(b'\n'):buf+=sock.recv(65536)
 r=json.loads(buf);report['calls'].append({'verb':verb,'args':args or {},'response':r})
 if not allow_error:assert r['ok'],r
 return r.get('result') if r['ok'] else r
def wait_for(fn,seconds=40):
 end=time.monotonic()+seconds
 while time.monotonic()<end:
  if fn():return
  time.sleep(.2)
 raise TimeoutError('fixture observation timed out')
def tmux(*args):return subprocess.run(['tmux','-L','agentmux',*args],env=env,capture_output=True,text=True,check=True)
sessions=[]
try:
 start=subprocess.run([str(am),'hub','start'],env=env,cwd=tree,capture_output=True,text=True,timeout=40);report['start']={'exit':start.returncode,'stdout':start.stdout,'stderr':start.stderr};check('hub started',start.returncode==0)
 for name,path in [('alpha',tree),('beta',root/'beta')]:
  call('repo_add',{'repo':name,'paths':[str(path)],'groups':['both']})
  result=call('spawn',{'repo':name,'role':'worker','agent':'same','cli':'shell'});sessions.append(result['session'])
 check('same local name produces distinct repo identities',sessions==['alpha-worker-same','beta-worker-same'])
 wait_for(lambda:all(not call('inbox',{'session':s})['messages'] for s in sessions))
 for target,expected in [('agent:alpha/worker/same',[sessions[0]]),('agent:beta/worker/same',[sessions[1]]),('agent:alpha-worker-same',[sessions[0]]),('role:alpha/worker',[sessions[0]]),('role:beta/worker',[sessions[1]]),('role:group:both/worker',sessions),('role:*/worker',sessions)]:
  check('resolve '+target,sorted(call('resolve',{'address':target})['recipients'])==sorted(expected))
  r=call('post',{'to':target,'kind':'note','body':'identity probe '+target});check('delivery recipients '+target,sorted(r['recipients'])==sorted(expected))
  wait_for(lambda:all(any(e['entity_id']==r['id']+'>'+s and e['event']=='acked' for e in call('events',{'entity':'delivery','limit':1000})) for s in expected))
  check('actual pane acknowledgement '+target,True)
 check('bare shared local name refused',not call('post',{'to':'same','kind':'note','body':'must not route'},True)['ok'])
 work=call('work_add',{'to':'role:alpha/worker','title':'Run unchanged orchtest acceptance suite','body':'Run exact checkout orchtest, return count, source revision and log digest.'})
 worker=root/'worker.py'
 worker.write_text('''import sys,json,pathlib,unittest,hashlib,traceback
tree,out,wid,revision,mode=sys.argv[1:];sys.path.insert(0,tree)
from hub.cli import call
p=pathlib.Path(out);result={}
try:
 result['whoami']=call('whoami',{})
 result['claim']=call('claim',{'work_id':wid})
 if mode=='run':
  assert result['claim']['result']['claimed']['id']==wid
  suite=unittest.defaultTestLoader.discover(str(pathlib.Path(tree)/'orchtest'),pattern='test_*.py',top_level_dir=tree)
  log=p.with_suffix('.log')
  with log.open('w') as stream:r=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
  attachment={'sourceRevision':revision,'tests':r.testsRun,'failures':len(r.failures),'errors':len(r.errors),'skips':len(r.skipped),'logPath':str(log),'logSha256':hashlib.sha256(log.read_bytes()).hexdigest()}
  assert r.wasSuccessful() and r.testsRun==28 and not r.skipped
  result['attachment']=attachment
  result['done']=call('release',{'work_id':wid,'outcome':'done','result':json.dumps(attachment)})
except Exception:result['failure']=traceback.format_exc()
p.write_text(json.dumps(result,indent=2))
''')
 for s,mode in [(sessions[1],'wrong-repo'),(sessions[0],'run')]:
  output=root/(mode+'.json');command=shlex.join([sys.executable,str(worker),str(tree),str(output),work['id'],commit,mode]);tmux('send-keys','-t',s,'-l',command);tmux('send-keys','-t',s,'Enter');wait_for(output.exists,45);r=json.loads(output.read_text());check(mode+' pane ran without exception','failure' not in r);check(mode+' native identity',r['whoami']['result']['caller']==s)
  if mode=='wrong-repo':check('beta cannot claim alpha work',r['claim']['result']['claimed'] is None)
 final=call('work_show',{'work_id':work['id']});check('operator sees alpha completion',final['state']=='done' and final['claimed_by']==sessions[0]);attachment=json.loads(final['result']);check('operator verifies real log digest',sha(P(attachment['logPath']))==attachment['logSha256']);check('operator verifies source and count',attachment['sourceRevision']==commit and attachment['tests']==28 and attachment['errors']==attachment['failures']==attachment['skips']==0)
 report['completedWork']=final;report['workerScriptSha256']=sha(worker)
except Exception:report['failure']=traceback.format_exc()
finally:
 for s in sessions:
  try:report.setdefault('killed',[]).append(call('kill',{'session':s}))
  except Exception as e:report.setdefault('cleanupErrors',[]).append(str(e))
 try:call('shutdown')
 except Exception:pass
 for sock in (root/'tmux').rglob('*'):
  if sock.is_socket():subprocess.run(['tmux','-S',str(sock),'kill-server'],env=env,capture_output=True)
 time.sleep(2)
 report['remainingSidecars']=[str(p) for s in sessions for p in (root/'state/run').glob(s+'.*')]
 report['sourceUnchanged']=all(sha(tree/n)==v for n,v in sources.items())
 report['success']=not report.get('failure') and report['sourceUnchanged'] and not report['remainingSidecars']
 (root/'result.json').write_text(json.dumps(report,indent=2));print(json.dumps({'root':str(root),'success':report['success'],'failure':report.get('failure'),'checks':len(report['checks'])}))
