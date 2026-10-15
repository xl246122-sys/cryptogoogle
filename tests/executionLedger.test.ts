import test from 'node:test';
import assert from 'node:assert/strict';
import {ExecutionFill, summarizeFills, latencyMetrics, validateFill} from '../src/services/executionLedger';
import {rememberAction, libraryJournal, flushLibraryQueue, effectiveExecutionRows} from '../src/services/modelLibrary';

const now = Date.now()-100000;
const fill = (id='buy', side:'BUY'|'SELL'='BUY', updates:Partial<ExecutionFill>={}):ExecutionFill => ({
  fillId:id,positionId:'p1',side,source:'MANUAL',price:side==='BUY'?100:110,quantity:1,executedAtMs:now+(side==='SELL'?1000:0),
  commission:.1,commissionAsset:'USDT',commissionAssetUsdtRate:null,referencePrice:null,referenceAtMs:null,timeApproximate:false,...updates});
const near = (a:number|null,b:number)=>assert.ok(a!==null && Math.abs(a-b)<1e-8,`${a} != ${b}`);

test('partial fills allocate entry fees; BTC fees reduce actual inventory without double counting',()=>{
  let s=summarizeFills([fill(),fill('s','SELL',{quantity:.4,commission:.044})]); near(s.realizedNetUsdt,3.916);near(s.inventory,.6);near(s.remainingCostUsdt,60.06);
  s=summarizeFills([fill('b','BUY',{commission:.001,commissionAsset:'BTC'}),fill('s','SELL',{quantity:.999,commission:.10989})]);near(s.realizedNetUsdt,9.78011);assert.ok(s.closed);
  s=summarizeFills([fill('b','BUY',{commission:0}),fill('s','SELL',{quantity:.99,commission:.01,commissionAsset:'BTC'})]);near(s.realizedNetUsdt,8.9);assert.ok(s.closed);
});
test('unknown fees and BNB conversion are never invented; explicit zero remains valid',()=>{
  assert.equal(summarizeFills([fill('b','BUY',{commission:null}),fill('s','SELL')]).realizedNetUsdt,null);
  assert.equal(summarizeFills([fill('b','BUY',{commissionAsset:'BNB'}),fill('s','SELL')]).realizedNetUsdt,null);
  near(summarizeFills([fill('b','BUY',{commission:.001,commissionAsset:'BNB',commissionAssetUsdtRate:600}),fill('s','SELL',{commission:0})]).realizedNetUsdt,9.4);
});
test('slippage and latency are diagnostic, missing or negative clock deltas stay unknown',()=>{
  const s=summarizeFills([fill('b','BUY',{referencePrice:99,referenceAtMs:now-5000}),fill('s','SELL')]);
  near(s.realizedNetUsdt,9.8);near(s.slippage[0].quoteDifferenceUsdt,1);assert.equal(s.slippage[0].benchmarkAgeMs,5000);
  assert.deepEqual(latencyMetrics(100,200,300,500),{signalToEntryMs:400,receivedToEntryMs:300,openedToEntryMs:200});
  assert.equal(latencyMetrics(500,undefined,undefined,100).signalToEntryMs,null);
});
test('reject overselling, duplicate fills, invalid fees and future benchmark',()=>{
  assert.throws(()=>summarizeFills([fill('s','SELL')]));assert.throws(()=>summarizeFills([fill(),fill()]));
  assert.ok(validateFill(fill('b','BUY',{commission:-1})));assert.ok(validateFill(fill('b','BUY',{price:NaN})));
  assert.ok(validateFill(fill('b','BUY',{price:1e308,quantity:1e308})));
  assert.ok(validateFill(fill('b','BUY',{referencePrice:100,referenceAtMs:now+1})));
  assert.throws(()=>summarizeFills([fill('b','BUY',{exchangeTradeId:'123'}),fill('b2','BUY',{exchangeTradeId:'123'})]));
});

class MemoryStorage {
  map=new Map<string,string>();
  get length(){return this.map.size;} key(i:number){return [...this.map.keys()][i]??null;}
  getItem(k:string){return this.map.get(k)??null;}setItem(k:string,v:string){this.map.set(k,v);}clear(){this.map.clear();this.map.set('cryptog_device_connection_v1',JSON.stringify({url:'https://example.test',token:'test_device_credential_12345678901234567890'}));}
}
const memory=new MemoryStorage();
Object.defineProperty(globalThis,'localStorage',{value:memory,configurable:true});
const action = (eventId:string)=>({eventId,recordType:'PHONE_RECEIVED' as const,alertId:'BTCUSDT_test',actedAtMs:now});
const ack = (id:string)=>new Response(JSON.stringify({ok:true,eventId:id}),{status:200});
let transport: typeof fetch;
let supportsProtocol = true;
Object.defineProperty(globalThis,'fetch',{configurable:true,
  get:()=>async(input:Parameters<typeof fetch>[0], init?:Parameters<typeof fetch>[1]) => String(input).includes('/capabilities')
    ? new Response(JSON.stringify({userActionProtocol:supportsProtocol?2:1}),{status:200}) : transport(input,init),
  set:(value:typeof fetch)=>{transport=value;},
});

test('concurrent append while request pending survives; only one drain runs',async()=>{
  memory.clear();let finish!:(v:Response)=>void;let calls=0;
  globalThis.fetch=async()=>{calls++;return await new Promise<Response>(resolve=>{finish=resolve;});};
  rememberAction(action('a'));const running=flushLibraryQueue();await new Promise(resolve=>setImmediate(resolve));rememberAction(action('b'));
  assert.equal(calls,1);finish(ack('a'));await running;
  assert.deepEqual(libraryJournal().map(r=>[r.action.eventId,r.status]),[['a','acked'],['b','pending']]);
  globalThis.fetch=async()=>ack('b');await flushLibraryQueue();assert.equal(libraryJournal()[1].status,'acked');
});
test('lost ACK keeps same durable event ID; retries do not append another local event',async()=>{
  memory.clear();globalThis.fetch=async()=>{throw new Error('offline');};
  rememberAction(action('a'));await flushLibraryQueue();rememberAction(action('a'));await flushLibraryQueue();
  assert.equal(libraryJournal().length,1);assert.equal(libraryJournal()[0].status,'pending');
  globalThis.fetch=async()=>ack('a');await flushLibraryQueue();assert.equal(libraryJournal()[0].status,'acked');
});
test('old server ACK without event ID does not clear queue; validation rejection remains visible',async()=>{
  memory.clear();globalThis.fetch=async()=>new Response(JSON.stringify({ok:true}),{status:200});
  rememberAction(action('a'));await flushLibraryQueue();assert.equal(libraryJournal()[0].status,'pending');
  globalThis.fetch=async()=>new Response(JSON.stringify({ok:false,eventId:'a',error:'invalid'}),{status:400});
  await flushLibraryQueue();assert.equal(libraryJournal()[0].status,'rejected');assert.equal(libraryJournal()[0].error,'invalid');
});
test('legacy queue-only actions migrate without losing pending events',async()=>{
  memory.clear();globalThis.fetch=async()=>{throw new Error('offline');};
  memory.setItem('shotcrypto_model_library_v1',JSON.stringify([action('old')]));
  memory.setItem('shotcrypto_model_library_queue_v1',JSON.stringify([action('old'),action('queue-only')]));
  const rows=libraryJournal();assert.equal(rows.length,2);assert.ok(rows.every(r=>r.status==='pending'));
  assert.equal(libraryJournal().length,2);
});
test('quota failure propagates and cannot masquerade as saved; corrupt journal is not erased',()=>{
  memory.clear();libraryJournal();const set=memory.setItem.bind(memory);memory.setItem=()=>{throw new Error('QuotaExceeded');};
  assert.throws(()=>rememberAction(action('quota')),/QuotaExceeded/);memory.setItem=set;
  memory.setItem('shotcrypto_model_event_v3:broken','not-json');assert.throws(()=>libraryJournal());
  assert.equal(memory.getItem('shotcrypto_model_event_v3:broken'),'not-json');memory.clear();
});
test('corrections preserve originals but contribute once; rejected corrections restore original',()=>{
  const original={action:{...action('a'),fill:fill()},status:'acked' as const};
  const correction={action:{...action('b'),fill:fill('fixed'),replacesEventId:'a'},status:'pending' as const};
  assert.deepEqual(effectiveExecutionRows([original,correction]).map(r=>r.action.eventId),['b']);
  assert.deepEqual(effectiveExecutionRows([original,{...correction,status:'rejected'}]).map(r=>r.action.eventId),['a']);
});
test('no action POST is sent to an old server without idempotency protocol',async()=>{
  memory.clear();supportsProtocol=false;let posts=0;
  globalThis.fetch=async()=>{posts++;return ack('a');};
  rememberAction(action('a'));await flushLibraryQueue();supportsProtocol=true;
  assert.equal(posts,0);assert.equal(libraryJournal()[0].status,'pending');
});
