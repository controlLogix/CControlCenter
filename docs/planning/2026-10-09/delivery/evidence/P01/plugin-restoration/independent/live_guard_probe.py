"""Real private dashboard + detached shell worker guard; no provider or operator state."""
import os,sys,json,tempfile,subprocess,threading,shutil,argparse,hashlib,shlex
from pathlib import Path
from http.server import ThreadingHTTPServer
p=argparse.ArgumentParser();p.add_argument('--repo',type=Path,required=True);p.add_argument('--plugin',type=Path,required=True);p.add_argument('--result',type=Path,required=True);a=p.parse_args();a.repo=a.repo.resolve();a.plugin=a.plugin.resolve();a.result=a.result.resolve()
for k in list(os.environ):
 if k.startswith('AGENTMUX_') or k in ('TMUX','CC_ENFORCE','TM_ENFORCE','CODEX_HOME','CLAUDE_CONFIG_DIR'):os.environ.pop(k)
checks=[]
with tempfile.TemporaryDirectory(prefix='plugin-live-review-') as td:
 base=Path(td);home=base/'home';home.mkdir();state=home/'.agentmux';run=state/'run';run.mkdir(parents=True);repo=base/'private project';repo.mkdir();sock=base/'socket';sock.mkdir()
 os.environ.update(HOME=str(home),AGENTMUX_HOME=str(state),TMUX_TMPDIR=str(sock),PYTHONDONTWRITEBYTECODE='1');os.chdir(repo);sys.path.insert(0,str(a.repo/'dashboard'));import server
 http=ThreadingHTTPServer(('127.0.0.1',0),server.Handler);t=threading.Thread(target=http.serve_forever,daemon=True);t.start()
 installed=base/'relocated plugin';shutil.copytree(a.plugin,installed);env=dict(os.environ,AGENTMUX_DASHBOARD=f'http://127.0.0.1:{http.server_address[1]}',AGENTMUX_REPO=str(a.repo));shim=installed/'hooks/agentmux-hook.sh';launcher=installed/'skills/agent-config/scripts/runtime.py'
 def hook(event,value):return subprocess.run(['/bin/sh',str(shim),event],input=json.dumps({'tool_input':value}),env=env,capture_output=True,text=True,timeout=10)
 try:
  c=subprocess.run([sys.executable,str(launcher),'coordination','agentdef','repo','reviewer','--description','Synthetic live guard review','--cli','codex','--persona','Review only','--json'],env=env,capture_output=True,text=True,timeout=15);assert c.returncode==0,(c.stdout,c.stderr);checks.append('real-definition-created-via-relocated-launcher')
  frames=[{'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':'agent_roster','arguments':{'name':'reviewer'}}},{'jsonrpc':'2.0','id':2,'method':'tools/list'}]
  mcp=subprocess.run([sys.executable,str(installed/'bin/agentmux-plugin'),'mcp'],input='\n'.join(json.dumps(x) for x in frames)+'\n',env=env,capture_output=True,text=True,timeout=10)
  assert mcp.returncode==0 and not mcp.stderr,(mcp.stdout,mcp.stderr)
  replies=[json.loads(line) for line in mcp.stdout.splitlines()]; detail=json.loads(replies[0]['result']['content'][0]['text']);assert detail['name']=='reviewer' and detail['persona']=='Review only';assert {x['name'] for x in replies[1]['result']['tools']}=={'agent_roster','team_roster'};checks.append('real-MCP-definition-detail-and-readonly-discovery')
  subprocess.run(['tmux','-L','agentmux','new-session','-d','-s','review-worker','sleep 90'],env=env,check=True)
  (run/'review-worker.agentdef').write_text('reviewer')
  snapshot=server.agents_snapshot();worker=next(x for x in snapshot['agents'] if x['name']=='review-worker');assert worker['state']=='detached' and worker['agentdef']=='reviewer';checks.append('real-private-detached-worker-visible')
  for event,value in [('pre-bash',{'command':'python3 coordination.py agentdef repo reviewer'}),('pre-edit',{'file_path':str(repo/'.agentmux/agents/reviewer.md')}),('pre-bash',{'command':'rm '+shlex.quote(str(repo/'.agentmux/agents/reviewer.md'))})]:
   r=hook(event,value);assert r.returncode==2 and 'review-worker' in r.stderr,(r.returncode,r.stdout,r.stderr);checks.append('live-refusal:'+event+':'+str(value))
  r=hook('pre-edit',{'file_path':str(repo/'app.py')});assert r.returncode==0 and not r.stdout and not r.stderr;checks.append('unrelated-edit-allowed')
  subprocess.run(['tmux','-L','agentmux','kill-session','-t','review-worker'],env=env,check=True)
  r=hook('pre-edit',{'file_path':str(repo/'.agentmux/agents/reviewer.md')});assert r.returncode==0,(r.stdout,r.stderr);checks.append('stale-worker-edit-allowed')
 finally:
  subprocess.run(['tmux','-L','agentmux','kill-server'],env=env,capture_output=True);http.shutdown();http.server_close();t.join();os.chdir(a.repo)
 report={'checks':checks,'passed':len(checks),'limits':['Actual local HTTP/SQLite and detached tmux sleep worker only; no attached GUI client, AI provider, authentication or P06 qualification.','Hook invocation only; definition endpoint itself has no authoritative live-worker guard.'],'pluginHashes':{p.relative_to(a.plugin).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in a.plugin.rglob('*') if p.is_file() and '__pycache__' not in p.parts}}
 a.result.parent.mkdir(parents=True,exist_ok=True);a.result.write_text(json.dumps(report,indent=2)+'\n')
 print(json.dumps({'passed':len(checks)}))
