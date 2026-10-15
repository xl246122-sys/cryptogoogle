import test from 'node:test';
import assert from 'node:assert/strict';
import {parseExitPush,recordExitPush,flushExitReceipts,bindExitDevice} from '../src/services/exitPush';
const payload={eventType:'POSITION_EXIT_NOTICE',deliveryId:'exit-delivery-'+'a'.repeat(64),noticeId:'exit-'+'b'.repeat(64),issuedAtMs:'1000',expiresAtMs:'301000'};
test('exit inbox hints never require fresh buy validity or create a BUY',()=>{
  assert.ok(parseExitPush(payload));
  assert.equal(parseExitPush({...payload,eventType:'BUY'}),null);
  assert.equal(parseExitPush({...payload,deliveryId:[]}),null);
  assert.equal(parseExitPush({...payload,expiresAtMs:'bad'}),null);
});
test('durable exit receipts retry lost ACK, deduplicate and stay bound to the original server/device',async()=>{
  const oldFetch=globalThis.fetch,oldStorage=globalThis.localStorage;const memory=new Map<string,string>();
  const configKey='cryptog_device_connection_v1',queueKey='cryptog_exit_receipts_v1';
  const config={url:'https://example.test',token:'a'.repeat(32)};
  memory.set(configKey,JSON.stringify(config));
  Object.defineProperty(globalThis,'localStorage',{configurable:true,value:{getItem:(k:string)=>memory.get(k)??null,setItem:(k:string,v:string)=>memory.set(k,v),removeItem:(k:string)=>memory.delete(k)}});
  try {
    await recordExitPush(payload,'received');await recordExitPush(payload,'received');await recordExitPush(payload,'opened');
    assert.equal(JSON.parse(memory.get(queueKey)!).length,2);
    globalThis.fetch=async()=>{throw new Error('lost ACK');};
    await assert.rejects(flushExitReceipts());assert.equal(JSON.parse(memory.get(queueKey)!).length,2);
    let requests=0;
    globalThis.fetch=async(_url,init)=>{requests++;const row=JSON.parse(String(init?.body));return {ok:true,json:async()=>({ok:true,deliveryId:row.deliveryId,kind:row.kind,serverReceivedAtMs:12345})} as Response;};
    memory.set(configKey,JSON.stringify({...config,token:'b'.repeat(32)}));
    await flushExitReceipts();assert.equal(requests,0);
    memory.set(configKey,JSON.stringify(config));await flushExitReceipts();assert.equal(requests,2);assert.deepEqual(JSON.parse(memory.get(queueKey)!),[]);
    globalThis.fetch=async()=>({ok:true,json:async()=>({ok:true,registered:true,pushEnabled:false})}) as Response;
    assert.equal(await bindExitDevice('fake-token-for-test-only'),false);
  } finally{globalThis.fetch=oldFetch;Object.defineProperty(globalThis,'localStorage',{configurable:true,value:oldStorage});}
});
