import assert from 'node:assert/strict';
import test from 'node:test';
import { fetchMarketState, hourlyBollinger, closedHourlyCloses, parseMarketState } from '../src/services/marketState';
import { validateConnection } from '../src/services/serverConnection';
import { readFileSync } from 'node:fs';
const now=Date.now();
const state=()=>({schema:1,ok:true,runtimeHealthy:true,feedHealthy:true,mode:'SHADOW',snapshot:{
  atMs:now,engineVersion:'Crypto-G stage1-dev',ruleVersion:'three-models-v1',status:'WAIT_CONFIRMATION',
  macro:{trend:'BULLISH',ma20:100,rsi:55,reason:'服务端说明'},reasons:['空间不足']}});
test('server state is authoritative and shadow does not imply buying',()=>{
  const m=parseMarketState(state(),now);assert.equal(m.dataReady,true);assert.match(m.regimeNameZh,/不推送新买入/);
  assert.match(m.regimeDescription,/空间不足/);assert.equal(m.volatility,undefined);
});
test('missing, stale, future and unhealthy snapshots cannot become a trend',()=>{
  assert.equal(parseMarketState(null,now).dataReady,false);
  assert.equal(parseMarketState(state(),now+10001).dataReady,false);
  assert.equal(parseMarketState(state(),now-6000).dataReady,false);
  assert.equal(parseMarketState({...state(),feedHealthy:false},now).dataReady,false);
  const s=state();s.snapshot.macro.rsi=NaN;assert.equal(parseMarketState(s,now).dataReady,false);
});
test('TLS URL and per-device credential are mandatory',()=>{
  const token='test_credential_12345678901234567890';
  assert.throws(()=>validateConnection({url:'http://example.test',token}));
  assert.throws(()=>validateConnection({url:'https://user:password@example.test',token}));
  assert.throws(()=>validateConnection({url:'https://example.test/path',token}));
  assert.throws(()=>validateConnection({url:'https://example.test',token:'short'}));
  assert.equal(validateConnection({url:'https://example.test',token}).url,'https://example.test');
});
test('application does not import old strategy or display synthetic adaptive target',()=>{
  const app=readFileSync('src/App.tsx','utf8');const radar=readFileSync('src/components/views/RadarView.tsx','utf8');
  assert.doesNotMatch(app,/QuantEngine|diagnoseMacroTrend/);assert.doesNotMatch(radar,/adaptiveTp|adaptiveSl|83450|锁定利润|稳吃/);
  assert.doesNotMatch(readFileSync('src/services/exportService.ts','utf8'),/import daemonSource/);
});

test('shadow research stays separate and disappears with stale server state',()=>{
 const s:any=state();s.snapshot.research=[{label:'普通超卖恢复',mode:'SHADOW',status:'SHADOW_CANDIDATE',reasons:[]},{label:'bad',mode:'LIVE',status:'SHADOW_CANDIDATE',reasons:[]}];
 const m=parseMarketState(s,now);assert.equal(m.research?.length,1);assert.deepEqual(m.rejectionReasons,['空间不足']);assert.equal(m.allowLongBreakout,false);
 assert.equal(parseMarketState(s,now+10001).research,undefined);
 s.snapshot.research=[{mode:'SHADOW',label:'bad',status:'SHADOW_CANDIDATE',reasons:null}];assert.deepEqual(parseMarketState(s,now).research,[]);
});

test('hourly bands use twenty closes and population deviation', () => {
 const values=Array.from({length:20},(_,i)=>100+i);
 const bands=hourlyBollinger(values)!;
 assert.ok(Math.abs(bands.upper-(109.5+2*Math.sqrt(33.25)))<1e-9);
 assert.ok(Math.abs(bands.lower-(109.5-2*Math.sqrt(33.25)))<1e-9);
 assert.deepEqual(hourlyBollinger(Array(20).fill(100)),{upper:100,lower:100});
 assert.equal(hourlyBollinger(values.slice(1)),undefined);
 assert.equal(hourlyBollinger([...values.slice(1),NaN]),undefined);
});
test('hourly display excludes forming bars and rejects stale or gapped data', () => {
 const end=1800000000000;
 const bars=Array.from({length:21},(_,i)=>[end-(20-i)*3600000,0,0,0,100+i,0,end-(19-i)*3600000-1]);
 assert.equal(closedHourlyCloses(bars,end+500).length,20);
 assert.equal(closedHourlyCloses(bars,end+500).at(-1),119);
 assert.deepEqual(closedHourlyCloses(bars,end+7200000),[]);
 assert.deepEqual(closedHourlyCloses(bars.filter((_,i)=>i!==10),end+500),[]);
});
test('bands come from healthy snapshots and invalid values are hidden',()=>{
 const s:any=state();s.snapshot.macro.bollinger={upper:110,lower:90};
 assert.deepEqual(parseMarketState(s,now).hourlyBollinger,{upper:110,lower:90});
 assert.equal(parseMarketState(s,now+10001).hourlyBollinger,undefined);
 s.snapshot.macro.bollinger.lower=120;assert.equal(parseMarketState(s,now).hourlyBollinger,undefined);
});

test('only validated cloud data can report synchronized trend',()=>{
 assert.equal(parseMarketState(state(),now).stateSource,'SERVER');
 assert.equal(parseMarketState(state(),now+10001).stateSource,'UNAVAILABLE');
});

test('connection failure never promotes local quotes to a cloud trend',async()=>{
 const originalFetch=globalThis.fetch;
 const originalStorage=Object.getOwnPropertyDescriptor(globalThis,'localStorage');
 let calls=0;
 try {
  Object.defineProperty(globalThis,'localStorage',{configurable:true,value:{getItem:()=>null}});
  globalThis.fetch=async()=>{calls++;throw new Error('unexpected fallback');};
  const result=await fetchMarketState();
  assert.equal(result.dataReady,false);assert.equal(result.stateSource,'UNAVAILABLE');
  assert.equal(result.allowLongBreakout,false);assert.equal(calls,0);
 } finally {
  globalThis.fetch=originalFetch;
  if(originalStorage)Object.defineProperty(globalThis,'localStorage',originalStorage);
  else delete (globalThis as any).localStorage;
 }
});
