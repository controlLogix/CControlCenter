import hashlib,importlib.util,json,os,subprocess
from pathlib import Path
from datetime import datetime,timezone
root=Path('C:/Users/RyanHelms/GitHub/agentmux');archive=root/'docs/planning/2026-10-09/delivery/evidence/P01/windows-clients'
out=Path('C:/Users/RyanHelms/.cache/agentmux/p01-wsl-inventory');out.mkdir(parents=True,exist_ok=True)
clients=json.loads((archive/'clients.json').read_text());entries=[]
def windows(path):
 assert path.startswith('/mnt/c/')
 return 'C:/'+path[len('/mnt/c/'):]
env={k:v for k,v in os.environ.items() if k.upper() in ('SYSTEMROOT','WINDIR','TEMP','TMP','USERPROFILE','APPDATA','LOCALAPPDATA','PATH','PROGRAMFILES','PROGRAMFILES(X86)','PROGRAMDATA')}
for name,client in clients.items():
 exe=windows(client['exe']);target=windows(client.get('script',client['exe']));launcher='/usr/local/bin/'+name
 direct=[exe]+([target] if target!=exe else [])+['--version']
 probes=[]
 for surface,command,actual in [('windows',direct,direct),('wsl',[launcher,'--version'],['wsl.exe','-d','Ubuntu-26.04','--user','ryan','--exec',launcher,'--version'])]:
  r=subprocess.run(actual,env=env,cwd=root,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,timeout=30)
  log={'surface':surface,'command':actual,'exitCode':r.returncode,'stdout':r.stdout,'stderr':r.stderr}
  data=(json.dumps(log,indent=2)+'\n').encode();(out/(name+'-'+surface+'.json')).write_bytes(data)
  probes.append({'surface':surface,'command':command,'exitCode':r.returncode,'version':r.stdout.strip() if r.returncode==0 else None,'installation':target,'executable':exe,'evidenceSha256':hashlib.sha256(data).hexdigest()})
 entries.append({'id':name,'status':'observed' if all(p['exitCode']==0 for p in probes) else 'unavailable','searchScope':'Seven installations from the reviewed Windows client map; not an exhaustive machine inventory','installationOwner':'windows','configOwner':'windows','authOwner':'windows','credentialsCopied':False,'linuxDuplicateInstalled':False,'stableTarget':target,'executableTarget':exe,'launcher':launcher,'probes':probes,'interopLimits':['Version probes only; authenticated inference, hub callbacks, concurrent sessions and final unchanged-launcher update remain unverified.','Default Windows configuration ownership follows invocation of the same installation without HOME/config overrides; credentials were not inspected.']})
entries.append({'id':'pi','status':'missing','searchScope':'Previous Windows PATH and npm/bin paths inspected in Windows client setup evidence; no exhaustive machine search','installationOwner':None,'configOwner':None,'authOwner':None,'credentialsCopied':False,'linuxDuplicateInstalled':False,'stableTarget':None,'executableTarget':None,'launcher':None,'probes':[],'interopLimits':['Not found within the recorded search scope; no support claim.']})
record={'schemaVersion':1,'kind':'observation','platform':'wsl','runtime':'linux','observedAt':datetime.now(timezone.utc).isoformat(),'candidateCommit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip(),'p06Accepted':False,'limits':['authenticated_workflows_unverified','hub_callbacks_unverified','concurrent_sessions_unverified','unchanged_launcher_update_unverified'],'clients':entries}
spec=importlib.util.spec_from_file_location('inventory',root/'tests/platform/inventory.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
errors=m.validate(record)
(out/'inventory.json').write_bytes((json.dumps(record,indent=2)+'\n').encode())
(out/'validation.json').write_bytes((json.dumps({'validInventory':not errors,'errors':errors,'p06Accepted':False,'validatorSha256':hashlib.sha256((root/'tests/platform/inventory.py').read_bytes()).hexdigest()},indent=2)+'\n').encode())
print(json.dumps({'validInventory':not errors,'errors':errors,'clients':[{ 'id':e['id'],'status':e['status'],'versions':[p['version'] for p in e['probes']]} for e in entries]},indent=2))
assert not errors
