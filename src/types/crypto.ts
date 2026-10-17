export type SignalStrategy =
  | 'FLASH_CRASH_REBOUND'
  | 'BURST_BREAKOUT'
  | 'RANGE_OSCILLATION'
  | 'VOLATILITY_MOMENTUM'
  | 'VWAP_MEAN_REVERSION'
  | 'RSI_DIVERGENCE'
  | 'TREND_PULLBACK_BUY';

export type MarketRegime =
  | 'UNKNOWN'
  | 'TRENDING_BULL'
  | 'TRENDING_BEAR'
  | 'MEAN_REVERTING_RANGE'
  | 'VOLATILE_BREAKOUT';

export interface MarketTicker {
  symbol: string;
  name: string;
  price: number;
  change24h: number;
  high24h: number;
  low24h: number;
  volume24h: number;
  quoteVolume24h: number;
  lastUpdate: number;
  dataSource?: string;
  latency?: number;
  sparkline?: number[];
}

export interface KlineCandle {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  /** Aggressive buy volume on this candle, from the exchange kline. */
  takerBuyBase?: number;
  vwap?: number;
  closeTime?: number;
  isClosed?: boolean;
}

export type CandleState = 'CLOSED' | 'FORMING' | 'STALE' | 'INVALID';

export type DecisionStatus =
  | 'BUY_CANDIDATE'
  | 'WAIT_CONFIRMATION'
  | 'BLOCK_ENTRY'
  | 'INSUFFICIENT_DATA';

export type VolatilityLevel = 'LOW' | 'MEDIUM' | 'HIGH' | 'UNKNOWN';

export interface VolatilityRegime {
  level: VolatilityLevel;
  levelNameZh: string; // '小幅度波动 (窄幅小波段)' | '中度波动 (标准箱体)' | '大幅度波动 (宽幅拉锯)'
  swingRangePct: number;
  bandwidthPct: number;
  quantilePct: number; // 滚动波动历史百分位 (0 - 100%)
  p25AtrPct: number; // 12H观察窗口 25分位数
  p75AtrPct: number; // 12H观察窗口 75分位数
  windowSummary: string; // "15m × 48根K线 (12小时滚动窗口)"
  adaptiveTp1: number;
  adaptiveTp2: number;
  adaptiveSl: number;
  descriptionZh: string;
}

export interface MacroTrendAnalysis {
  stateSource?: 'SERVER' | 'UNAVAILABLE' | 'CACHE';
  rejectionReasons?: string[];
  research?: {label:string;status:string;reasons:string[]}[];
  hourlyTrend: 'BEARISH' | 'BULLISH' | 'RANGING';
  isStronglyBearish?: boolean;
  hourlyMa20: number;
  hourlyBollinger?: { upper: number; lower: number };
  hourlyMa50: number;
  hourlyRsi: number;
  trendDriftPercent: number;
  allowLongBreakout: boolean;
  regime: MarketRegime;
  regimeNameZh: string;
  regimeDescription: string;
  biasZh: string;
  minRequiredDropPct?: number;
  volatility?: VolatilityRegime;
  dataReady?: boolean;
  layers?: { d1: string; h4: string; h1: string; label: string; score: number };
  levels?: { name: string; price: number }[];
  watchCandidates?: { module: string; name: string; expiresAt?: number; tierLabel?: string; issue?: string }[];
  lab?: ReleaseLab;
  freshness?: { context: string; derivatives: string };
  breaker?: { state: string; reason?: string; pausedUntil?: number; consecutiveStops?: number; dayR?: number };
}

export interface ReleaseModule {
  module: string;
  stage: string;
  label: string;
  push: boolean;
  tierLabel: string;
  records: number;
  remainingMs?: number | null;
  gaps?: string[];
}

export interface ReleaseLab {
  source: 'SERVER' | 'LOCAL';
  modules: ReleaseModule[];
  l1: { status?: string; applied: boolean; samples?: number | null; minSamples?: number; proposal?: { pThreshold?: number; entryOffsetPct?: number; stopBufferPct?: number } };
  promotions: number;
  daily?: { day?: string; summary?: string } | null;
  hypotheses: { module?: string; feature?: string; claim?: string; status?: string; applied: boolean }[];
  veto?: { vetoEnabled?: boolean; vetoed?: number; passed?: number; vetoedMeanR?: number | null; passedMeanR?: number | null } | null;
  gates?: { minTrades?: number; minExpectancyPct?: number; minWinRate?: number; minProfitFactor?: number };
  continuity?: {
    cost?: { month?: string; frictionPct?: number; floorPct?: number; measuredPct?: number | null; source?: string; applied: boolean };
    environment?: { quarter?: string; status?: string; cutoff?: number | null; priorCutoff?: number; samples?: number; applied: boolean };
    environmentOpen?: string | null;
  } | null;
  note?: string;
}

export interface TradeRules {
  model: 'BREAKOUT' | 'REBOUND' | 'RANGE' | 'PULLBACK';
  ruleVersion: 'three-models-v1' | 'experimental-v1' | 'three-models-v2' | 'experimental-v2' | 'short-horizon-v1' | 'short-horizon-v2';
  maxHoldMinutes: number;
  minNetTp1: number;
  minNetRr?: number;
  frictionPct?: number;
  maxNetTarget: number | null;
  invalidationPrice: number;
  tp1Fraction: number;
  targetBasis: string;
  exitRule: string;
}

export interface TradeSignal {
  id: string;
  symbol: string;
  coinName: string;
  signalType: 'BUY';
  strategy: SignalStrategy;
  strategyNameZh: string;
  actionBadgeZh: string;
  entryPrice: number;
  targetTP1: number;
  targetTP2: number;
  stopLoss: number;
  profitPercent1: number;
  profitPercent2: number;
  stopLossPercent: number;
  riskRewardRatio: number;
  timeHorizon: string; // e.g. "15m - 1.5h"
  confidence: number; // 规则匹配度评分 (0 - 100)
  ruleScore?: number; // 确定性规则得分 (0 - 100)
  decisionStatus?: DecisionStatus; // 统一决策状态
  confirmationTime?: number; // 确认K线收盘时间戳
  engineVersion?: string; // 引擎版本
  expiresAt?: number;
  tierLabel?: string;
  aiExplain?: string;
  positionFractionPct?: number;
  timeStopMinutes?: number;
  entryMin?: number;
  entryMax?: number;
  breakoutLevel?: number;
  validityReason?: string;
  tradeRules?: TradeRules;
  regime: MarketRegime;
  reasonZh: string;
  analysis: {
    vwapDiffPercent?: number;
    rsi14?: number;
    atrPercent?: number;
    volumeMultiplier?: number;
    momentumZScore?: number;
    orderFlowImbalance?: number;
    vwapAtrSpread?: number;
    effectiveDropPct?: number;
    volatilityLevel?: VolatilityLevel;
    volatilityNameZh?: string;
    quantilePct?: number;
    netProfitPct1?: number; // 扣除手续费与滑点后的净收益率
    netProfitPct2?: number;
    netRiskReward?: number; // 净盈亏比
    estimatedFriction?: number; // 预估总交易摩擦 (手续费+滑点)
    structureSupportPrice?: number; // 结构支撑位
    structureResistancePrice?: number; // 结构目标位
    bidAskSpreadPct?: number; // 盘口买卖价差比率
    ruleScore?: number;
    historicalWinRateNote?: string; // 历史胜率说明（未验证）
  };
  timestamp: number;
  read: boolean;
}

export interface WatchlistItem {
  symbol: string;
  name: string;
  alertAbovePrice?: number;
  alertBelowPrice?: number;
  alertChangePercent?: number;
  positionEntryPrice?: number;
  positionSize?: number;
  notes?: string;
  addedAt: number;
  /** Alert that this simulated buy came from. */
  linkedAlertId?: string;
  linkedStrategy?: string;
  linkedTp1?: number;
  linkedTp2?: number;
  linkedSl?: number;
  linkedEngine?: string;
  linkedTradeRules?: TradeRules;
  positionDeadlineMs?: number;
}

export interface ClosedPositionRecord {
  accountingSource?: 'SIMULATED';
  id: string;
  symbol: string;
  name: string;
  entryPrice: number;
  exitPrice: number;
  positionSize: number;
  quantity: number;
  grossPnl: number;
  pnlPercent: number;
  feeAmount: number;
  netPnl: number;
  openedAt: number;
  closedAt: number;
  outcome: 'WIN' | 'LOSS' | 'BREAKEVEN';
  closeReason?: string;
}

export interface ScannerConfig {
  scanIntervalMs: number;
  soundEnabled: boolean;
  soundVolume: number;
  pushEnabled: boolean;
  autoPopupEnabled: boolean;
  minConfidence: number;
  minProfitTarget: number;
  maxHoldingHours: number;
  activeStrategies: {
    FLASH_CRASH_REBOUND: boolean;
    BURST_BREAKOUT: boolean;
    RANGE_OSCILLATION: boolean;
    VOLATILITY_MOMENTUM: boolean;
    VWAP_MEAN_REVERSION: boolean;
    RSI_DIVERGENCE: boolean;
    TREND_PULLBACK_BUY: boolean;
  };
  monitoredSymbols: string[];
  activeDataProvider: 'BINANCE' | 'FINNHUB' | 'MASSIVE' | 'ALPHA_VANTAGE';
}

export interface ApiProviderConfig {
  name: string;
  id: 'BINANCE' | 'FINNHUB' | 'MASSIVE' | 'ALPHA_VANTAGE';
  apiKey: string;
  status: 'active' | 'standby' | 'error';
  latencyMs: number | null;
  description: string;
  isPrimary: boolean;
}
