import hashlib,json,os,signal,subprocess,threading,time,shutil,re
from pathlib import Path
w=Path('/home/ryan/.cache/agentmux-governance/p01-dashboard-full-vkqiqkjv');out=w/'dashboard-full-repaired';out.mkdir(exist_ok=True);repo=Path('/mnt/c/Users/RyanHelms/GitHub/agentmux');old=json.loads((w/'evidence/dashboard-full-result.json').read_text());env=old['isolation'];env['PLAYWRIGHT_DIR']=str(w/'dependencies/node_modules/playwright');checkout=w/'checkout'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
report={'candidateBase':old['candidate'],'overlays':{},'isolation':env,'versions':old['versions'],'checks':[],'limits':['External orchestration plugin absent: two suites skip16+4tests; not pass.','Python3.14 archivedgateway differential unavailable; separate3.12evidence retained.','Full repaired dashboard run is not phase acceptance.']}
for name in ['dashboard/test_field_panels.py','dashboard/test_e2e.mjs','hub/names.py','hub/tests/test_hub_offline.py']:
 original=subprocess.check_output(['git','show',old['candidate']+':'+name],cwd=checkout)
 shutil.copyfile(repo/name,checkout/name)
 report['overlays'][name]={'baselineSha256':hashlib.sha256(original).hexdigest(),'replacementSha256':sha(repo/name),'copiedSourceMatches':sha(repo/name)==sha(checkout/name)}
report['sourceHashes']={n:sha(checkout/n) for n in old['sourceHashes']}
stop=threading.Event()
def monitor():
 handles={}
 with (out/'dashboard-full-runner.log').open('wb') as dest:
  while not stop.is_set():
   for path in (w/'tmp').glob('*/suite.log'):
    if path not in handles:
     try:handles[path]=path.open('rb')
     except OSError:continue
   for src in handles.values():dest.write(src.read());dest.flush()
   for f in (w/'tmp').glob('agentmux-gate-fail-*.out'):
    # Previous failures remain preserved in the original evidence directory.
    if f.stat().st_mtime >= started_epoch:shutil.copyfile(f,out/f.name)
   time.sleep(.1)
  for src in handles.values():dest.write(src.read());src.close()
started_epoch=time.time();thread=threading.Thread(target=monitor);thread.start();started=time.monotonic()
with (out/'dashboard-full-wrapper.log').open('w') as stream:
 child=subprocess.Popen(['bash','dashboard/check_test_residue.sh','--root',env['AGENTMUX_HOME'],'--','bash','dashboard/run_tests.sh'],cwd=checkout,env=env,stdout=stream,stderr=subprocess.STDOUT,start_new_session=True)
 try:rc=child.wait(timeout=2700)
 except subprocess.TimeoutExpired:
  os.killpg(child.pid,signal.SIGTERM)
  try:child.wait(timeout=15)
  except subprocess.TimeoutExpired:os.killpg(child.pid,signal.SIGKILL);child.wait()
  rc=124
stop.set();thread.join();report['exitCode']=rc;report['seconds']=round(time.monotonic()-started,3)
report['sourceUnchanged']=all(sha(checkout/n)==v for n,v in report['sourceHashes'].items())
report['workingTreeMatchesOverlay']=all(sha(repo/n)==v['replacementSha256'] for n,v in report['overlays'].items())
report['suiteResults']=[x for x in (out/'dashboard-full-runner.log').read_text().splitlines() if re.match(r'^(test_|check_test_|smoke\.sh)',x)]
report['actualSuiteCount']=len(report['suiteResults']);report['zeroCheckSuites']=[x for x in report['suiteResults'] if 'passed 0,' in x]
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
report['logs']={p.name:sha(p) for p in out.glob('*.log')};report['harnessSha256']=sha(Path(__file__))
(out/'dashboard-full-repaired-result.json').write_text(json.dumps(report,indent=2)+'\n');shutil.copyfile(__file__,out/'dashboard-full-repaired.py');print(json.dumps({'exitCode':rc,'seconds':report['seconds'],'actualSuites':report['actualSuiteCount'],'out':str(out)}))
