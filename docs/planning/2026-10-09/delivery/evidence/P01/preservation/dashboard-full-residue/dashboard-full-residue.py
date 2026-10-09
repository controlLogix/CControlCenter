import hashlib,json,subprocess,time,shutil
from pathlib import Path
w=Path('/home/ryan/.cache/agentmux-governance/p01-dashboard-full-vkqiqkjv');out=w/'dashboard-full-residue';out.mkdir(exist_ok=True);repo=Path('/mnt/c/Users/RyanHelms/GitHub/agentmux');checkout=w/'checkout';env=json.loads((w/'evidence/dashboard-full-result.json').read_text())['isolation'];source=repo/'dashboard/test_residue.sh';target=checkout/'dashboard/test_residue.sh'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
old=sha(target);new=source.read_bytes();shutil.copyfile(source,target);report={'originalSha256':old,'replacementSha256':sha(source),'checks':[],'retention':'Original26checks retained; only curl readiness stub waits for server startup record. Original start-failure exit7 retained.','limits':['Focused fixture qualification, not full dashboard acceptance.']}
try:
 for mode in ['positive1','positive2','controlled-startup-delay']:
  if mode.startswith('controlled'):
   text=new.decode();needle="with (root / 'servers').open('a') as f:";assert text.count(needle)==1;target.write_text(text.replace(needle,"time.sleep(0.5)  # disposable startup-delay probe\n"+needle))
  start=time.monotonic();r=subprocess.run(['bash','dashboard/test_residue.sh'],cwd=checkout,env=env,capture_output=True,text=True,timeout=240);log=out/(mode+'.log');log.write_text(r.stdout+r.stderr);report['checks'].append({'mode':mode,'exitCode':r.returncode,'seconds':round(time.monotonic()-start,3),'logSha256':sha(log),'tail':(r.stdout+r.stderr).splitlines()[-5:]});print(json.dumps(report['checks'][-1]),flush=True)
finally:target.write_bytes(new)
report['allPassed']=all(x['exitCode']==0 for x in report['checks']);report['copiedSourceRestored']=sha(target)==sha(source);report['harnessSha256']=sha(Path(__file__));(out/'dashboard-full-residue-result.json').write_text(json.dumps(report,indent=2)+'\n');shutil.copyfile(__file__,out/'dashboard-full-residue.py')
