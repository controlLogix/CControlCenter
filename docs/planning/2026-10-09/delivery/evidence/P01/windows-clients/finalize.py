from pathlib import Path
import json,hashlib,shutil
root=Path('/home/ryan/.cache/agentmux-governance/windows-cli-links/20261009-192119');p=root/'forward.py';s=p.read_text();start=s.index('def command(');end=s.index('def environment(')
command='''def command(client,args):
    config=json.loads((ROOT/'clients.json').read_text())[client]
    output=[config['exe']]
    if 'script' in config:output.append(windows_path(config['script']))
    variadic=set(config.get('variadicPaths',[]))
    comma=set(config.get('commaPaths',[]))
    active=None
    literal=False
    def convert(value,key):
        return ','.join(windows_path(v) for v in value.split(',')) if key in comma else windows_path(value)
    for arg in args:
        if literal:
            output.append(arg);continue
        if arg=='--':
            output.append(arg);literal=True;active=None;continue
        key,sep,value=arg.partition('=')
        attached=False
        if key not in config['paths'] and len(arg)>2 and arg[:2] in config['paths'] and arg[:2].startswith('-') and not arg.startswith('--'):
            key,sep,value=arg[:2],'',arg[2:];attached=True
        if key in config['paths']:
            if sep or attached:
                output.append(key+sep+convert(value,key))
                active=key if key in variadic else None
            else:
                output.append(arg);active=key
        elif active is not None and not arg.startswith('-'):
            output.append(convert(arg,active))
            if active not in variadic:active=None
        else:
            output.append(arg)
            if arg.startswith('-'):active=None
    return output

'''
s=s[:start]+command+s[end:];p.write_text(s)
c=json.loads((root/'clients.json').read_text());c['claude']['variadicPaths']=['--add-dir','--mcp-config'];c['codex']['variadicPaths']=['--image','-i'];c['codex']['commaPaths']=['--image','-i'];(root/'clients.json').write_text(json.dumps(c,indent=2)+'\n')
p=root/'restore.py';s=p.read_text();needle="for e in entries:\n    p=Path(e['path'])";replacement="for e in entries:\n    if e['type']=='file':\n        assert hashlib.sha256(Path(e['backup']).read_bytes()).hexdigest()==e['originalSha256'],f'Backup changed: {e[\"backup\"]}'\n    p=Path(e['path'])";assert needle in s;s=s.replace(needle,replacement);compile(s,str(p),'exec');p.write_text(s)
durable=Path.home()/'.local/share/agentmux/windows-clients';durable.mkdir(parents=True,exist_ok=True)
for name in ['forward.py','clients.json']:
 assert not (durable/name).exists();shutil.copy2(root/name,durable/name)
(durable/'forward.py').chmod(0o755)
print(durable)