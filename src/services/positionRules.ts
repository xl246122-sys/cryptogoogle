import type { WatchlistItem } from '../types/crypto';

/** Advisory only. Never marks a position closed or claims a Binance fill. */
export function positionRuleNotice(item: WatchlistItem, freshPrice: number | null, now = Date.now()): string | null {
  if (!(item.positionEntryPrice && item.positionEntryPrice > 0) || !item.linkedTradeRules) return null;
  if (item.positionDeadlineMs && now >= item.positionDeadlineMs) return '已到该模型最长持有时间：按规则应退出剩余仓位，请核对实际成交并记录；系统未自动卖出。';
  if (!freshPrice || !Number.isFinite(freshPrice)) return '等待新鲜行情核对价格退出条件；时间上限仍然有效。';
  if (item.linkedSl && freshPrice <= item.linkedSl) return '已触及结构止损：按规则退出剩余仓位；这里只是提醒，未自动卖出。';
  if (freshPrice <= item.linkedTradeRules.invalidationPrice) return '已触及模型失效位：按规则退出剩余仓位；这里只是提醒，未自动卖出。';
  if (item.linkedTp2 && freshPrice >= item.linkedTp2) return '价格已达到 TP2：按规则退出剩余仓位，请核对实际成交。';
  if (item.linkedTp1 && freshPrice >= item.linkedTp1) return `价格已达到 TP1：计划退出初始仓位的 ${Math.round(item.linkedTradeRules.tp1Fraction * 100)}%，请核对是否已经执行，避免重复减仓。`;
  return '尚未触及价格退出条件，按原止损和时间上限观察。';
}
