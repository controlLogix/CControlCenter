import pathlib,subprocess,json,hashlib,os
root=pathlib.Path(__file__).resolve().parent; reportpath=root/'result.json'; old=reportpath.read_bytes(); r=json.loads(old)
r['reportHistory']=[{'sha256':r.pop('previousReportSha256'),'note':'Initial file exchange and tool inventory.'},{'sha256':hashlib.sha256(old).hexdigest(),'note':'Added successful WSL-to-Windows cwd inheritance. Supplement outer cwd label corrected to actual producer cwd.'}]
r['records'][-1]['cwd']=os.getcwd()
fixture=root/'git fixture with spaces'; fixture.mkdir()
for name,args in [('windows-git-init',['C:/Program Files/Git/cmd/git.exe','-C',str(fixture),'init']),('windows-git-fixture-cwd',['C:/Program Files/Git/cmd/git.exe','-C',str(fixture),'rev-parse','--show-toplevel'])]:
 p=subprocess.run(args,cwd=root,capture_output=True,text=True,encoding='utf-8',timeout=20); r['records'].append({'name':name,'argv':args,'cwd':str(root),'exitCode':p.returncode,'stdout':p.stdout,'stderr':p.stderr})
r['scripts'].append({'path':str(pathlib.Path(__file__)),'sha256':hashlib.sha256(pathlib.Path(__file__).read_bytes()).hexdigest()})
reportpath.write_text(json.dumps(r,indent=2)+'\n',encoding='utf-8'); print(json.dumps({'report':str(reportpath),'sha256':hashlib.sha256(reportpath.read_bytes()).hexdigest(),'gitRecords':r['records'][-2:]}))
