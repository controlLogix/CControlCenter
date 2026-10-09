from pathlib import Path
import os,json,hashlib,shutil,pwd
root=Path('/home/ryan/.cache/agentmux-governance/windows-cli-links/20261009-192119');manifest_path=root/'restore-manifest.json';m=json.loads(manifest_path.read_text());assert os.geteuid()==0
users=[p for p in pwd.getpwall() if p.pw_uid>=1000 and p.pw_uid<65534 and p.pw_shell not in ['/sbin/nologin','/usr/sbin/nologin','/bin/false']]
assert [(p.pw_name,p.pw_uid) for p in users]==[('ryan',1000)]
for e in m['entries']:
 p=Path(e['path']);e['originalUid']=p.lstat().st_uid;e['originalGid']=p.lstat().st_gid
for name in m['clients']:
 p=Path('/usr/local/bin')/name;assert not any(e['path']==str(p) for e in m['entries']);e={'path':str(p)}
 if p.is_symlink():e.update(type='symlink',target=os.readlink(p),originalUid=p.lstat().st_uid,originalGid=p.lstat().st_gid)
 elif p.exists():
  assert p.is_file();b=root/'backups'/str(len(m['entries']));shutil.copy2(p,b);b.chmod(0o600);e.update(type='file',backup=str(b),originalUid=p.stat().st_uid,originalGid=p.stat().st_gid,originalMode=p.stat().st_mode&0o777,originalSha256=hashlib.sha256(p.read_bytes()).hexdigest())
 else:e['type']='absent'
 if p.exists() or p.is_symlink():p.unlink()
 p.symlink_to(root/'forward.py');e['installedTarget']=str(root/'forward.py');m['entries'].append(e)
m['systemEntryScope']={'distribution':'Ubuntu-26.04','windowsUser':'RyanHelms','interactiveLinuxUser':'ryan','otherUsers':'Nix build service users have nologin shells; no other ordinary interactive user found.','originalNativeCodexTarget':'/home/ryan/.codex/lib/node_modules/@openai/codex/bin/codex.js','nativePackageStillPresent':Path('/home/ryan/.codex/lib/node_modules/@openai/codex/bin/codex.js').exists()}
manifest_path.write_text(json.dumps(m,indent=2)+'\n');restore=root/'restore.py';s=restore.read_text();s=s.replace("print('Restored all recorded entries.","    if e['type']!='absent':os.chown(p,e['originalUid'],e['originalGid'],follow_symlinks=False)\nprint('Restored all recorded entries.");restore.write_text(s);compile(s,str(restore),'exec');print(json.dumps(m['systemEntryScope']));print('System links installed:',len(m['clients']))