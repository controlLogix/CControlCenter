import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {resolve} from 'node:path';
import {evaluateTransition} from './index.js';

const modelPath = process.env.AGENTMUX_STATE_MODELS ?? resolve(process.env.AGENTMUX_SCHEMA_DIR ?? 'contracts/v1/schemas','../models/state-machines.json');
const models = JSON.parse(readFileSync(modelPath,'utf8')).machines;
function request(machine: string, edge: any): any {
  return {schemaVersion:'1.0.0',machine,
    ownerSnapshot:{entityId:'entity',ownerHubId:'hub',scopeId:'scope',state:edge.from,revision:7,cancellationPending:edge.from === 'cancel_requested'},
    intent:{entityId:'entity',expectedRevision:7,event:edge.event,operationId:'operation',payloadDigest:`sha256:${'a'.repeat(64)}`},
    authority:{entityId:'entity',ownerHubId:'hub',scopeId:'scope',actorRole:edge.actorRole,evidenceRefs:['fixture:owner-observation']},
    guards:Object.fromEntries(edge.requires.map((g: string) => [g,`fixture:${g}`]))};
}

test('all 68 model edges require the exact role, revision and evidence',()=>{
  let edges=0;
  for (const [name,machine] of Object.entries(models) as [string,any][]) {
    for (const edge of machine.transitions) {
      const r=request(name,edge), before=JSON.stringify(r);
      const result=evaluateTransition(r,modelPath) as any;
      assert.equal(result.state,edge.to); assert.equal(result.revision,8);
      assert.equal(JSON.stringify(r),before);
      result.evidenceRefs.push('fixture:mutation'); assert.equal(r.authority.evidenceRefs.length,1);
      for (const guard of edge.requires) {
        const missing=structuredClone(r); delete missing.guards[guard];
        assert.throws(()=>evaluateTransition(missing,modelPath));
      }
      const wrongRole=structuredClone(r); wrongRole.authority.actorRole='wrong_role';
      assert.throws(()=>evaluateTransition(wrongRole,modelPath));
      const stale=structuredClone(r); stale.intent.expectedRevision=6;
      assert.throws(()=>evaluateTransition(stale,modelPath)); edges++;
    }
  }
  assert.equal(edges,68);
});

test('malformed requests cannot invent state, authority, guards or revisions',()=>{
  const base=request('plugin',models.plugin.transitions[0]);
  const mutations:((r:any)=>void)[]=[
    r=>{r.extra=true;},r=>{r.ownerSnapshot.extra=true;},r=>{r.intent.extra=true;},r=>{r.authority.extra=true;},
    r=>{r.guards.extra='fixture:extra';},r=>{r.guards.package_provenance_valid=true;},
    r=>{r.authority.evidenceRefs=[];},r=>{r.authority.evidenceRefs=['same','same'];},r=>{r.authority.evidenceRefs=[' '];},
    r=>{r.authority.ownerHubId='other';},r=>{r.authority.scopeId='other';},r=>{r.authority.entityId='other';},
    r=>{r.intent.entityId='other';},r=>{r.intent.payloadDigest='not-a-digest';},r=>{r.machine='unknown';},
    r=>{r.ownerSnapshot.state='ready';},r=>{r.ownerSnapshot.revision=-1;},
    r=>{r.ownerSnapshot.revision=Number.MAX_SAFE_INTEGER;r.intent.expectedRevision=Number.MAX_SAFE_INTEGER;},
    r=>{r.ownerSnapshot.cancellationPending='false';},r=>{r.intent.operationId='unsafe.dot';}
  ];
  for (const mutate of mutations) { const r=structuredClone(base);mutate(r);assert.throws(()=>evaluateTransition(r,modelPath)); }
});

test('cancellation remains sticky through uncertainty and blocks normal completion',()=>{
  for (const event of ['reconcile_running','reconcile_terminal']) {
    const edge=models.attempt.transitions.find((e:any)=>e.from==='effect_uncertain' && e.event===event);
    const r=request('attempt',edge);r.ownerSnapshot.cancellationPending=true;
    assert.throws(()=>evaluateTransition(r,modelPath));
  }
  const edge=models.attempt.transitions.find((e:any)=>e.from==='effect_uncertain' && e.event==='reconcile_cancel_pending');
  const r=request('attempt',edge);r.ownerSnapshot.cancellationPending=true;
  const result=evaluateTransition(r,modelPath) as any;
  assert.equal(result.state,'cancel_requested');assert.equal(result.cancellationPending,true);
  const confirmed=models.attempt.transitions.find((e:any)=>e.from==='effect_uncertain' && e.event==='reconcile_cancelled');
  const finalRequest=request('attempt',confirmed);finalRequest.ownerSnapshot.cancellationPending=true;
  const finalResult=evaluateTransition(finalRequest,modelPath) as any;
  assert.equal(finalResult.state,'cancelled');assert.equal(finalResult.cancellationPending,false);
});

test('evidence reference limits count Unicode code points',()=>{
  const r=request('plugin',models.plugin.transitions[0]);
  r.authority.evidenceRefs=['😀'.repeat(300)];
  assert.doesNotThrow(()=>evaluateTransition(r,modelPath));
  r.authority.evidenceRefs=['😀'.repeat(513)];
  assert.throws(()=>evaluateTransition(r,modelPath));
  for (const blank of ['\u0085','\ufeff','\u001c','\u2000\u3000']) {
    r.authority.evidenceRefs=[blank];
    assert.throws(()=>evaluateTransition(r,modelPath));
  }
});
