import assert from 'node:assert/strict';
import test from 'node:test';
import { saveConnection, clearConnection } from '../src/services/serverConnection';
import { fetchAIState, getInitialAIState } from '../src/services/aiEngine';
import { fetchMarketState, getInitialMarketState } from '../src/services/marketState';
import { writeStartupCache } from '../src/services/startupCache';

test('startup merges requests, restores display safely, expires cache and isolates connections', async () => {
  const oldFetch = globalThis.fetch, oldStorage = globalThis.localStorage, oldNow = Date.now;
  const storage = new Map<string, string>();
  Object.defineProperty(globalThis, 'localStorage', {configurable: true, value: {
    getItem: (k: string) => storage.get(k) || null,
    setItem: (k: string, v: string) => storage.set(k, v), removeItem: (k: string) => storage.delete(k),
  }});
  let now = oldNow(); Date.now = () => now;
  try {
    saveConnection({url: 'https://startup.test', token: 'x'.repeat(32)});
    assert.equal(getInitialAIState(), null);
    let resolve!: (v: Response) => void, calls = 0;
    globalThis.fetch = () => { calls++; return new Promise(r => { resolve = r; }); };
    const first = fetchAIState(), second = fetchAIState();
    assert.equal(calls, 1);
    resolve(new Response(JSON.stringify({ok: true, hasApiKey: true, config: {model: 'deepseek-chat', apiKey: 'secret'},
      evalCount: 77, recentEvaluations: [], activeSignals: {buy: {}}, lastEvaluation: {isBuy: true}, lastSignal: {id: 'buy'}})));
    await Promise.all([first, second]);
    assert.equal(getInitialAIState()?.evalCount, 77);
    assert.equal(storage.get('cryptog_startup_ai')?.includes('secret'), false);
    now += 16000;
    const restored = getInitialAIState();
    assert.equal(restored?.config.model, 'deepseek-chat');
    assert.equal(restored?.ok, false);
    assert.equal(restored?.lastSignal, null);
    assert.equal(restored?.lastEvaluation, null);
    assert.deepEqual(restored?.activeSignals, {});
    globalThis.fetch = async () => { throw Error('offline'); };
    assert.equal((await fetchAIState()).evalCount, 77);
    assert.equal((await fetchAIState()).isLocalOnly, true);
    writeStartupCache('market', {dataReady: true, hourlyMa20: 80000, hourlyRsi: 50, allowLongBreakout: true});
    assert.equal(getInitialMarketState().stateSource, 'CACHE');
    assert.equal(getInitialMarketState().dataReady, false);
    assert.equal(getInitialMarketState().allowLongBreakout, false);
    now += 3600001;
    assert.equal(getInitialMarketState().stateSource, 'UNAVAILABLE');
    now += 86400000;
    assert.equal(getInitialAIState(), null);
    saveConnection({url: 'https://startup.test', token: 'y'.repeat(32)});
    assert.equal(getInitialAIState(), null);
    globalThis.fetch = () => { calls++; return new Promise(r => { resolve = r; }); };
    const market1 = fetchMarketState(), market2 = fetchMarketState();
    const before = calls;
    assert.equal(market1, market2);
    clearConnection();
    resolve(new Response('{}'));
    assert.equal((await market1).stateSource, 'UNAVAILABLE');
    assert.equal(calls, before);
  } finally {
    globalThis.fetch = oldFetch; Date.now = oldNow;
    Object.defineProperty(globalThis, 'localStorage', {configurable: true, value: oldStorage});
  }
});
