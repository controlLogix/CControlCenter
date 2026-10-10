import pathlib,tempfile,subprocess,os,hashlib,json,shutil,difflib,tarfile,io,time
repo=pathlib.Path('/mnt/c/Users/RyanHelms/GitHub/agentmux'); root=pathlib.Path(tempfile.mkdtemp(prefix='preservation-faults-',dir='/home/ryan/.cache/agentmux-governance'));base=root/'base';base.mkdir()
blob=subprocess.check_output(['git','archive','HEAD','agentmux.sh','taskmgmt','dashboard','hub','.agentmux'],cwd=repo)
with tarfile.open(fileobj=io.BytesIO(blob)) as t:t.extractall(base,filter='data')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
cases=[
('lock','taskmgmt/run.py','    lock = directory / ".lock"','    yield\n    return\n    lock = directory / ".lock"',['python3','dashboard/test_runlock.py','TestReleaseIsConditional.test_only_one_waiter_gets_in_at_a_time'],'two holders were inside the lock together'),
('stdin','taskmgmt/notify.py','stdin=subprocess.DEVNULL,','',['python3','dashboard/test_no_inherited_stdin.py'],'FAIL'),
('warrant','taskmgmt/coordination.py','if not secrets.compare_digest(str(record.get("secret") or ""), secret):','if False:',['python3','dashboard/test_warrant.py','TestTheWarrantItself.test_a_wrong_secret_is_refused'],'FAIL: test_a_wrong_secret_is_refused'),
('archive','agentmux.sh','  mv_T "$log" "$dest" || return 1','  : "$log" "$dest"',['bash','dashboard/test_evidence_archive.sh'],'AssertionError'),
('inbox','agentmux.sh',"grep -Eq '^[A-Za-z0-9_.-]{1,64}$'", "grep -Eq '.*'",['bash','dashboard/test_inbox_guard.sh'],'queue/dev.jsonl was destroyed'),
('modal','agentmux.sh','modal_text() {','modal_text() {\n  return 1',['bash','dashboard/test_modal_guard.sh'],'MISSED - send would actuate this'),
('courier','taskmgmt/courier.py','if not isinstance(recipient, str) or not NAME_PATTERN.fullmatch(recipient):','if False:',['python3','dashboard/test_courier.py'],'recipient with a slash')]
results=[]
for name,path,old,new,cmd,expected in cases:
 work=root/name;shutil.copytree(base,work)
 target=work/path; original=target.read_bytes();text=original.decode('utf8').replace('\r\n','\n')
 # Inbox occurrence is scoped to cmd_inbox, never another shared validator.
 if name=='inbox':
  start=text.index('cmd_inbox() {');idx=text.index(old,start);changed=text[:idx]+text[idx:].replace(old,new,1)
 else:
  assert old in text,(name,old);changed=text.replace(old,new,1)
 target.write_text(changed,encoding='utf8');(root/(name+'.diff')).write_text(''.join(difflib.unified_diff(text.splitlines(True),changed.splitlines(True),fromfile='original/'+path,tofile='mutant/'+path)))
 # Test shell copies normalize line endings only; retain precise hashes.
 test=work/cmd[1]; test_original=sha(repo/cmd[1]); copied=sha(test)
 if cmd[0]=='bash':test.write_text(test.read_text().replace('\r',''))
 home=work/'private';home.mkdir(); env={'HOME':str(home),'AGENTMUX_HOME':str(home/'state'),'CLAUDE_CONFIG_DIR':str(home/'claude'),'CODEX_HOME':str(home/'codex'),'TMUX_TMPDIR':str(home),'TMPDIR':str(home),'PATH':'/usr/bin:/bin','PYTHONDONTWRITEBYTECODE':'1','GIT_CONFIG_NOSYSTEM':'1','GIT_CONFIG_GLOBAL':str(home/'gitconfig'),'AGENTMUX_NO_COURIER':'1','AGENTMUX_NO_TOAST':'1'}
 started=time.monotonic();p=subprocess.run(cmd,cwd=work,env=env,capture_output=True,text=True,timeout=90)
 log=p.stdout+p.stderr;(root/(name+'.log')).write_text(log)
 passed=p.returncode==1 and expected in log and ('Traceback' not in log or 'AssertionError' in log)
 results.append({'name':name,'source':path,'originalSha256':hashlib.sha256(original).hexdigest(),'matchesCurrentRepository':hashlib.sha256(original).hexdigest()==sha(repo/path),'mutantSha256':sha(target),'diffSha256':sha(root/(name+'.diff')),'test':cmd[1],'originalTestSha256':test_original,'copiedTestSha256':copied,'executedTestSha256':sha(test),'testAdaptation':'CRLF normalization only' if cmd[0]=='bash' else 'none','command':cmd,'exitCode':p.returncode,'expectedAssertion':expected,'observedExpectedAssertion':expected in log,'negativeControlPassed':passed,'logSha256':sha(root/(name+'.log')),'seconds':round(time.monotonic()-started,3)})
 print(name,p.returncode,passed,flush=True)
 if not passed:print(log[-2200:],flush=True)
report={'candidate':subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip(),'root':str(root),'historicalExclusions':'Do not repeat argument/run/lifecycle/coordination/residue historical baselines; these seven cover separate retained predicates.','results':results,'status':'passed' if all(x['negativeControlPassed'] for x in results) else 'findings','limits':['Fault sensitivity of selected existing assertions only, not proof of complete security coverage.','No providers or live operator state; tests use copied source/private homes and their declared fake or offline dependencies.','Runtime and test line endings normalized only where recorded; source mutation diffs retained.']}
(root/'result.json').write_text(json.dumps(report,indent=2)+'\n');print(root)