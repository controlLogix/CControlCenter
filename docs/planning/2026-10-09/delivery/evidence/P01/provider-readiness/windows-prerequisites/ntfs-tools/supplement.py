import pathlib,subprocess,json,hashlib,sys
root=pathlib.Path(__file__).resolve().parent
p=root/'result.json'; original=p.read_bytes(); report=json.loads(original)
wsl=root.as_posix(); wsl='/mnt/'+root.drive[0].lower()+wsl[2:]
script="""import subprocess,sys,json,os
p=subprocess.run(['/mnt/c/Users/RyanHelms/AppData/Local/Programs/Python/Python314/python.exe',sys.argv[2],'launched from WSL with spaces'],cwd=sys.argv[1],capture_output=True,text=True,timeout=20); print(json.dumps({'launcherCwd':os.getcwd(),'requestedCwd':sys.argv[1],'argv':p.args,'exitCode':p.returncode,'stdout':p.stdout,'stderr':p.stderr})); sys.exit(p.returncode)
"""
a=['wsl.exe','-d','Ubuntu-26.04','--','python3','-c',script,wsl,str(root/'windows-child.py')]
r=subprocess.run(a,capture_output=True,text=True,encoding='utf-8',timeout=30)
report['previousReportSha256']=hashlib.sha256(original).hexdigest()
report['records'].append(dict(name='wsl-exec-windows-python-cwd',argv=a,cwd=str(root),exitCode=r.returncode,stdout=r.stdout,stderr=r.stderr))
report['scripts'].append(dict(path=str(pathlib.Path(__file__)),sha256=hashlib.sha256(pathlib.Path(__file__).read_bytes()).hexdigest()))
p.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
print(r.stdout); print(r.stderr); print(json.dumps({'reportSha256':hashlib.sha256(p.read_bytes()).hexdigest(),'exitCode':r.returncode}))
