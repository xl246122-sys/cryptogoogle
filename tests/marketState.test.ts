import assert from 'node:assert/strict';
import test from 'node:test';
import { parseMarketState } from '../src/services/marketState';
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
