import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync,mkdtempSync,cpSync,writeFileSync,rmSync} from 'node:fs';
import {resolve} from 'node:path';
import {tmpdir} from 'node:os';
import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {strictLoads,canonicalBytes,payloadDigest,signClaims,publicKeyForSeed,verifyAttestation,verifyEnvelope,validate} from './index.js';

test('rejects duplicate escaped keys, comments, trailing syntax and invalid UTF-8',()=>{
  for(const raw of ['{"a":1,"\\u0061":2}','{"x":{"a":1,"a":2}}','{/*x*/"a":1}','[1,]','true false','9007199254740992','"\\ud800"','1e999']) assert.throws(()=>strictLoads(raw));
  assert.throws(()=>strictLoads(Buffer.from([0xc0,0xaf])));
  assert.deepEqual(strictLoads('{"a":{"x":1},"b":{"x":2}}'),{a:{x:1},b:{x:2}});
});
test('preserves hostile property names without prototype mutation',()=>{
  const v=strictLoads('{"__proto__":{"polluted":true}}');
  assert.equal(canonicalBytes(v).toString(),'{"__proto__":{"polluted":true}}');
  assert.equal(({} as any).polluted,undefined);
});
test('canonical numbers and UTF-16 property ordering match JCS',()=>{
  assert.equal(canonicalBytes({z:-0,a:[1e30,1e-7,0.000001]}).toString(),'{"a":[1e+30,1e-7,0.000001],"z":0}');
  assert.equal(canonicalBytes({'\ufffd':1,'\ud83d\ude00':2}).toString(),'{"😀":2,"�":1}');
  assert.throws(()=>canonicalBytes(new Date()));
  assert.throws(()=>canonicalBytes({get secret(){throw Error('getter invoked');}}));
});
test('RFC8032 seed derives the published public key',()=>{
  const seed=Buffer.from('9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60','hex');
  assert.equal(publicKeyForSeed(seed).toString('hex'),'d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a');
  assert.equal(signClaims({a:1},seed),signClaims({a:1},seed));
});
test('bounds canonical output, container depth and dense arrays',()=>{
  assert.throws(()=>canonicalBytes('x'.repeat(1048576)));
  let nested:any=[];
  for(let i=1;i<64;i++)nested=[nested];
  canonicalBytes(nested);
  assert.throws(()=>canonicalBytes([nested]));
  assert.throws(()=>strictLoads('['.repeat(65)+']'.repeat(65)));
  const sparse:any=[];sparse.length=1;sparse.extra=1;
  assert.throws(()=>canonicalBytes(sparse));
});
test('CLI rejects an oversized frame once and resumes at the next line',()=>{
  const cli=fileURLToPath(new URL('./cli.js',import.meta.url));
  const p=spawnSync(process.execPath,[cli],{input:'x'.repeat(1048577)+'\n'+JSON.stringify({op:'parse',raw:'{}'})+'\n',encoding:'utf8'});
  assert.equal(p.status,0);
  const rows=p.stdout.trim().split('\n').map(s=>JSON.parse(s));
  assert.equal(rows.length,2);assert.equal(rows[0].ok,false);assert.deepEqual(rows[1],{ok:true,result:{}});
  const eof=spawnSync(process.execPath,[cli],{input:'x'.repeat(1048577),encoding:'utf8'});
  assert.equal(eof.status,0);assert.equal(eof.stdout.trim().split('\n').length,1);
});
test('compiled schema cache invalidates when trusted schema bytes change',()=>{
  const root=process.env.AGENTMUX_SCHEMA_DIR;
  assert.ok(root,'Set AGENTMUX_SCHEMA_DIR to promoted schema directory');
  const copy=mkdtempSync(resolve(tmpdir(),'agentmux-schema-'));
  try {
    cpSync(root,copy,{recursive:true});
    const fixturePath=process.env.AGENTMUX_CONTRACT_EXAMPLES;
    assert.ok(fixturePath);
    const value=JSON.parse(readFileSync(fixturePath,'utf8'))['operation-context'];
    validate('operation-context',value,copy);
    validate('operation-context',value,copy);
    const path=resolve(copy,'operation-context.schema.json');
    const schema=JSON.parse(readFileSync(path,'utf8'));
    schema.properties.operationId.const='different-operation';
    writeFileSync(path,JSON.stringify(schema));
    assert.throws(()=>validate('operation-context',value,copy));
    validate('operation-context',value,root);
  }finally{rmSync(copy,{recursive:true,force:true});}
});
test('validates promoted schemas and rejects unsigned outer changes',()=>{
  const fixturePath=process.env.AGENTMUX_CONTRACT_EXAMPLES;
  assert.ok(fixturePath,'Set AGENTMUX_CONTRACT_EXAMPLES to promoted valid-examples.json');
  const fixtures=JSON.parse(readFileSync(resolve(fixturePath),'utf8'));
  const envelope=structuredClone(fixtures.messageEnvelope ?? fixtures['message-envelope']);
  assert.ok(envelope,'Message envelope fixture is required');
  const seed=Buffer.alloc(32,7), key=publicKeyForSeed(seed), payload=envelope.payload;
  const a=envelope.ingressAttestation;
  a.claims.operation.payloadDigest=payloadDigest(payload);
  envelope.operation=structuredClone(a.claims.operation);
  a.signature=signClaims(a.claims,seed);
  validate('message-envelope',envelope);
  const now=a.claims.issuedAt;
  assert.deepEqual(verifyEnvelope(envelope,key,a.claims.audience,now),a.claims);
  const tampered=structuredClone(envelope);tampered.sourceInstanceId='attacker';
  assert.throws(()=>verifyEnvelope(tampered,key,a.claims.audience,now));
  assert.throws(()=>verifyAttestation(a,key,a.claims.audience,a.claims.expiresAt,payload));
  assert.throws(()=>verifyAttestation(a,key,a.claims.audience,now,{changed:true}));
  assert.throws(()=>verifyAttestation(a,Buffer.alloc(32,9),a.claims.audience,now,payload));
});
