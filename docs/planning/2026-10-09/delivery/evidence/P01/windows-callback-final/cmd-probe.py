import subprocess,os,json
from pathlib import Path
root='/home/ryan/.cache/agentmux-governance/windows-callback-proposal'
script='#!/usr/bin/python3\nimport sys,json\nprint(json.dumps({"argv":sys.argv[1:],"stdin":sys.stdin.read()}))\nsys.exit(7)\n'
subprocess.run(['wsl','-d','Ubuntu-26.04','--exec','python3','-c','from pathlib import Path; p=Path('+repr(root+'/argv-probe')+');p.write_text('+repr(script)+');p.chmod(0o700)'],check=True)
env=dict(os.environ,AGENTMUX_WSL_DISTRO='Ubuntu-26.04',AGENTMUX_WSL_BIN=root+'/argv-probe',AGENTMUX_WSL_CWD=root)
args=['a space','','one!two','C:\\folder with spaces\\file','雪','amp & pipe | text']
cmd=subprocess.list2cmdline(['C:\\Users\\RyanHelms\\GitHub\\agentmux\\agentmux.cmd',*args])
r=subprocess.run('cmd.exe /d /c '+cmd,env=env,input='stdin proof',text=True,capture_output=True,timeout=20)
result={'args':args,'code':r.returncode,'stdout':r.stdout,'stderr':r.stderr};print(json.dumps(result,ensure_ascii=True));assert r.returncode==7,result;assert json.loads(r.stdout)=={'argv':args,'stdin':'stdin proof'},result
Path(os.environ['TEMP'],'callback-cmd-result.json').write_text(json.dumps(result,indent=2),encoding='utf8')

