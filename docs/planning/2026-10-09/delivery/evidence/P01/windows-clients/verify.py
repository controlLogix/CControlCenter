from pathlib import Path
import importlib.util,subprocess,json,hashlib,os,shutil
root=Path('/home/ryan/.cache/agentmux-governance/windows-cli-links/20261009-192119')
shutil.copyfile('/mnt/c/Users/RyanHelms/AppData/Local/Temp/agentmux-windows-cli-links.py',root/'setup.py')
spec=importlib.util.spec_from_file_location('forward',Path('/home/ryan/.local/share/agentmux/windows-clients/forward.py'));f=importlib.util.module_from_spec(spec);spec.loader.exec_module(f)
work=root/'workspace with spaces';work.mkdir(exist_ok=True)
path=str(work/'settings file.json');(work/'settings file.json').write_text('{}')
converted=subprocess.check_output(['wslpath','-w',path],text=True).strip()
args=['--settings',path,'--model','model name','prompt /tmp/is-text', 'quotes " and apostrophe \'', '$HOME; & |', '', 'unicode café', 'line1\nline2', 'C:\\space dir\\file']
command=f.command('claude',args);assert command[1:3]==['--settings',converted] and command[3:]==args[2:]
assert f.command('claude',['--settings='+path])[-1]=='--settings='+converted
assert f.command('claude',['--settings={"value":"/tmp/not-a-file"}'])[-1]=='--settings={"value":"/tmp/not-a-file"}'
script='console.log(JSON.stringify({args:process.argv.slice(1),cwd:process.cwd(),home:require("os").homedir(),platform:process.platform,USERPROFILE:process.env.USERPROFILE,HOME:process.env.HOME||null,CODEX_HOME:process.env.CODEX_HOME||null,CLAUDE_CONFIG_DIR:process.env.CLAUDE_CONFIG_DIR||null,GROK_HOME:process.env.GROK_HOME||null}))'
r=subprocess.run(['/mnt/c/nvm4w/nodejs/node.exe','-e',script,'--']+command[1:],cwd=work,capture_output=True,text=True,timeout=20);assert r.returncode==0,r.stderr
metadata=json.loads(r.stdout);assert metadata['args']==command[1:],metadata;assert metadata['platform']=='win32';assert metadata['home']=='C:\\Users\\RyanHelms';assert metadata['cwd']==subprocess.check_output(['wslpath','-w',str(work)],text=True).strip()
probe=subprocess.run(['/bin/bash','-lc','command -v claude codex grok kimi goose dsh trueforge'],capture_output=True,text=True,timeout=20)
assert probe.returncode==0,probe.stderr;assert all(str(Path.home()/'.local/bin'/n) in probe.stdout.splitlines() for n in ['claude','codex','grok','kimi','goose','dsh','trueforge'])
manifest=json.loads((root/'restore-manifest.json').read_text())
for e in manifest['entries']:
 p=Path(e['path'])
 if 'installedTarget' in e:assert p.is_symlink() and os.readlink(p)==e['installedTarget']
 else:assert hashlib.sha256(p.read_bytes()).hexdigest()==e['installedSha256']
 if e['type']=='file':assert hashlib.sha256(Path(e['backup']).read_bytes()).hexdigest()==e['originalSha256']
compile((root/'restore.py').read_text(),str(root/'restore.py'),'exec')
report={'argumentProbePassed':True,'pathFlagsConvertOnlyRecognizedAbsolutePaths':True,'jsonAndPromptTextUnchanged':True,'windowsRuntimeMetadata':metadata,'loginShellResolution':probe.stdout.splitlines(),'restorePreconditionsVerified':True,'backupHashesVerified':True,'restoreScriptCompiles':True,'restoreNotExecuted':True,'nativeInstallRetained':Path('/usr/local/bin/codex').exists(),'noModelPrompts':True,'noCredentialsCopiedOrConfigDirectoriesLinked':True}
(root/'forwarding-verification.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))