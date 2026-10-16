import type { MacroTrendAnalysis } from '../types/crypto';
import { connection } from './serverConnection';

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
    s.ruleVersion !== 'three-models-v1' ||
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
    hourlyTrend: m.trend,
    isStronglyBearish: m.is_strongly_bearish === true,
    hourlyMa20: m.ma20,
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
    hourlyRsi: m.rsi,
    trendDriftPercent: 0,
    allowLongBreakout: false,
    regime: m.trend === 'BULLISH' ? 'TRENDING_BULL' : m.trend === 'BEARISH' ? 'TRENDING_BEAR' : 'MEAN_REVERTING_RANGE',
    dataReady: true,
    regimeNameZh: `${title} · ${shadow ? '研究观察，不推送新买入' : '基线监控'}`,
    regimeDescription: `${typeof m.reason === 'string' ? m.reason : ''} ${
      reasons || (shadow ? '观察到候选，仍需验证' : '候选需打开复核')
    }`,
    biasZh: `${s.engineVersion} / ${s.ruleVersion} · ${new Date(s.atMs).toLocaleTimeString()} · 收盘结构；目标以具体信号为准`,
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

export async function fetchMarketState(): Promise<MacroTrendAnalysis> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 4000);
  try {
    const { url, token } = connection();
    const response = await fetch(`${url}/model-library/market-state`, {
      headers: { 'X-Library-Token': token },
      signal: controller.signal,
      cache: 'no-store',
    });
    if (response.ok) {
      const parsed = parseMarketState(await response.json());
      return parsed;
    }
    return unknownMarket('云端趋势暂不可用；实时报价仍可查看，等待重新同步');
  } catch {
    return unknownMarket('云端趋势暂不可用；实时报价仍可查看，等待重新同步');
  } finally {
    clearTimeout(timeout);
  }
}
