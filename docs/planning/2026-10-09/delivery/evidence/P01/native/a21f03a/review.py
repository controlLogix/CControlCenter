import json,pathlib,subprocess,hashlib,io,importlib.util
root=pathlib.Path(__file__).parent;candidate='a21f03a8a6792f4fa21099afe62804a56dfa7fc4';review={'runId':38012525208,'candidate':candidate,'phaseAccepted':False,'platforms':{}}
s=importlib.util.spec_from_file_location('admission','tests/contracts/plugin_preservation.py');a=importlib.util.module_from_spec(s);s.loader.exec_module(a)
for host,job in [('linux',114095482071),('macos',114095482371)]:
 p=root/host
 if not p.exists():continue
 reports={f.name:json.loads(f.read_text()) for f in p.glob('*.json')};refs=[]
 for name,d in reports.items():
  for key in ['sourceHashes','sourceSha256','sourceHashesAfter']:
   if isinstance(d.get(key),dict):refs.extend((name,k,v) for k,v in d[key].items())
 paths=sorted({k for _,k,_ in refs});raw=subprocess.check_output(['git','cat-file','--batch'],input=''.join(candidate+':'+k+'\n' for k in paths).encode());stream=io.BytesIO(raw);actual={}
 for path in paths:
  header=stream.readline().split();assert header[1]==b'blob',header;actual[path]=hashlib.sha256(stream.read(int(header[2]))).hexdigest();assert stream.read(1)==b'\n'
 mismatch=[(n,k,v,actual[k]) for n,k,v in refs if v!=actual[k]];assert not mismatch,mismatch
 ci=reports['ci-result.json'];c=reports['contracts.json'];h=reports['hub-full-result.json'];plugin=reports['plugin-preservation.json']
 assert ci['sourceCommit']==candidate and ci['exitCode']==0 and len(ci['checks'])==23 and all(x['exitCode']==0 for x in ci['checks'])
 assert a.admitted(plugin,{k:actual[k] for k in plugin['sourceHashes']}) and plugin['isolatedHomeRemoved']
 assert plugin['logSha256']==hashlib.sha256((p/'plugin-preservation.log').read_bytes()).hexdigest()
 assert ci['pluginPreservation']['reportSha256']==hashlib.sha256((p/'plugin-preservation.json').read_bytes()).hexdigest()
 admission=subprocess.run(['python','docs/planning/2026-10-09/delivery/check_conformance_evidence.py','--report',str(p/'contracts.json'),'--candidate',candidate,'--environment',host],capture_output=True,text=True);assert admission.returncode==0,admission.stdout+admission.stderr;(p/'independent-admission.txt').write_text(admission.stdout+admission.stderr)
 (p/'job.log').write_bytes(subprocess.check_output(['gh','run','view','38012525208','--job',str(job),'--log']))
 review['platforms'][host]={'jobId':job,'jobUrl':f'https://github.com/controlLogix/agentmux/actions/runs/38012525208/job/{job}','checks':len(ci['checks']),'failedChecks':[],'hashComparisons':len(refs),'sourceMismatches':mismatch,'conformance':{k:c[k] for k in ['testsRun','failures','errors','skips','exitCode','sourceUnchangedDuringRun']},'independentAdmissionExit':admission.returncode,'hub':{k:h[k] for k in ['tests','status','failures','skips']},'caseCounts':{n:len(reports[n]['cases']) for n in ['storage-result.json','leaf-result.json','signed-leaf-result.json']},'plugin':{'tests':plugin['tests'],'sourceReferences':len(plugin['sourceHashes']),'sourceUnchanged':plugin['sourceUnchangedDuringRun'],'isolatedHomeRemoved':True,'independentAdmission':True,'exactLogHashMatch':True,'ciReportHashMatch':True,'methodStatuses':sorted({m['status'] for su in plugin['suites'] for m in su['methods']})},'reportHashes':{n:hashlib.sha256((p/n).read_bytes()).hexdigest() for n in reports}}
review['limits']=['Native exact-candidate fixture and compatibility evidence; not provider inference, P06 qualification or P01 phase acceptance.','Previous candidate and WSL evidence kept distinct.'];(root/'independent-native-review.json').write_text(json.dumps(review,indent=2)+'\n');print(json.dumps(review,indent=2))
