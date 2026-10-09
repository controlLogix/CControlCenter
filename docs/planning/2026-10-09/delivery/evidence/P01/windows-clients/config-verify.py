from pathlib import Path
import importlib.util,os,subprocess,json,hashlib
root=Path('/home/ryan/.cache/agentmux-governance/windows-cli-links/20261009-192119');spec=importlib.util.spec_from_file_location('forward',root/'forward.py');f=importlib.util.module_from_spec(spec);spec.loader.exec_module(f)
script='console.log(JSON.stringify({home:require("os").homedir(),USERPROFILE:process.env.USERPROFILE,CODEX_HOME:process.env.CODEX_HOME||null,CLAUDE_CONFIG_DIR:process.env.CLAUDE_CONFIG_DIR||null,probe:process.env.AGENTMUX_FORWARD_PROBE||null}))'
base=dict(os.environ)
for key in ['CODEX_HOME','CLAUDE_CONFIG_DIR']:base.pop(key,None)
base['AGENTMUX_FORWARD_PROBE']='preserved';base['WSLENV']=':'.join([x for x in base.get('WSLENV','').split(':') if x.split('/',1)[0] not in ['CODEX_HOME','CLAUDE_CONFIG_DIR']]+['AGENTMUX_FORWARD_PROBE/w'])
results=[]
for label,overrides in [('default',{}),('linux-config',{'CODEX_HOME':str(root/'fixture config/.codex'),'CLAUDE_CONFIG_DIR':str(root/'fixture config/.claude')}),('windows-config',{'CODEX_HOME':'C:\\Users\\RyanHelms\\AppData\\Local\\Temp\\codex fixture','CLAUDE_CONFIG_DIR':'C:\\Users\\RyanHelms\\AppData\\Local\\Temp\\claude fixture'})]:
 env=f.environment({**base,**overrides});r=subprocess.run(['/mnt/c/nvm4w/nodejs/node.exe','-e',script],env=env,cwd='/tmp',capture_output=True,text=True,timeout=20);assert r.returncode==0,r.stderr;data=json.loads(r.stdout)
 assert data['home']=='C:\\Users\\RyanHelms' and data['probe']=='preserved'
 for key,value in overrides.items():
  expected=f.windows_path(value);assert data[key]==expected,(key,data[key],expected)
 if not overrides:assert data['CODEX_HOME'] is None and data['CLAUDE_CONFIG_DIR'] is None
 results.append({'case':label,'passed':True,'metadata':data})
report={'cases':results,'otherWSLENVEntryPreserved':True,'globalHOMEOverrideAdded':False,'noCredentialsReadCopiedOrRefreshed':True,'launcherSha256':hashlib.sha256((root/'forward.py').read_bytes()).hexdigest(),'source':'https://learn.microsoft.com/en-us/windows/wsl/interop','limits':['Overrides validated through harmless Windows Node metadata, not authenticated model calls.','Automatic GROK_HOME and Kimi-specific config forwarding are not implemented or qualified. Explicit WSLENV supplied by the caller is preserved; separate validation is required for those providers.']}
(root/'config-override-verification.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))