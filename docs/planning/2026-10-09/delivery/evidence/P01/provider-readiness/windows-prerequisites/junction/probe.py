import pathlib,tempfile,os,subprocess,json,hashlib,traceback,time,tomllib
P=pathlib.Path
base=P(tempfile.mkdtemp(prefix='agentmux-codex-junction-')).absolute()
canonical=base/'synthetic-windows-profile';linked=base/'wsl-profile-alias';work=base/'work'
for p in (canonical,work,base/'tmp',base/'local',base/'roaming'):p.mkdir()
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
script=P(__file__);(base/'probe.py').write_bytes(script.read_bytes())
node=P('C:/nvm4w/nodejs/node.exe');cli=P('C:/nvm4w/nodejs/node_modules/@openai/codex/bin/codex.js')
auth=canonical/'auth.json';config=canonical/'config.toml'
auth.write_text('{"OPENAI_API_KEY":"dummy-agentmux-never-valid-before"}\n',encoding='utf-8')
config.write_text('cli_auth_credentials_store = "file"\n[features]\nshell_snapshot = false\n',encoding='utf-8')
env={k:os.environ[k] for k in ('SystemRoot','WINDIR','COMSPEC','PATHEXT') if k in os.environ}
env.update({'PATH':str(node.parent)+';'+str(P(os.environ['SystemRoot'])/'System32'),'CODEX_HOME':str(linked),'USERPROFILE':str(base),'HOME':str(base),'APPDATA':str(base/'roaming'),'LOCALAPPDATA':str(base/'local'),'TEMP':str(base/'tmp'),'TMP':str(base/'tmp'),'HTTP_PROXY':'http://127.0.0.1:9','HTTPS_PROXY':'http://127.0.0.1:9','ALL_PROXY':'http://127.0.0.1:9'})
report={'fixture':str(base),'started':time.time(),'scope':'Installed Windows Codex; dummy auth and config persistence through a directory junction only. No real credentials, service calls, inference or isolated session qualification.','environment':env,'sourceBefore':{str(p):sha(p) for p in (node,cli,script)},'commands':[],'checks':[]}
def check(n,v):
 report['checks'].append({'name':n,'passed':bool(v)});assert v,n
def run(name,cmd,data=None):
 r=subprocess.run(cmd,input=data,text=True,encoding='utf-8',cwd=work,env=env,capture_output=True,timeout=30)
 (base/(name+'.stdout.log')).write_text(r.stdout,encoding='utf-8');(base/(name+'.stderr.log')).write_text(r.stderr,encoding='utf-8')
 report['commands'].append({'name':name,'argv':cmd,'exit':r.returncode});check(name+' succeeds',r.returncode==0)
def client(name,args,data=None):run(name,[str(node),str(cli),*args],data)
try:
 check('canonical target stays in checked fixture',canonical.resolve().is_relative_to(base.resolve()))
 check('alias parent stays in checked fixture',linked.parent.resolve()==base.resolve())
 check('alias does not already exist',not linked.exists())
 cmd=P(os.environ['SystemRoot'])/'System32'/'cmd.exe'
 run('create-junction',[str(cmd),'/d','/c','mklink','/J',str(linked),str(canonical)])
 check('profile alias is a directory junction',linked.is_junction())
 check('junction resolves to synthetic Windows profile',linked.resolve()==canonical.resolve())
 report['junctionBefore']={'target':os.readlink(linked),'resolved':str(linked.resolve())}
 before_config=sha(config)
 client('dummy-save',['-c','cli_auth_credentials_store="file"','login','--with-api-key'],'dummy-agentmux-never-valid-after\n')
 check('auth save reaches synthetic canonical file',json.loads(auth.read_text(encoding='utf-8'))['OPENAI_API_KEY']=='dummy-agentmux-never-valid-after')
 check('alias auth and canonical auth are same file',os.path.samefile(linked/'auth.json',auth))
 check('auth save leaves config unchanged',sha(config)==before_config)
 before_auth=sha(auth)
 client('config-edit',['-c','cli_auth_credentials_store="file"','features','enable','shell_snapshot'])
 check('config edit reaches synthetic canonical file',tomllib.loads(config.read_text(encoding='utf-8'))['features']['shell_snapshot'] is True)
 check('alias config and canonical config are same file',os.path.samefile(linked/'config.toml',config))
 check('config edit leaves auth unchanged',sha(auth)==before_auth)
 check('junction remains',linked.is_junction() and linked.resolve()==canonical.resolve())
 regular_auth=[p for p in base.rglob('auth.json') if p.is_file() and not p.is_symlink() and p.parent!=linked]
 check('only one regular credential file exists',regular_auth==[auth])
 report['passed']=True
except Exception:report['passed']=False;report['failure']=traceback.format_exc()
finally:
 report['sourceUnchanged']=all(sha(P(p))==h for p,h in report['sourceBefore'].items())
 report['junctionAfter']={'isJunction':linked.is_junction(),'target':os.readlink(linked) if linked.is_junction() else None,'resolved':str(linked.resolve()) if linked.exists() else None}
 report['fixtureRetained']=True
 report['files']={str(p.relative_to(base)):sha(p) for p in base.rglob('*') if p.is_file() and not p.is_symlink()}
 (base/'result.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
 print(json.dumps({'fixture':str(base),'passed':report['passed'],'failure':report.get('failure'),'checks':len(report['checks']),'sourceUnchanged':report['sourceUnchanged']}))
