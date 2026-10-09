import pathlib,os,json,hashlib,subprocess,time,shutil
home=pathlib.Path.home();root=home/'.cache/agentmux-governance/windows-cli-links'/time.strftime('%Y%m%d-%H%M%S');root.mkdir(parents=True,mode=0o700);(root/'backups').mkdir(mode=0o700)
clients={
 'claude':{'exe':'/mnt/c/nvm4w/nodejs/node_modules/@anthropic-ai/claude-code/bin/claude.exe','paths':['--settings','--plugin-dir','--add-dir','--mcp-config']},
 'codex':{'exe':'/mnt/c/nvm4w/nodejs/node.exe','script':'/mnt/c/nvm4w/nodejs/node_modules/@openai/codex/bin/codex.js','paths':['--cd','-C','--add-dir','--image','-i']},
 'grok':{'exe':'/mnt/c/Users/RyanHelms/.grok/bin/grok.exe','paths':['--cwd','--prompt-file','--debug-file']},
 'kimi':{'exe':'/mnt/c/Users/RyanHelms/.kimi-code/bin/kimi.exe','paths':['--skills-dir','--agent-file','--add-dir']},
 'goose':{'exe':'/mnt/c/Users/RyanHelms/.local/bin/goose.exe','paths':[]},
 'dsh':{'exe':'/mnt/c/nvm4w/nodejs/node.exe','script':'/mnt/c/nvm4w/nodejs/node_modules/@deepseek-ai/dsh/lib/bin.js','paths':[]},
 'trueforge':{'exe':'/mnt/c/nvm4w/nodejs/node.exe','script':'/mnt/c/nvm4w/nodejs/node_modules/@truefoundry/trueforge/dist/cli.js','paths':[]}}
for v in clients.values():
 assert pathlib.Path(v['exe']).is_file()
 if 'script' in v:assert pathlib.Path(v['script']).is_file()
(root/'clients.json').write_text(json.dumps(clients,indent=2)+'\n')
launcher='''#!/usr/bin/python3
"""Forward to the Windows installation; keep its Windows home and credentials."""
import json,os,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent

def windows_path(value):
    if value.startswith('/'):
        return subprocess.check_output(['/usr/bin/wslpath','-w',value],text=True).strip()
    return value

def command(client,args):
    config=json.loads((ROOT/'clients.json').read_text())[client]
    output=[config['exe']]
    if 'script' in config:output.append(windows_path(config['script']))
    path_next=False
    for arg in args:
        if path_next:
            output.append(windows_path(arg));path_next=False;continue
        key,sep,value=arg.partition('=')
        if key in config['paths']:
            if sep:output.append(key+'='+windows_path(value))
            else:output.append(arg);path_next=True
        else:output.append(arg)
    return output

if __name__=='__main__':
    client=Path(sys.argv[0]).name
    argv=command(client,sys.argv[1:])
    os.execv(argv[0],argv)
'''
(root/'forward.py').write_text(launcher);(root/'forward.py').chmod(0o755)
manifest={'root':str(root),'scope':'WSL links only; Windows binaries/auth/config unchanged. No native installation removed.','entries':[],'clients':clients}
def backup(path):
 entry={'path':str(path)}
 if path.is_symlink():entry.update(type='symlink',target=os.readlink(path))
 elif path.exists():
  assert path.is_file(),str(path);b=root/'backups'/str(len(manifest['entries']));shutil.copy2(path,b);b.chmod(0o600);entry.update(type='file',backup=str(b),originalMode=path.stat().st_mode & 0o777,originalSha256=hashlib.sha256(path.read_bytes()).hexdigest())
 else:entry['type']='absent'
 manifest['entries'].append(entry);return entry
localbin=home/'.local/bin';localbin.mkdir(parents=True,exist_ok=True)
for name in clients:
 path=localbin/name;entry=backup(path)
 if path.is_symlink() or path.exists():path.unlink()
 path.symlink_to(root/'forward.py');entry['installedTarget']=str(root/'forward.py')
block='# Agentmux Windows CLI forwarding: prefer Windows-backed user launchers.\nexport PATH="$HOME/.local/bin:$PATH"\n'
for name in ['.profile','.bashrc']:
 path=home/name;entry=backup(path);old=path.read_text() if path.exists() else ''
 if name=='.bashrc':new=block+old
 else:new=old+'\n'+block
 path.write_text(new);entry['installedSha256']=hashlib.sha256(path.read_bytes()).hexdigest()
(root/'restore-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
restore='''#!/usr/bin/python3
"""Restore only installed entries that have not changed since this setup."""
import json,os,shutil
from pathlib import Path
import hashlib
root=Path(__file__).resolve().parent
entries=json.loads((root/'restore-manifest.json').read_text())['entries']
for e in entries:
    p=Path(e['path'])
    if 'installedTarget' in e:
        assert p.is_symlink() and os.readlink(p)==e['installedTarget'],f'Changed since setup: {p}'
    else:
        assert hashlib.sha256(p.read_bytes()).hexdigest()==e['installedSha256'],f'Changed since setup: {p}'
for e in reversed(entries):
    p=Path(e['path'])
    if p.exists() or p.is_symlink():p.unlink()
    if e['type']=='symlink':p.symlink_to(e['target'])
    elif e['type']=='file':shutil.copyfile(e['backup'],p);p.chmod(e['originalMode'])
print('Restored all recorded entries. Windows installations were untouched.')
'''
(root/'restore.py').write_text(restore);(root/'restore.py').chmod(0o700)
print(str(root),flush=True)
results={'root':str(root),'runs':[]}
for cwd in ['/mnt/c/Users/RyanHelms/GitHub/agentmux','/tmp']:
 for name in clients:
  for flag in (['--help'] if name=='trueforge' else ['--version','--help']):
   r=subprocess.run([str(localbin/name),flag],cwd=cwd,capture_output=True,text=True,timeout=40)
   log=root/(name+'-'+('linux' if cwd=='/tmp' else 'mounted')+'-'+flag[2:]+'.log');log.write_text(r.stdout+r.stderr)
   results['runs'].append({'client':name,'cwd':cwd,'flag':flag,'exitCode':r.returncode,'log':str(log),'logSha256':hashlib.sha256(log.read_bytes()).hexdigest()})
(root/'results.json').write_text(json.dumps(results,indent=2)+'\n');print(json.dumps({'results':str(root/'results.json'),'runs':len(results['runs']),'failures':[x for x in results['runs'] if x['exitCode']!=0]}),flush=True)