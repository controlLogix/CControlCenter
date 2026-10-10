import subprocess,pathlib,tempfile,tarfile,io,hashlib,json,time,shutil
commit='80f43e02f3344696a3985c48ef12578319f3bd0f'
repo='/mnt/c/Users/RyanHelms/GitHub/agentmux'
base=pathlib.Path(tempfile.mkdtemp(prefix='amx80f-',dir='/tmp'))
out=pathlib.Path('/home/ryan/.cache/agentmux-governance')/('native-qualification-'+base.name);out.mkdir()
(out/'runner.py').write_bytes(pathlib.Path(__file__).read_bytes())
for d in ('r','h','c','t'): (base/d).mkdir()
raw=subprocess.check_output(['git','-C',repo,'archive',commit])
with tarfile.open(fileobj=io.BytesIO(raw)) as t:t.extractall(base/'r',filter='data')
root=base/'r'
files={str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()}
env={'HOME':str(base/'h'),'XDG_CACHE_HOME':str(base/'c'),'TMPDIR':str(base/'t'),'TMUX_TMPDIR':str(base/'t'),'PATH':'/home/ryan/.cache/agentmux-governance/venv/bin:/home/ryan/.cache/agentmux-governance/tools:/usr/local/bin:/usr/bin:/bin','LANG':'C.UTF-8','PYTHONDONTWRITEBYTECODE':'1'}
report={'commit':commit,'checkout':str(root),'archiveSha256':hashlib.sha256(raw).hexdigest(),'environment':env,'files':files,'commands':[]}
(out/'setup.json').write_text(json.dumps(report,indent=2));print(str(out),flush=True)
for name,args in (('full',['--profile','full']),('callbacks',['hub.tests.test_windows_callbacks'])):
 cmd=['/home/ryan/.cache/agentmux-governance/venv/bin/python','-m','hub.tests.run_local']+args
 before=set((base/'c').rglob('result.json'));start=time.monotonic()
 with (out/(name+'.log')).open('wb') as log:r=subprocess.run(cmd,cwd=root,env=env,stdout=log,stderr=subprocess.STDOUT)
 added=set((base/'c').rglob('result.json'))-before
 if len(added)==1:shutil.copyfile(added.pop(),out/(name+'-result.json'))
 report['commands'].append({'name':name,'argv':cmd,'exit':r.returncode,'seconds':time.monotonic()-start});print(name,r.returncode,flush=True)
report['sourceUnchanged']=all(p.is_file() and hashlib.sha256(p.read_bytes()).hexdigest()==h for n,h in files.items() for p in [root/n])
report['privateStateRetained']=str(base)
(out/'qualification.json').write_text(json.dumps(report,indent=2));print(json.dumps({'out':str(out),'sourceUnchanged':report['sourceUnchanged'],'commands':report['commands']}),flush=True)