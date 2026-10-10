import pathlib,tempfile,os,subprocess,json,hashlib,traceback,time,tomllib
P=pathlib.Path
base=P(tempfile.mkdtemp(prefix='agentmux-codex-links-'))
home=base/'profile';targets=base/'synthetic-targets';work=base/'work'
for p in (home,targets,work,base/'tmp',base/'local',base/'roaming'):p.mkdir()
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
script=P(__file__);(base/'probe.py').write_bytes(script.read_bytes())
node=P('C:/nvm4w/nodejs/node.exe');cli=P('C:/nvm4w/nodejs/node_modules/@openai/codex/bin/codex.js')
auth=targets/'auth.json';config=targets/'config.toml'
auth.write_text('{"OPENAI_API_KEY":"dummy-agentmux-never-valid-before"}\n')
config.write_text('cli_auth_credentials_store = "file"\n[features]\nshell_snapshot = false\n')
env={k:os.environ[k] for k in ('SystemRoot','WINDIR','COMSPEC','PATHEXT') if k in os.environ}
env.update({'PATH':str(node.parent)+';'+str(P(os.environ['SystemRoot'])/'System32'),'CODEX_HOME':str(home),'USERPROFILE':str(base),'HOME':str(base),'APPDATA':str(base/'roaming'),'LOCALAPPDATA':str(base/'local'),'TEMP':str(base/'tmp'),'TMP':str(base/'tmp'),'HTTP_PROXY':'http://127.0.0.1:9','HTTPS_PROXY':'http://127.0.0.1:9','ALL_PROXY':'http://127.0.0.1:9'})
report={'fixture':str(base),'started':time.time(),'scope':'Installed Windows binary; synthetic file persistence only; no real credentials, authentication-service validation, refresh or inference.','environment':env,'sourceBefore':{str(p):sha(p) for p in (node,cli,script)},'commands':[],'checks':[]}
def check(n,v):
 report['checks'].append({'name':n,'passed':bool(v)});assert v,n
def run(name,args,data=None):
 cmd=[str(node),str(cli),*args];r=subprocess.run(cmd,input=data,text=True,cwd=work,env=env,capture_output=True,timeout=30)
 (base/(name+'.stdout.log')).write_text(r.stdout);(base/(name+'.stderr.log')).write_text(r.stderr)
 report['commands'].append({'name':name,'argv':cmd,'exit':r.returncode});check(name+' succeeds',r.returncode==0)
try:
 for n in ('auth.json','config.toml'):os.symlink(str(targets/n),str(home/n),target_is_directory=False)
 report['linksBefore']={n:os.readlink(home/n) for n in ('auth.json','config.toml')}
 before_config=sha(config)
 run('dummy-save',['-c','cli_auth_credentials_store="file"','login','--with-api-key'],'dummy-agentmux-never-valid-after\n')
 check('auth remains a link',(home/'auth.json').is_symlink())
 check('auth link target unchanged',os.readlink(home/'auth.json')==str(auth))
 check('synthetic target received dummy key',json.loads(auth.read_text())['OPENAI_API_KEY']=='dummy-agentmux-never-valid-after')
 check('auth save did not change synthetic config',sha(config)==before_config)
 before_auth=sha(auth)
 run('config-edit',['-c','cli_auth_credentials_store="file"','features','enable','shell_snapshot'])
 check('config remains a link',(home/'config.toml').is_symlink())
 check('config link target unchanged',os.readlink(home/'config.toml')==str(config))
 check('synthetic config target edited',tomllib.loads(config.read_text())['features']['shell_snapshot'] is True)
 check('config edit did not change synthetic auth',sha(auth)==before_auth)
 report['passed']=True
except Exception:report['passed']=False;report['failure']=traceback.format_exc()
finally:
 report['sourceUnchanged']=all(sha(P(p))==h for p,h in report['sourceBefore'].items())
 report['linksAfter']={n:{'isLink':(home/n).is_symlink(),'target':os.readlink(home/n) if (home/n).is_symlink() else None} for n in ('auth.json','config.toml')}
 report['fixtureRetained']=True
 report['files']={str(p.relative_to(base)):sha(p) for p in base.rglob('*') if p.is_file() and not p.is_symlink()}
 (base/'result.json').write_text(json.dumps(report,indent=2));print(json.dumps({'fixture':str(base),'passed':report['passed'],'failure':report.get('failure'),'checks':len(report['checks']),'sourceUnchanged':report['sourceUnchanged']}))
