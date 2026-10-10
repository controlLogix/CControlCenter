import pathlib,tempfile,hashlib,json,subprocess,os,difflib,sys
SRC=pathlib.Path('/mnt/c/Users/RyanHelms/GitHub/agentmux/analysis/comms-2026-09')
root=pathlib.Path(tempfile.mkdtemp(prefix='har20-',dir='/home/ryan/.cache/agentmux-governance'))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def dump(p,rows):p.write_text(''.join(json.dumps(r)+'\n' for r in rows))
names=['correlate.py','spotcheck.py','determinism.sh','spotcheck.judgments.json','spotcheck.pass1.judgments.json']
original={n:sha(SRC/n) for n in names}
(root/'history').mkdir();(root/'out').mkdir();(root/'raw').mkdir()
for n in names:
 if n.endswith('.json'):(root/'history'/n).write_bytes((SRC/n).read_bytes())
 else:(root/n).write_bytes((SRC/n).read_bytes())
(root/'spotcheck.pass1.judgments.json').write_bytes((SRC/'spotcheck.pass1.judgments.json').read_bytes())
old=(root/'determinism.sh').read_text();new=old.replace('/tmp/am-det-1.txt',str(root/'det-1.txt')).replace('/tmp/am-det-2.txt',str(root/'det-2.txt'));(root/'determinism.sh').write_text(new)
(root/'adaptation.diff').write_text(''.join(difflib.unified_diff(old.splitlines(True),new.splitlines(True),fromfile='original/determinism.sh',tofile='fixture/determinism.sh')))
queues=[];receipts=[]
for name in ['agree','disagree','unverifiable']:
 body=name+' unique synthetic delivery body for raw verification'; qpath=root/'raw'/f'{name}-queue.jsonl';rpath=root/'raw'/f'{name}-session.jsonl'
 dump(qpath,[{'body':body}])
 if name!='unverifiable':dump(rpath,[{'type':'user','message':{'content':body if name=='agree' else 'different message with no matching needle'}}])
 row={'src':'courier','type':'queued','t':'2026-09-20T12:00:00Z','agent':name,'sender':'sender','prefix':body,'body_sha':hashlib.sha1(body.encode()).hexdigest(),'body_len':len(body),'ref':str(qpath)+':1','detail':{'kind':'request','courier_outcome':'sent'}};queues.append(row)
 receipts.append(dict(row,src='receipts',type='received',ref=str(rpath)+':1',detail={'cli':'claude','session_id':name,'map_conf':'high','envelope':True}))
dump(root/'out/courier.jsonl',queues);dump(root/'out/receipts.jsonl',receipts)
for n in ['receipts.rescued-claude-config.jsonl','panes.jsonl','transcripts.jsonl']:dump(root/'out'/n,[])
# Every raw source reference is explicitly fixture-owned, including deliberately missing input.
for row in queues+receipts:assert pathlib.Path(row['ref'].rsplit(':',1)[0]).is_relative_to(root)
input_paths=list((root/'raw').iterdir())+list((root/'out').iterdir())+list((root/'history').iterdir())+[root/'spotcheck.pass1.judgments.json']
inputs={str(p.relative_to(root)):sha(p) for p in input_paths}
(root/'sitecustomize.py').write_text('''import sys,os,pathlib
ROOT=pathlib.Path(os.environ['HAR20_ROOT']).resolve()
def audit(event,args):
 if event in ('socket.connect','socket.bind','subprocess.Popen','os.system'):raise AssertionError('External action forbidden: '+event)
 if event=='open' and isinstance(args[0],(str,bytes,os.PathLike)):
  flags=args[2] or 0
  if flags & (os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC|os.O_APPEND):
   assert pathlib.Path(os.fsdecode(args[0])).resolve().is_relative_to(ROOT), args[0]
sys.addaudithook(audit)
''')
env={'PATH':'/usr/bin:/bin','HOME':str(root),'PYTHONPATH':str(root),'HAR20_ROOT':str(root),'PYTHONDONTWRITEBYTECODE':'1'}
runs=[]
outputs=['out/outcomes.jsonl','out/summary.md','out/spotcheck.sample.jsonl','out/spotcheck.raw.jsonl','spotcheck.judgments.json']
for index in range(2):
 p=subprocess.run(['bash',str(root/'determinism.sh')],env=env,capture_output=True,text=True,timeout=30)
 (root/f'flow-{index}.log').write_text(p.stdout+p.stderr)
 assert p.returncode==0,p.stderr
 assert 'DETERMINISTIC: identical sha1 across two runs' in p.stdout,p.stdout
 rows=[json.loads(x) for x in (root/'out/spotcheck.raw.jsonl').read_text().splitlines()]
 got={r['agent']:r['verdict'] for r in rows};assert got=={x:x for x in ['agree','disagree','unverifiable']},got
 assert len(rows)==3
 runs.append({'exitCode':p.returncode,'verdicts':got,'sha256':{n:sha(root/n) for n in outputs},'logSha256':sha(root/f'flow-{index}.log')})
assert runs[0]['sha256']==runs[1]['sha256']
assert inputs=={str(p.relative_to(root)):sha(p) for p in input_paths}
assert original=={n:sha(SRC/n) for n in names}
report={'status':'passed','scope':'HAR-20-C01/C02 synthetic fresh judgments and full repeated analysis flow','root':str(root),'sourceHashes':original,'copiedHashes':{n:sha(root/n) for n in ['correlate.py','spotcheck.py','determinism.sh']},'adaptation':'Only determinism.sh two /tmp output path literals redirected to fixture-owned paths; text copy normalizes CRLF to LF. Python scripts copied byte-for-byte.','adaptationDiffSha256':sha(root/'adaptation.diff'),'inputsUnchanged':True,'historicalJudgmentsPreserved':True,'sourceUnchanged':True,'inputHashes':inputs,'runs':runs,'limits':['Synthetic source records intentionally include a mismatched raw body and a deleted session to test independent judgments.','Not reanalysis of private historical transcripts or proof of historical verdict correctness.','Shell flow is path-adapted, not original-byte execution. Original script exit code alone is not sufficient: harness also requires DETERMINISTIC marker and independently compares SHA256 outputs.','Each shell invocation runs correlate->spotcheck->correlate twice; two invocations qualify four cycles.']}
(root/'result.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps({'root':str(root),'status':'passed','verdicts':runs[0]['verdicts']}))