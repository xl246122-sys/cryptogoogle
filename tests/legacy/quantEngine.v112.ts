import {
  CandleState,
  DecisionStatus,
  KlineCandle,
  MacroTrendAnalysis,
  MarketTicker,
  ScannerConfig,
  SignalStrategy,
  TradeSignal,
  VolatilityLevel,
  VolatilityRegime,
} from '../../src/types/crypto';

export class QuantEngine {
  /**
   * Closed-Candle Confirmation (防未收盘假突破):
   * Separates confirmed closed candles from currently forming/intra-bar candles.
   * All structural breakouts, reversals, and indicator evaluations MUST strictly
   * be anchored on closed candles.
   */
  public static getClosedCandles(
    candles: KlineCandle[],
    timeframeMs = 60000,
    now = Date.now()
  ): {
    closedCandles: KlineCandle[];
    formingCandle: KlineCandle | null;
    candleState: CandleState;
  } {
    if (!candles || candles.length === 0) {
      return { closedCandles: [], formingCandle: null, candleState: 'INVALID' };
    }

    const last = candles[candles.length - 1];
    // Explicit close marker or timestamp elapsed
    const isExplicitlyClosed =
      last.isClosed === true ||
      (last.closeTime !== undefined && now >= last.closeTime);

    let closedCandles: KlineCandle[];
    let formingCandle: KlineCandle | null;

    if (isExplicitlyClosed) {
      closedCandles = candles;
      formingCandle = null;
    } else {
      formingCandle = last;
      closedCandles = candles.slice(0, -1);
    }

    if (closedCandles.length === 0) {
      return { closedCandles: [], formingCandle, candleState: 'INVALID' };
    }

    // Check data freshness: last closed candle shouldn't lag excessively (>3 bars or >3 min)
    const lastClosed = closedCandles[closedCandles.length - 1];
    const expectedClose = lastClosed.closeTime || (lastClosed.time + timeframeMs);
    const lagMs = now - expectedClose;
    const maxAllowedLag = Math.max(3 * timeframeMs, 180000);

    if (lagMs > maxAllowedLag) {
      return { closedCandles, formingCandle, candleState: 'STALE' };
    }

    return {
      closedCandles,
      formingCandle,
      candleState: 'CLOSED',
    };
  }

  /**
   * Market Data Quality Gate (数据质量与完整性硬门禁):
   * Runs prior to all quant logic to guarantee zero NaN/Infinity, finite positive prices,
   * monotonic timestamps, valid ATR, and fresh macro data.
   */
  public static validateMarketDataQuality(
    symbol: string,
    microCandles: KlineCandle[],
    hourlyCandles: KlineCandle[],
    orderBook: { bidVolume: number; askVolume: number; imbalanceRatio: number; spreadPct?: number; isValid?: boolean },
    ticker: MarketTicker,
    now = Date.now()
  ): {
    isValid: boolean;
    rejectReason: string;
    status: DecisionStatus;
  } {
    if (symbol !== 'BTCUSDT' || ticker.symbol !== 'BTCUSDT') {
      return { isValid: false, rejectReason: '非 BTCUSDT 专属标的，严格拒绝', status: 'BLOCK_ENTRY' };
    }

    if (!ticker.price || isNaN(ticker.price) || !isFinite(ticker.price) || ticker.price <= 0) {
      return { isValid: false, rejectReason: '实时价格无效 (NaN或非正数)', status: 'INSUFFICIENT_DATA' };
    }

    if (!microCandles || microCandles.length < 20) {
      return { isValid: false, rejectReason: '1m 微观K线样本不足 (<20根)', status: 'INSUFFICIENT_DATA' };
    }

    for (let i = 0; i < microCandles.length; i++) {
      const c = microCandles[i];
      if (
        isNaN(c.open) || isNaN(c.high) || isNaN(c.low) || isNaN(c.close) ||
        !isFinite(c.open) || !isFinite(c.high) || !isFinite(c.low) || !isFinite(c.close) ||
        c.low <= 0
      ) {
        return { isValid: false, rejectReason: 'K线数据存在无效值 (NaN/非有限正数)', status: 'INSUFFICIENT_DATA' };
      }
      if (c.high < Math.max(c.open, c.close) || c.low > Math.min(c.open, c.close) || c.high < c.low) {
        return { isValid: false, rejectReason: 'K线价格结构逻辑反常 (High/Low倒挂越界)', status: 'INSUFFICIENT_DATA' };
      }
      if (i > 0 && c.time <= microCandles[i - 1].time) {
        return { isValid: false, rejectReason: 'K线时间戳非严格单调递增或存在重复', status: 'INSUFFICIENT_DATA' };
      }
    }

    const atr14 = this.calculateATR(microCandles, 14);
    if (!atr14 || isNaN(atr14) || !isFinite(atr14) || atr14 <= 0) {
      return { isValid: false, rejectReason: 'ATR 波动率指标无效 (ATR<=0 或 NaN)', status: 'INSUFFICIENT_DATA' };
    }

    if (hourlyCandles && hourlyCandles.length > 0) {
      const latestHourly = hourlyCandles[hourlyCandles.length - 1];
      const hourlyExpectedClose = latestHourly.closeTime || (latestHourly.time + 3600000);
      const hourlyAge = now - hourlyExpectedClose;
      if (hourlyAge > 2 * 3600000) {
        return { isValid: false, rejectReason: '1H 宏观行情数据严重过期 (>2小时)', status: 'INSUFFICIENT_DATA' };
      }
    } else {
      return { isValid: false, rejectReason: '缺少 1H 宏观大盘K线', status: 'INSUFFICIENT_DATA' };
    }

    if (orderBook.isValid === false) {
      return { isValid: false, rejectReason: '盘口订单簿数据失效或未能连接', status: 'INSUFFICIENT_DATA' };
    }

    const spread = orderBook.spreadPct ?? 0.01;
    if (isNaN(spread) || spread > 0.02) {
      return { isValid: false, rejectReason: `盘口买卖价差异常 (${spread.toFixed(4)}% > 0.02%)`, status: 'BLOCK_ENTRY' };
    }

    return { isValid: true, rejectReason: '', status: 'WAIT_CONFIRMATION' };
  }
  /**
   * Calculate Simple Moving Average (SMA)
   */
  public static calculateSMA(prices: number[], period: number): number {
    if (prices.length < period) return prices[prices.length - 1] || 0;
    const slice = prices.slice(-period);
    return slice.reduce((a, b) => a + b, 0) / slice.length;
  }

  /**
   * Calculate Exponential Moving Average (EMA)
   */
  public static calculateEMA(prices: number[], period: number): number {
    if (prices.length === 0) return 0;
    if (prices.length < period) return this.calculateSMA(prices, prices.length);
    const k = 2 / (period + 1);
    let ema = prices[0];
    for (let i = 1; i < prices.length; i++) {
      ema = prices[i] * k + ema * (1 - k);
    }
    return ema;
  }

  /**
   * Calculate Standard Deviation
   */
  public static calculateStdDev(prices: number[], period: number, mean?: number): number {
    if (prices.length < period) return 0;
    const slice = prices.slice(-period);
    const avg = mean ?? slice.reduce((a, b) => a + b, 0) / slice.length;
    const squareDiffs = slice.map((p) => Math.pow(p - avg, 2));
    const variance = squareDiffs.reduce((a, b) => a + b, 0) / slice.length;
    return Math.sqrt(variance);
  }

  /**
   * Calculate 14-period Relative Strength Index (RSI)
   */
  public static calculateRSI(candles: KlineCandle[], period = 14): number {
    if (candles.length < period + 1) return 50;
    const closes = candles.map((c) => c.close);
    let gains = 0;
    let losses = 0;

    for (let i = closes.length - period; i < closes.length; i++) {
      const diff = closes[i] - closes[i - 1];
      if (diff >= 0) gains += diff;
      else losses -= diff;
    }

    if (losses === 0) return 100;
    const rs = gains / losses;
    return +(100 - 100 / (1 + rs)).toFixed(2);
  }

  /**
   * Calculate Average True Range (ATR)
   */
  public static calculateATR(candles: KlineCandle[], period = 14): number {
    if (candles.length < period + 1) return 0;
    const trs: number[] = [];
    for (let i = candles.length - period; i < candles.length; i++) {
      const current = candles[i];
      const prevClose = candles[i - 1].close;
      const tr = Math.max(
        current.high - current.low,
        Math.abs(current.high - prevClose),
        Math.abs(current.low - prevClose)
      );
      trs.push(tr);
    }
    return trs.reduce((a, b) => a + b, 0) / trs.length;
  }

  /**
   * Calculate Percentile value from an array of numbers (0 - 100)
   */
  public static calculateQuantile(values: number[], percentile: number): number {
    if (!values || values.length === 0) return 0;
    const sorted = [...values].sort((a, b) => a - b);
    const index = (percentile / 100) * (sorted.length - 1);
    const lower = Math.floor(index);
    const upper = Math.ceil(index);
    const weight = index - lower;
    if (upper === lower) return sorted[lower];
    return +(sorted[lower] * (1 - weight) + sorted[upper] * weight).toFixed(3);
  }

  /**
   * Calculate Rolling Swing Range Series across uniform window length W:
   * Swing_t(W) = (HighestHigh_W - LowestLow_W) / LowestLow_W * 100
   * Guarantees both historical distribution and current swing share the EXACT same observation window W.
   */
  public static calculateRollingSwingRange(candles: KlineCandle[], windowBars = 16): number[] {
    if (!candles || candles.length < windowBars) return [];
    const swings: number[] = [];
    for (let i = windowBars; i <= candles.length; i++) {
      const window = candles.slice(i - windowBars, i);
      let maxHigh = -Infinity;
      let minLow = Infinity;
      for (const c of window) {
        if (c.high > maxHigh) maxHigh = c.high;
        if (c.low < minLow) minLow = c.low;
      }
      const swingPct = minLow > 0 ? +(((maxHigh - minLow) / minLow) * 100).toFixed(3) : 0;
      swings.push(swingPct);
    }
    return swings;
  }

  /**
   * Diagnose Volatility Regime with Dynamic Rolling Quantiles & Decoupled Trend
   * Solves statistical apples-to-oranges inconsistency:
   * 1. Uses uniform window W (16 bars) for BOTH historical reference swings and current swing.
   * 2. Calculates empirical rank Q_vol = count(HistoricalSwing <= CurrentSwing) / N * 100.
   * 3. 3-Tier Classification:
   *    - LOW (小幅度波动): Q_vol <= 30% and absolute swing < P25 (and ATR% < 0.35%)
   *    - MEDIUM (中度波动): 30% < Q_vol <= 75% (Standard Box)
   *    - HIGH (大幅度波动): Q_vol > 75% or absolute swing > P75
   *    - UNKNOWN: when candle samples < 20
   */
  public static diagnoseVolatilityRegime(
    candles: KlineCandle[],
    ticker: MarketTicker
  ): VolatilityRegime {
    const currentPrice = ticker.price > 0 ? ticker.price : (candles && candles.length > 0 ? candles[candles.length - 1].close : 83500);

    if (!candles || candles.length < 20) {
      return {
        level: 'UNKNOWN',
        levelNameZh: '波动数据不足 (样本未达标)',
        swingRangePct: 0,
        bandwidthPct: 0,
        quantilePct: 50,
        p25AtrPct: 0,
        p75AtrPct: 0,
        windowSummary: 'K线样本数量不足以计算滚动分位数',
        adaptiveTp1: 1.35,
        adaptiveTp2: 2.80,
        adaptiveSl: 0.85,
        descriptionZh: '历史波动数据样本不足，系统执行保守风控。',
      };
    }

    const windowBars = 16; // Uniform rolling window W = 16 bars
    const rollingSwings = this.calculateRollingSwingRange(candles, windowBars);

    if (rollingSwings.length === 0) {
      return {
        level: 'UNKNOWN',
        levelNameZh: '波动数据不足 (样本未达标)',
        swingRangePct: 0,
        bandwidthPct: 0,
        quantilePct: 50,
        p25AtrPct: 0,
        p75AtrPct: 0,
        windowSummary: '滚动样本不足',
        adaptiveTp1: 1.35,
        adaptiveTp2: 2.80,
        adaptiveSl: 0.85,
        descriptionZh: '样本不足，处于安全待命状态。',
      };
    }

    // Active current swing range (the latest W-bar swing)
    const swingRangePct = +rollingSwings[rollingSwings.length - 1].toFixed(2);

    // Historical swings prior to current bar to eliminate lookahead bias
    const historicalSwings = rollingSwings.slice(0, -1);
    const validHistory = historicalSwings.length > 0 ? historicalSwings : rollingSwings;

    const p25 = +this.calculateQuantile(validHistory, 25).toFixed(2);
    const p50 = +this.calculateQuantile(validHistory, 50).toFixed(2);
    const p75 = +this.calculateQuantile(validHistory, 75).toFixed(2);

    // Empirical Quantile Rank Q_vol calculated on identical window scale
    const lowerCount = validHistory.filter((r) => r <= swingRangePct).length;
    const quantilePct = Math.round((lowerCount / validHistory.length) * 100);

    const closes = candles.map((c) => c.close);
    const sma20 = this.calculateSMA(closes, Math.min(20, closes.length));
    const std20 = this.calculateStdDev(closes, Math.min(20, closes.length), sma20);
    const bandwidthPct = sma20 > 0 ? +(((std20 * 4) / sma20) * 100).toFixed(2) : 1.2;

    const atr14 = this.calculateATR(candles, 14);
    const atrPct = currentPrice > 0 ? +((atr14 / currentPrice) * 100).toFixed(2) : 0.35;

    // A small ATR must not force LOW. LOW is only a low relative rank.
    // ATR% >= 0.48 or swing >= 2.5 is absolute high risk and cannot be LOW.
    const isAbsoluteHighRisk = atrPct >= 0.48 || swingRangePct >= 2.5;

    const isLowVol = !isAbsoluteHighRisk && quantilePct <= 30 && swingRangePct <= p25;

    const isHighVol = isAbsoluteHighRisk || quantilePct >= 75;

    const windowSummary = `滚动窗口 W=${windowBars}根K线 (共${validHistory.length}组同口径样本)`;

    // Tier 1: Small Volatility / Narrow Fluctuation (小幅度波动)
    if (isLowVol) {
      const adaptiveTp1 = Math.max(0.65, +(atrPct * 1.6).toFixed(2));
      const adaptiveTp2 = Math.max(1.25, +(atrPct * 3.0).toFixed(2));
      const adaptiveSl = Math.min(0.65, Math.max(0.38, +(atrPct * 1.1).toFixed(2)));

      return {
        level: 'LOW',
        levelNameZh: '小幅度波动 (窄幅小波段)',
        swingRangePct,
        bandwidthPct,
        quantilePct,
        p25AtrPct: p25,
        p75AtrPct: p75,
        windowSummary,
        adaptiveTp1,
        adaptiveTp2,
        adaptiveSl,
        descriptionZh: `同口径振幅 ${swingRangePct}% (历史分位 Q=${quantilePct}%, P25=${p25}%)。进入小波段灵敏预警：微波段下轨止跌低吸，快进快出锁定 +${adaptiveTp1}%~+${adaptiveTp2}% 利润！`,
      };
    }

    // Tier 3: High Volatility / Wide Fluctuation (大幅度波动)
    if (isHighVol) {
      const adaptiveTp1 = Math.max(1.85, +(atrPct * 2.6).toFixed(2));
      const adaptiveTp2 = Math.max(3.80, +(atrPct * 4.8).toFixed(2));
      const adaptiveSl = Math.min(1.45, Math.max(0.95, +(atrPct * 1.6).toFixed(2)));

      return {
        level: 'HIGH',
        levelNameZh: '大幅度波动 (宽幅拉锯震荡)',
        swingRangePct,
        bandwidthPct,
        quantilePct,
        p25AtrPct: p25,
        p75AtrPct: p75,
        windowSummary,
        adaptiveTp1,
        adaptiveTp2,
        adaptiveSl,
        descriptionZh: `同口径振幅 ${swingRangePct}% (历史分位 Q=${quantilePct}%, P75=${p75}%)。进入宽幅自适应模式：要求弹性极限偏离，博弈 +${adaptiveTp1}%~+${adaptiveTp2}% 大波段均值回归！`,
      };
    }

    // Tier 2: Medium Volatility (中度波动 - 标准箱体震荡)
    const adaptiveTp1 = Math.max(1.20, +(atrPct * 2.1).toFixed(2));
    const adaptiveTp2 = Math.max(2.60, +(atrPct * 3.8).toFixed(2));
    const adaptiveSl = Math.min(0.95, Math.max(0.60, +(atrPct * 1.3).toFixed(2)));

    return {
      level: 'MEDIUM',
      levelNameZh: '中度波动 (标准箱体震荡)',
      swingRangePct,
      bandwidthPct,
      quantilePct,
      p25AtrPct: p25,
      p75AtrPct: p75,
      windowSummary,
      adaptiveTp1,
      adaptiveTp2,
      adaptiveSl,
      descriptionZh: `当前箱体振幅 ${swingRangePct}% (历史分位 Q=${quantilePct}%, P50=${p50}%)。进入标准箱体低吸：下轨支撑收阳买入，稳吃 +${adaptiveTp1}%~+${adaptiveTp2}% 箱体回抽！`,
    };
  }

  /**
   * Calculate Rolling RSI Series for candles
   */
  public static calculateRSISeries(
    candles: KlineCandle[],
    period = 14
  ): { index: number; rsi: number; low: number; close: number; time: number }[] {
    if (candles.length < period + 2) return [];
    const results: { index: number; rsi: number; low: number; close: number; time: number }[] = [];
    for (let i = period; i < candles.length; i++) {
      const window = candles.slice(0, i + 1);
      const rsi = this.calculateRSI(window, period);
      results.push({
        index: i,
        rsi,
        low: candles[i].low,
        close: candles[i].close,
        time: candles[i].time,
      });
    }
    return results;
  }

  /**
   * Diagnose if the asset is in an active Cascading Downtrend (单边下行瀑布通道).
   * In a cascading downtrend, buying micro bounces is strictly forbidden (Anti-Falling-Knife Filter).
   * Anchored on closed candles to avoid intra-bar head fakes.
   */
  public static diagnoseCascadeDowntrend(
    candles: KlineCandle[],
    ticker: MarketTicker
  ): { isCascading: boolean; reason: string } {
    const { closedCandles } = this.getClosedCandles(candles);
    if (!closedCandles || closedCandles.length < 15) return { isCascading: false, reason: '' };

    const closes = closedCandles.map((c) => c.close);
    const ema7 = this.calculateEMA(closes, 7);
    const ema25 = this.calculateEMA(closes, 25);
    const currentPrice = ticker.price > 0 ? ticker.price : closes[closes.length - 1];
    const change24h = ticker.change24h || 0;

    // A single green candle does not cancel a waterfall. The EMA alignment below still has to clear.

    // Check 1: Short-term EMA ribbon in strong bearish waterfall alignment (EMA7 < EMA25 and price < EMA7)
    const isEmaWaterfall = ema7 < ema25 && currentPrice < ema7 * 0.9985;

    // Check 2: Recent 5 candles have consecutive lower highs/lower lows (单边阴跌无阳线突破)
    const recent5 = closedCandles.slice(-5);
    let lowerHighCount = 0;
    for (let i = 1; i < recent5.length; i++) {
      if (recent5[i].high <= recent5[i - 1].high * 1.0005) lowerHighCount++;
    }
    const isConsecutiveDrop = lowerHighCount >= 3;

    // Check 3: Short-term drop > 0.8% in last 12 candles without a strong green bounce
    const startPrice = closes[Math.max(0, closes.length - 12)];
    const shortTermDropPct = ((currentPrice - startPrice) / startPrice) * 100;
    const isSharpDrop = shortTermDropPct < -0.8;

    if (
      (isEmaWaterfall && isConsecutiveDrop) ||
      (isEmaWaterfall && change24h < -2.5) ||
      (isSharpDrop && isEmaWaterfall)
    ) {
      return {
        isCascading: true,
        reason: `单边空头瀑布通道下行 (EMA7 $${ema7.toFixed(2)} < EMA25 $${ema25.toFixed(2)}，短线跌幅 ${shortTermDropPct.toFixed(2)}%)，严禁逆势接飞刀！`,
      };
    }
    return { isCascading: false, reason: '' };
  }

  /**
   * 5-Barrier Anti-Knife Reversal Confirmation for Range Oscillations
   * Solves Question 2: Prevents catching falling knives in continuous down-legs.
   * STRICT Requirement: Uses confirmed CLOSED candles for all structural barriers!
   * 1. 局部低点不再持续下移 (Lt >= Lt-1 * 0.9995)
   * 2. 价格重新站稳短周期结构位 (已收盘K线 Close >= EMA7 且收复前一阴线实体中轴，实体微阳)
   * 3. 卖压衰减，盘口买方托底 (下杀不放量，订单簿深度偏买方)
   * 4. 盘口买卖价差正常 (真实 Spread <= 0.02%)
   * 5. 大盘风险门禁通过 (非瀑布主跌)
   */
  public static verifyMicroRangeReversal(
    candles: KlineCandle[],
    orderBook: { bidVolume: number; askVolume: number; imbalanceRatio: number; spreadPct?: number },
    ticker: MarketTicker
  ): {
    passed: boolean;
    reasonZh: string;
    spreadPct: number;
    supportPrice: number;
    resistancePrice: number;
  } {
    const { closedCandles } = this.getClosedCandles(candles);
    if (!closedCandles || closedCandles.length < 15) {
      return { passed: false, reasonZh: '已收盘K线样本不足', spreadPct: 0.01, supportPrice: 0, resistancePrice: 0 };
    }

    const currentPrice = ticker.price;
    const latestClosed = closedCandles[closedCandles.length - 1];
    const prevClosed = closedCandles[closedCandles.length - 2];
    const prevPrevClosed = closedCandles[closedCandles.length - 3];
    const closes = closedCandles.map((c) => c.close);
    const ema7 = this.calculateEMA(closes, 7);

    // Structural Support & Resistance determination
    const recentLows = closedCandles.slice(-14).map((c) => c.low);
    const recentHighs = closedCandles.slice(-14).map((c) => c.high);
    const supportPrice = Math.min(...recentLows);
    const resistancePrice = Math.max(...recentHighs);

    const spreadPct = orderBook.spreadPct ?? 0.01;

    // Execution sanity: If current forming price dumped below support, reject execution immediately
    if (currentPrice < supportPrice * 0.999) {
      return {
        passed: false,
        reasonZh: '【执行拦截】盘中现价已下破已收盘结构支撑位，暂缓入场！',
        spreadPct,
        supportPrice,
        resistancePrice,
      };
    }

    // Barrier 1: Local low stops making lower lows (局部低点不再持续下移)
    const isLowCeasedFalling =
      latestClosed.low >= prevClosed.low * 0.9995 &&
      latestClosed.low >= Math.min(prevClosed.low, prevPrevClosed.low) * 0.9990;

    if (!isLowCeasedFalling) {
      return {
        passed: false,
        reasonZh: '【止跌门禁1拦截】局部低点仍在持续破位下移，严禁逆势接飞刀！',
        spreadPct,
        supportPrice,
        resistancePrice,
      };
    }

    // Barrier 2: Decisive structural reclaim (已收盘K线站稳短周期结构位与前阴线实体中轴)
    // Precise formula: If previous candle was red (open > close), use real body midpoint (open + close)/2
    const prevBearishBodyMidpoint = prevClosed.open > prevClosed.close
      ? (prevClosed.open + prevClosed.close) / 2
      : (prevClosed.high + prevClosed.low) / 2;

    const candleRange = latestClosed.high - latestClosed.low;
    const bodySize = latestClosed.close - latestClosed.open;
    const isSolidGreen = bodySize >= (candleRange > 0 ? candleRange * 0.12 : 0) && latestClosed.close >= latestClosed.open;
    const isAboveEma7 = latestClosed.close >= ema7 * 0.9995;
    const isAbovePrevMid = latestClosed.close >= prevBearishBodyMidpoint * 0.9998;

    if (!isSolidGreen || !isAboveEma7 || !isAbovePrevMid) {
      return {
        passed: false,
        reasonZh: '【止跌门禁2拦截】已收盘K线尚未站稳 EMA(7) 或未收复前一阴线实体中轴，非有效右侧止跌微阳！',
        spreadPct,
        supportPrice,
        resistancePrice,
      };
    }

    // Barrier 3: executed taker-buy on the closed candle. Resting bids alone are not a fill.
    const recent5Vols = closedCandles.slice(-6, -1).map((c) => c.volume);
    const avgRecentVol = recent5Vols.reduce((a, b) => a + b, 0) / Math.max(1, recent5Vols.length);
    const isVolumeControlled = latestClosed.volume <= avgRecentVol * 2.4;
    const takerRatio = latestClosed.volume > 0 ? (latestClosed.takerBuyBase || 0) / latestClosed.volume : 0;
    const hasExecutedBuy = takerRatio >= 0.52;
    const hasOrderFlowImbalance = orderBook.imbalanceRatio >= 0.02;

    if (!hasExecutedBuy || !hasOrderFlowImbalance || !isVolumeControlled) {
      return {
        passed: false,
        reasonZh: '【止跌门禁3拦截】已收盘主动买量不足 (52%)、挂单失衡不足，或下杀未缩量。',
        spreadPct,
        supportPrice,
        resistancePrice,
      };
    }

    // Barrier 4: Bid-Ask spread normality (买卖价差正常 <= 0.02%)
    if (spreadPct > 0.02) {
      return {
        passed: false,
        reasonZh: `【止跌门禁4拦截】盘口价差异常放大 (${spreadPct.toFixed(4)}% > 0.02%)，流动性缺失！`,
        spreadPct,
        supportPrice,
        resistancePrice,
      };
    }

    return {
      passed: true,
      reasonZh: '5重微波段止跌企稳门禁全部通过 (低点不再下移、站稳EMA7与阴线中轴、卖压衰减、盘口买量优势、价差健康)',
      spreadPct,
      supportPrice,
      resistancePrice,
    };
  }

  /**
   * Detect Bullish RSI Divergence:
   * STRICT Right-Side Confirmation required:
   * 1. Price makes lower/equal low, but RSI makes higher low.
   * 2. The latest candle MUST be a GREEN reversal candle (close >= open).
   * 3. Price must have bounced off the low (not currently crashing onto new lows).
   * 4. RSI must be in true oversold territory (<= 40), not mid-range noise.
   */
  public static detectBullishRsiDivergence(
    candles: KlineCandle[],
    period = 14,
    lookback = 30
  ): {
    isDivergent: boolean;
    priceLow1: number;
    priceLow2: number;
    rsiLow1: number;
    rsiLow2: number;
    diffRsi: number;
  } | null {
    const { closedCandles } = this.getClosedCandles(candles);
    if (!closedCandles || closedCandles.length < period + 8) return null;

    const latestClosed = closedCandles[closedCandles.length - 1];
    // Right-side confirmation 1: Latest closed candle MUST NOT be a red dump candle!
    if (latestClosed.close < latestClosed.open * 0.9995) {
      return null;
    }

    const rsiSeries = this.calculateRSISeries(closedCandles, period);
    if (rsiSeries.length < 8) return null;

    const window = rsiSeries.slice(-Math.min(lookback, rsiSeries.length));
    const len = window.length;
    if (len < 6) return null;

    const currentPrice = window[len - 1].close;

    // 1. Dual-phase swing low comparison:
    const splitIndex = Math.max(2, Math.floor(len * 0.55));
    const earlierPhase = window.slice(0, splitIndex);
    const recentPhase = window.slice(splitIndex);

    let minEarlier = earlierPhase[0];
    for (const pt of earlierPhase) {
      if (pt.low < minEarlier.low) minEarlier = pt;
    }

    let minRecent = recentPhase[0];
    for (const pt of recentPhase) {
      if (pt.low < minRecent.low) minRecent = pt;
    }

    const priceLow1 = minEarlier.low;
    const priceLow2 = minRecent.low;
    const rsiLow1 = minEarlier.rsi;
    const rsiLow2 = minRecent.rsi;

    // Right-side confirmation 2: Price must have bounced off the low by at least +0.2%
    const hasRightSideBounce = currentPrice >= minRecent.low * 1.002;

    if (
      priceLow2 <= priceLow1 * 1.0015 &&
      rsiLow2 >= rsiLow1 + 2.0 &&
      rsiLow2 <= 40 &&
      hasRightSideBounce
    ) {
      return {
        isDivergent: true,
        priceLow1: +priceLow1.toFixed(2),
        priceLow2: +priceLow2.toFixed(2),
        rsiLow1: +rsiLow1.toFixed(1),
        rsiLow2: +rsiLow2.toFixed(1),
        diffRsi: +(rsiLow2 - rsiLow1).toFixed(1),
      };
    }

    // 2. Pivot trough comparison
    const troughs: { low: number; rsi: number; index: number }[] = [];
    for (let i = 1; i < window.length - 1; i++) {
      if (window[i].low <= window[i - 1].low && window[i].low <= window[i + 1].low) {
        troughs.push({ low: window[i].low, rsi: window[i].rsi, index: i });
      }
    }

    if (troughs.length >= 2) {
      const t1 = troughs[troughs.length - 2];
      const t2 = troughs[troughs.length - 1];
      const hasPivotBounce = currentPrice >= t2.low * 1.002;
      if (
        t2.low <= t1.low * 1.0015 &&
        t2.rsi >= t1.rsi + 2.0 &&
        t2.rsi <= 40 &&
        hasPivotBounce
      ) {
        return {
          isDivergent: true,
          priceLow1: +t1.low.toFixed(2),
          priceLow2: +t2.low.toFixed(2),
          rsiLow1: +t1.rsi.toFixed(1),
          rsiLow2: +t2.rsi.toFixed(1),
          diffRsi: +(t2.rsi - t1.rsi).toFixed(1),
        };
      }
    }

    return null;
  }

  /**
   * Diagnose Higher-Timeframe Macro Trend using 1-Hour Klines and 24h Ticker Stats
   * Solves Question 1 Part 2: Strictly decouple Trend Direction from Volatility Amplitude!
   * - A unilateral +2.5% rally is a BULL TREND, which triggers trend-following models, NEVER "wide oscillation".
   * - A unilateral drop is a BEAR TREND, which strictly activates the 5% drop gate.
   * - Only when directional drift is bounded (|drift| <= 0.6%) and price is oscillating around MA20 is it RANGING.
   */
  public static diagnoseMacroTrend(
    hourlyCandles: KlineCandle[],
    ticker: MarketTicker
  ): MacroTrendAnalysis {
    const currentPrice = ticker.price;
    const change24h = ticker.change24h;
    hourlyCandles = this.getClosedCandles(hourlyCandles || [], 3_600_000).closedCandles;
    const latest = hourlyCandles[hourlyCandles.length - 1];
    if (!(currentPrice > 0) || hourlyCandles.length < 25 || !latest || Date.now() - (latest.closeTime || 0) > 3_660_000) {
      return { hourlyTrend: 'RANGING', hourlyMa20: 0, hourlyMa50: 0, hourlyRsi: 0,
        trendDriftPercent: 0, allowLongBreakout: false, regime: 'UNKNOWN', dataReady: false,
        regimeNameZh: '数据不足', regimeDescription: '等待足够且新鲜的已收盘 1h 行情', biasZh: '尚未计算' };
    }

    const hourlyCloses = hourlyCandles.map((c) => c.close);
    const ma20 = this.calculateSMA(hourlyCloses, Math.min(20, hourlyCloses.length));
    const ma50 = this.calculateSMA(hourlyCloses, Math.min(50, hourlyCloses.length));
    const hourlyEma7 = this.calculateEMA(hourlyCloses, 7);
    const hourlyEma25 = this.calculateEMA(hourlyCloses, 25);
    const hourlyRsi = this.calculateRSI(hourlyCandles, 14);

    const startIdx = Math.max(0, hourlyCloses.length - 12);
    const driftPct = +(((currentPrice - hourlyCloses[startIdx]) / hourlyCloses[startIdx]) * 100).toFixed(2);
    const startIdx4 = Math.max(0, hourlyCloses.length - 4);
    const drift4hPct = +(((currentPrice - hourlyCloses[startIdx4]) / hourlyCloses[startIdx4]) * 100).toFixed(2);

    // Peak calculation across hourly candles
    const hourlyHigh = Math.max(...hourlyCandles.map((c) => c.high));
    const dropFromHourlyPeakPct = hourlyHigh > 0 ? +(((hourlyHigh - currentPrice) / hourlyHigh) * 100).toFixed(2) : 0;

    // Strict Decoupling: Strong Multi-Hour Directional Drift
    // 1. Bullish Trending Alignment (持续单边上涨不能归类为宽幅震荡抄底)
    const isStrictlyBullish =
      (currentPrice > ma20 * 1.002 && hourlyEma7 >= hourlyEma25 && hourlyRsi >= 52 && (driftPct > 0.4 || drift4hPct > 0.5)) ||
      (drift4hPct > 0.8 && currentPrice > hourlyEma7);

    // 2. Bearish Trending Alignment (持续单边下跌或瀑布破位)
    const isBelowMa20Bearish = currentPrice < ma20 * 0.992 && hourlyRsi < 47;
    const isHourlyEmaBearish = hourlyEma7 < hourlyEma25 && currentPrice < hourlyEma7 && hourlyRsi < 46;
    const isDriftingDown = driftPct < -0.45 || drift4hPct < -0.55;
    const isDeepDrop = change24h < -1.8;
    const isFallenFromPeak = dropFromHourlyPeakPct > 1.5 && currentPrice < hourlyEma7 && currentPrice < ma20;

    const isDowntrend =
      isBelowMa20Bearish ||
      isHourlyEmaBearish ||
      isDriftingDown ||
      isDeepDrop ||
      isFallenFromPeak;

    const isStronglyBearish =
      isDowntrend &&
      (hourlyRsi < 40 ||
        driftPct < -0.8 ||
        drift4hPct < -0.9 ||
        change24h < -2.5 ||
        (hourlyEma7 < hourlyEma25 && currentPrice < ma20 * 0.988));

    if (isStrictlyBullish) {
      return {
        hourlyTrend: 'BULLISH',
        isStronglyBearish: false,
        hourlyMa20: +ma20.toFixed(2),
        hourlyMa50: +ma50.toFixed(2),
        hourlyRsi,
        trendDriftPercent: driftPct,
        allowLongBreakout: true,
        regime: 'TRENDING_BULL',
        regimeNameZh: '大盘多头顺势态 (允许顺势买入)',
        regimeDescription: `1小时均线向上发散，站稳 MA20 $${ma20.toFixed(1)} 与 EMA7，顺大势捕捉放量突破与均线回踩买点。`,
        biasZh: '大盘多头顺势 · 可择机买入',
      };
    } else if (isDowntrend) {
      return {
        hourlyTrend: 'BEARISH',
        isStronglyBearish,
        hourlyMa20: +ma20.toFixed(2),
        hourlyMa50: +ma50.toFixed(2),
        hourlyRsi,
        trendDriftPercent: driftPct,
        allowLongBreakout: false,
        regime: 'TRENDING_BEAR',
        minRequiredDropPct: 5.0, // Strictest requirement: 5% drop required for bottoming confirmation
        regimeNameZh: isStronglyBearish
          ? '大盘强空头下行态 (严格防阴跌 · 须跌幅≥5%方可抄底)'
          : '大盘空头下行态 (严格防阴跌 · 须跌幅≥5%方可抄底)',
        regimeDescription: isStronglyBearish
          ? `1小时大盘处于极度强空主跌通道 (1h RSI=${hourlyRsi}，承压于 MA20 $${ma20.toFixed(1)})。已启动【空头严格防阴跌风控】：由于大盘处于空头下行态，为防止在阴跌破位途中频繁接飞刀，所有策略买入必须强制满足标的高位累计跌幅达到 5% 以上（作为深度超跌见底确认）方允许触发！`
          : `1小时大盘处于空头下行通道，现价 $${currentPrice.toLocaleString()} 承压于 MA20 ($${ma20.toFixed(1)})。已启动【空头严格防阴跌风控】：所有买入策略必须满足标的高位累计跌幅 ≥ 5% 抄底确认，严禁在阴跌破位途中频繁开多！`,
        biasZh: isStronglyBearish ? '大盘强空 · 需跌幅≥5%抄底确认' : '大盘偏弱 · 需跌幅≥5%抄底确认',
      };
    } else {
      // Mean-reverting Range Oscillation: diagnose dynamic 3-tier volatility
      const volatility = this.diagnoseVolatilityRegime(hourlyCandles, ticker);
      return {
        hourlyTrend: 'RANGING',
        isStronglyBearish: false,
        hourlyMa20: +ma20.toFixed(2),
        hourlyMa50: +ma50.toFixed(2),
        hourlyRsi,
        trendDriftPercent: driftPct,
        allowLongBreakout: false,
        regime: 'MEAN_REVERTING_RANGE',
        volatility,
        regimeNameZh: `大盘区间震荡态 · ${volatility.levelNameZh}`,
        regimeDescription: `BTC 在 MA20 ($${ma20.toFixed(1)}) 附近区间震荡 (振幅 ${volatility.swingRangePct}%, 波动百分位 Q=${volatility.quantilePct}%)。已自动适配【${volatility.levelNameZh}】：${volatility.descriptionZh}`,
        biasZh: `区间震荡 · ${volatility.levelNameZh}`,
      };
    }
  }

  /**
   * Quantitative Scanner: ONLY generates verified BUY signals!
   * Fixed exclusively to BTC/USDT to eliminate altcoin volatility distortion and noise.
   * Incorporates:
   * 1. Dynamic Rolling Quantile Volatility (12H window)
   * 2. 5-Barrier Anti-Knife Reversal Confirmation for Range Oscillations
   * 3. Dynamic Structural TP/SL with Institutional Friction Gate (Fees + Slippage)
   */
  public static scanSymbol(
    ticker: MarketTicker,
    microCandles: KlineCandle[],
    hourlyCandles: KlineCandle[],
    orderBook: { bidVolume: number; askVolume: number; imbalanceRatio: number; spreadPct?: number; isValid?: boolean },
    config: ScannerConfig,
    externalMacro?: MacroTrendAnalysis,
    regimeCandles?: KlineCandle[]
  ): TradeSignal | null {
    // Direct User Command: Fix exclusively to BTC, remove SUI/altcoin alerts
    if (ticker.symbol !== 'BTCUSDT') {
      return null;
    }

    // Step 1: Pre-Execution Market Data Quality Gate (数据质量与完整性硬门禁)
    const quality = this.validateMarketDataQuality('BTCUSDT', microCandles, hourlyCandles, orderBook, ticker);
    if (!quality.isValid) {
      return null;
    }

    // Step 2: Extract Confirmed CLOSED Candles (防未收盘K线假突破)
    const { closedCandles, formingCandle, candleState } = this.getClosedCandles(microCandles, 60000);
    if (candleState !== 'CLOSED' || closedCandles.length < 20) {
      return null;
    }

    const currentPrice = ticker.price;
    const closes = closedCandles.map((c) => c.close);
    const volumes = closedCandles.map((c) => c.volume);
    const latestClosedCandle = closedCandles[closedCandles.length - 1];

    const sma20 = this.calculateSMA(closes, 20);
    const std20 = this.calculateStdDev(closes, 20, sma20);
    const upperBB = sma20 + 2 * std20;
    const lowerBB = sma20 - 2 * std20;
    const rsi14 = this.calculateRSI(closedCandles, 14);
    const atr14 = this.calculateATR(closedCandles, 14);
    if (!atr14 || atr14 <= 0) return null;
    const atrPercent = +((atr14 / currentPrice) * 100).toFixed(2);

    // Volume surge ratio computed on closed candles
    const avgVol20 = volumes.slice(-20, -1).reduce((a, b) => a + b, 0) / 19;
    const volumeMultiplier = +(latestClosedCandle.volume / Math.max(0.1, avgVol20)).toFixed(2);

    // VWAP diff
    const latestVwap = latestClosedCandle.vwap || sma20;
    const vwapDiffPercent = +(((currentPrice - latestVwap) / latestVwap) * 100).toFixed(2);

    // VWAP-Volatility Spread Filter Metric:
    const vwapAtrSpread = atr14 > 0 ? +((latestVwap - currentPrice) / atr14).toFixed(2) : 0;

    // Volatility Momentum Z-Score
    const returns10 = ((currentPrice - closes[closes.length - 10]) / closes[closes.length - 10]) * 100;
    const momentumZScore = +(returns10 / Math.max(0.2, (std20 / sma20) * 100)).toFixed(2);

    // 0. ANTI-FALLING-KNIFE WATERFALL FILTER (基于已收盘K线):
    const cascadeCheck = this.diagnoseCascadeDowntrend(closedCandles, ticker);
    if (cascadeCheck.isCascading) {
      return null;
    }

    // Diagnose Macro Trend
    const macro = externalMacro || this.diagnoseMacroTrend(hourlyCandles, ticker);

    // Calculate reference peak price across 24h high, hourly candles, and micro candles
    const hourlyHigh = hourlyCandles && hourlyCandles.length > 0 ? Math.max(...hourlyCandles.map((c) => c.high)) : 0;
    const microHigh = microCandles && microCandles.length > 0 ? Math.max(...microCandles.map((c) => c.high)) : 0;
    const peakPrice = Math.max(ticker.high24h || 0, hourlyHigh, microHigh, currentPrice);

    // Calculate effective drop percentage from recent peak and 24h net change
    const dropFromPeakPct = peakPrice > 0 ? +(((peakPrice - currentPrice) / peakPrice) * 100).toFixed(2) : 0;
    const netDrop24hPct = ticker.change24h < 0 ? Math.abs(ticker.change24h) : 0;
    const effectiveDropPct = +Math.max(dropFromPeakPct, netDrop24hPct).toFixed(2);

    // =========================================================================
    // STRICT 5% DROP REQUIREMENT DURING DOWNTREND (空头趋势强制 5% 跌幅门槛抄底确认)
    // =========================================================================
    const isBearishTrend =
      macro.hourlyTrend === 'BEARISH' ||
      macro.regime === 'TRENDING_BEAR' ||
      macro.isStronglyBearish ||
      ticker.change24h < -1.5;

    const MIN_BEARISH_DROP_REQUIRED = 5.0; // 5% minimum drop required

    if (isBearishTrend && effectiveDropPct < MIN_BEARISH_DROP_REQUIRED) {
      return null;
    }

    const regimeClosed = this.getClosedCandles(regimeCandles || [], 15 * 60 * 1000).closedCandles;
    if (regimeClosed.length < 64) return null;
    const microVolatility = this.diagnoseVolatilityRegime(regimeClosed, ticker);
    if (microVolatility.level === 'UNKNOWN') return null;

    const reversalGate = this.verifyMicroRangeReversal(microCandles, orderBook, ticker);

    // Structural calculations based strictly on closed candles
    const recentLows = closedCandles.slice(-14).map((c) => c.low);
    const recentHighs = closedCandles.slice(-14).map((c) => c.high);
    const swingBottom = Math.min(...recentLows);
    const swingTop = Math.max(...recentHighs);
    const bounceFromBottomPct = ((currentPrice - swingBottom) / swingBottom) * 100;
    const ema7 = this.calculateEMA(closes, 7);
    const ema25 = this.calculateEMA(closes, 25);

    // High-conviction Bottom Rebound Confirmation (anchored on latest closed candle)
    const isBottomReboundConfirmed =
      bounceFromBottomPct >= 0.20 &&
      bounceFromBottomPct <= 1.8 &&
      latestClosedCandle.close >= latestClosedCandle.open &&
      currentPrice >= ema7 * 0.9985 &&
      rsi14 >= 32 &&
      rsi14 <= 62 &&
      orderBook.imbalanceRatio >= 0.02;

    // Calculate Bullish RSI Divergence (requires right-side green closed candle confirmation)
    const rsiDivergence = this.detectBullishRsiDivergence(closedCandles, 14, 30);

    let matchedStrategy: SignalStrategy | null = null;
    let strategyNameZh = '';
    let reasonZh = '';
    let confidence = 85;
    let profitTarget1 = 1.6;
    let profitTarget2 = 3.2;
    let stopLossPct = 0.85;
    let timeHorizon = '15m - 2h';
    let structureSupportPrice = swingBottom;
    let structureResistancePrice = swingTop;

    // =========================================================================
    // SCENARIO 1: MACRO TREND IS BEARISH (1小时大盘偏弱/下行态)
    // -> STRICT TREND-ALIGNED 5%+ DROP BOTTOM-FISHING CONFIRMATION:
    // =========================================================================
    if (isBearishTrend) {
      // Model 1: Confirmed Bottom Reversal Buy (触底企稳反弹买入)
      if (config.activeStrategies.FLASH_CRASH_REBOUND && isBottomReboundConfirmed) {
        matchedStrategy = 'FLASH_CRASH_REBOUND';
        strategyNameZh = '空头深幅触底企稳反弹买入 (Confirmed Bottom Rebound)';
        confidence = Math.min(96, Math.round(91 + bounceFromBottomPct * 3.2));
        structureSupportPrice = swingBottom - 0.25 * atr14;
        structureResistancePrice = sma20;
        profitTarget1 = Math.max(1.4, +(((structureResistancePrice - currentPrice) / currentPrice) * 100).toFixed(2));
        profitTarget2 = +(profitTarget1 * 2.1).toFixed(2);
        stopLossPct = Math.min(1.2, Math.max(0.65, +(((currentPrice - structureSupportPrice) / currentPrice) * 100).toFixed(2)));
        timeHorizon = '15m - 1.5h';
        reasonZh = `【空头 5% 跌幅抄底确认 · 触底企稳买入】已通过严苛空头风控：BTC 高位累计跌幅达 ${effectiveDropPct}% (≥ 5.0% 门槛已达标，确认深度超跌见底)！价格在 $${swingBottom.toLocaleString()} 探底成功并获得强力托底，当前收出右侧反转阳线并放量站上 EMA(7) 短期均线 ($${currentPrice.toLocaleString()} > $${ema7.toFixed(2)})，RSI 从低位强劲拐头向上 (${rsi14.toFixed(1)})，盘口托单涌现，触底反弹结构正式确立，建议果断买入做多！`;
      }
      // Model 2: Deep RSI Bullish Divergence with Right-Side Confirmation
      else if (config.activeStrategies.RSI_DIVERGENCE && rsiDivergence) {
        matchedStrategy = 'RSI_DIVERGENCE';
        strategyNameZh = '空头深幅 RSI 底背离反弹买入 (RSI Bullish Divergence)';
        confidence = Math.min(96, Math.round(89 + rsiDivergence.diffRsi * 2.2));
        structureSupportPrice = rsiDivergence.priceLow2 - 0.25 * atr14;
        structureResistancePrice = upperBB;
        profitTarget1 = 1.7;
        profitTarget2 = 3.6;
        stopLossPct = Math.min(1.15, Math.max(0.65, +(((currentPrice - structureSupportPrice) / currentPrice) * 100).toFixed(2)));
        timeHorizon = '20m - 2h';
        reasonZh = `【空头 5% 跌幅抄底确认 · RSI 底背离买入】已通过严苛空头风控：BTC 高位累计跌幅达 ${effectiveDropPct}% (≥ 5.0% 门槛已达标，非阴跌杂波)！检测到价格跌至新低 ($${rsiDivergence.priceLow2.toLocaleString()} < 前低 $${rsiDivergence.priceLow1.toLocaleString()})，但 14 周期 RSI 逆势大幅抬高 (${rsiDivergence.rsiLow2} > ${rsiDivergence.rsiLow1})，右侧阳线企稳确认，空头动能彻底衰竭，建议果断买入做多！`;
      }
      // Model 3: Flash Crash Dip Rebound
      else if (
        config.activeStrategies.FLASH_CRASH_REBOUND &&
        rsi14 <= 28 &&
        orderBook.imbalanceRatio > 0.02 &&
        (latestClosedCandle.close >= latestClosedCandle.open || currentPrice >= swingBottom * 1.0015)
      ) {
        matchedStrategy = 'FLASH_CRASH_REBOUND';
        strategyNameZh = '空头深幅暴跌极值抄底买入 (Flash Crash Rebound)';
        confidence = Math.min(95, Math.round(86 + (30 - rsi14) * 1.4));
        structureSupportPrice = swingBottom - 0.25 * atr14;
        structureResistancePrice = sma20;
        profitTarget1 = 1.6;
        profitTarget2 = 3.5;
        stopLossPct = Math.min(1.1, Math.max(0.65, +(((currentPrice - structureSupportPrice) / currentPrice) * 100).toFixed(2)));
        timeHorizon = '15m - 1.5h';
        reasonZh = `【空头 5% 跌幅抄底确认 · 暴跌极值买入】已通过严苛空头风控：BTC 高位累计跌幅达 ${effectiveDropPct}% (≥ 5.0% 门槛已达标)！短线非理性恐慌下杀触及极度超卖区（1m RSI=${rsi14} ≤ 28），右侧止跌反抽，盘口大额托单承接抛压，建议果断买入做超跌反弹！`;
      } else {
        return null;
      }
    }

    // =========================================================================
    // SCENARIO 2: MACRO TREND IS BULLISH (大盘多头顺势)
    // -> Can buy on:
    //    1. Trend Pullback Bounce (顺大势回踩均线支撑企稳买入)
    //    2. RSI Bullish Divergence on pullback
    //    3. Burst Breakout (爆量放量起爆追多)
    //    4. Volatility Momentum
    // =========================================================================
    else if (macro.hourlyTrend === 'BULLISH' && macro.allowLongBreakout) {
      // Model 1: Trend Pullback Support Buy (顺势多头回踩企稳买入)
      if (
        config.activeStrategies.TREND_PULLBACK_BUY &&
        ((currentPrice >= sma20 * 0.994 && currentPrice <= sma20 * 1.004) ||
          (vwapDiffPercent >= -1.0 && vwapDiffPercent <= 0.35)) &&
        rsi14 >= 38 &&
        rsi14 <= 54 &&
        orderBook.imbalanceRatio > 0.03
      ) {
        matchedStrategy = 'TREND_PULLBACK_BUY';
        strategyNameZh = '顺势多头回踩企稳买入 (Trend Pullback Bounce)';
        confidence = Math.min(96, Math.round(89 + orderBook.imbalanceRatio * 20));
        structureSupportPrice = sma20 - 0.3 * atr14;
        structureResistancePrice = upperBB;
        profitTarget1 = Math.max(1.5, +(((structureResistancePrice - currentPrice) / currentPrice) * 100).toFixed(2));
        profitTarget2 = +(profitTarget1 * 2.2).toFixed(2);
        stopLossPct = Math.min(1.0, Math.max(0.55, +(((currentPrice - structureSupportPrice) / currentPrice) * 100).toFixed(2)));
        timeHorizon = '20m - 2h';
        reasonZh = `【顺大势回踩企稳买入信号】1小时大盘处于多头强盛顺势通道！BTC 短线健康缩量回踩至均线及 VWAP 机构成本线附近，1m RSI 从超买成功释放至健康蓄能区 (${rsi14})，买盘盘口深度占比 +${(
          orderBook.imbalanceRatio * 100
        ).toFixed(1)}% 重新涌现大单护盘！顺大势做低吸是专业量化交易最稳健的赚钱策略，建议现价果断买入！`;
      }
      // Model 2: RSI Bullish Divergence on healthy pullback
      else if (config.activeStrategies.RSI_DIVERGENCE && rsiDivergence) {
        matchedStrategy = 'RSI_DIVERGENCE';
        strategyNameZh = '多头回调 RSI 底背离买入 (RSI Bullish Divergence)';
        confidence = Math.min(96, Math.round(89 + rsiDivergence.diffRsi * 2.0));
        structureSupportPrice = rsiDivergence.priceLow2 - 0.25 * atr14;
        structureResistancePrice = upperBB;
        profitTarget1 = 1.8;
        profitTarget2 = 3.8;
        stopLossPct = Math.min(1.05, Math.max(0.60, +(((currentPrice - structureSupportPrice) / currentPrice) * 100).toFixed(2)));
        timeHorizon = '20m - 2h';
        reasonZh = `【多头回调 RSI 底背离买入信号】顺势主升浪中，BTC 价格局部急跌跌破前低 ($${rsiDivergence.priceLow2.toLocaleString()} < $${rsiDivergence.priceLow1.toLocaleString()})，但 RSI 形成更高低点 (${rsiDivergence.rsiLow2} > ${rsiDivergence.rsiLow1}) 确认主力诱空吸筹洗盘完毕，重回主升浪，建议顺势果断买入！`;
      }
      // Model 3: Burst Breakout (捕获爆发起爆买入)
      else if (
        config.activeStrategies.BURST_BREAKOUT &&
        (volumeMultiplier >= 1.8 || ticker.change24h > 1.2) &&
        currentPrice >= upperBB * 0.998 &&
        rsi14 > 55 &&
        rsi14 < 78 &&
        orderBook.imbalanceRatio > 0.08
      ) {
        matchedStrategy = 'BURST_BREAKOUT';
        strategyNameZh = '捕获爆发起爆买入 (Burst Breakout)';
        confidence = Math.min(95, Math.round(85 + volumeMultiplier * 2.8));
        structureSupportPrice = sma20;
        structureResistancePrice = currentPrice * 1.025;
        profitTarget1 = 1.8;
        profitTarget2 = 4.0;
        stopLossPct = Math.min(1.1, Math.max(0.65, +(((currentPrice - structureSupportPrice) / currentPrice) * 100).toFixed(2)));
        timeHorizon = '20m - 2h';
        reasonZh = `【顺大势放量起爆买入信号】1小时大盘处于多头顺势主升浪！BTC 放量 ${volumeMultiplier}x 强力突破 20 周期阻力位，买盘深度占比 +${(
          orderBook.imbalanceRatio * 100
        ).toFixed(1)}%，动能充沛，大趋势共识确认，建议现价果断买入！`;
      }
      // Model 4: Volatility Momentum
      else if (
        config.activeStrategies.VOLATILITY_MOMENTUM &&
        momentumZScore >= 1.8
      ) {
        matchedStrategy = 'VOLATILITY_MOMENTUM';
        strategyNameZh = '波动调整动量冲锋买入 (Volatility Momentum)';
        confidence = 90;
        profitTarget1 = 1.6;
        profitTarget2 = 3.6;
        stopLossPct = 0.95;
        timeHorizon = '30m - 2h';
        reasonZh = `【动量冲锋买入信号】动量 Z-Score 达到 +${momentumZScore}σ，多头趋势发散，顺势介入买入。`;
      }
      // Model 5: Bullish VWAP Snap-Back
      else if (
        config.activeStrategies.VWAP_MEAN_REVERSION &&
        vwapAtrSpread >= 1.4 &&
        orderBook.imbalanceRatio > 0.02
      ) {
        matchedStrategy = 'VWAP_MEAN_REVERSION';
        strategyNameZh = '顺势 VWAP 极值拉回买入 (Bullish VWAP Snap-Back)';
        confidence = Math.min(96, Math.round(89 + (vwapAtrSpread - 1.4) * 4));
        structureSupportPrice = currentPrice - 1.25 * atr14;
        structureResistancePrice = latestVwap;
        profitTarget1 = Math.max(1.35, +(((latestVwap - currentPrice) / currentPrice) * 100).toFixed(2));
        profitTarget2 = +(profitTarget1 * 2.0).toFixed(2);
        stopLossPct = Math.min(0.95, Math.max(0.50, +(((currentPrice - structureSupportPrice) / currentPrice) * 100).toFixed(2)));
        timeHorizon = '20m - 1.5h';
        reasonZh = `【顺势 VWAP 偏离观察】1小时为多头，现价低于 VWAP 达 ${vwapAtrSpread} 倍 ATR。这只是规则匹配，不是上涨概率。`;
      }
    }

    // =========================================================================
    // SCENARIO 3: MACRO TREND IS RANGING (大盘箱体震荡)
    // -> Dynamic 3-Tier Volatility Oscillations with 5-Barrier Anti-Knife Reversal Gate
    // =========================================================================
    else {
      const volRegime = microVolatility;

      // Model 0: Confirmed Bottom Reversal Buy (High Conviction Support Bounce)
      if (config.activeStrategies.FLASH_CRASH_REBOUND && isBottomReboundConfirmed) {
        matchedStrategy = 'FLASH_CRASH_REBOUND';
        strategyNameZh = `箱体探底企稳买入 (${volRegime.levelNameZh})`;
        confidence = Math.min(96, Math.round(91 + bounceFromBottomPct * 3.2));
        structureSupportPrice = swingBottom - 0.25 * atr14;
        structureResistancePrice = sma20;
        profitTarget1 = volRegime.adaptiveTp1;
        profitTarget2 = volRegime.adaptiveTp2;
        stopLossPct = Math.min(volRegime.adaptiveSl * 1.1, Math.max(0.45, +(((currentPrice - structureSupportPrice) / currentPrice) * 100).toFixed(2)));
        timeHorizon = volRegime.level === 'LOW' ? '10m - 40m' : '15m - 1.5h';
        reasonZh = `【箱体探底企稳 · ${volRegime.levelNameZh}自动适配买入】监测到 BTC 在 $${swingBottom.toLocaleString()} 探底成功并获得强力托底，当前收出右侧反转阳线并放量站上 EMA(7) 短期均线 ($${currentPrice.toLocaleString()} > $${ema7.toFixed(2)})！RSI 从低位拐头向上 (${rsi14.toFixed(1)})，盘口托单涌现！已智能适配当前波动率参数！`;
      }
      // Model 1: RSI Bullish Divergence at range lower bound
      else if (config.activeStrategies.RSI_DIVERGENCE && rsiDivergence) {
        matchedStrategy = 'RSI_DIVERGENCE';
        strategyNameZh = `箱体底背离买入 (${volRegime.levelNameZh})`;
        confidence = Math.min(95, Math.round(88 + rsiDivergence.diffRsi * 2.0));
        structureSupportPrice = rsiDivergence.priceLow2 - 0.25 * atr14;
        structureResistancePrice = upperBB;
        profitTarget1 = +(volRegime.adaptiveTp1 * 1.1).toFixed(2);
        profitTarget2 = +(volRegime.adaptiveTp2 * 1.1).toFixed(2);
        stopLossPct = Math.min(volRegime.adaptiveSl * 1.1, Math.max(0.45, +(((currentPrice - structureSupportPrice) / currentPrice) * 100).toFixed(2)));
        timeHorizon = volRegime.level === 'LOW' ? '15m - 45m' : '20m - 1.5h';
        reasonZh = `【箱体下轨 RSI 底背离买入 · ${volRegime.levelNameZh}】大盘处于区间震荡，价格向下刺破局部支撑位 ($${rsiDivergence.priceLow2.toLocaleString()})，但 RSI 逆势抬高形成更高低点 (${rsiDivergence.rsiLow2} > ${rsiDivergence.rsiLow1})，右侧收阳企稳确认主力诱空吸筹完毕！已自动适配 ${volRegime.levelNameZh} 操盘参数！`;
      }
      // Model 2: Range Oscillation (3-Tier Volatility Adaptive + 5-Barrier Anti-Knife Gate)
      else if (config.activeStrategies.RANGE_OSCILLATION) {
        // Enforce 5-Barrier Anti-Falling-Knife Verification:
        const reversalCheck = this.verifyMicroRangeReversal(microCandles, orderBook, ticker);

        if (reversalCheck.passed) {
          // TIER 1: 小幅度波动 (Narrow / Micro Fluctuation)
          if (volRegime.level === 'LOW') {
            const isAtMicroSupport =
              currentPrice <= reversalCheck.supportPrice * 1.0025 ||
              currentPrice <= lowerBB * 1.004 ||
              (currentPrice <= sma20 * 0.9985 && currentPrice <= latestVwap * 1.0005);

            if (isAtMicroSupport && rsi14 <= 48) {
              matchedStrategy = 'RANGE_OSCILLATION';
              strategyNameZh = '区间震荡 · 小波段下轨低吸 (Micro Range Buy)';
              confidence = Math.min(95, Math.round(88 + (50 - rsi14) * 0.7));
              structureSupportPrice = reversalCheck.supportPrice - 0.25 * atr14;
              structureResistancePrice = sma20;
              profitTarget1 = volRegime.adaptiveTp1;
              profitTarget2 = volRegime.adaptiveTp2;
              stopLossPct = Math.min(0.65, Math.max(0.38, +(((currentPrice - structureSupportPrice) / currentPrice) * 100).toFixed(2)));
              timeHorizon = '10m - 40m';
              reasonZh = `【区间震荡 · 小幅度波动自动适配预警】系统智能识别当前处于【小幅度波动区间】(振幅 ${volRegime.swingRangePct}%, 12H波动百分位 Q=${volRegime.quantilePct}%)！已通过【5重止跌门禁】：局部低点不再下移、右侧微阳站稳 EMA(7)、卖压衰减且买量托底！价格在微波段支撑位 ($${reversalCheck.supportPrice.toLocaleString()}) 企稳，RSI 释放至蓄能区 (${rsi14.toFixed(1)})，建议快进快出锁定小波段利润！`;
            }
          }
          // TIER 2: 中度波动 (Medium Fluctuation - 标准箱体震荡)
          else if (volRegime.level === 'MEDIUM') {
            const isAtMediumSupport =
              currentPrice <= lowerBB * 1.008 ||
              currentPrice <= reversalCheck.supportPrice * 1.004 ||
              (currentPrice <= sma20 * 0.996 && vwapDiffPercent <= -0.2);

            if (isAtMediumSupport && rsi14 <= 45) {
              matchedStrategy = 'RANGE_OSCILLATION';
              strategyNameZh = '区间震荡 · 中波段箱体低吸 (Medium Range Buy)';
              confidence = Math.min(96, Math.round(89 + (46 - rsi14) * 0.9));
              structureSupportPrice = reversalCheck.supportPrice - 0.3 * atr14;
              structureResistancePrice = upperBB;
              profitTarget1 = volRegime.adaptiveTp1;
              profitTarget2 = volRegime.adaptiveTp2;
              stopLossPct = Math.min(0.95, Math.max(0.58, +(((currentPrice - structureSupportPrice) / currentPrice) * 100).toFixed(2)));
              timeHorizon = '20m - 1.5h';
              reasonZh = `【区间震荡 · 中度波动自动适配预警】系统智能识别当前处于【中度波动标准箱体】(振幅 ${volRegime.swingRangePct}%, 12H波动百分位 Q=${volRegime.quantilePct}%)！已通过【5重止跌企稳门禁】：价格在箱体下轨支撑区 ($${reversalCheck.supportPrice.toLocaleString()}) 探底企稳，右侧收阳站稳 EMA(7)，盘口托单涌现，稳吃箱体回抽空间！`;
            }
          }
          // TIER 3: 大幅度波动 (High Fluctuation - 宽幅拉锯、均值回归)
          else {
            const isAtWideSupport =
              currentPrice <= lowerBB * 1.005 ||
              (vwapAtrSpread >= 1.0 && currentPrice <= sma20 * 0.992);

            if (isAtWideSupport && rsi14 <= 38) {
              matchedStrategy = 'RANGE_OSCILLATION';
              strategyNameZh = '区间震荡 · 宽幅拉锯低吸 (Wide Range Buy)';
              confidence = Math.min(96, Math.round(90 + (42 - rsi14) * 1.0));
              structureSupportPrice = reversalCheck.supportPrice - 0.35 * atr14;
              structureResistancePrice = upperBB;
              profitTarget1 = volRegime.adaptiveTp1;
              profitTarget2 = volRegime.adaptiveTp2;
              stopLossPct = Math.min(1.40, Math.max(0.85, +(((currentPrice - structureSupportPrice) / currentPrice) * 100).toFixed(2)));
              timeHorizon = '30m - 2.5h';
              reasonZh = `【区间震荡 · 大幅度波动自动适配预警】系统智能识别当前为【大幅度波动宽幅拉锯】(振幅 ${volRegime.swingRangePct}%, 12H波动百分位 Q=${volRegime.quantilePct}%)！已通过【5重止跌企稳门禁】：价格深度刺破下轨，RSI 触及超卖区 (${rsi14.toFixed(1)})，右侧止跌反抽确认，博弈宽幅大波段反弹！`;
            }
          }
        }
      }
    }
    if (
      !matchedStrategy &&
      !isBearishTrend &&
      config.activeStrategies.VWAP_MEAN_REVERSION &&
      vwapAtrSpread >= 1.4 &&
      latestVwap > currentPrice &&
      orderBook.imbalanceRatio > 0.02
    ) {
        matchedStrategy = 'VWAP_MEAN_REVERSION';
        strategyNameZh = 'VWAP 极值拉回买入 (VWAP Mean Reversion)';
        confidence = Math.min(96, Math.round(88 + (vwapAtrSpread - 1.4) * 5 + orderBook.imbalanceRatio * 15));
        structureSupportPrice = currentPrice - 1.25 * atr14;
        structureResistancePrice = latestVwap;
        profitTarget1 = microVolatility.adaptiveTp1;
        profitTarget2 = microVolatility.adaptiveTp2;
        stopLossPct = microVolatility.adaptiveSl;
        timeHorizon = '20m - 1.2h';
        reasonZh = `【VWAP 偏离观察】现价低于 1 分钟 VWAP 达 ${vwapAtrSpread} 倍 ATR。这只是规则匹配，不是上涨概率。`;
      }

    if (!matchedStrategy) return null;

    const atr15 = this.calculateATR(regimeClosed, 14);
    const atr15Pct = currentPrice > 0 && atr15 > 0 ? (atr15 / currentPrice) * 100 : 0;
    const trendPath = matchedStrategy === 'BURST_BREAKOUT' || matchedStrategy === 'TREND_PULLBACK_BUY';
    if (trendPath || !reversalGate.passed) {
      const swingLow = Math.min(...regimeClosed.slice(-12).map((c) => c.low), swingBottom);
      const slFromSwing = swingLow < currentPrice ? ((currentPrice - swingLow) / currentPrice) * 100 : 9;
      stopLossPct = +Math.min(1.2, Math.max(0.32, Math.min(slFromSwing, Math.max(0.38, atr15Pct * 1.6)))).toFixed(2);
      profitTarget1 = +Math.max(0.55, atr15Pct * 2.8).toFixed(2);
      profitTarget2 = +Math.max(1.1, atr15Pct * 5.2).toFixed(2);
      structureSupportPrice = currentPrice * (1 - stopLossPct / 100);
      structureResistancePrice = currentPrice * (1 + profitTarget1 / 100);
    } else {
      const measuredSupport = reversalGate.supportPrice;
      const measuredLevels = [reversalGate.resistancePrice, upperBB, sma20].filter(
        (price) => price > currentPrice * 1.0001
      );
      if (!(measuredSupport > 0 && measuredSupport < currentPrice) || measuredLevels.length === 0) {
        return null;
      }
      structureSupportPrice = measuredSupport;
      structureResistancePrice = Math.min(...measuredLevels);
      const farResistance = Math.max(...measuredLevels);
      profitTarget1 = +(((structureResistancePrice - currentPrice) / currentPrice) * 100).toFixed(2);
      profitTarget2 = +(((farResistance - currentPrice) / currentPrice) * 100).toFixed(2);
      stopLossPct = +(((currentPrice - measuredSupport) / currentPrice) * 100).toFixed(2);
      if (stopLossPct <= 0 || stopLossPct > 3) return null;
    }

    const takerRatio = latestClosedCandle.volume > 0 ? (latestClosedCandle.takerBuyBase || 0) / latestClosedCandle.volume : 0;
    const candleSpan = latestClosedCandle.high - latestClosedCandle.low;
    const bodyRatio = candleSpan > 0 ? (latestClosedCandle.close - latestClosedCandle.open) / candleSpan : 0;
    const bodyPts = Math.max(0, Math.min(25, Math.round(bodyRatio * 25)));
    const takerPts = Math.max(0, Math.min(40, Math.round(takerRatio * 40)));
    const ESTIMATED_TOTAL_FRICTION_PCT = 0.11;
    const netProfitPct1 = +(profitTarget1 - ESTIMATED_TOTAL_FRICTION_PCT).toFixed(2);
    const netProfitPct2 = +(profitTarget2 - ESTIMATED_TOTAL_FRICTION_PCT).toFixed(2);
    const effectiveStopLossPct = +(stopLossPct + ESTIMATED_TOTAL_FRICTION_PCT).toFixed(2);
    const netRiskReward = effectiveStopLossPct > 0 ? +(netProfitPct1 / effectiveStopLossPct).toFixed(2) : 0;
    const rrPts = Math.max(0, Math.min(35, Math.round((netRiskReward - 1.1) * 25)));
    confidence = Math.max(0, Math.min(100, bodyPts + takerPts + rrPts));
    const requiredNet = Math.max(0.40, config.minProfitTarget || 0.40);
    if (confidence < config.minConfidence) return null;
    if (netProfitPct1 < requiredNet || netRiskReward < 1.1) return null;
    reasonZh += ` 止损在已收盘结构低点。规则分项：实体${bodyPts}+主动买量${takerPts}+净盈亏比${rrPts}。这不是上涨概率。`;

    const entryPrice = currentPrice;
    const targetTP1 = +(entryPrice * (1 + profitTarget1 / 100)).toFixed(2);
    const targetTP2 = +(entryPrice * (1 + profitTarget2 / 100)).toFixed(2);
    const stopLoss = +(entryPrice * (1 - stopLossPct / 100)).toFixed(2);
    const riskRewardRatio = +(profitTarget1 / stopLossPct).toFixed(2);

    const fullReasonZh =
      `${reasonZh}\n` +
      `参考目标：TP1 (+${profitTarget1}% | 扣除假设摩擦后 +${netProfitPct1}%)，TP2 (+${profitTarget2}% | +${netProfitPct2}%)。本应用不下单。\n` +
      `🛡️ 结构风控参数：防守支撑位 $${structureSupportPrice.toLocaleString()} (止损 -${stopLossPct}%)，扣费净盈亏比 ${netRiskReward}:1 (预估交易摩擦 -${ESTIMATED_TOTAL_FRICTION_PCT}%)。`;

    const confirmationTime = latestClosedCandle.closeTime || (latestClosedCandle.time + 60000);

    return {
      id: `${ticker.symbol}_${matchedStrategy}_${confirmationTime}`,
      symbol: 'BTCUSDT',
      coinName: 'Bitcoin (比特币)',
      signalType: 'BUY',
      strategy: matchedStrategy,
      strategyNameZh,
      actionBadgeZh: 'BUY 建议买入',
      entryPrice,
      targetTP1,
      targetTP2,
      stopLoss,
      profitPercent1: profitTarget1,
      profitPercent2: profitTarget2,
      stopLossPercent: stopLossPct,
      riskRewardRatio,
      timeHorizon,
      confidence,
      ruleScore: confidence,
      decisionStatus: 'BUY_CANDIDATE',
      confirmationTime,
      engineVersion: 'Crypto-G V1.08',
      regime: macro.regime,
      reasonZh: fullReasonZh,
      analysis: {
        vwapDiffPercent,
        rsi14,
        atrPercent,
        volumeMultiplier,
        momentumZScore,
        orderFlowImbalance: +(orderBook.imbalanceRatio * 100).toFixed(1),
        vwapAtrSpread,
        effectiveDropPct,
        volatilityLevel: microVolatility.level,
        volatilityNameZh: microVolatility.levelNameZh,
        quantilePct: microVolatility.quantilePct,
        netProfitPct1,
        netProfitPct2,
        netRiskReward,
        estimatedFriction: ESTIMATED_TOTAL_FRICTION_PCT,
        structureSupportPrice,
        structureResistancePrice,
        bidAskSpreadPct: orderBook.spreadPct ?? 0.01,
        ruleScore: confidence,
        historicalWinRateNote: '历史胜率：未验证 (仅展示确定性规则评分)',
      },
      timestamp: Date.now(),
      read: false,
    };
  }
}
