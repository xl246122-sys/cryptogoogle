import assert from 'node:assert/strict';
import test from 'node:test';
import { fetchMarketState, hourlyBollinger, closedHourlyCloses, parseMarketState } from '../src/services/marketState';
import { validateConnection } from '../src/services/serverConnection';
import { readFileSync } from 'node:fs';
const now=Date.now();
const state=()=>({schema:1,ok:true,runtimeHealthy:true,feedHealthy:true,mode:'SHADOW',snapshot:{
  atMs:now,engineVersion:'Crypto-G stage1-dev',ruleVersion:'three-models-v1',status:'WAIT_CONFIRMATION',
  macro:{trend:'BULLISH',ma20:100,rsi:55,reason:'服务端说明'},reasons:['空间不足']}});
test('the trend card prefers the live hour and the live environment', () => {
  const s: any = state();
  s.snapshot.macro.liveRsi = 46.2;
  s.snapshot.macro.liveMa20 = 81560.25;
  s.snapshot.shortHorizonV2 = {
    env: { states: { d1: 'ABOVE_99', h4: 'DOWN', h1: 'DOWN' }, score: -32, label: 'closed' },
    displayEnv: { states: { d1: 'ABOVE_99', h4: 'DOWN', h1: 'UP' }, score: 8, label: 'live' },
  };
  const m = parseMarketState(s, now);
  assert.equal(m.hourlyRsi, 46.2);
  assert.equal(m.hourlyMa20, 81560.25);
  assert.equal(m.layers?.h1, '多头');
  assert.equal(m.layers?.h4, '空头');
});
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

test('v2 snapshot carries environment, watch countdown and the release lab', () => {
  const s: any = state();
  s.snapshot.ruleVersion = 'short-horizon-v2';
  s.snapshot.engineVersion = 'Crypto-G V1.47';
  s.snapshot.shortHorizonV2 = {
    env: {states: {d1: 'UP', h4: 'DOWN', h1: 'ABOVE_99'}, score: 12, label: '1D 多头 · 4H 空头 · 1H 多头回调（评分 +12）'},
    levels: [{name: '日线 EMA99', price: 100}, {name: '坏价', price: 0}],
    candidates: [{module: 'S2', name: '支撑回踩', issue: '盈亏比不足'}],
  };
  s.snapshot.signal = {rule_version: 'short-horizon-v2', module: 'S1', strategy_name_zh: '急跌收回', tier_label: '观察级·未验证', expires_at: now + 60000};
  s.evolution = {promotions: 0, modules: [{module: 'S1', stage: 'RESEARCH', label: '研究', push: true, tierLabel: '观察级·未验证', records: 0}],
    l1: {status: 'INSUFFICIENT', applied: true, samples: 3}, hypotheses: [{module: 'S1', claim: '量能过滤', status: 'PENDING_P4', applied: true}]};
  s.context = {healthy: true};
  s.derivatives = {healthy: false};
  s.shortHorizonV2 = {breaker: {pausedUntil: 0, consecutiveStops: 0, dayR: 0, reason: null}};
  const m = parseMarketState(s, now);
  assert.equal(m.layers?.d1, '多头');
  assert.equal(m.layers?.h4, '空头');
  assert.equal(m.levels?.length, 1);
  assert.equal(m.watchCandidates?.[0].expiresAt, now + 60000);
  assert.equal(m.watchCandidates?.[1].issue, '盈亏比不足');
  assert.equal(m.lab?.source, 'SERVER');
  assert.equal(m.lab?.l1.applied, false);
  assert.equal(m.lab?.hypotheses[0].applied, false);
  s.continuity = {
    cost: {month: '2026-09', frictionPct: 0.31, floorPct: 0.24, measuredPct: 0.31, source: 'FILLS', applied: true},
    environment: {quarter: '2026-Q3', cutoff: 10, priorCutoff: 0, status: 'HELD', applied: true},
  };
  const withJobs = parseMarketState(s, now);
  assert.equal(withJobs.lab?.continuity?.cost?.applied, false);
  assert.equal(withJobs.lab?.continuity?.cost?.frictionPct, 0.31);
  assert.equal(withJobs.lab?.continuity?.environment?.applied, false);
  assert.equal(withJobs.lab?.continuity?.environment?.cutoff, 10);
  assert.equal(m.freshness?.context, '1D/4H/1H 新鲜');
  assert.equal(m.breaker?.state, '未熔断');
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
