import {connect,headers} from '@nats-io/transport-node';
import {jetstream,jetstreamManager} from '@nats-io/jetstream';

// Disposable fixture only: business authorization and production ownership are absent.
function bytes(value:unknown):Uint8Array{return Buffer.from(JSON.stringify(value),'utf8');}
function headerMap(value:Record<string,string>={}){const h=headers();for(const [k,v] of Object.entries(value))h.set(k,v);return h;}
function safeError(error:any):object {
  const code=Number(error?.code ?? error?.api_error?.err_code);
  const status=Number(error?.status);
  const category=code===10071?'conflict':(code===10037 || status===404)?'not_found':error?.message==='operation_conflict'?'operation_conflict':error?.message==='history_gap'?'history_gap':'broker_error';
  return {ok:false,error:category,...(Number.isFinite(code)?{apiCode:code}:{})};
}
async function execute(r:any):Promise<object>{
  const url=process.env.AMX_STORAGE_URL;
  if(!url || !process.env.AMX_STORAGE_TOKEN)return {ok:false,error:'missing_fixture_environment'};
  // The harness supplies an isolated local broker, never a real team endpoint.
  if(!['127.0.0.1','localhost','[::1]'].includes(new URL(url).hostname))return {ok:false,error:'nonlocal_broker'};
  const nc=await connect({servers:url,token:process.env.AMX_STORAGE_TOKEN,reconnect:false,timeout:3000});
  try{
    const js=jetstream(nc,{timeout:3000}), manager=await jetstreamManager(nc,{timeout:3000});
    let result:unknown;
    if(r.op==='inspect'){
      const info=await manager.streams.info(r.stream);
      result={serverVersion:nc.info?.version,config:info.config,state:info.state};
    }else if(r.op==='publish'){
      const ack=await js.publish(r.subject,bytes(r.record),{expect:{lastSubjectSequence:r.expectedSequence},msgID:r.msgId,headers:headerMap(r.headers)});
      result={sequence:ack.seq,duplicate:ack.duplicate,stream:ack.stream};
    }else if(r.op==='read'){
      const message=await manager.streams.getMessage(r.stream,{last_by_subj:r.subject});
      if(!message)return {ok:false,error:'not_found'};
      result={record:JSON.parse(new TextDecoder('utf8',{fatal:true}).decode(message.data)),sequence:message.seq};
    }else if(r.op==='reconcile'){
      const info=await manager.streams.info(r.stream);
      // A bounded complete fixture history is required; gaps cannot mean no operation.
      if(info.state.first_seq>1 || info.state.num_deleted || info.state.messages>10000)throw Error('history_gap');
      let start=1, found:any=null;
      while(start<=info.state.last_seq){
        const message=await manager.streams.getMessage(r.stream,{seq:start});
        if(!message)throw Error('history_gap');
        if(message.seq>info.state.last_seq)break;
        if(message.subject!==r.subject){start=message.seq+1;continue;}
        const record=JSON.parse(new TextDecoder('utf8',{fatal:true}).decode(message.data));
        if(record.operation?.operationId===r.operationId){
          if(record.operation.payloadDigest!==r.payloadDigest)throw Error('operation_conflict');
          found={record,sequence:message.seq,replayed:true};break;
        }
        start=message.seq+1;
      }
      if(!found)return {ok:false,error:'not_found'};
      result=found;
    }else if(r.op==='batch' && r.messages){
      // Raw protocol mode allows negative header/sequence fixtures independently.
      const replies=[];
      for(const message of r.messages){
        const ack=await nc.request(message.subject,bytes(message.record),{headers:headerMap(message.headers),timeout:3000});
        const body=ack.data.length ? JSON.parse(ack.string()) : {staged:true};
        if(body.error)return {ok:false,error:'batch_rejected',apiCode:body.error.err_code};
        replies.push(body);
      }
      result={replies};
    }else if(r.op==='batch'){
      if(!Array.isArray(r.records) || r.records.length<2 || r.records.length>1000)return {ok:false,error:'invalid_batch'};
      const batch=await js.startBatch(r.subject,bytes(r.records[0]),{expect:{lastSubjectSequence:r.expectedSequence}});
      const last=r.records.length-1;
      for(let i=1;i<last;i++)await batch.add(r.subject,bytes(r.records[i]),{ack:true});
      if(r.commit===false){
        await batch.add(r.subject,bytes(r.records[last]),{ack:true});
        await nc.flush();result={batch:batch.id,staged:batch.count,committed:false};
      }else{
        const ack=await batch.commit(r.subject,bytes(r.records[last]));
        result={sequence:ack.seq,stream:ack.stream,batch:ack.batch,count:ack.count,committed:true};
      }
    }else return {ok:false,error:'unknown_operation'};
    return {ok:true,result};
  }finally{await nc.close();}
}

// One request per process. Do not emit credentials, requests or broker error text.
let input=Buffer.alloc(0),tooLarge=false;
for await(const chunk of process.stdin){
  const b=Buffer.from(chunk);
  if(input.length+b.length>1048576){tooLarge=true;input=Buffer.alloc(0);break;}
  input=Buffer.concat([input,b]);
}
let output:object;
try{output=tooLarge?{ok:false,error:'size_limit'}:await execute(JSON.parse(new TextDecoder('utf8',{fatal:true}).decode(input)));}
catch(error){output=safeError(error);}
process.stdout.write(JSON.stringify(output)+'\n');
