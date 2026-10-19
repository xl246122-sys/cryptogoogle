import assert from 'node:assert/strict';
import test from 'node:test';
import {parsePositions,reviewNotice} from '../src/services/positions';
const now=1700000000000;
const state=()=>({ok:true,schema:1,runtimeHealthy:true,positionNotifications:'SHADOW_EVENTS_ONLY',snapshot:{atMs:now},positions:[{
  positionId:'p',status:'MONITORING',remainingQuantity:.5,atMs:now,reason:null,
  unresolvedNotices:[{id:'exit-a',kind:'STOP_EXIT',quantity:.5,atMs:now-1000}]}]});
test('positions are independent of entry/feed permission; stale runtime is explicit',()=>{
  assert.equal(parsePositions({...state(),feedHealthy:false},now).fresh,true);
  assert.equal(parsePositions(state(),now+10001).fresh,false);
  assert.equal(parsePositions(state(),now-6000).fresh,false);
  assert.equal(parsePositions({...state(),runtimeHealthy:false},now).positions.length,1);
});
test('unsupported server and malformed inventory/notices cannot look managed',()=>{
  assert.throws(()=>parsePositions({ok:true,schema:1},now));
  const bad=state();bad.positions[0].remainingQuantity=-1;assert.throws(()=>parsePositions(bad,now));
  const badNotice=state();badNotice.positions[0].unresolvedNotices[0].kind='BUY';assert.throws(()=>parsePositions(badNotice,now));
});
test('lost or mismatched review ACK is not shown as success',async()=>{
  const oldFetch=globalThis.fetch;const oldStorage=globalThis.localStorage;
  Object.defineProperty(globalThis,'localStorage',{configurable:true,value:{getItem:()=>JSON.stringify({url:'https://example.test',token:'a'.repeat(32),cacheScope:'position-test'})}});
  try {
    globalThis.fetch=async()=>({ok:true,json:async()=>({ok:true,noticeId:'wrong',kind:'USER_REVIEWED',serverReceivedAtMs:now})}) as Response;
    await assert.rejects(reviewNotice('exit-a'));
    globalThis.fetch=async()=>{throw new Error('lost ACK');};
    await assert.rejects(reviewNotice('exit-a'));
    globalThis.fetch=async()=>({ok:true,json:async()=>({ok:true,noticeId:'exit-a',kind:'USER_REVIEWED',serverReceivedAtMs:now})}) as Response;
    assert.equal(await reviewNotice('exit-a'),now);
  } finally {globalThis.fetch=oldFetch;Object.defineProperty(globalThis,'localStorage',{configurable:true,value:oldStorage});}
});

test('account risk rejects malformed amounts and expires manual balance independently of feed',()=>{
 const accountRisk={source:'MANUAL_UNVERIFIED',fresh:true,coverageComplete:true,updatedMs:now-900001,knownOpenPositions:1,totalPlannedRiskUsdt:2,singleTradeRiskBudgetUsdt:2.5,equityUsdt:500};
 assert.equal(parsePositions({...state(),accountRisk},now).accountRisk?.fresh,false);
 assert.equal(parsePositions({...state(),accountRisk:{...accountRisk,equityUsdt:'500'}},now).accountRisk,undefined);
});
