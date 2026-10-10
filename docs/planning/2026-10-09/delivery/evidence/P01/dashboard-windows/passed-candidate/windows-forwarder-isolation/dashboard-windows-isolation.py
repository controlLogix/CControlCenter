import hashlib,importlib.util,json,os,subprocess,tempfile
from pathlib import Path
root=Path(tempfile.mkdtemp(prefix='p01-dashboard-windows-isolation-',dir='/home/ryan/.cache/agentmux-governance'));home=root/'codex';home.mkdir();env={'PATH':'/usr/local/bin:/usr/bin:/bin','HOME':str(root),'CODEX_HOME':str(home),'LANG':'C.UTF-8'}
wrapper=Path('/home/ryan/.local/share/agentmux/windows-clients/forward.py');spec=importlib.util.spec_from_file_location('forward',wrapper);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
report={'root':str(root),'wrapperSha256':hashlib.sha256(wrapper.read_bytes()).hexdigest(),'clientsSha256':hashlib.sha256((wrapper.parent/'clients.json').read_bytes()).hexdigest(),'checks':[]}
config=json.loads((wrapper.parent/'clients.json').read_text())['codex']
probe="console.log(JSON.stringify({CODEX_HOME:process.env.CODEX_HOME,providerEnvPresent:['OPENAI_API_KEY','CODEX_CUSTOM_API_KEY','ANTHROPIC_API_KEY'].some(k=>!!process.env[k])}))"
p=subprocess.run([config['exe'],'-e',probe],env=m.environment(env),capture_output=True,text=True,timeout=20);report['windowsEnvironment']=json.loads(p.stdout);assert not report['windowsEnvironment']['providerEnvPresent'];assert 'p01-dashboard-windows-isolation-' in report['windowsEnvironment']['CODEX_HOME']
def run(name,args):
 r=subprocess.run(['codex',*args],env=env,cwd=root,capture_output=True,text=True,stdin=subprocess.DEVNULL,timeout=30);(root/(name+'.log')).write_text(r.stdout+r.stderr);report['checks'].append({'name':name,'command':['codex',*args],'exitCode':r.returncode,'output':r.stdout+r.stderr});return r
(home/'config.toml').write_text('p01_private_configuration_sentinel = true\n')
r=run('private-config-rejection',['exec','--strict-config','--skip-git-repo-check','noop']);assert r.returncode!=0 and 'p01_private_configuration_sentinel' in (r.stdout+r.stderr)
(home/'config.toml').write_text('')
(home/'p01-private.config.toml').write_text('model_provider="p01_private"\nmodel="fixture-no-inference"\n[model_providers.p01_private]\nname="private-test"\nbase_url="http://127.0.0.1:1/v1"\nwire_api="responses"\nenv_key="P01_MISSING_PROVIDER_KEY"\n')
r=run('private-profile-missing-key',['exec','--strict-config','--profile','p01-private','--skip-git-repo-check','noop']);assert r.returncode!=0 and 'P01_MISSING_PROVIDER_KEY' in (r.stdout+r.stderr)
report['version']=run('windows-version',['--version']).stdout.strip();report['qualified']=True;report['limits']=['Config sentinel proves actual Windows CLI loaded private CODEX_HOME. Windows node probe confirms translated private path and no provider keys.','Profile selects loopback custom provider with absent key; CLI must reject missing key before inference. No real credentials loaded by fixture.','No filesystem tracing of Windows default profile reads; explicit CODEX_HOME routing and observed private configuration errors qualify this test boundary, not an OS-wide access audit.']
(root/'isolation-result.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))
