import { ExecutionLedgerPanel } from './ExecutionLedgerPanel';
import { fetchEntryQuote } from '../services/signalValidity';
import React, { useState, useEffect, useRef } from 'react';
import { MarketTicker, WatchlistItem, ClosedPositionRecord } from '../types/crypto';
import { positionRuleNotice } from '../services/positionRules';
import {
  fetchTrackStatus,
  LibraryTrackStatus,
  recordStillHolding,
  recordUserClose,
  recordSimBuy,
} from '../services/modelLibrary';
import {
  TrendingUp,
  TrendingDown,
  DollarSign,
  Receipt,
  X,
  History,
  Trash2,
  Sparkles,
  Target,
  ShieldAlert,
  ArrowRight,
  Scale,
  RefreshCw,
  Coins,
} from 'lucide-react';

interface BtcPositionDashboardProps {
  btcTicker?: MarketTicker;
  btcWatchlistItem?: WatchlistItem;
  onUpdateWatchlist: (item: WatchlistItem) => void;
}

const STORAGE_KEY = 'shotcrypto_btc_realized_trades';

export const BtcPositionDashboard: React.FC<BtcPositionDashboardProps> = ({
  btcTicker,
  btcWatchlistItem,
  onUpdateWatchlist,
}) => {
  const livePrice = btcTicker?.price || 0;
  const priceChange24h = btcTicker?.change24h || 0;

  // Active Position Parameters
  const entryPrice = btcWatchlistItem?.positionEntryPrice || 0;
  const positionSize = btcWatchlistItem?.positionSize || 5000;
  const openedAt = btcWatchlistItem?.addedAt || Date.now();
  const [ruleClock, setRuleClock] = useState(Date.now());
  useEffect(() => {
    const timer = window.setInterval(() => setRuleClock(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);
  const freshPrice = btcTicker && ruleClock - btcTicker.lastUpdate <= 10000 ? livePrice : null;
  const ruleNotice = btcWatchlistItem ? positionRuleNotice(btcWatchlistItem, freshPrice, ruleClock) : null;

  // Closed Trades History & Realized PnL State
  const [closedTrades, setClosedTrades] = useState<ClosedPositionRecord[]>(() => {
    try {
      const saved = localStorage.getItem(STORAGE_KEY);
      if (saved) {
        const parsed = JSON.parse(saved);
        if (Array.isArray(parsed)) {
          return parsed.filter((row) => row?.id !== 'trade-init-btc-1');
        }
      }
    } catch {
      // Fallback
    }
    return [];
  });

  const [showCloseModal, setShowCloseModal] = useState(false);
  const closing = useRef(false);
  const [trackStatus, setTrackStatus] = useState<LibraryTrackStatus | null>(null);
  const [holdAck, setHoldAck] = useState(0);
  const linkedAlertId = btcWatchlistItem?.linkedAlertId || '';
  const [showHistory, setShowHistory] = useState(false);
  const [isEditingEntry, setIsEditingEntry] = useState(false);
  const [tempEntryInput, setTempEntryInput] = useState(entryPrice > 0 ? entryPrice.toString() : '');
  const [tempSizeInput, setTempSizeInput] = useState(positionSize.toString());

  // Save trades to localStorage whenever updated
  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(closedTrades));
    } catch {
      // storage unavailable
    }
  }, [closedTrades]);

  useEffect(() => {
    if (!linkedAlertId || !(entryPrice > 0)) {
      setTrackStatus(null);
      return;
    }
    let cancelled = false;
    const pull = () => {
      fetchTrackStatus(linkedAlertId).then((status) => {
        if (!cancelled) setTrackStatus(status);
      });
    };
    pull();
    const timer = window.setInterval(pull, 20000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [linkedAlertId, entryPrice]);

  // Sync temp input if prop changes
  useEffect(() => {
    if (!isEditingEntry) {
      setTempEntryInput(entryPrice > 0 ? entryPrice.toFixed(2) : '');
      setTempSizeInput(positionSize.toString());
    }
  }, [entryPrice, positionSize, isEditingEntry]);

  // Calculations for Active Position
  const hasActivePosition = entryPrice > 0 && livePrice > 0;
  const btcQuantity = entryPrice > 0 ? positionSize / entryPrice : 0;
  const priceDiff = livePrice - entryPrice;
  const priceDiffPercent = entryPrice > 0 ? (priceDiff / entryPrice) * 100 : 0;
  const floatingGrossPnl = entryPrice > 0 ? (positionSize * priceDiffPercent) / 100 : 0;
  const estimatedTotalFee = (positionSize + btcQuantity * livePrice) * 0.00055; // Explicit simulated cost assumption on each leg.
  const floatingNetPnl = floatingGrossPnl - estimatedTotalFee;
  const isPnlPositive = floatingNetPnl >= 0;

  // Realized Metrics Aggregate Calculation
  const totalRealizedNetPnl = closedTrades.filter(t => t.accountingSource === 'SIMULATED').reduce((acc, t) => acc + (t.netPnl || 0), 0);
  const knownSimulations = closedTrades.filter(t=>t.accountingSource==='SIMULATED');
  const winningTrades = knownSimulations.filter(t=>t.outcome==='WIN');
  const winRate = knownSimulations.length ? Math.round(winningTrades.length/knownSimulations.length*100) : null;

  const handleSaveActivePosition = (e: React.FormEvent) => {
    e.preventDefault();
    const parsedEntry = parseFloat(tempEntryInput);
    const parsedSize = parseFloat(tempSizeInput);
    if (!Number.isFinite(parsedSize) || parsedSize <= 0 || !Number.isFinite(parsedEntry) || parsedEntry <= 0) return;
    if (entryPrice > 0) { window.alert('已有模拟持仓，请先记录退出；实际成交的更正请使用上方账本，避免覆盖原机会'); return; }
    const started = Date.now();
    const manualId = `manual-simulation-${started}`;
    try { recordSimBuy({alertId: manualId, entryPrice: parsedEntry, positionSize: parsedSize}); }
    catch { window.alert('记录保存失败，未创建模拟持仓'); return; }

    onUpdateWatchlist({
      ...(btcWatchlistItem || { symbol: 'BTCUSDT', name: 'Bitcoin (比特币)', addedAt: Date.now() }),
      symbol: 'BTCUSDT',
      name: 'Bitcoin (比特币)',
      positionEntryPrice: !isNaN(parsedEntry) && parsedEntry > 0 ? parsedEntry : 0,
      positionSize: parsedSize,
      // A manually replaced entry is no longer the original signal's position.
      ...(parsedEntry !== entryPrice ? {
        linkedAlertId: undefined, linkedTradeRules: undefined, positionDeadlineMs: undefined,
        linkedTp1: undefined, linkedTp2: undefined, linkedSl: undefined,
      } : {}),
      addedAt: started,
      linkedAlertId: manualId,
    });
    setIsEditingEntry(false);
  };

  const handleClosePositionConfirm = async (_outcome: 'WIN' | 'LOSS' | 'BREAKEVEN', closeReason: string) => {
    if (!hasActivePosition || closing.current) return;
    closing.current = true;
    const quote = await fetchEntryQuote('SELL');
    if (!quote) { closing.current = false; window.alert('新鲜币安买一报价不可用，未记录模拟退出'); return; }
    const gross = btcQuantity * (quote.price-entryPrice);
    const fee = (positionSize+btcQuantity*quote.price)*0.00055;
    const net = gross-fee;
    try {
      recordUserClose({alertId: linkedAlertId || `manual-${openedAt}`, entryPrice, exitPrice: quote.price, positionSize,
        note: `${closeReason}；模拟买一价退出，两侧各0.055%成本假设，非实际成交`});
    } catch { closing.current = false; window.alert('记录保存失败，持仓未清空'); return; }

    const newRecord: ClosedPositionRecord = {
      id: `trade-btc-${Date.now()}`,
      symbol: 'BTCUSDT',
      name: 'Bitcoin (比特币)',
      entryPrice,
      exitPrice: quote.price,
      positionSize,
      quantity: btcQuantity,
      grossPnl: +gross.toFixed(2),
      pnlPercent: +(100*net/positionSize).toFixed(2),
      feeAmount: +fee.toFixed(2),
      netPnl: +net.toFixed(2),
      accountingSource: 'SIMULATED',
      openedAt,
      closedAt: Date.now(),
      outcome: net > 0 ? 'WIN' : net < 0 ? 'LOSS' : 'BREAKEVEN',
      closeReason,
    };

    setClosedTrades([newRecord, ...closedTrades]);


    // Reset active position. The model library row stays.
    onUpdateWatchlist({
      ...(btcWatchlistItem || { symbol: 'BTCUSDT', name: 'Bitcoin (比特币)', addedAt: Date.now() }),
      positionEntryPrice: 0,
      linkedAlertId: undefined,
      linkedTradeRules: undefined,
      positionDeadlineMs: undefined,
      linkedTp1: undefined, linkedTp2: undefined, linkedSl: undefined,
    });

    setShowCloseModal(false);
    closing.current = false;
  };

  const handleDeleteHistoryTrade = (id: string) => {
    setClosedTrades(closedTrades.filter((t) => t.id !== id));
  };

  const handleClearAllHistory = () => {
    if (window.confirm('只清空手机上的流水显示。服务器分析库里的预警和补记不会删除。')) {
      setClosedTrades([]);
    }
  };

  const stillHoldingKey = linkedAlertId ? `shotcrypto_still_holding_${linkedAlertId}` : '';
  const stillHoldingUntil = stillHoldingKey ? Number(localStorage.getItem(stillHoldingKey) || 0) : 0;
  const showForgotClose = hasActivePosition && Date.now() > stillHoldingUntil && holdAck >= 0;
  const touchHint = trackStatus?.slTouched
    ? '服务器已经看到价格碰到止损。'
    : trackStatus?.tp1Touched
      ? '服务器已经看到价格碰到 TP1。'
      : '若你已经在币安卖掉，请补记卖出价。服务器按预警所属模型的退出规则记录参考路径；旧版预警仍按原观察窗口处理。参考路径不会当成你的成交价。';

  return (
    <div className="space-y-3">
      <ExecutionLedgerPanel alertId={linkedAlertId}/>
      {/* 1. BTC Active Position Tracker Card */}
      <div className="p-3.5 rounded-2xl bg-[#1c2029] border border-[#2b313f] space-y-3 shadow-sm">
        {/* Card Header */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 rounded-xl bg-[#fbbc04]/15 border border-[#fbbc04]/40 flex items-center justify-center text-[#fbbc04] font-bold text-sm">
              ₿
            </div>
            <div>
              <div className="flex items-center gap-1.5">
                <span className="text-sm font-semibold text-white">BTC 模拟持仓追踪</span>
                <span className="text-[9px] px-1.5 py-0.2 rounded-full bg-[#143820] text-[#81c995] font-semibold border border-[#2a6831]/60">
                  BTC/USDT
                </span>
              </div>
              <div className="text-[10px] text-[#9aa0a6] font-mono">
                现价: <strong className="text-white">${livePrice > 0 ? livePrice.toLocaleString() : '连接中...'}</strong>
                <span className={priceChange24h >= 0 ? ' text-[#81c995] ml-1.5' : ' text-[#f28b82] ml-1.5'}>
                  {priceChange24h >= 0 ? '+' : ''}{priceChange24h}%
                </span>
              </div>
            </div>
          </div>

          <button
            type="button"
            onClick={() => setIsEditingEntry(!isEditingEntry)}
            className="text-[11px] font-medium text-[#8ab4f8] hover:text-[#aecbfa] px-2.5 py-1 rounded-full bg-[#1a3258] border border-[#3b6bb0]/50 active:scale-95 transition-all"
          >
            {isEditingEntry ? '取消修改' : hasActivePosition ? '调整仓位' : '录入建仓'}
          </button>
        </div>

        {/* Edit Active Position Form */}
        {isEditingEntry && (
          <form onSubmit={handleSaveActivePosition} className="p-3 rounded-xl bg-[#171a21] border border-[#383e4c] space-y-2.5">
            <div className="grid grid-cols-2 gap-2 text-xs">
              <div>
                <label className="text-[10px] text-[#9aa0a6] block mb-1">开仓入场价 (USD)</label>
                <input
                  type="number"
                  step="0.01"
                  value={tempEntryInput}
                  onChange={(e) => setTempEntryInput(e.target.value)}
                  placeholder={`现价 ${livePrice.toFixed(2)}`}
                  className="w-full px-2.5 py-1.5 bg-[#13161c] border border-[#383e4c] focus:border-[#8ab4f8] rounded-xl text-white font-mono text-xs focus:outline-none"
                />
              </div>
              <div>
                <label className="text-[10px] text-[#9aa0a6] block mb-1">投入本金 (USD)</label>
                <input
                  type="number"
                  step="100"
                  value={tempSizeInput}
                  onChange={(e) => setTempSizeInput(e.target.value)}
                  placeholder="5000"
                  className="w-full px-2.5 py-1.5 bg-[#13161c] border border-[#383e4c] focus:border-[#8ab4f8] rounded-xl text-white font-mono text-xs focus:outline-none"
                />
              </div>
            </div>
            <div className="flex items-center justify-between pt-1">
              <button
                type="button"
                onClick={() => setTempEntryInput(livePrice.toFixed(2))}
                className="text-[11px] text-[#81c995] font-mono hover:underline"
              >
                填入当前市价: ${livePrice.toFixed(2)}
              </button>
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={() => setIsEditingEntry(false)}
                  className="px-3 py-1 rounded-full text-xs text-[#9aa0a6] hover:text-white"
                >
                  取消
                </button>
                <button
                  type="submit"
                  className="px-4 py-1 rounded-full bg-[#1a73e8] hover:bg-[#1557b0] text-white font-medium text-xs shadow-sm active:scale-95 transition-all"
                >
                  保存持仓
                </button>
              </div>
            </div>
          </form>
        )}

        {ruleNotice && <div role="status" className="p-3 rounded-xl border border-[#664d12] text-xs text-[#fdd663] space-y-1">
          <p>{ruleNotice}</p>
          <p>该笔最晚退出时间：{btcWatchlistItem?.positionDeadlineMs ? new Date(btcWatchlistItem.positionDeadlineMs).toLocaleString() : '旧记录未提供'}</p>
          <p>提示基于页面行情；后台自动卖出未启用。</p>
        </div>}
        {trackStatus?.model && <div className="text-xs text-[#9aa0a6]">
          云端参考路径：{trackStatus.pathStatus || '观察中'}（不是用户成交）
          {trackStatus.observationGap ? ' · 存在行情采样缺口' : ''}
        </div>}
        {/* Active Position Details or Empty Guidance */}
        {hasActivePosition ? (
          <div className="space-y-2.5">
            {/* Live Floating PnL Highlight Banner */}
            <div
              className={`p-3 rounded-xl border flex items-center justify-between ${
                isPnlPositive
                  ? 'bg-gradient-to-r from-[#14231a] to-[#172d1f] border-[#2a6831]/70'
                  : 'bg-gradient-to-r from-[#231518] to-[#30161b] border-[#6b252b]/70'
              }`}
            >
              <div>
                <div className="text-[10px] text-[#9aa0a6] flex items-center gap-1 font-mono">
                  <span>模拟浮盈（两侧各0.055%成本假设）</span>
                </div>
                <div className="flex items-baseline gap-2 mt-0.5">
                  <span
                    className={`text-xl font-bold font-mono tracking-tight ${
                      isPnlPositive ? 'text-[#81c995]' : 'text-[#f28b82]'
                    }`}
                  >
                    {isPnlPositive ? '+' : ''}${floatingNetPnl.toFixed(2)}
                  </span>
                  <span
                    className={`text-xs font-mono font-bold px-1.5 py-0.2 rounded-full ${
                      isPnlPositive ? 'bg-[#1e4620] text-[#81c995]' : 'bg-[#441717] text-[#f28b82]'
                    }`}
                  >
                    {isPnlPositive ? '+' : ''}{(positionSize > 0 ? floatingNetPnl/positionSize*100 : 0).toFixed(2)}%
                  </span>
                </div>
              </div>

              <button
                type="button"
                onClick={() => setShowCloseModal(true)}
                className="px-3.5 py-1.5 rounded-full bg-[#1c2029] hover:bg-[#252932] text-white font-medium text-xs border border-[#383e4c] active:scale-95 shadow-sm transition-all"
              >
                记录模拟退出
              </button>
            </div>

            {showForgotClose && (
              <div className="p-2.5 rounded-xl bg-[#1c2029] border border-[#fbbc04]/40 space-y-2">
                <p className="text-[11px] text-[#fdd663] leading-relaxed">{touchHint}</p>
                <div className="flex flex-wrap gap-1.5">
                  <p className="text-[11px] text-[#9aa0a6]">实际成交请在上方账本逐笔补录，不能把目标触达价当作成交价。</p>
                  <button
                    type="button"
                    onClick={() => {
                      if (stillHoldingKey) {
                        localStorage.setItem(stillHoldingKey, String(Date.now() + 2 * 60 * 60 * 1000));
                      }
                      recordStillHolding(linkedAlertId);
                      setHoldAck(Date.now());
                    }}
                    className="px-2.5 py-1 rounded-full bg-transparent text-[#9aa0a6] text-[11px]"
                  >
                    我还在持有
                  </button>
                </div>
              </div>
            )}

            {/* Position Metrics Matrix */}
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-1.5 text-xs font-mono">
              <div className="p-2 rounded-xl bg-[#171a21] border border-[#282d38]">
                <span className="text-[10px] text-[#9aa0a6] block">开仓入场价</span>
                <span className="font-semibold text-white mt-0.5 block">${entryPrice.toLocaleString()}</span>
              </div>
              <div className="p-2 rounded-xl bg-[#171a21] border border-[#282d38]">
                <span className="text-[10px] text-[#9aa0a6] block">投入本金</span>
                <span className="font-semibold text-white mt-0.5 block">${positionSize.toLocaleString()}</span>
              </div>
              <div className="p-2 rounded-xl bg-[#171a21] border border-[#282d38]">
                <span className="text-[10px] text-[#9aa0a6] block">折合持币数量</span>
                <span className="font-semibold text-[#fdd663] mt-0.5 block">{btcQuantity.toFixed(4)} BTC</span>
              </div>
              <div className="p-2 rounded-xl bg-[#171a21] border border-[#282d38]">
                <span className="text-[10px] text-[#9aa0a6] block">预估总摩擦</span>
                <span className="font-semibold text-[#c4c7c5] mt-0.5 block">-${estimatedTotalFee.toFixed(2)}</span>
              </div>
            </div>
          </div>
        ) : (
          <div className="p-4 rounded-xl bg-[#171a21] border border-[#282d38] text-center space-y-2">
            <Coins className="w-6 h-6 text-[#9aa0a6] mx-auto opacity-40" />
            <div className="text-xs font-semibold text-[#e2e2e8]">当前未录入 BTC 持仓</div>
            <p className="text-[11px] text-[#9aa0a6] max-w-sm mx-auto">
              在量化雷达触发买入预警时，点击「记入自选持仓跟踪」，系统将在此实时监控浮动盈亏。
            </p>
          </div>
        )}
      </div>

      {/* 2. Realized PnL Statistics Strip */}
      <div className="grid grid-cols-3 gap-2">
        <div className="p-3 rounded-2xl bg-[#1c2029] border border-[#2b313f] text-center">
          <span className="text-[10px] text-[#9aa0a6] block">模拟净收益（成本假设）</span>
          <span
            className={`text-sm font-bold font-mono mt-0.5 block ${
              totalRealizedNetPnl >= 0 ? 'text-[#81c995]' : 'text-[#f28b82]'
            }`}
          >
            {totalRealizedNetPnl >= 0 ? '+' : ''}${totalRealizedNetPnl.toFixed(2)}
          </span>
        </div>
        <div className="p-3 rounded-2xl bg-[#1c2029] border border-[#2b313f] text-center">
          <span className="text-[10px] text-[#9aa0a6] block">模拟盈利占比</span>
          <span className="text-sm font-bold font-mono text-[#81c995] mt-0.5 block">{winRate === null ? '未统计' : `${winRate}%`}</span>
        </div>
        <div className="p-3 rounded-2xl bg-[#1c2029] border border-[#2b313f] text-center">
          <span className="text-[10px] text-[#9aa0a6] block">累计已平仓</span>
          <span className="text-sm font-bold font-mono text-white mt-0.5 block">{closedTrades.length} 笔</span>
        </div>
      </div>

      {/* 3. Closed Trades History Feed */}
      <div className="space-y-2">
        <div className="flex items-center justify-between px-1">
          <div className="flex items-center gap-1.5">
            <History className="w-3.5 h-3.5 text-[#8ab4f8]" />
            <h3 className="text-xs font-semibold text-white">模拟 / 旧版流水（非实盘统计）</h3>
          </div>
          {closedTrades.length > 0 && (
            <button
              onClick={handleClearAllHistory}
              className="text-[11px] text-[#9aa0a6] hover:text-[#f28b82] transition-colors"
            >
              清空手机流水
            </button>
          )}
        </div>

        {closedTrades.length === 0 ? (
          <div className="p-6 rounded-2xl bg-[#171a21] border border-[#282d38] text-center text-[11px] text-[#9aa0a6]">
            暂无已平仓的交易流水记录
          </div>
        ) : (
          <div className="space-y-2">
            {closedTrades.map((t) => {
              const isWin = t.outcome === 'WIN';
              return (
                <div
                  key={t.id}
                  className="p-3 rounded-xl bg-[#1c2029] border border-[#282d38] space-y-1.5 text-xs font-mono"
                >
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-1.5">
                      <span
                        className={`text-[9.5px] px-1.5 py-0.2 rounded font-semibold ${
                          isWin ? 'bg-[#1e4620] text-[#81c995]' : 'bg-[#441717] text-[#f28b82]'
                        }`}
                      >
                        {t.accountingSource !== 'SIMULATED' ? '旧记录·成本未核验' : t.outcome === 'BREAKEVEN' ? '模拟持平' : isWin ? '模拟盈利' : '模拟亏损'}
                      </span>
                      <span className="font-bold text-white text-xs">{t.symbol}</span>
                      <span className="text-[10px] text-[#9aa0a6]">
                        {new Date(t.closedAt).toLocaleDateString([], { month: '2-digit', day: '2-digit' })}{' '}
                        {new Date(t.closedAt).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                      </span>
                    </div>

                    <div className="flex items-center gap-2">
                      <span className={`font-bold ${t.netPnl >= 0 ? 'text-[#81c995]' : 'text-[#f28b82]'}`}>
                        {t.netPnl >= 0 ? '+' : ''}${t.netPnl.toFixed(2)} ({t.pnlPercent >= 0 ? '+' : ''}{t.pnlPercent}%)
                      </span>
                      <button
                        onClick={() => handleDeleteHistoryTrade(t.id)}
                        className="text-[#9aa0a6] hover:text-[#f28b82] p-0.5"
                        title="只从手机流水隐藏，分析库保留"
                      >
                        <Trash2 className="w-3 h-3" />
                      </button>
                    </div>
                  </div>

                  <div className="flex items-center justify-between text-[11px] text-[#9aa0a6] pt-0.5">
                    <span>
                      买入: ${t.entryPrice.toLocaleString()} → 平仓: ${t.exitPrice.toLocaleString()}
                    </span>
                    <span>投入: ${t.positionSize.toLocaleString()}</span>
                  </div>

                  {t.closeReason && (
                    <div className="text-[10px] text-[#8ab4f8] bg-[#171a21] px-2 py-0.5 rounded border border-[#282d38]">
                      操盘备注: {t.closeReason}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Close Position Modal */}
      {showCloseModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/75 backdrop-blur-sm animate-fadeIn">
          <div className="w-full max-w-sm bg-[#171a21] border border-[#2b313f] rounded-2xl p-4 space-y-3.5 shadow-2xl">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-semibold text-white">确认模拟退出 BTC 持仓</h3>
              <button onClick={() => setShowCloseModal(false)} className="text-[#9aa0a6] hover:text-white">
                <X className="w-4 h-4" />
              </button>
            </div>

            <div className="p-3 rounded-xl bg-[#1c2029] border border-[#282d38] space-y-1.5 text-xs font-mono">
              <div className="flex justify-between text-[#9aa0a6]">
                <span>开仓入场价</span>
                <span className="text-white">${entryPrice.toLocaleString()}</span>
              </div>
              <div className="flex justify-between text-[#9aa0a6]">
                <span>市价预览（确认时复核买一）</span>
                <span className="text-white">${livePrice.toLocaleString()}</span>
              </div>
              <div className="flex justify-between text-[#9aa0a6]">
                <span>持仓投入本金</span>
                <span className="text-white">${positionSize.toLocaleString()}</span>
              </div>
              <div className="flex justify-between text-[#9aa0a6] pt-1 border-t border-[#282d38]">
                <span>模拟成本后盈亏预览</span>
                <span className={`font-bold ${isPnlPositive ? 'text-[#81c995]' : 'text-[#f28b82]'}`}>
                  {isPnlPositive ? '+' : ''}${floatingNetPnl.toFixed(2)} ({isPnlPositive ? '+' : ''}{(positionSize > 0 ? floatingNetPnl/positionSize*100 : 0).toFixed(2)}%)
                </span>
              </div>
            </div>

            <div className="grid grid-cols-2 gap-2 pt-1">
              <button
                type="button"
                onClick={() => handleClosePositionConfirm(isPnlPositive ? 'WIN' : 'LOSS', isPnlPositive ? '按现价手动止盈' : '按现价手动止损')}
                className={`py-2 px-3 rounded-xl font-medium text-xs text-white shadow-sm transition-all active:scale-95 ${
                  isPnlPositive ? 'bg-[#34a853] hover:bg-[#2d9249]' : 'bg-[#ea4335] hover:bg-[#c53929]'
                }`}
              >
                {isPnlPositive ? '确认模拟退出' : '确认模拟退出'}
              </button>
              <button
                type="button"
                onClick={() => setShowCloseModal(false)}
                className="py-2 px-3 rounded-xl bg-[#232834] hover:bg-[#2b313f] text-[#c4c7c5] font-medium text-xs border border-[#383e4c]"
              >
                暂不平仓
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
