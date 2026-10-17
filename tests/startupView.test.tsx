import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import assert from 'node:assert/strict';
import test from 'node:test';
import { PlanFacts, GuardLabDrawer } from '../src/components/HorizonPanels';
import { SystemGuardView } from '../src/components/views/SystemGuardView';
import { RadarView } from '../src/components/views/RadarView';
import { environmentBias } from '../src/components/TrendStrengthIndicator';
import type { MacroTrendAnalysis } from '../src/types/crypto';
import { AIQuantView, apiSwitchLabel } from '../src/components/views/AIQuantView';
import type { TradeSignal } from '../src/types/crypto';
import { saveConnection } from '../src/services/serverConnection';
import { writeStartupCache } from '../src/services/startupCache';

test('PlanFacts still renders when the strategy name is missing', () => {
  const signal = { tierLabel: '观察级·未验证', entryMin: 100, entryMax: 100.2, stopLoss: 99.5, targetTP1: 101, targetTP2: 102, timeHorizon: '6 小时' } as unknown as TradeSignal;
  const html = renderToStaticMarkup(<PlanFacts signal={signal} />);
  assert.ok(html.includes('进场区'));
  assert.ok(!html.includes('试运行'));
});

test('AI first paint never mistakes loading for an unconfigured key or active monitoring', () => {
  const old = globalThis.localStorage, data = new Map<string,string>();
  Object.defineProperty(globalThis, 'localStorage', {configurable:true, value:{
    getItem:(k:string)=>data.get(k)||null, setItem:(k:string,v:string)=>data.set(k,v),
  }});
  try {
    saveConnection({url:'https://ui.test',token:'z'.repeat(32)});
    let html = renderToStaticMarkup(<AIQuantView/>);
    assert.ok(html.includes('正在连接云端 AI'));
    assert.ok(!html.includes('立即配置 API 密钥'));
    assert.ok(!html.includes('监控已开'));
    assert.ok(!html.includes('监控暂停'));
    assert.ok(!html.includes('Gemini 2.5 Flash'));
    writeStartupCache('ai', {config:{model:'deepseek-chat'},hasApiKey:true,evalCount:77,recentEvaluations:[]});
    html = renderToStaticMarkup(<AIQuantView/>);
    assert.ok(html.includes('已恢复上次记录'));
    assert.ok(html.includes('DeepSeek-V3'));
    assert.ok(html.includes('77'));
    assert.ok(!html.includes('立即配置 API 密钥'));
    assert.ok(!html.includes('监控已开'));
    assert.ok(!html.includes('监控暂停'));
  } finally { Object.defineProperty(globalThis,'localStorage',{configurable:true,value:old}); }
});

test('radar keeps only the 1D 4H 1H bearish flags inside the trend card', () => {
  assert.equal(environmentBias('空头'), '空头');
  assert.equal(environmentBias('空头反弹'), '空头');
  assert.equal(environmentBias('多头回调'), '非空头');
  assert.equal(environmentBias('多头'), '非空头');
  assert.equal(environmentBias(undefined), '—');
  const market = {
    dataReady: true, stateSource: 'SERVER', hourlyTrend: 'RANGING', hourlyRsi: 50.98, hourlyMa20: 81575.49,
    hourlyMa50: 0, trendDriftPercent: 0, allowLongBreakout: false, regime: 'MEAN_REVERTING_RANGE',
    regimeNameZh: '验收', regimeDescription: '验收', biasZh: '验收',
    layers: { d1: '多头回调', h4: '空头', h1: '空头反弹', label: '验收', score: -32 },
    levels: [{ name: '日线 EMA99', price: 76972.28 }],
  } as MacroTrendAnalysis;
  const html = renderToStaticMarkup(<RadarView tickers={{}} latestSignals={[]} scanIntervalSec={2} macroTrend={market} onSelectSignal={() => {}} onSwitchTab={() => {}} onTriggerTestSignal={() => {}} />);
  assert.ok(html.includes('1D'));
  assert.ok(html.includes('4H'));
  assert.ok(html.includes('1H'));
  assert.ok(html.includes('非空头'));
  assert.ok(html.includes('空头'));
  assert.ok(!html.includes('日线 EMA99'));
  assert.ok(!html.includes('观察级候选'));
  assert.ok(!html.includes('>三层环境<'));
});

test('the system guard drawer stays closed and leaves the guardian card in view', () => {
  const market = {
    dataReady: true, stateSource: 'SERVER', hourlyTrend: 'RANGING', hourlyRsi: 46, hourlyMa20: 81560,
    hourlyMa50: 0, trendDriftPercent: 0, allowLongBreakout: false, regime: 'MEAN_REVERTING_RANGE',
    regimeNameZh: '震荡背景 · 基线监控', regimeDescription: '验收', biasZh: 'Crypto-G V1.47 / short-horizon-v2',
    breaker: { state: '未熔断' }, freshness: { context: '1D/4H/1H 新鲜', derivatives: '衍生品新鲜' },
  } as MacroTrendAnalysis;
  const drawer = renderToStaticMarkup(<GuardLabDrawer market={market} />);
  assert.ok(drawer.includes('<details'));
  assert.ok(!drawer.includes('<details open'));
  assert.ok(drawer.includes('版本与策略实验室'));
  assert.ok(drawer.includes('未熔断'));
  assert.ok(drawer.includes('1D/4H/1H 新鲜'));
  assert.ok(drawer.includes('策略实验室'));
  const page = renderToStaticMarkup(<SystemGuardView config={{ soundEnabled: true, soundVolume: 0.5, autoPopupEnabled: false, activeStrategies: { BURST_BREAKOUT: true, FLASH_CRASH_REBOUND: true, RANGE_OSCILLATION: true } } as never} macroTrend={market} onUpdateConfig={() => {}} onRequestNotificationPermission={() => {}} hasNotificationPermission={true} />);
  assert.ok(page.indexOf('版本与策略实验室') < page.indexOf('系统与量化守护'));
  assert.ok(page.includes('24/7 守护中'));
});

test('the AI brain switch names the model API and leaves system monitoring on', () => {
  assert.equal(apiSwitchLabel(false, false, 'DEEPSEEK'), '状态同步中');
  assert.equal(apiSwitchLabel(true, false, 'DEEPSEEK'), 'DeepSeek 已关');
  assert.equal(apiSwitchLabel(true, true, 'DEEPSEEK'), 'DeepSeek 已开');
  assert.equal(apiSwitchLabel(true, false, 'GEMINI'), 'Gemini 已关');
});
