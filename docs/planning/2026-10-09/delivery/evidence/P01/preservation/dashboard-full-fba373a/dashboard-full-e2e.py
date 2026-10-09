import hashlib,json,os,signal,subprocess,time,shutil
from pathlib import Path
w=Path('/home/ryan/.cache/agentmux-governance/p01-dashboard-full-vkqiqkjv');out=w/'evidence';repo=Path('/mnt/c/Users/RyanHelms/GitHub/agentmux');d=json.loads((out/'dashboard-full-result.json').read_text());env=d['isolation'];env['PLAYWRIGHT_DIR']=str(w/'dependencies/node_modules/playwright')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
source=repo/'dashboard/test_e2e.mjs';target=w/'checkout/dashboard/test_e2e.mjs';old=sha(target);shutil.copyfile(source,target);started=time.monotonic();log=out/'dashboard-full-focused-e2e.log'
with log.open('w') as stream:
 p=subprocess.Popen(['bash','dashboard/test_e2e.sh'],cwd=w/'checkout',env=env,stdout=stream,stderr=subprocess.STDOUT,start_new_session=True)
 try:rc=p.wait(timeout=300)
 except subprocess.TimeoutExpired:os.killpg(p.pid,signal.SIGTERM);p.wait(timeout=20);rc=124
report={'candidateBase':d['candidate'],'command':['bash','dashboard/test_e2e.sh'],'exitCode':rc,'seconds':round(time.monotonic()-started,3),'changedSource':'dashboard/test_e2e.mjs','originalSha256':old,'replacementSha256':sha(source),'copiedSourceMatches':sha(source)==sha(target),'logSha256':sha(log),'retention':'Strict deepEqual retained; expected list adds existing Federation view after Hub, introduced by3aec6c03; no product capability removed.','tail':log.read_text(errors='replace').splitlines()[-8:],'limits':['Focused browser run; full candidate rerun remains separate.']}
(out/'dashboard-full-focused-e2e.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))
