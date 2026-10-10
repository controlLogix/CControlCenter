"""Run preserved CLI assertions through relocated real plugin launcher and real private HTTP runtime."""
import argparse,sys,os,json,tempfile,shutil,subprocess,unittest,hashlib
from pathlib import Path
parser=argparse.ArgumentParser();parser.add_argument('--repo',type=Path,required=True);parser.add_argument('--plugin',type=Path,required=True);parser.add_argument('--suite',choices=['agents','teams'],required=True);parser.add_argument('--result',type=Path,required=True);a=parser.parse_args()
a.repo=a.repo.resolve();a.plugin=a.plugin.resolve();a.result=a.result.resolve()
os.environ['PYTHONDONTWRITEBYTECODE']='1'
for k in list(os.environ):
 if k.startswith('AGENTMUX_') or k in ('CC_ENFORCE','TM_ENFORCE','CODEX_HOME','CLAUDE_CONFIG_DIR'):os.environ.pop(k)
sys.path.insert(0,str(a.repo/'dashboard'))
with tempfile.TemporaryDirectory(prefix='plugin-review-relocated-') as td:
 installed=Path(td)/'package with spaces';shutil.copytree(a.plugin,installed);launcher=installed/'skills/agent-config/scripts/runtime.py'
 if a.suite=='agents':
  import test_agentcli as m
  base=m.AgentCLI
 else:
  import test_teamcli as m
  base=m.TeamCLI
 class ThroughPlugin(base):
  def cli(self,*args,code=0):
   env=dict(os.environ,AGENTMUX_REPO=str(a.repo),AGENTMUX_DASHBOARD=f'http://127.0.0.1:{self.httpd.server_address[1]}')
   if a.suite=='teams':env.update(AGENTMUX_AGENT='teamcli-test',AGENTMUX_TRUST_IDENTITY='1')
   result=subprocess.run([sys.executable,str(launcher),'coordination',*args],env=env,capture_output=True,text=True,timeout=20)
   self.assertEqual(result.returncode,code,result.stdout+result.stderr)
   return result
 result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(ThroughPlugin))
 os.chdir(m.OLD_CWD);m.TEMP.cleanup()
 report={'suite':a.suite,'tests':result.testsRun,'failures':[str(t) for t,_ in result.failures],'errors':[str(t) for t,_ in result.errors],'skips':result.skipped,'pluginHashes':{p.relative_to(a.plugin).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in a.plugin.rglob('*') if p.is_file() and '__pycache__' not in p.parts},'limitations':['Real private dashboard/SQLite/CLI; preserved tests invoked via relocated package launcher.','Team selection and provider launch use original bounded fixtures; no model/provider execution or host plugin loading.']}
 a.result.parent.mkdir(parents=True,exist_ok=True);a.result.write_text(json.dumps(report,indent=2)+'\n')
 raise SystemExit(not result.wasSuccessful() or bool(result.skipped))
