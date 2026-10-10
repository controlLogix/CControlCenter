import hashlib,json,os,pathlib,subprocess,sys,time
root=pathlib.Path(__file__).resolve().parent
records=[]
def run(name,argv,cwd=None):
    start=time.monotonic()
    try:
        p=subprocess.run(argv,cwd=cwd,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=35)
        r=dict(name=name,argv=argv,cwd=str(cwd) if cwd else os.getcwd(),exitCode=p.returncode,stdout=p.stdout,stderr=p.stderr,durationSeconds=time.monotonic()-start)
    except Exception as e:r=dict(name=name,argv=argv,cwd=str(cwd) if cwd else os.getcwd(),failure=repr(e),durationSeconds=time.monotonic()-start)
    records.append(r)
    return r
wslpath='/mnt/'+root.drive[0].lower()+root.as_posix()[2:]
wsl_script="""import pathlib,sys,json,os
p=pathlib.Path(sys.argv[1]); p.joinpath('from-wsl.bin').write_bytes(b'WSL shared NTFS marker\\x00\\xff\\r\\n'); print(json.dumps({'cwd':os.getcwd(),'argv':sys.argv,'path':str(p),'bytesHex':p.joinpath('from-wsl.bin').read_bytes().hex()}))
"""
win_script="""import pathlib,sys,json,os
p=pathlib.Path.cwd(); data=p.joinpath('from-wsl.bin').read_bytes(); assert data==b'WSL shared NTFS marker\\x00\\xff\\r\\n'; p.joinpath('from-windows.bin').write_bytes(b'Windows shared NTFS marker\\x00\\xfe\\r\\n'); print(json.dumps({'cwd':os.getcwd(),'argv':sys.argv,'python':sys.executable,'inputBytesHex':data.hex(),'outputBytesHex':p.joinpath('from-windows.bin').read_bytes().hex()}))
"""
(root/'windows-child.py').write_text(win_script,encoding='utf-8')
run('wsl-write',['wsl.exe','-d','Ubuntu-26.04','--','python3','-c',wsl_script,wslpath])
run('windows-read-write',[sys.executable,str(root/'windows-child.py'),'argument with spaces','--literal=value with spaces'],root)
verify_script="""import pathlib,sys,json,os
p=pathlib.Path(sys.argv[1]); data=p.joinpath('from-windows.bin').read_bytes(); assert data==b'Windows shared NTFS marker\\x00\\xfe\\r\\n'; print(json.dumps({'cwd':os.getcwd(),'argv':sys.argv,'inputBytesHex':data.hex(),'files':[{'name':v.name,'sha256':__import__('hashlib').sha256(v.read_bytes()).hexdigest()} for v in sorted(p.glob('from-*.bin'))]}))
"""
run('wsl-read-verify',['wsl.exe','-d','Ubuntu-26.04','--','python3','-c',verify_script,wslpath])
run('windows-git-version',['C:/Program Files/Git/cmd/git.exe','--version'],root)
run('windows-git-cwd',['C:/Program Files/Git/cmd/git.exe','-C',str(root),'rev-parse','--show-toplevel'],root)
run('windows-python-path',['where.exe','python'],root)
run('windows-python3-path',['where.exe','python3'],root)
run('windows-git-path',['where.exe','git'],root)
run('windows-python-default-version',['python','--version'],root)
run('windows-python3-default-version',['python3','--version'],root)
run('windows-git-default-version',['git','--version'],root)
inventory="""import pathlib,json,hashlib,shutil
base=pathlib.Path('/home/ryan/.local/share/agentmux/windows-clients'); out={'sourceFiles':[],'commands':[]}
for name in ('forward.py','clients.json'):
 p=base/name; out['sourceFiles'].append({'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'bytes':p.stat().st_size})
for name in ('claude','codex','grok','kimi','goose','dsh','trueforge','pi'):
 q=shutil.which(name); p=pathlib.Path(q) if q else None; out['commands'].append({'command':name,'path':q,'symlink':p.is_symlink() if p else False,'resolved':str(p.resolve()) if p else None,'sha256':hashlib.sha256(p.read_bytes()).hexdigest() if p and p.is_file() else None})
print(json.dumps(out))
"""
run('wsl-forwarder-inventory',['wsl.exe','-d','Ubuntu-26.04','--','python3','-c',inventory])
report={'scope':'Synthetic NTFS files and installed tool versions only. No model, auth or config operations.','fixture':str(root),'wslFixture':wslpath,'python':sys.executable,'records':records,'scripts':[{'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in [pathlib.Path(__file__),root/'windows-child.py']],'limits':['The git rev-parse failure is expected because this fixture is not a Git repository.','This does not qualify the crossrepo home path, callback delivery, client auth, session isolation or actual model execution.']}
(root/'result.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'fixture':str(root),'records':[{'name':r['name'],'exitCode':r.get('exitCode'),'failure':r.get('failure')} for r in records],'reportSha256':hashlib.sha256((root/'result.json').read_bytes()).hexdigest()}))
