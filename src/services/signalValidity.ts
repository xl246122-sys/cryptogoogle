import type { TradeSignal, SignalStrategy, MarketRegime, TradeRules } from '../types/crypto';

export const SIGNAL_POLICY = { maxAgeMs: 120_000, ttlMs: 90_000, quoteAgeMs: 10_000, friction: 0.11, minNet: 0.40, minRR: 1.10 };
export interface EntryQuote { price: number; timestamp: number }
export const finiteNumber = (value: unknown): number | undefined => {
  if ((typeof value !== 'string' && typeof value !== 'number') || value === '') return undefined;
  const n = Number(value);
  return Number.isFinite(n) ? n : undefined;
};
const strategies: SignalStrategy[] = ['BURST_BREAKOUT', 'TREND_PULLBACK_BUY', 'FLASH_CRASH_REBOUND', 'RSI_DIVERGENCE', 'RANGE_OSCILLATION', 'VWAP_MEAN_REVERSION', 'VOLATILITY_MOMENTUM'];
const regimes: Record<string, MarketRegime> = { BULLISH: 'TRENDING_BULL', BEARISH: 'TRENDING_BEAR', RANGING: 'MEAN_REVERTING_RANGE' };

/** Missing protocol fields never acquire a fabricated timestamp or analytics value. */
export function parseCloudSignal(data: Record<string, unknown>): TradeSignal | null {
  if (!data || data.symbol !== 'BTCUSDT' || data.signalType !== 'BUY' || !strategies.includes(data.strategy as SignalStrategy)) return null;
  const required = ['entryPrice', 'targetTP1', 'targetTP2', 'stopLoss', 'timestamp', 'confirmationTime', 'expiresAt', 'entryMin', 'entryMax', 'ruleScore'];
  if (required.some(key => finiteNumber(data[key]) === undefined)) return null;
  const n = (key: string) => finiteNumber(data[key])!;
  const entry = n('entryPrice'), tp1 = n('targetTP1'), tp2 = n('targetTP2'), sl = n('stopLoss');
  let tradeRules: TradeRules;
  try { tradeRules = JSON.parse(String(data.tradeRules)); } catch { return null; }
  const model = { BURST_BREAKOUT: 'BREAKOUT', FLASH_CRASH_REBOUND: 'REBOUND', RANGE_OSCILLATION: 'RANGE' }[String(data.strategy)];
  if (!tradeRules || !model || tradeRules.model !== model || !['three-models-v1','experimental-v1'].includes(tradeRules.ruleVersion)) return null;
  const experiment=tradeRules.ruleVersion==='experimental-v1';
  const requiredMin = experiment || model === 'BREAKOUT' ? 0.4 : 1;
  if ((experiment ? ![60,90,120].includes(tradeRules.maxHoldMinutes) : tradeRules.maxHoldMinutes !== (model === 'REBOUND' ? 90 : 240)) || tradeRules.minNetTp1 !== requiredMin
      || tradeRules.maxNetTarget !== (experiment || model === 'BREAKOUT' ? null : model === 'REBOUND' ? 6 : 4)
      || !Number.isFinite(tradeRules.invalidationPrice) || tradeRules.invalidationPrice < sl || tradeRules.invalidationPrice >= entry
      || !Number.isFinite(tradeRules.tp1Fraction) || tradeRules.tp1Fraction <= 0 || tradeRules.tp1Fraction > 1
      || typeof tradeRules.exitRule !== 'string' || typeof tradeRules.targetBasis !== 'string') return null;
  if (tradeRules.tp1Fraction !== (tp1 === tp2 ? 1 : model === 'BREAKOUT' ? 0.5 : model === 'REBOUND' ? 0.7 : 1)) return null;
  if (!(sl > 0 && sl < entry && entry < tp1 && tp1 <= tp2 && n('entryMin') > sl && n('entryMin') <= entry && entry <= n('entryMax') && n('entryMax') < tp1)) return null;
  if (n('ruleScore') < 0 || n('ruleScore') > 100 || typeof data.id !== 'string' || !data.id) return null;
  const breakoutLevel = finiteNumber(data.breakoutLevel);
  if (data.strategy === 'BURST_BREAKOUT' && !(breakoutLevel !== undefined && breakoutLevel > 0 && entry > breakoutLevel)) return null;
  const analysis: TradeSignal['analysis'] = { historicalWinRateNote: '历史胜率：未验证' };
  const fields = ['rsi14', 'atrPercent', 'volumeMultiplier', 'momentumZScore', 'vwapDiffPercent', 'orderFlowImbalance', 'quantilePct', 'netProfitPct1', 'netProfitPct2', 'netRiskReward', 'estimatedFriction', 'structureSupportPrice', 'bidAskSpreadPct'] as const;
  for (const key of fields) { const value = finiteNumber(data[key]); if (value !== undefined) analysis[key] = value; }
  if (['LOW', 'MEDIUM', 'HIGH'].includes(String(data.volatilityLevel))) analysis.volatilityLevel = data.volatilityLevel as 'LOW' | 'MEDIUM' | 'HIGH';
  return {
    id: data.id, symbol: 'BTCUSDT', coinName: 'Bitcoin (比特币)', signalType: 'BUY', strategy: data.strategy as SignalStrategy,
    strategyNameZh: typeof data.strategyNameZh === 'string' ? data.strategyNameZh : '云端候选', actionBadgeZh: '等待价格复核',
    entryPrice: entry, targetTP1: tp1, targetTP2: tp2, stopLoss: sl,
    profitPercent1: +(100 * (tp1 / entry - 1)).toFixed(2), profitPercent2: +(100 * (tp2 / entry - 1)).toFixed(2),
    stopLossPercent: +(100 * (1 - sl / entry)).toFixed(2), riskRewardRatio: +((tp1 - entry) / (entry - sl)).toFixed(2),
    timeHorizon: typeof data.timeHorizon === 'string' ? data.timeHorizon : '未提供', confidence: n('ruleScore'), ruleScore: n('ruleScore'),
    decisionStatus: 'WAIT_CONFIRMATION', confirmationTime: n('confirmationTime'), timestamp: n('timestamp'),
    expiresAt: n('expiresAt'), entryMin: n('entryMin'), entryMax: n('entryMax'), breakoutLevel,
    engineVersion: typeof data.engineVersion === 'string' ? data.engineVersion : undefined, tradeRules,
    regime: regimes[String(data.regime)] ?? 'UNKNOWN',
    reasonZh: typeof data.reasonZh === 'string' ? data.reasonZh : '模型分析未提供', analysis, read: false,
  };
}

export function signalTimeIssue(signal: TradeSignal, now = Date.now()): string | null {
  const { timestamp, confirmationTime, expiresAt } = signal;
  if (![timestamp, confirmationTime, expiresAt, signal.entryMin, signal.entryMax].every(v => typeof v === 'number' && Number.isFinite(v) && v > 0)) return '缺少有效期或入场区间，请等待新版信号';
  if (timestamp > now + 5000 || confirmationTime! > timestamp || expiresAt! <= timestamp || expiresAt! - timestamp > SIGNAL_POLICY.ttlMs || expiresAt! - confirmationTime! > SIGNAL_POLICY.maxAgeMs) return '信号时间异常，禁止入场';
  if (now >= expiresAt!) return '信号已过期，禁止按旧信号入场';
  return null;
}

export function entryIssue(signal: TradeSignal, quote: EntryQuote | null, now = Date.now()): string | null {
  const timeIssue = signalTimeIssue(signal, now);
  if (timeIssue) return timeIssue;
  if (!quote || !Number.isFinite(quote.price) || quote.price <= 0 || !Number.isFinite(quote.timestamp) || now - quote.timestamp > SIGNAL_POLICY.quoteAgeMs || quote.timestamp > now + 5000) return '当前币安报价不可用或已过期，暂停入场';
  if (signal.breakoutLevel !== undefined && quote.price <= signal.breakoutLevel) return '价格已跌回突破位，突破失效';
  if (signal.tradeRules && quote.price <= signal.tradeRules.invalidationPrice) return '当前价格已触及该模型失效位';
  if (quote.price < signal.entryMin! || quote.price > signal.entryMax!) return '当前价格已离开有效入场区间';
  if (!(signal.stopLoss < quote.price && quote.price < signal.targetTP1)) return '当前价格已触及止盈或止损边界';
  const net = (signal.targetTP1 / quote.price - 1) * 100 - SIGNAL_POLICY.friction;
  const risk = (1 - signal.stopLoss / quote.price) * 100 + SIGNAL_POLICY.friction;
  if (net < Math.max(SIGNAL_POLICY.minNet, signal.tradeRules?.minNetTp1 ?? SIGNAL_POLICY.minNet) - 1e-9 || risk <= 0 || net / risk < SIGNAL_POLICY.minRR - 1e-9) return '当前价格扣预设成本后的收益/盈亏比不足';
  return null;
}

/** Same Binance Global venue as the daemon. No cache, US exchange, or synthetic fallback. */
export async function fetchEntryQuote(side: 'BUY' | 'SELL' = 'BUY'): Promise<EntryQuote | null> {
  for (const base of ['https://data-api.binance.vision/api/v3', 'https://api.binance.com/api/v3']) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 3000);
    try {
      const response = await fetch(`${base}/ticker/24hr?symbol=BTCUSDT`, { signal: controller.signal, cache: 'no-store' });
      if (!response.ok) continue;
      const data = await response.json();
      const price = finiteNumber(side === 'BUY' ? data.askPrice : data.bidPrice), timestamp = finiteNumber(data.closeTime);
      const now = Date.now();
      if (data.symbol === 'BTCUSDT' && price && timestamp && now - timestamp <= SIGNAL_POLICY.quoteAgeMs && timestamp <= now + 5000) return { price, timestamp };
    } catch { /* fail closed; try only another endpoint for the same venue */ }
    finally { clearTimeout(timeout); }
  }
  return null;
}
