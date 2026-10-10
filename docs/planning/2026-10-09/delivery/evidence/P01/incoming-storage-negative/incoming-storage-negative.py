import hashlib,json,os,subprocess,sys
from pathlib import Path
root=Path('/mnt/c/Users/RyanHelms/GitHub/agentmux');os.chdir(root)
source=root/'tests/storage/run.py';before=source.read_bytes();text=before.decode()
needle="                complete['state'] = {'status': 'blocked', 'taskId': operation}\n"
mutation="                await broker.client(language, {'op': 'publish', 'subject': incoming_subject, 'record': complete, 'expectedSequence': 0})\n"
assert text.count(needle)==1
out=Path.home()/'.cache/agentmux-governance/p01-incoming-storage-negative-reviewed';out.mkdir(parents=True,exist_ok=True)
env=dict(os.environ,AGENTMUX_EVIDENCE_DIR=str(out))
code='__file__='+repr(str(source))+'\nexec(compile('+repr(text.replace(needle,needle+mutation))+','+repr(str(source))+',"exec"))'
r=subprocess.run([sys.executable,'-c',code],env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
(out/'negative.log').write_bytes(r.stdout.encode())
assert r.returncode==1,r.stdout
assert 'partial incoming state, attribution or claim became durable' in r.stdout,r.stdout
assert source.read_bytes()==before
report={'mutation':'Publish partial blocked task before attribution and claim construction; no assertions removed','exitCode':r.returncode,'expectedFailure':'partial incoming state, attribution or claim became durable','sourceSha256':hashlib.sha256(before).hexdigest(),'sourceUnchanged':True,'logSha256':hashlib.sha256(r.stdout.encode()).hexdigest(),'limits':['Isolated instrumented runner, not a committed product change. All original storage cases execute before this injected failure.']}
(out/'review.json').write_bytes((json.dumps(report,indent=2)+'\n').encode());print(json.dumps(report))
