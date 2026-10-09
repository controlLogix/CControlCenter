import hashlib,json,os,signal,subprocess,time,shutil,socket,urllib.request
from pathlib import Path
w=Path('/home/ryan/.cache/agentmux-governance/p01-dashboard-full-vkqiqkjv');out=w/'dashboard-full-mqtt';out.mkdir(exist_ok=True);repo=Path('/mnt/c/Users/RyanHelms/GitHub/agentmux');checkout=w/'checkout';d=json.loads((w/'evidence/dashboard-full-result.json').read_text());env=d['isolation'];source=repo/'dashboard/test_mqtt.py';target=checkout/'dashboard/test_mqtt.py'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
old=sha(target);shutil.copyfile(source,target);orig=(checkout/'dashboard/mqtt.py').read_bytes();report={'originalTestSha256':old,'replacementTestSha256':sha(source),'productionMqttSha256':hashlib.sha256(orig).hexdigest(),'checks':[],'retention':'All original assertions retained. Move bounded DISCONNECT observation before exact CONNECT/PUBLISH packet counts; no production protocol change.'}
for mode in ['positive1','positive2','negative-suppress-publish']:
 mqtt=checkout/'dashboard/mqtt.py'
 if mode.startswith('negative'):
  text=orig.decode();needle='self._send(_packet(PUBLISH, 0, _string(topic) + raw))';assert text.count(needle)==1;mqtt.write_text(text.replace(needle,'pass  # Deliberately broken disposable negative fixture: no PUBLISH sent.'))
 with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
 state=w/('mqtt-'+mode);state.mkdir(exist_ok=True);runenv=dict(env,AGENTMUX_HOME=str(state),AGENTMUX_BASE_URL='http://127.0.0.1:'+str(port));serverlog=(out/(mode+'-server.log')).open('w');server=subprocess.Popen(['python3','dashboard/server.py','--port',str(port)],cwd=checkout,env=runenv,stdout=serverlog,stderr=subprocess.STDOUT,start_new_session=True)
 try:
  for _ in range(100):
   try:urllib.request.urlopen(runenv['AGENTMUX_BASE_URL'],timeout=.5).close();break
   except OSError:time.sleep(.1)
  started=time.monotonic();r=subprocess.run(['python3','dashboard/test_mqtt.py'],cwd=checkout,env=runenv,capture_output=True,text=True,timeout=120);log=out/(mode+'.log');log.write_text(r.stdout+r.stderr);failed=[x for x in (r.stdout+r.stderr).splitlines() if 'FAIL' in x];report['checks'].append({'mode':mode,'exitCode':r.returncode,'seconds':round(time.monotonic()-started,3),'logSha256':sha(log),'failureLines':failed,'tail':(r.stdout+r.stderr).splitlines()[-3:]})
 finally:
  os.killpg(server.pid,signal.SIGTERM)
  try:server.wait(timeout=10)
  except subprocess.TimeoutExpired:os.killpg(server.pid,signal.SIGKILL);server.wait()
  serverlog.close();mqtt.write_bytes(orig)
report['positivePass']=all(x['exitCode']==0 for x in report['checks'][:2]);report['negativeRejected']=report['checks'][2]['exitCode']!=0 and any('broker got exactly one PUBLISH' in x for x in report['checks'][2]['failureLines']);report['productionRestored']=sha(checkout/'dashboard/mqtt.py')==hashlib.sha256(orig).hexdigest();report['workingSourceUnchanged']=sha(source)==report['replacementTestSha256'];report['harnessSha256']=sha(Path(__file__));(out/'dashboard-full-mqtt-result.json').write_text(json.dumps(report,indent=2)+'\n');shutil.copyfile(__file__,out/'dashboard-full-mqtt.py');print(json.dumps(report))
