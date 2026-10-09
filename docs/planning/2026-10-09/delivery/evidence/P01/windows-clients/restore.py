#!/usr/bin/python3
"""Restore only installed entries that have not changed since this setup."""
import json,os,shutil
from pathlib import Path
import hashlib
root=Path(__file__).resolve().parent
entries=json.loads((root/'restore-manifest.json').read_text())['entries']
for e in entries:
    if e['type']=='file':
        assert hashlib.sha256(Path(e['backup']).read_bytes()).hexdigest()==e['originalSha256'],f'Backup changed: {e["backup"]}'
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
    if e['type']!='absent':os.chown(p,e['originalUid'],e['originalGid'],follow_symlinks=False)
print('Restored all recorded entries. Windows installations were untouched.')
