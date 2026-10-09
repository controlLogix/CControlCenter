import pathlib,tempfile,subprocess,tarfile,io,os,json,hashlib,time,shutil
repo=pathlib.Path('/mnt/c/Users/RyanHelms/GitHub/agentmux'); root=pathlib.Path(tempfile.mkdtemp(prefix='p01-field-race-')); checkout=root/'checkout';checkout.mkdir()
archive=subprocess.check_output(['git','-C',str(repo),'archive','37e0d8cd7439d31a491ac673e73438f7885cd04e'])
with tarfile.open(fileobj=io.BytesIO(archive)) as t:t.extractall(checkout,filter='data')
source=repo/'dashboard/test_field_panels.py';target=checkout/'dashboard/test_field_panels.py';target.write_bytes(source.read_bytes())
evidence=pathlib.Path('/home/ryan/.cache/agentmux-governance/field-race-evidence');evidence.mkdir(parents=True,exist_ok=True)
env=os.environ.copy()
for k in list(env):
 if k.startswith(('AGENTMUX_','TMUX','NATS_')):env.pop(k)
for k,n in [('HOME','home'),('AGENTMUX_HOME','state'),('TMUX_TMPDIR','tmux'),('XDG_CONFIG_HOME','config'),('XDG_CACHE_HOME','cache')]:
 (root/n).mkdir();env[k]=str(root/n)
env['PYTHONDONTWRITEBYTECODE']='1'
result={'candidateBase':'37e0d8cd7439d31a491ac673e73438f7885cd04e','changedSource':'dashboard/test_field_panels.py','changedSourceSha256':hashlib.sha256(target.read_bytes()).hexdigest(),'environment':{'python':subprocess.check_output(['python3','--version'],text=True).strip(),'platform':subprocess.check_output(['uname','-a'],text=True).strip()},'isolation':{k:env[k] for k in ['HOME','AGENTMUX_HOME','TMUX_TMPDIR','XDG_CONFIG_HOME','XDG_CACHE_HOME']},'runs':[]}
for label in ['positive','guard-removed']:
 if label=='guard-removed':
  p=checkout/'dashboard/netscan.py';s=p.read_text();needle='raise Invalid("a scan is already running; stop it first")';assert s.count(needle)==1;s=s.replace(needle,'pass  # deliberate isolated mutation');p.write_text(s)
 started=time.monotonic();r=subprocess.run(['python3','dashboard/test_field_panels.py'],cwd=checkout,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=240)
 log=evidence/(label+'.log');log.write_bytes(r.stdout)
 result['runs'].append({'label':label,'command':['python3','dashboard/test_field_panels.py'],'exitCode':r.returncode,'seconds':round(time.monotonic()-started,3),'log':str(log),'logSha256':hashlib.sha256(r.stdout).hexdigest(),'summary':[x for x in r.stdout.decode(errors='replace').splitlines() if 'FAIL' in x or 'passed ' in x or 'scan worker' in x or 'two at once' in x or 'concurrent scan' in x]})
 print(json.dumps(result['runs'][-1]),flush=True)
shutil.rmtree(root);result['cleanupComplete']=not root.exists();result['sourceUnchanged']=hashlib.sha256(source.read_bytes()).hexdigest()==result['changedSourceSha256'];(evidence/'result.json').write_text(json.dumps(result,indent=2)+'\n');print(str(evidence/'result.json'))