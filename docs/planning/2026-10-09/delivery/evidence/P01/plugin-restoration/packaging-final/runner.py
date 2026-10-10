import hashlib,importlib.util,json,os,sys,tempfile,time,unittest
from pathlib import Path
repo=Path('/mnt/c/Users/RyanHelms/GitHub/agentmux');pkg=repo/'plugins/agentmux-orchestration'
def hashes():return{p.relative_to(pkg).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()for p in sorted(pkg.rglob('*'))if p.is_file()and'__pycache__'not in p.parts}
out=Path(tempfile.mkdtemp(prefix='plugin-packaging-final-',dir='/home/ryan/.cache/agentmux-governance'))
before=hashes();old=dict(os.environ)
with tempfile.TemporaryDirectory(prefix='packaging-private-')as private:
    os.environ.clear();os.environ.update(PATH='/usr/local/bin:/usr/bin:/bin',HOME=private,AGENTMUX_HOME=private+'/state',CLAUDE_CONFIG_DIR=private+'/claude',CODEX_HOME=private+'/codex',PYTHONDONTWRITEBYTECODE='1',AGENTMUX_PLUGIN_ROOT=str(pkg))
    os.chdir(repo);suite=unittest.TestSuite()
    for i,path in enumerate((repo/'dashboard/test_plugin_skills.py',pkg/'tests/test_packaging.py')):
        spec=importlib.util.spec_from_file_location('packaging_final_'+str(i),path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);suite.addTests(unittest.defaultTestLoader.loadTestsFromModule(module))
    with(out/'tests.log').open('w',encoding='utf-8')as log:
        start=time.monotonic();result=unittest.TextTestRunner(stream=log,verbosity=2).run(suite)
    os.environ.clear();os.environ.update(old)
after=hashes()
record={'candidateBase':'80f43e02f3344696a3985c48ef12578319f3bd0f','command':['python3',__file__],'tests':result.testsRun,'failures':result.failures,'errors':result.errors,'skips':result.skipped,'successful':result.wasSuccessful(),'seconds':time.monotonic()-start,'packageHashes':before,'packageUnchanged':before==after,'python':sys.version,'originalTestSha256':hashlib.sha256((repo/'dashboard/test_plugin_skills.py').read_bytes()).hexdigest(),'logSha256':hashlib.sha256((out/'tests.log').read_bytes()).hexdigest(),'scope':'Unchanged4 runtime launcher checks plus3 packaging checks on final assembled package, private configuration, no providers or personal installation.'}
(out/'result.json').write_bytes((json.dumps(record,indent=2)+'\n').encode('utf-8'));print(out)
assert result.testsRun==7 and result.wasSuccessful()and not result.skipped and before==after
