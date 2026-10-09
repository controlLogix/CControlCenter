import {ContractError,strictLoads,canonicalBytes,payloadDigest,signClaims,verifyAttestation,verifyEnvelope,validate,validatePayload,evaluateTransition} from './index.js';

function hex(raw:unknown):Buffer {
  if(typeof raw!=='string' || !/^[0-9a-fA-F]{64}$/.test(raw)) throw new ContractError('invalid_key');
  return Buffer.from(raw,'hex');
}
function request(raw:Buffer):object {
  try {
    const r=strictLoads(raw) as any;
    let result:unknown;
    switch(r?.op) {
      case 'parse': result=strictLoads(r.raw);break;
      case 'canonical':result={canonical:canonicalBytes(r.value).toString('utf8'),sha256:payloadDigest(r.value)};break;
      case 'sign':result=signClaims(r.claims,hex(r.seedHex));break;
      case 'verify':result=verifyAttestation(r.attestation,hex(r.publicKeyHex),r.expectedAudience,r.now,r.payload);break;
      case 'verifyEnvelope':result=verifyEnvelope(r.envelope,hex(r.publicKeyHex),r.expectedAudience,r.now);break;
      case 'validatePayload':result=validatePayload(r.envelope);break;
      case 'evaluateTransition':result=evaluateTransition(r.request);break;
      case 'validate':result=validate(r.schema,r.value);break;
      default:throw new ContractError('unknown_operation');
    }
    return {ok:true,result};
  }catch(error){return {ok:false,error:error instanceof ContractError?error.code:'invalid_request'};}
}
let pending=Buffer.alloc(0);
let discarding=false;
const frameLimit=1048576;
process.stdin.on('data',(chunk:Buffer)=>{
  let start=0;
  while(start<chunk.length){
    const end=chunk.indexOf(10,start), stop=end<0?chunk.length:end;
    if(!discarding){
      const piece=chunk.subarray(start,stop);
      if(pending.length+piece.length>frameLimit){
        pending=Buffer.alloc(0);discarding=true;
        process.stdout.write(JSON.stringify({ok:false,error:'invalid_json'})+'\n');
      }else pending=Buffer.concat([pending,piece]);
    }
    if(end<0) break;
    if(!discarding)process.stdout.write(JSON.stringify(request(pending))+'\n');
    pending=Buffer.alloc(0);discarding=false;start=end+1;
  }
});
process.stdin.on('end',()=>{if(!discarding && pending.length)process.stdout.write(JSON.stringify(request(pending))+'\n');});
