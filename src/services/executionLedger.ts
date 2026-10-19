/** User-reported spot fills; no exchange authentication or order execution. */
export interface ExecutionFill {
  fillId: string;
  positionId: string;
  side: 'BUY' | 'SELL';
  price: number;
  quantity: number; // Exchange gross executed BTC quantity, before commission.
  executedAtMs: number;
  commission: number | null; // null = unknown; explicit 0 = fee-free.
  commissionAsset: string;
  commissionAssetUsdtRate: number | null; // contemporaneous conversion, not today's BNB price
  referencePrice: number | null; // contemporaneous decision ask (buy) / bid (sell)
  referenceAtMs: number | null;
  timeApproximate: boolean;
  source: 'MANUAL';
  exchangeTradeId?: string | null;
}

export function validateFill(fill: ExecutionFill, now = Date.now()): string | null {
  if (!fill || fill.source !== 'MANUAL' || !['BUY', 'SELL'].includes(fill.side)) return '成交方向或来源无效';
  if (![fill.fillId, fill.positionId].every(id => typeof id === 'string' && /^[a-zA-Z0-9_.-]{1,160}$/.test(id))) return '成交或持仓编号无效';
  if (![fill.price, fill.quantity, fill.executedAtMs].every(n => Number.isFinite(n) && n > 0) || fill.executedAtMs > now + 5000) return '请填写有效成交价、数量和非未来成交时间';
  if (!(fill.price * fill.quantity > 0 && fill.price * fill.quantity <= 1e15)) return '成交金额超出记录范围';
  if (typeof fill.timeApproximate !== 'boolean') return '需标明时间是否近似';
  if (fill.exchangeTradeId && !/^\d{1,40}$/.test(fill.exchangeTradeId)) return '币安成交编号应为数字';
  if (fill.commission !== null && (!Number.isFinite(fill.commission) || fill.commission < 0)) return '手续费未知请留空，已知请填非负数';
  if (!/^[A-Z0-9]{1,12}$/.test(fill.commissionAsset)) return '手续费币种无效';
  if (fill.commissionAsset === 'BTC' && fill.commission !== null && fill.commission >= fill.quantity) return 'BTC 手续费不能大于成交数量';
  if (fill.commissionAssetUsdtRate !== null && !(Number.isFinite(fill.commissionAssetUsdtRate) && fill.commissionAssetUsdtRate > 0)) return '折算汇率无效';
  const feeRate = fill.commissionAsset === 'BTC' ? fill.price : fill.commissionAsset === 'USDT' ? 1 : fill.commissionAssetUsdtRate;
  if (fill.commission !== null && feeRate !== null && !(fill.commission * feeRate <= 1e15)) return '手续费折算金额超出记录范围';
  if ((fill.referencePrice === null) !== (fill.referenceAtMs === null)) return '滑点基准价和基准时间必须同时填写';
  if (fill.referencePrice !== null && (!(Number.isFinite(fill.referencePrice) && fill.referencePrice > 0) || !Number.isFinite(fill.referenceAtMs) || fill.referenceAtMs! <= 0 || fill.referenceAtMs! > fill.executedAtMs)) return '滑点基准必须是成交之前的有效报价';
  return null;
}

export function summarizeFills(fills: ExecutionFill[]) {
  let inventory = 0, cost = 0, realized = 0, fees = 0, feesKnown = true, bought = 0, sold = 0, invested = 0;
  const seen = new Set<string>();
  const exchangeIds = new Set<string>();
  const slippage: {fillId: string; quoteDifferenceUsdt: number | null; benchmarkAgeMs: number | null}[] = [];
  let positionId: string | undefined;
  for (const f of [...fills].sort((a, b) => a.executedAtMs - b.executedAtMs || a.fillId.localeCompare(b.fillId))) {
    const issue = validateFill(f); if (issue) throw new Error(issue);
    if (seen.has(f.fillId)) throw new Error('重复成交编号'); seen.add(f.fillId);
    if (f.exchangeTradeId) { if (exchangeIds.has(f.exchangeTradeId)) throw new Error('同一币安成交编号已记录'); exchangeIds.add(f.exchangeTradeId); }
    if (positionId && positionId !== f.positionId) throw new Error('请按独立持仓计算'); positionId = f.positionId;
    const baseFee = f.commissionAsset === 'BTC' ? (f.commission ?? 0) : 0;
    const rate = f.commissionAsset === 'USDT' ? 1 : f.commissionAsset === 'BTC' ? f.price : f.commissionAssetUsdtRate;
    const converted = f.commission === 0 ? 0 : f.commission === null || rate === null ? null : f.commission * rate;
    if (converted === null) feesKnown = false; else fees += converted;
    // BTC commission changes inventory; do not also subtract its USDT value.
    const cashFee = f.commissionAsset === 'BTC' ? 0 : (converted ?? 0);
    if (f.side === 'BUY') {
      inventory += f.quantity - baseFee; cost += f.price * f.quantity + cashFee; bought += f.quantity; invested += f.price * f.quantity + cashFee;
    } else {
      const consumed = f.quantity + baseFee;
      if (consumed > inventory + 1e-10 || inventory <= 0) throw new Error('卖出数量（含 BTC 手续费）超过已记录持仓，请先补齐买入');
      const allocated = cost * Math.min(consumed, inventory) / inventory;
      realized += f.quantity * f.price - cashFee - allocated;
      inventory = Math.max(0, inventory - consumed); cost -= allocated; sold += f.quantity;
    }
    slippage.push({fillId: f.fillId,
      quoteDifferenceUsdt: f.referencePrice === null ? null : (f.side === 'BUY' ? f.price - f.referencePrice : f.referencePrice - f.price) * f.quantity,
      benchmarkAgeMs: f.referenceAtMs === null ? null : f.executedAtMs - f.referenceAtMs});
  }
  return {investedUsdt: feesKnown ? invested : null,
    wholeTradeNetPct: feesKnown && invested > 0 && inventory < 1e-10 ? realized / invested * 100 : null,
    accountingVersion: 'actual-cashflow-v2.1', inventory: feesKnown ? inventory : null, inventoryBeforeUnknownFees: inventory, remainingCostUsdt: feesKnown ? cost : null,
    realizedNetUsdt: feesKnown ? realized : null, feeUsdt: feesKnown ? fees : null, feesKnown, bought, sold,
    closed: feesKnown && bought > 0 && inventory < 1e-10, slippage, source: 'MANUAL_UNVERIFIED' as const};
}

export function latencyMetrics(signalAt?: number, receivedAt?: number, openedAt?: number, entryAt?: number) {
  const delta = (end?: number, start?: number) => end && start && end >= start ? end - start : null;
  return {signalToEntryMs: delta(entryAt, signalAt), receivedToEntryMs: delta(entryAt, receivedAt), openedToEntryMs: delta(entryAt, openedAt)};
}
