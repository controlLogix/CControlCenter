import sys,json,pathlib,unittest,hashlib,traceback
tree,out,wid,revision,mode=sys.argv[1:];sys.path.insert(0,tree)
from hub.cli import call
p=pathlib.Path(out);result={}
try:
 result['whoami']=call('whoami',{})
 result['claim']=call('claim',{'work_id':wid})
 if mode=='run':
  assert result['claim']['result']['claimed']['id']==wid
  suite=unittest.defaultTestLoader.discover(str(pathlib.Path(tree)/'orchtest'),pattern='test_*.py',top_level_dir=tree)
  log=p.with_suffix('.log')
  with log.open('w') as stream:r=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
  attachment={'sourceRevision':revision,'tests':r.testsRun,'failures':len(r.failures),'errors':len(r.errors),'skips':len(r.skipped),'logPath':str(log),'logSha256':hashlib.sha256(log.read_bytes()).hexdigest()}
  assert r.wasSuccessful() and r.testsRun==28 and not r.skipped
  result['attachment']=attachment
  result['done']=call('release',{'work_id':wid,'outcome':'done','result':json.dumps(attachment)})
except Exception:result['failure']=traceback.format_exc()
p.write_text(json.dumps(result,indent=2))
