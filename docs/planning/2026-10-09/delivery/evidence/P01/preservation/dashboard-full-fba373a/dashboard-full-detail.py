import hashlib,json,os,subprocess,time,shutil,re
from pathlib import Path
w=Path('/home/ryan/.cache/agentmux-governance/p01-dashboard-full-vkqiqkjv');out=w/'evidence';p=out/'dashboard-full-result.json';d=json.loads(p.read_text());env=d['isolation'];env['PLAYWRIGHT_DIR']=str(w/'dependencies/node_modules/playwright');checks=[]
for name in ['test_orchestration_plugin.py','test_plugin_skills.py','test_gateway.py']:
 r=subprocess.run(['python3','dashboard/'+name],cwd=w/'checkout',env=env,capture_output=True,text=True,timeout=60)
 f=out/('dashboard-full-detail-'+name+'.log');f.write_text(r.stdout+r.stderr)
 checks.append({'name':name,'exitCode':r.returncode,'log':f.name,'sha256':hashlib.sha256(f.read_bytes()).hexdigest(),'skipLines':[x for x in (r.stdout+r.stderr).splitlines() if 'skip' in x.lower()]})
remaining=[]
for entry in Path('/proc').iterdir():
 if not entry.name.isdigit() or int(entry.name)==os.getpid():continue
 try:
  if str(w).encode() in (entry/'environ').read_bytes():remaining.append({'pid':int(entry.name),'command':(entry/'comm').read_text().strip()})
 except OSError:pass
d['followupSkipInspection']=checks;d['remainingOwnedProcessesAfterCleanup']=remaining
d['runnerLogSha256']=hashlib.sha256((out/'dashboard-full-runner.log').read_bytes()).hexdigest()
lines=(out/'dashboard-full-runner.log').read_text().splitlines();d['suiteResults']=[x for x in lines if re.match(r'^(test_|check_test_|smoke\.sh)',x)]
d['actualSuiteCount']=len(d['suiteResults']);d['zeroCheckSuites']=[x for x in d['suiteResults'] if 'passed 0,' in x]
d['versions']={}
for tool,args in [('node',['node','--version']),('tmux',['tmux','-V']),('codex',['codex','--version'])]:d['versions'][tool]=subprocess.check_output(args,env=env,text=True).strip()
d['versions']['playwright']='1.64.0'
d['status']='failed-with-explicit-missing-coverage';d['failures']=['test_field_panels.py:451 scan completion can precede concurrent-start rejection assertion','test_e2e.mjs:71 navigation order expectation differs from rendered rail'];d['testSourcesChanged']=False
for name in ['dashboard-full-run.py','dashboard-full-monitor.py']:
 source=Path('/mnt/c/Users/RyanHelms/AppData/Local/Temp')/name;shutil.copyfile(source,out/name)
d['harnessHashes']={f.name:hashlib.sha256(f.read_bytes()).hexdigest() for f in out.glob('dashboard-full-*.py')}
p.write_text(json.dumps(d,indent=2)+'\n');print(json.dumps({'actualSuites':d['actualSuiteCount'],'remainingProcesses':remaining,'skipDetails':checks}))
