import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { SignalAlertModal } from '../src/components/SignalAlertModal';
import { entryIssue, fetchEntryQuote, parseCloudSignal, signalTimeIssue, aiEntryAllowed } from '../src/services/signalValidity';
import { QuantEngine } from './legacy/quantEngine.v112';
import { positionRuleNotice } from '../src/services/positionRules';

const wire = JSON.parse(readFileSync(new URL('./signal_payload.fixture.json', import.meta.url), 'utf8'));
test('AI card rejects expired, stale, non-BTC and nonfinite opportunities',()=>{
  const now=1000000,q={price:100,timestamp:now};
  const data={symbol:'BTCUSDT',signalType:'BUY',scenario:'FLASH_REBOUND_FAST',entryMin:99.9,entryMax:100.05,targetTP1:100.7,stopLoss:99.7,atMs:now,expiresAt:now+10000,cardText:'six fields'};
  assert.ok(aiEntryAllowed(data,q,now));
  for(const edit of [{symbol:'SUIUSDT'},{expiresAt:now},{targetTP1:Infinity},{targetTP1:100.69},{expiresAt:now+10001}]) assert.equal(aiEntryAllowed({...data,...edit},q,now),false);
  assert.equal(aiEntryAllowed(data,{...q,timestamp:now-2001},now),false);
});
function sample() {
  const now = Date.now();
  const parsed = parseCloudSignal({ ...wire, timestamp: String(now), confirmationTime: String(now-1000), expiresAt: String(now+90000) });
  assert.ok(parsed);
  return parsed;
}
test('real Python output parses without inventing analysis', () => {
  const signal = sample();
  assert.equal(signal.analysis.rsi14, Number(wire.rsi14));
  assert.equal(signal.analysis.momentumZScore, undefined);
  assert.equal(signal.analysis.bidAskSpreadPct, undefined);
  assert.equal(entryIssue(signal, { price: signal.entryPrice, timestamp: Date.now() }), null);
});
test('legacy, missing timestamp, NaN, bad bounds and unrecognised strategy fail closed', () => {
  for (const patch of [{ timestamp: undefined }, { expiresAt: undefined }, { entryPrice: 'NaN' },
    { entryMin: 'Infinity' }, { entryMax: '1' }, { breakoutLevel: undefined }, { strategy: 'FAKE' }]) {
    assert.equal(parseCloudSignal({ ...wire, ...patch }), null);
  }
});
test('zero analysis values remain zero; missing values remain absent', () => {
  const signal = parseCloudSignal({ ...wire, rsi14: '0', quantilePct: '0', volumeMultiplier: undefined, netRiskReward: undefined });
  assert.ok(signal);
  assert.equal(signal.analysis.rsi14, 0);
  assert.equal(signal.analysis.quantilePct, 0);
  assert.equal(signal.analysis.volumeMultiplier, undefined);
  assert.equal(signal.analysis.netRiskReward, undefined);
});
test('expiry boundary, future creation and overly long validity are rejected', () => {
  const s = sample();
  assert.ok(signalTimeIssue(s, s.expiresAt));
  assert.ok(signalTimeIssue({ ...s, timestamp: Date.now()+6000 }));
  assert.ok(signalTimeIssue({ ...s, expiresAt: s.timestamp + 91000 }));
  assert.ok(signalTimeIssue({ ...s, confirmationTime: s.timestamp-120001 }));
});
test('stale/missing/wrong-side quotes and prices outside interval cannot enter', () => {
  const s = sample();
  const q = { price: s.entryPrice, timestamp: Date.now() };
  assert.ok(entryIssue(s, null));
  assert.ok(entryIssue(s, { ...q, timestamp: q.timestamp-11000 }));
  assert.ok(entryIssue(s, { ...q, price: Number.NaN }));
  assert.ok(entryIssue(s, { ...q, price: s.breakoutLevel! }));
  assert.ok(entryIssue(s, { ...q, price: s.entryMax! + 0.01 }));
  assert.ok(entryIssue(s, { ...q, price: s.entryMin! - 0.01 }));
  assert.ok(entryIssue({ ...s, targetTP1: s.entryPrice * 1.0045 }, q));
});
test('expired modal disables simulated entry and labels missing analysis honestly', () => {
  const now = Date.now();
  const s = { ...sample(), timestamp: now-100000, confirmationTime: now-101000, expiresAt: now-10000, analysis: { quantilePct: 0 } };
  const html = renderToStaticMarkup(React.createElement(SignalAlertModal, { signal: s, onClose() {}, onAddToPosition() {} }));
  assert.match(html, /信号已过期/);
  assert.match(html, /disabled=""/);
  assert.match(html, /未提供/);
  assert.match(html, /0%/);
  assert.doesNotMatch(html, /TP1 预期净利|Q=50/);
});
test('quote fetch uses fresh Binance Global ask and rejects fallback stale data', async () => {
  const original = globalThis.fetch;
  const urls: string[] = [];
  try {
    globalThis.fetch = (async (input: any) => {
      urls.push(String(input));
      return new Response(JSON.stringify({ symbol: 'BTCUSDT', askPrice: '100.65', closeTime: Date.now() }));
    }) as typeof fetch;
    assert.equal((await fetchEntryQuote())?.price, 100.65);
    assert.ok(urls.every(u => !u.includes('binance.us')));
    globalThis.fetch = (async () => new Response(JSON.stringify({ symbol: 'BTCUSDT', askPrice: '100.65', closeTime: Date.now()-11000 }))) as typeof fetch;
    assert.equal(await fetchEntryQuote(), null);
    globalThis.fetch = (async () => { throw new Error('offline'); }) as typeof fetch;
    assert.equal(await fetchEntryQuote(), null);
  } finally { globalThis.fetch = original; }
});
test('missing hourly data produces unavailable macro, never fabricated RSI or MA', () => {
  const macro = QuantEngine.diagnoseMacroTrend([], { symbol: 'BTCUSDT', name: 'Bitcoin', price: 100, change24h: -3, high24h: 104, low24h: 99, volume24h: 10, quoteVolume24h: 1000, lastUpdate: Date.now() });
  assert.equal(macro.dataReady, false);
  assert.equal(macro.regime, 'UNKNOWN');
  assert.equal(macro.hourlyMa20, 0);
});

test('independent rules are required and cannot weaken the rebound floor', () => {
  assert.equal(parseCloudSignal({ ...wire, tradeRules: undefined }), null);
  const rules = JSON.parse(wire.tradeRules);
  assert.equal(parseCloudSignal({ ...wire, tradeRules: JSON.stringify({ ...rules, maxHoldMinutes: 720 }) }), null);
  assert.equal(parseCloudSignal({ ...wire, tradeRules: JSON.stringify({ ...rules, tp1Fraction: 0.2 }) }), null);
  const s = sample();
  s.tradeRules = { ...s.tradeRules!, model: 'REBOUND', maxHoldMinutes: 90, minNetTp1: 1, maxNetTarget: 6, tp1Fraction: .7 };
  s.targetTP1 = s.entryPrice * 1.008;
  assert.ok(entryIssue(s, { price: s.entryPrice, timestamp: Date.now() }));
});
test('expiry of a held position is independent of entry signal TTL and requires no price', () => {
  const s = sample(), now = Date.now();
  const item = { symbol: 'BTCUSDT', name: 'Bitcoin', addedAt: now-1000, positionEntryPrice: s.entryPrice,
    linkedTradeRules: s.tradeRules, positionDeadlineMs: now+1000, linkedSl: s.stopLoss, linkedTp1: s.targetTP1, linkedTp2: s.targetTP2 };
  assert.match(positionRuleNotice(item, null, now+1000)!, /最长持有时间/);
  assert.match(positionRuleNotice(item, null, now)!, /等待新鲜行情/);
  assert.match(positionRuleNotice(item, s.stopLoss, now)!, /结构止损/);
  assert.match(positionRuleNotice(item, s.tradeRules!.invalidationPrice, now)!, /失效位/);
  assert.match(positionRuleNotice(item, s.targetTP1, now)!, /50%/);
  assert.equal(item.positionEntryPrice, s.entryPrice); // Notices never auto-close positions.
});
test('short-horizon-v2 keeps the 0.50% net floor, 30 minute window and 0.24% friction', () => {
  const now = Date.now();
  const rules = { model: 'RANGE', ruleVersion: 'short-horizon-v2', maxHoldMinutes: 360, minNetTp1: 0.5,
    minNetRr: 1, frictionPct: 0.24, maxNetTarget: null, invalidationPrice: 100.2, tp1Fraction: 0.5,
    targetBasis: 'TP1', exitRule: 'TP1 卖 50%' };
  const data = { ...wire, strategy: 'RANGE_OSCILLATION', id: 'BTCUSDT_S2_1', breakoutLevel: undefined,
    entryPrice: '100.5', entryMin: '100.4', entryMax: '100.6', stopLoss: '100', targetTP1: '102', targetTP2: '103',
    timestamp: String(now), confirmationTime: String(now - 1000), expiresAt: String(now + 20 * 60 * 1000),
    estimatedFriction: '0.24', tradeRules: JSON.stringify(rules) };
  const signal = parseCloudSignal(data);
  assert.ok(signal);
  assert.equal(signal.tradeRules?.ruleVersion, 'short-horizon-v2');
  assert.equal(signalTimeIssue(signal, now), null);
  assert.equal(entryIssue(signal, { price: 100.5, timestamp: now }, now), null);
  assert.equal(parseCloudSignal({ ...data, tradeRules: JSON.stringify({ ...rules, minNetTp1: 0.4 }) }), null);
  assert.ok(signalTimeIssue({ ...signal, expiresAt: signal.confirmationTime! + 31 * 60 * 1000 }, now));
});
test('modal renders the actual model exit fraction and holding limit', () => {
  const s=sample();
  const html=renderToStaticMarkup(React.createElement(SignalAlertModal,{signal:s,onClose(){},onAddToPosition(){}}));
  assert.match(html,/最长持有 240 分钟/);
  assert.match(html,/初始仓位 50%/);
  assert.match(html,/止损不自动上移/);
});
