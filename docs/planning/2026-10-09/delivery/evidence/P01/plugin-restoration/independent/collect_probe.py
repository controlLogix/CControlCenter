import os,sys,json,tempfile,subprocess,shutil,hashlib
from pathlib import Path
repo=Path(sys.argv[1]).resolve(); out=Path(sys.argv[2]).resolve(); package=repo/'plugins/agentmux-orchestration';records=[]
for key in list(os.environ):
 if key.startswith('AGENTMUX_') or key in ('CC_ENFORCE','TM_ENFORCE','CODEX_HOME','CLAUDE_CONFIG_DIR','GIT_DIR','GIT_WORK_TREE'):os.environ.pop(key)
bridge=r"""import sys,json,importlib.util
from pathlib import Path
cfg=json.loads(Path(__file__).with_name('fixture.json').read_text())
spec=importlib.util.spec_from_file_location('actual_dispatch',cfg['source']);d=importlib.util.module_from_spec(spec);spec.loader.exec_module(d)
d.REPO=Path(cfg['repo']);events=[]
d.entity=lambda key:cfg['task']
d.live_agents=lambda:dict.fromkeys(cfg['live'],{})
d.board=lambda *a,**kw:{'members':cfg['members']}
d.release_all=lambda *a,**kw:events.append(['release',a[0]]) or True
def mux(*args,**kw):
 events.append(['agentmux',*args]);return (cfg['states'].get(args[1],0) if args[0]=='wait' else 0,'','')
d.agentmux=mux
d.comment=lambda *a,**kw:events.append(['comment',*a]) or {}
d.set_status=lambda *a,**kw:events.append(['status',*a]) or {}
rc=d.main(sys.argv[1:]);Path(cfg['events']).write_text(json.dumps(events));sys.exit(rc)
"""
with tempfile.TemporaryDirectory(prefix='plugin-collect-review-') as temp:
 base=Path(temp); installed=base/'relocated plugin';shutil.copytree(package,installed); launcher=installed/'skills/agent-config/scripts/runtime.py'
 for case in ['success','wrong-branch','dirty-lead','dirty-member','unmanaged','conflict','absent-evidence','busy-member']:
  root=base/case;root.mkdir();lead=root/'lead';lead.mkdir();member=root/'member';runtime=root/'trusted fixture runtime';(runtime/'taskmgmt').mkdir(parents=True);(runtime/'taskmgmt/dispatch.py').write_text(bridge)
  env=dict(os.environ,HOME=str(root/'home'),AGENTMUX_HOME=str(root/'state'),AGENTMUX_REPO=str(runtime),PYTHONDONTWRITEBYTECODE='1',GIT_CONFIG_NOSYSTEM='1',GIT_CONFIG_GLOBAL='/dev/null');Path(env['HOME']).mkdir()
  def git(*args,cwd=lead):
   r=subprocess.run(['git','-C',str(cwd),*args],env=env,capture_output=True,text=True,timeout=20);assert r.returncode==0,(args,r.stderr);return r.stdout.strip()
  git('init','-b','integration');git('config','user.name','Fixture');git('config','user.email','fixture@example.invalid');(lead/'shared.txt').write_text('base\n');git('add','.');git('commit','-m','base')
  branch='unmanaged' if case=='unmanaged' else 'agentmux/tm-900-worker';git('worktree','add','-b',branch,str(member));(member/'result.txt').write_text('member result\n');git('add','.',cwd=member);git('commit','-m','member',cwd=member)
  if case=='dirty-lead':(lead/'dirty.txt').write_text('keep lead')
  if case=='dirty-member':(member/'dirty.txt').write_text('keep member')
  if case=='conflict':
   (member/'shared.txt').write_text('member conflict\n');git('add','.',cwd=member);git('commit','-m','member conflict',cwd=member);(lead/'shared.txt').write_text('lead conflict\n');git('add','.');git('commit','-m','lead conflict')
  original=git('rev-parse','HEAD'); tip=git('rev-parse',branch)
  cfg={'source':str(repo/'taskmgmt/dispatch.py'),'repo':str(lead),'events':str(root/'events.json'),'task':{'id':'TM-900','status':'in_progress','worktree':str(lead),'branch':'expected-other' if case=='wrong-branch' else 'integration','evidence':[] if case=='absent-evidence' else ['fixture-result'],'touches':[]},'members':[{'member_name':'tm-900-worker','worktree':str(member),'branch':branch}],'live':['tm-900','tm-900-worker'],'states':{'tm-900':0,'tm-900-worker':2 if case=='busy-member' else 0}}
  fixture=runtime/'taskmgmt/fixture.json';fixture.write_text(json.dumps(cfg))
  r=subprocess.run([sys.executable,str(launcher),'dispatch','collect','TM-900'],env=env,capture_output=True,text=True,timeout=30);expected='submitted' if case=='success' else 'parked' if case=='conflict' else 'working' if case in ('absent-evidence','busy-member') else 'unresolved';assert r.returncode==0 and r.stdout.strip().splitlines()[-1]=='TM-900: '+expected,(case,r.stdout,r.stderr)
  events=json.loads((root/'events.json').read_text());assert not any(e[:3]==['status','TM-900','done'] for e in events)
  if case=='success':
   assert (lead/'result.txt').read_text()=='member result\n' and not member.exists() and not git('branch','--list',branch)
   cfg['live']=['tm-900'];fixture.write_text(json.dumps(cfg));repeat=subprocess.run([sys.executable,str(launcher),'dispatch','collect','TM-900'],env=env,capture_output=True,text=True,timeout=30);assert repeat.returncode==0 and repeat.stdout.strip().splitlines()[-1]=='TM-900: submitted';assert (lead/'result.txt').exists();records.append({'case':'repeat','outcome':'submitted','assertion':'already integrated missing branch/tree handled without data loss'})
  else:
   assert member.exists() and git('rev-parse',branch)==tip and git('rev-parse','HEAD')==original
   assert not (lead/'.git/MERGE_HEAD').exists()
   if case.startswith('dirty-'):assert ((lead if case=='dirty-lead' else member)/'dirty.txt').exists()
   if case in ('absent-evidence','busy-member'):assert not any(e[:2]==['agentmux','kill'] for e in events)
  records.append({'case':case,'outcome':expected,'events':events,'stdout':r.stdout,'assertion':'real Git merge/cleanup verified' if case=='success' else 'member commits/tree and original lead HEAD retained'})
 report={'passed':len(records),'cases':records,'sourceHashes':{p:hashlib.sha256((repo/p).read_bytes()).hexdigest() for p in ['taskmgmt/dispatch.py','taskmgmt/coordination.py','plugins/agentmux-orchestration/skills/agent-config/scripts/runtime.py']},'limits':['Relocated unchanged plugin launcher invokes disposable trusted runtime adapter importing unchanged actual dispatch implementation.','Actual main/collect/integrate/teardown and Git repositories/worktrees/commits; board/pane/claim transports replaced by explicit fixture functions. No real provider, dashboard, authentication or host integration qualification.','Repeated collect uses retained roster, already removed member branch/tree, and synthetic live idle lead; it does not claim real-pane repeat behavior.']}
 out.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps({'passed':len(records)}))
