import type { MacroTrendAnalysis, ReleaseLab } from '../types/crypto';
import { connection } from './serverConnection';
import { readStartupCache, writeStartupCache } from './startupCache';

export function getInitialMarketState(): MacroTrendAnalysis {
  const cached = readStartupCache<MacroTrendAnalysis>('market', 3600000);
  if (!cached?.value.dataReady || !Number.isFinite(cached.value.hourlyMa20)) return unknownMarket('正在连接云端');
  return {...cached.value, stateSource: 'CACHE', dataReady: false, allowLongBreakout: false,
    regimeNameZh: '上次趋势 · 正在同步',
    regimeDescription: `上次更新 ${new Date(cached.at).toLocaleTimeString()}，仅供回看，等待实时校验`,
    rejectionReasons: [], research: []};
}
let pendingMarket: Promise<MacroTrendAnalysis> | null = null;
let pendingIdentity = '';

export function unknownMarket(reason = '服务器不可用、未配置或行情过期，暂停解释买入机会'): MacroTrendAnalysis {
  return {
    stateSource: 'UNAVAILABLE',
    hourlyTrend: 'RANGING',
    hourlyMa20: 0,
    hourlyMa50: 0,
    hourlyRsi: 0,
    trendDriftPercent: 0,
    allowLongBreakout: false,
    regime: 'UNKNOWN',
    dataReady: false,
    regimeNameZh: '服务端状态未知',
    regimeDescription: reason,
    biasZh: '请勿根据本地价格推断服务端正在正常扫描',
  };
}

export function parseMarketState(value: any, now = Date.now()): MacroTrendAnalysis {
  const s = value?.snapshot,
    m = s?.macro;
  if (
    value?.schema !== 1 ||
    value?.ok !== true ||
    value.runtimeHealthy !== true ||
    value.feedHealthy !== true ||
    !s ||
    !Number.isFinite(s.atMs) ||
    now - s.atMs > 10000 ||
    s.atMs - now > 5000 ||
    !['three-models-v1','three-models-v2','short-horizon-v2'].includes(s.ruleVersion) ||
    typeof s.engineVersion !== 'string'
  )
    return unknownMarket();
  if (s.status === 'BLOCK_ENTRY' || !m)
    return unknownMarket(`行情校验未通过：${Array.isArray(s.reasons) ? s.reasons.join('；') : '数据不足'}`);
  if (
    !['BULLISH', 'BEARISH', 'RANGING'].includes(m.trend) ||
    !Number.isFinite(m.ma20) ||
    m.ma20 <= 0 ||
    !Number.isFinite(m.rsi) ||
    m.rsi < 0 ||
    m.rsi > 100
  )
    return unknownMarket('服务端状态字段不完整');
  const title = { BULLISH: '多头背景', BEARISH: '空头背景', RANGING: '震荡背景' }[
    m.trend as 'BULLISH' | 'BEARISH' | 'RANGING'
  ];
  const reasons = Array.isArray(s.reasons) ? s.reasons.filter((r: unknown) => typeof r === 'string').join('；') : '';
  const shadow = value.mode === 'SHADOW';
  return {
    stateSource: 'SERVER',
    costSnapshot: s.costSnapshot && Number.isFinite(s.costSnapshot.frictionPct) && s.costSnapshot.frictionPct >= .24 ? s.costSnapshot : undefined,
    hourlyTrend: m.trend,
    isStronglyBearish: m.is_strongly_bearish === true,
    hourlyMa20: Number.isFinite(m.liveMa20) && m.liveMa20 > 0 ? m.liveMa20 : m.ma20,
    hourlyBollinger: validBands(m.bollinger),
    rejectionReasons: s.signal
      ? []
      : Array.isArray(s.reasons)
      ? s.reasons.filter((x: unknown) => typeof x === 'string')
      : [],
    research: Array.isArray(s.research)
      ? s.research
          .filter(
            (x: any) =>
              x?.mode === 'SHADOW' &&
              typeof x.label === 'string' &&
              ['REJECTED', 'SHADOW_CANDIDATE', 'ERROR'].includes(x.status) &&
              Array.isArray(x.reasons)
          )
          .map((x: any) => ({
            label: x.label,
            status: x.status,
            reasons: x.reasons.filter((r: unknown) => typeof r === 'string'),
          }))
      : undefined,
    hourlyMa50: 0,
    hourlyRsi: Number.isFinite(m.liveRsi) && m.liveRsi >= 0 && m.liveRsi <= 100 ? m.liveRsi : m.rsi,
    trendDriftPercent: 0,
    allowLongBreakout: false,
    regime: m.trend === 'BULLISH' ? 'TRENDING_BULL' : m.trend === 'BEARISH' ? 'TRENDING_BEAR' : 'MEAN_REVERTING_RANGE',
    dataReady: true,
    regimeNameZh: `${title} · ${shadow ? '研究观察，不推送新买入' : '基线监控'}`,
    regimeDescription: `${typeof m.reason === 'string' ? m.reason : ''} ${
      reasons || (shadow ? '观察到候选，仍需验证' : '候选需打开复核')
    }`,
    biasZh: `${s.engineVersion} / ${s.ruleVersion} · ${new Date(s.atMs).toLocaleTimeString()} · 收盘结构；目标以具体信号为准`,
    layers: readLayers(s.shortHorizonV2),
    decisionContext: readDecisionContext(value.decisionContext, s.atMs),
    levels: readLevels(s.shortHorizonV2),
    watchCandidates: readWatch(s),
    lab: readLab(value.evolution, value.continuity),
    freshness: readFreshness(value),
    breaker: readBreaker(value.shortHorizonV2, now),
  };
}

const LAYER_NAMES: Record<string, string> = { UP: '多头', ABOVE_99: '多头回调', BELOW_99: '空头反弹', DOWN: '空头' };

export function readDecisionContext(raw:any, snapshotAt:number):MacroTrendAnalysis['decisionContext'] {
  if(!raw || raw.atMs!==snapshotAt || !['d1','h4','h1'].every(tf=>
    Number.isFinite(raw.frames?.[tf]?.closeTime) && raw.frames[tf].closeTime>0 && raw.frames[tf].closeTime<snapshotAt && LAYER_NAMES[raw.frames[tf].state]) ||
    !['S1','S2','S3','S4'].every(m=>typeof raw.gates?.[m]==='boolean'))return undefined;
  return {atMs:raw.atMs,frames:Object.fromEntries(['d1','h4','h1'].map(tf=>[tf,{closeTime:raw.frames[tf].closeTime,state:LAYER_NAMES[raw.frames[tf].state]}])),
    gates:raw.gates,reasons:Array.isArray(raw.reasons)?raw.reasons.filter((s:unknown)=>typeof s==='string'):[]};
}

function readLayers(view: any): MacroTrendAnalysis['layers'] {
  const env = view?.displayEnv?.states ? view.displayEnv : view?.env;
  const states = env?.states;
  if (!states || !['d1', 'h4', 'h1'].every((key) => typeof LAYER_NAMES[states[key]] === 'string')) return undefined;
  if (typeof env.label !== 'string' || !Number.isFinite(env.score)) return undefined;
  return { d1: LAYER_NAMES[states.d1], h4: LAYER_NAMES[states.h4], h1: LAYER_NAMES[states.h1], label: env.label, score: env.score };
}

function readLevels(view: any): MacroTrendAnalysis['levels'] {
  if (!Array.isArray(view?.levels)) return undefined;
  const rows = view.levels.filter((row: any) => typeof row?.name === 'string' && Number.isFinite(row.price) && row.price > 0)
    .map((row: any) => ({ name: row.name, price: row.price }));
  return rows.length ? rows : undefined;
}

function readWatch(snapshot: any): MacroTrendAnalysis['watchCandidates'] {
  const rows: NonNullable<MacroTrendAnalysis['watchCandidates']> = [];
  const signal = snapshot?.signal;
  if (signal?.rule_version === 'short-horizon-v2' && typeof signal.module === 'string') {
    const expires = Number(signal.expires_at);
    rows.push({
      module: signal.module,
      name: typeof signal.strategy_name_zh === 'string' ? signal.strategy_name_zh : signal.module,
      expiresAt: Number.isFinite(expires) && expires > 0 ? expires : undefined,
      tierLabel: typeof signal.tier_label === 'string' ? signal.tier_label : '观察级·未验证',
    });
  }
  if (Array.isArray(snapshot?.shortHorizonV2?.candidates)) {
    for (const item of snapshot.shortHorizonV2.candidates) {
      if (typeof item?.module !== 'string') continue;
      rows.push({
        module: item.module,
        name: typeof item.name === 'string' ? item.name : item.module,
        issue: typeof item.issue === 'string' ? item.issue : undefined,
      });
    }
  }
  return rows.length ? rows : undefined;
}

function readContinuity(raw: any): ReleaseLab['continuity'] {
  if (!raw || typeof raw !== 'object') return null;
  const cost = raw.cost;
  const env = raw.environment;
  const job: NonNullable<ReleaseLab['continuity']> = {};
  if (cost && typeof cost === 'object') {
    job.cost = {
      month: typeof cost.month === 'string' ? cost.month : undefined,
      frictionPct: finite(cost.frictionPct), floorPct: finite(cost.floorPct),
      measuredPct: finite(cost.measuredPct) ?? null, source: typeof cost.source === 'string' ? cost.source : undefined,
      applied: false,
    };
  }
  if (env && typeof env === 'object') {
    job.environment = {
      quarter: typeof env.quarter === 'string' ? env.quarter : undefined,
      status: typeof env.status === 'string' ? env.status : undefined,
      cutoff: finite(env.cutoff) ?? null, priorCutoff: finite(env.priorCutoff) ?? 0,
      samples: finite(env.samples), applied: false,
    };
  }
  if (typeof raw.environmentOpen === 'string') job.environmentOpen = raw.environmentOpen;
  return job.cost || job.environment || job.environmentOpen ? job : null;
}

function readLab(raw: any, continuity?: any): ReleaseLab | undefined {
  if (!raw || !Array.isArray(raw.modules)) return undefined;
  const modules = raw.modules.filter((row: any) => typeof row?.module === 'string' && typeof row.label === 'string' && typeof row.tierLabel === 'string')
    .map((row: any) => ({
      module: row.module, stage: typeof row.stage === 'string' ? row.stage : 'RESEARCH', label: row.label,
      push: row.push === true, tierLabel: row.tierLabel, records: Number.isFinite(row.records) ? row.records : 0,
      remainingMs: Number.isFinite(row.remainingMs) ? row.remainingMs : null,
      gaps: Array.isArray(row.gaps) ? row.gaps.filter((gap: unknown) => typeof gap === 'string') : [],
    }));
  if (!modules.length) return undefined;
  const l1 = raw.l1 || {};
  const hypotheses = Array.isArray(raw.hypotheses) ? raw.hypotheses.filter((item: any) => item && typeof item === 'object').slice(0, 6).map((item: any) => ({
    module: typeof item.module === 'string' ? item.module : undefined,
    feature: typeof item.feature === 'string' ? item.feature : undefined,
    claim: typeof item.claim === 'string' ? item.claim : undefined,
    status: typeof item.status === 'string' ? item.status : undefined,
    applied: false,
  })) : [];
  return {
    source: 'SERVER', modules, promotions: Number.isFinite(raw.promotions) ? raw.promotions : 0,
    l1: { status: typeof l1.status === 'string' ? l1.status : 'INSUFFICIENT', applied: false,
      samples: Number.isFinite(l1.samples) ? l1.samples : null, minSamples: Number.isFinite(l1.minSamples) ? l1.minSamples : 200,
      proposal: l1.proposal && typeof l1.proposal === 'object' ? {
        pThreshold: finite(l1.proposal.pThreshold), entryOffsetPct: finite(l1.proposal.entryOffsetPct), stopBufferPct: finite(l1.proposal.stopBufferPct),
      } : undefined },
    daily: raw.daily && typeof raw.daily.summary === 'string' ? { day: raw.daily.day, summary: raw.daily.summary } : null,
    hypotheses,     veto: raw.veto && typeof raw.veto === 'object' ? {
      vetoEnabled: typeof raw.veto.vetoEnabled === 'boolean' ? raw.veto.vetoEnabled : undefined,
      vetoed: finite(raw.veto.vetoed), passed: finite(raw.veto.passed),
      vetoedMeanR: finite(raw.veto.vetoedMeanR) ?? null, passedMeanR: finite(raw.veto.passedMeanR) ?? null,
    } : null,
    continuity: readContinuity(continuity),
    gates: raw.gates && typeof raw.gates === 'object' ? {
      minTrades: finite(raw.gates.minTrades), minExpectancyPct: finite(raw.gates.minExpectancyPct),
      minWinRate: finite(raw.gates.minWinRate), minProfitFactor: finite(raw.gates.minProfitFactor),
    } : undefined,
  };
}

function finite(value: unknown): number | undefined {
  return typeof value === 'number' && Number.isFinite(value) ? value : undefined;
}

function readFreshness(value: any): MacroTrendAnalysis['freshness'] {
  if (!value?.context && !value?.derivatives) return undefined;
  return {
    context: value.context?.healthy === true ? '1D/4H/1H 新鲜' : '1D/4H/1H 未见新鲜标记',
    derivatives: value.derivatives?.healthy === true ? '衍生品新鲜' : '衍生品未见新鲜标记',
  };
}

function readBreaker(tracker: any, now: number): MacroTrendAnalysis['breaker'] {
  const breaker = tracker?.breaker;
  if (!breaker || typeof breaker !== 'object') return undefined;
  const pausedUntil = Number(breaker.pausedUntil);
  if (Number.isFinite(pausedUntil) && pausedUntil > now) {
    return { state: '暂停交易级', reason: typeof breaker.reason === 'string' ? breaker.reason : undefined, pausedUntil };
  }
  return {
    state: '未熔断',
    consecutiveStops: Number.isFinite(breaker.consecutiveStops) ? breaker.consecutiveStops : undefined,
    dayR: Number.isFinite(breaker.dayR) ? breaker.dayR : undefined,
  };
}

function validBands(bands: any): MacroTrendAnalysis['hourlyBollinger'] {
  return Number.isFinite(bands?.upper) && Number.isFinite(bands?.lower) &&
    bands.lower > 0 && bands.upper >= bands.lower ? { upper: bands.upper, lower: bands.lower } : undefined;
}

export function closedHourlyCloses(klines: any[], now = Date.now()): number[] {
  if (!Array.isArray(klines)) return [];
  const closed = klines.filter(k => Array.isArray(k) && Number.isFinite(k[6]) && k[6] < now).slice(-20);
  if (closed.length !== 20 || now - closed[19][6] > 3600000 ||
      closed.some((k, i) => !Number.isFinite(Number(k[4])) || Number(k[4]) <= 0 ||
        !Number.isFinite(k[0]) || k[6] - k[0] !== 3599999 ||
        (i > 0 && k[0] - closed[i - 1][0] !== 3600000))) return [];
  return closed.map(k => Number(k[4]));
}

export function hourlyBollinger(closes: number[]): MacroTrendAnalysis['hourlyBollinger'] {
  const window = closes.slice(-20);
  if (window.length !== 20 || window.some(x => !Number.isFinite(x) || x <= 0)) return undefined;
  const middle = window.reduce((sum, x) => sum + x, 0) / 20;
  const deviation = Math.sqrt(window.reduce((sum, x) => sum + (x - middle) ** 2, 0) / 20);
  return validBands({ upper: middle + 2 * deviation, lower: middle - 2 * deviation });
}

export function fetchMarketState(): Promise<MacroTrendAnalysis> {
  let key: string;
  try { const c = connection(); key = c.url + c.token; } catch { return Promise.resolve(unknownMarket()); }
  if (pendingMarket && pendingIdentity === key) return pendingMarket;
  pendingIdentity = key;
  const promise = requestMarketState(key).finally(() => { if (pendingMarket === promise) pendingMarket = null; });
  pendingMarket = promise;
  return promise;
}
async function requestMarketState(key: string): Promise<MacroTrendAnalysis> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 4000);
  try {
    const { url, token } = connection();
    const response = await fetch(`${url}/model-library/market-state?view=radar`, {
      headers: { 'X-Library-Token': token },
      signal: controller.signal,
      cache: 'no-store',
    });
    if (response.ok) {
      const parsed = parseMarketState(await response.json());
      const current = connection();
      if (current.url + current.token !== key) return unknownMarket();
      if (parsed.dataReady) writeStartupCache('market', parsed);
      return parsed;
    }
    return unknownMarket('云端趋势暂不可用；实时报价仍可查看，等待重新同步');
  } catch {
    return unknownMarket('云端趋势暂不可用；实时报价仍可查看，等待重新同步');
  } finally {
    clearTimeout(timeout);
  }
}
