import assert from 'node:assert/strict';
import test from 'node:test';
import { fetchAIState, updateAIConfig, triggerAIAnalysis } from '../src/services/aiEngine';

test('aiEngine service: fetch, update config, and trigger analysis', async () => {
  const oldFetch = globalThis.fetch;
  const oldStorage = globalThis.localStorage;
  const fakeToken = 'a'.repeat(32);
  Object.defineProperty(globalThis, 'localStorage', {
    configurable: true,
    value: {
      getItem: () => JSON.stringify({ url: 'https://example.test', token: fakeToken }),
    },
  });

  try {
    // 1. Test fetchAIState
    globalThis.fetch = async (url: any) => {
      assert.ok(String(url).includes('/model-library/ai-state'));
      return {
        ok: true,
        json: async () => ({
          ok: true,
          hasApiKey: true,
          config: {
            apiKey: 'AIza****6789',
            provider: 'GEMINI',
            model: 'gemini-3.8-flash',
            intervalSeconds: 300,
            enabled5m: true,
            enabledEventTrigger: true,
            eventCooldownSeconds: 180,
          },
          evalCount: 12,
          buyCount: 2,
          lastEvaluation: null,
          recentEvaluations: [],
          activeSignals: {},
        }),
      } as any;
    };

    const state = await fetchAIState();
    assert.equal(state.ok, true);
    assert.equal(state.hasApiKey, true);
    assert.equal(state.config.model, 'gemini-3.8-flash');
    assert.equal(state.evalCount, 12);

    // 2. Test updateAIConfig
    let capturedBody: any = null;
    globalThis.fetch = async (url: any, opts: any) => {
      assert.ok(String(url).includes('/model-library/ai-config'));
      assert.equal(opts.method, 'POST');
      capturedBody = JSON.parse(opts.body);
      return {
        ok: true,
        json: async () => ({ ok: true, config: capturedBody }),
      } as any;
    };

    const updateRes = await updateAIConfig({
      provider: 'DEEPSEEK',
      model: 'deepseek-chat',
      apiKey: 'sk-test-secret-key-123',
    });
    assert.equal(updateRes.ok, true);
    assert.equal(capturedBody.provider, 'DEEPSEEK');
    assert.equal(capturedBody.model, 'deepseek-chat');

    // 3. Test triggerAIAnalysis
    globalThis.fetch = async (url: any, opts: any) => {
      assert.ok(String(url).includes('/model-library/ai-trigger'));
      assert.equal(opts.method, 'POST');
      return {
        ok: true,
        json: async () => ({
          ok: true,
          triggerReason: 'MANUAL_UI',
          atMs: 1792000000000,
          evaluation: {
            id: 'eval_test_1',
            atMs: 1792000000000,
            triggerReason: 'MANUAL_UI',
            model: 'deepseek-chat',
            provider: 'DEEPSEEK',
            isBuy: false,
            confidence: 60,
            scenario: 'NONE',
            scenarioNameZh: '观望无机会',
            summaryZh: '大盘震荡无明确突破',
          },
          signalPushed: false,
        }),
      } as any;
    };

    const triggerRes = await triggerAIAnalysis();
    assert.equal(triggerRes.ok, true);
    assert.equal(triggerRes.evaluation?.isBuy, false);
    assert.equal(triggerRes.signalPushed, false);
  } finally {
    globalThis.fetch = oldFetch;
    Object.defineProperty(globalThis, 'localStorage', { configurable: true, value: oldStorage });
  }
});
