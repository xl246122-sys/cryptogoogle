import React, { useState, useEffect, useMemo, useRef } from 'react';
import { TradeSignal, WatchlistItem } from '../types/crypto';
import { EntryQuote, entryIssue, fetchEntryQuote, signalTimeIssue } from '../services/signalValidity';
import {
  X,
  Zap,
  Clock,
  Target,
  ShieldAlert,
  Copy,
  Check,
  PlusCircle,
  Calculator,
  RotateCcw,
  ArrowUpRight,
  ArrowDownRight,
  Coins,
  CheckCircle,
  ShieldCheck,
  Percent,
} from 'lucide-react';

interface SignalAlertModalProps {
  signal: TradeSignal | null;
  onClose: () => void;
  onAddToPosition: (signal: TradeSignal, customAmount?: number, checkedPrice?: number) => void;
  defaultInvestmentAmount?: number;
  watchlist?: WatchlistItem[];
}

export const SignalAlertModal: React.FC<SignalAlertModalProps> = ({
  signal,
  onClose,
  onAddToPosition,
  defaultInvestmentAmount,
  watchlist,
}) => {
  const [copied, setCopied] = useState(false);
  const currentSignalId = useRef(signal?.id);
  currentSignalId.current = signal?.id;
  const [quote, setQuote] = useState<EntryQuote | null>(null);
  const [quoteSignalId, setQuoteSignalId] = useState<string | null>(null);
  const [clock, setClock] = useState(Date.now());
  const [checking, setChecking] = useState(false);
  const [actionIssue, setActionIssue] = useState<string | null>(null);
  useEffect(() => {
    let disposed = false;
    let fetching = false;
    setQuote(null);
    setQuoteSignalId(null);
    setActionIssue(null);
    const refresh = async () => {
      if (!signal || fetching || signalTimeIssue(signal)) return;
      fetching = true;
      const next = await fetchEntryQuote();
      if (!disposed) { setQuote(next); setQuoteSignalId(signal.id); setClock(Date.now()); }
      fetching = false;
    };
    void refresh();
    const timer = setInterval(() => { setClock(Date.now()); void refresh(); }, 5000);
    const clockTimer = setInterval(() => setClock(Date.now()), 1000);
    return () => { disposed = true; clearInterval(timer); clearInterval(clockTimer); };
  }, [signal]);

  // Compute default investment amount
  const defaultSize = useMemo(() => {
    if (defaultInvestmentAmount && defaultInvestmentAmount > 0) {
      return defaultInvestmentAmount;
    }
    const found = watchlist?.find((w) => w.symbol === (signal?.symbol || 'BTCUSDT'));
    return found?.positionSize && found.positionSize > 0 ? found.positionSize : 5000;
  }, [defaultInvestmentAmount, watchlist, signal?.symbol]);

  // Configurable investment amount input
  const [investmentAmount, setInvestmentAmount] = useState<string>(defaultSize.toString());

  // Reset or sync when signal changes
  useEffect(() => {
    if (signal) {
      setInvestmentAmount(defaultSize.toString());
    }
  }, [signal, defaultSize]);

  if (!signal) return null;
  const validityIssue = entryIssue(signal, quoteSignalId === signal.id ? quote : null, clock);
  const addCheckedPosition = async () => {
    setChecking(true);
    const latest = signalTimeIssue(signal) ? null : await fetchEntryQuote();
    if (currentSignalId.current !== signal.id) { setChecking(false); return; }
    const issue = entryIssue(signal, latest);
    setQuote(latest); setQuoteSignalId(signal.id); setClock(Date.now()); setActionIssue(issue);
    setChecking(false);
    if (issue || !latest) return;
    onAddToPosition(signal, amountNum, latest.price);
    onClose();
  };

  // Numerical calculations for potential profit/loss in USD
  const parsedAmount = parseFloat(investmentAmount);
  const amountNum = !isNaN(parsedAmount) && parsedAmount > 0 ? parsedAmount : 0;

  const estimatedCoinQty =
    signal.entryPrice > 0 && amountNum > 0 ? amountNum / signal.entryPrice : 0;

  const tp1ProfitUSD = amountNum > 0 ? (amountNum * signal.profitPercent1) / 100 : 0;
  const tp2ProfitUSD = amountNum > 0 ? (amountNum * signal.profitPercent2) / 100 : 0;
  const slLossUSD = amountNum > 0 ? (amountNum * signal.stopLossPercent) / 100 : 0;

  const tp1TotalPayout = amountNum + tp1ProfitUSD;
  const tp2TotalPayout = amountNum + tp2ProfitUSD;
  const slRemainingPrincipal = Math.max(0, amountNum - slLossUSD);

  const presetAmounts = [1000, 2000, 5000, 10000, 20000];

  const formatPrice = (p: number) =>
    `$${p.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

  const handleCopyParams = () => {
    const coinSymbol = signal.symbol.replace('USDT', '');
    const coinQtyFormatted = estimatedCoinQty.toFixed(4);
    const netTp1Text = signal.analysis?.netProfitPct1 ? ` (扣费净利 +${signal.analysis.netProfitPct1}%)` : '';
    const netRRText = signal.analysis?.netRiskReward ? ` | 扣费净盈亏比: ${signal.analysis.netRiskReward}:1` : '';

    const text = `【Crypto-G 历史候选参数（非即时买入指令）】\n币种: ${signal.coinName} (${signal.symbol})\n生成时参考价: ${formatPrice(signal.entryPrice)}\n计划本金: $${amountNum.toLocaleString()} (~${coinQtyFormatted} ${coinSymbol})\nTP1止盈: ${formatPrice(signal.targetTP1)} (+${signal.profitPercent1}%${netTp1Text} | +$${tp1ProfitUSD.toFixed(2)})\nTP2止盈: ${formatPrice(signal.targetTP2)} (+${signal.profitPercent2}% | +$${tp2ProfitUSD.toFixed(2)})\nSL止损: ${formatPrice(signal.stopLoss)} (-${signal.stopLossPercent}% | -$${slLossUSD.toFixed(2)})\n盈亏比: ${signal.riskRewardRatio}:1${netRRText} | 规则匹配度: ${signal.ruleScore || signal.confidence}/100 (历史胜率未验证)\n持仓周期: ${signal.timeHorizon}\n策略: ${signal.strategyNameZh}\n有效至: ${signal.expiresAt ? new Date(signal.expiresAt).toLocaleString() : "未提供"}；实际入场须重新复核\n分析: ${signal.reasonZh}`;

    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const netTp1 = signal.analysis?.netProfitPct1;
  const netRR = signal.analysis?.netRiskReward;
  const friction = signal.analysis?.estimatedFriction;
  const metric = (value: number | undefined, suffix = '') => value !== undefined && Number.isFinite(value) ? `${value}${suffix}` : '未提供';

  return (
    <div className="fixed inset-0 z-50 flex items-end sm:items-center justify-center p-0 sm:p-4 bg-black/75 backdrop-blur-sm animate-fadeIn">
      {/* Android Material 3 Bottom Sheet Container */}
      <div className="relative w-full max-w-lg bg-[#171a21] border border-[#2b313f] rounded-t-3xl sm:rounded-2xl shadow-2xl overflow-hidden max-h-[90vh] flex flex-col">
        {/* Top Sheet Drag Indicator */}
        <div className="pt-2.5 pb-1 flex justify-center sm:hidden">
          <div className="w-9 h-1 rounded-full bg-[#383e4c]"></div>
        </div>

        {/* Modal Header */}
        <div className="px-4 py-3 bg-[#1c2029] border-b border-[#282d38] flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-xl flex items-center justify-center border bg-[#143820] border-[#2a6831]/60 text-[#81c995]">
              <Zap className="w-4 h-4 fill-current" />
            </div>
            <div>
              <div className="flex items-center gap-1.5">
                <span className="text-[10px] font-semibold px-2 py-0.2 rounded-full border bg-[#143820] text-[#81c995] border-[#2a6831]/60">
                  {validityIssue ? '暂不可入场' : '当前报价通过复核'}
                </span>
                <span className="text-[10px] text-[#9aa0a6] font-mono">
                  规则匹配度 {signal.ruleScore || signal.confidence}/100 (胜率未验证)
                </span>
              </div>
              <h3 className="text-sm font-semibold text-white tracking-tight mt-0.5">
                {signal.coinName} ({signal.symbol})
              </h3>
            </div>
          </div>

          <button
            onClick={onClose}
            className="w-8 h-8 rounded-full bg-[#232834] hover:bg-[#2b313f] text-[#9aa0a6] hover:text-white flex items-center justify-center transition-colors"
            aria-label="关闭弹窗"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Modal Scrollable Body */}
        <div className="p-3.5 sm:p-4 overflow-y-auto space-y-3 text-xs">
          <div role="status" className="p-3 rounded-xl border border-[#664d12] text-[#fdd663] space-y-1">
            <p>{actionIssue || validityIssue || '报价在有效区间内；以下止盈止损仍是生成时的参考值。'}</p>
            <p>有效区间：{signal.entryMin ? formatPrice(signal.entryMin) : '未提供'} – {signal.entryMax ? formatPrice(signal.entryMax) : '未提供'}</p>
            <p>有效至：{signal.expiresAt ? new Date(signal.expiresAt).toLocaleTimeString() : '未提供'} · 当前卖一价：{quoteSignalId === signal.id && quote ? formatPrice(quote.price) : '等待复核'}</p>
          </div>
          {signal.tradeRules && <div className="p-3 rounded-xl border border-[#2b313f] text-[#c4c7c5] space-y-1">
            <p>独立规则：{({BREAKOUT: '突破', REBOUND: '暴跌反弹', RANGE: '区间震荡'})[signal.tradeRules.model]} · {signal.tradeRules.ruleVersion}</p>
            <p>失效位：{formatPrice(signal.tradeRules.invalidationPrice)} · 最长持有 {signal.tradeRules.maxHoldMinutes} 分钟</p>
            <p>空间门槛：扣预设成本后 TP1 ≥{signal.tradeRules.minNetTp1}%；不足即跳过。</p>
            <p>目标依据：{signal.tradeRules.targetBasis}</p>
            <p>持仓时间从记入模拟买入时开始；退出条件优先，不要求至少持有 10 分钟。</p>
          </div>}
          {/* Strategy Title Chip */}
          <div className="bg-[#1c2029] p-2.5 rounded-xl border border-[#282d38] flex items-center justify-between">
            <div>
              <div className="text-[10px] text-[#9aa0a6]">触发核心量化模型</div>
              <div className="text-xs font-semibold text-[#fdd663] mt-0.5">
                {signal.strategyNameZh}
              </div>
            </div>
            {signal.analysis?.volatilityNameZh ? (
              <span className="text-[10px] font-mono text-[#fdd663] bg-[#382b0e] px-2 py-0.5 rounded-full border border-[#664d12]">
                ⚡ {signal.analysis.volatilityNameZh}
              </span>
            ) : signal.analysis?.effectiveDropPct !== undefined ? (
              <span className="text-[10px] font-mono text-[#f28b82] bg-[#441717] px-2 py-0.5 rounded-full border border-[#6b252b]/50">
                跌幅 -{signal.analysis.effectiveDropPct}% (≥5%抄底确认)
              </span>
            ) : null}
          </div>

          {/* Key Execution Matrix Grid */}
          <div className="grid grid-cols-2 gap-2 text-xs">
            {/* Entry Price */}
            <div className="p-2.5 rounded-xl bg-[#1c2029] border border-[#282d38]">
              <div className="text-[10px] text-[#9aa0a6]">信号生成时参考价</div>
              <div className="text-base font-bold font-mono text-white mt-0.5">
                {formatPrice(signal.entryPrice)}
              </div>
              <div className="text-[10px] font-mono text-[#81c995] mt-0.5">
                入场须通过当前价格复核
              </div>
            </div>

            {/* Time Horizon */}
            <div className="p-2.5 rounded-xl bg-[#1c2029] border border-[#282d38]">
              <div className="text-[10px] text-[#9aa0a6] flex items-center gap-1">
                <Clock className="w-3 h-3 text-[#fdd663]" />
                <span>预估持仓周期</span>
              </div>
              <div className="text-base font-bold font-mono text-[#fdd663] mt-0.5">
                {signal.timeHorizon}
              </div>
              <div className="text-[10px] text-[#9aa0a6] mt-0.5">
                达标即走·不恋战
              </div>
            </div>

            {/* Target Take Profit */}
            <div className="p-2.5 rounded-xl bg-[#14231a] border border-[#1f4028]">
              <div className="text-[10px] text-[#81c995] flex items-center justify-between">
                <span className="flex items-center gap-1">
                  <Target className="w-3 h-3" />
                  <span>目标 TP1 / TP2</span>
                </span>
                {netTp1 && (
                  <span className="text-[9px] px-1 py-0.1 rounded bg-[#1e4620] text-[#81c995] font-semibold">
                    净利 +{netTp1}%
                  </span>
                )}
              </div>
              <div className="text-sm font-bold font-mono text-[#81c995] mt-0.5">
                {formatPrice(signal.targetTP1)}{' '}
                <span className="text-[10px] font-normal">
                  (+{signal.profitPercent1}%)
                </span>
              </div>
              <div className="text-[10px] text-[#81c995]/80 font-mono mt-0.5">
                TP2: {formatPrice(signal.targetTP2)} (+{signal.profitPercent2}%)
              </div>
            </div>

            {/* Stop Loss */}
            <div className="p-2.5 rounded-xl bg-[#231518] border border-[#4f2328]">
              <div className="text-[10px] text-[#f28b82] flex items-center justify-between">
                <span className="flex items-center gap-1">
                  <ShieldAlert className="w-3 h-3" />
                  <span>严格防守止损 (SL)</span>
                </span>
                {netRR && (
                  <span className="text-[9px] px-1 py-0.1 rounded bg-[#331c20] text-[#f28b82] font-semibold">
                    净比 {netRR}:1
                  </span>
                )}
              </div>
              <div className="text-sm font-bold font-mono text-[#f28b82] mt-0.5">
                {formatPrice(signal.stopLoss)}{' '}
                <span className="text-[10px] font-normal">
                  (-{signal.stopLossPercent}%)
                </span>
              </div>
              <div className="text-[10px] text-[#9aa0a6] mt-0.5 font-mono">
                {signal.analysis?.structureSupportPrice
                  ? `结构支撑: ${formatPrice(signal.analysis.structureSupportPrice)}`
                  : `盈亏比 ${signal.riskRewardRatio}:1`}
              </div>
            </div>
          </div>

          {/* Institutional Friction & Friction Gate Audit Pill */}
          <div className="p-2.5 rounded-xl bg-[#141822] border border-[#242b3a] flex items-center justify-between text-[11px] font-mono">
            <div className="flex items-center gap-1.5 text-[#9aa0a6]">
              <ShieldCheck className="w-3.5 h-3.5 text-[#81c995]" />
              <span>成本假设：{metric(friction, '%')}（非账户实际费率）</span>
            </div>
            <span className="text-[#81c995] font-semibold">{validityIssue ? '等待有效复核' : '报价通过'}</span>
          </div>

          {/* Potential USD Profit Calculator */}
          <div className="p-3 rounded-xl bg-[#1c2029] border border-[#2b313f] space-y-2.5">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-1.5 text-xs font-semibold text-[#81c995]">
                <Calculator className="w-3.5 h-3.5" />
                <span>预估收益试算器 (Profit Calculator)</span>
              </div>
              <span className="text-[10px] font-mono text-[#9aa0a6]">
                联动底仓: <strong className="text-white">${defaultSize.toLocaleString()}</strong>
              </span>
            </div>

            {/* Configurable Investment Amount Input */}
            <p className="text-[10px] text-[#9aa0a6]">以下分别假设全仓在单一价位退出，未扣成本；不是上方模型分批退出计划的净收益。</p>
            <div className="space-y-1.5">
              <div className="flex items-center justify-between text-[11px] text-[#9aa0a6]">
                <span>计划投入本金 (USD)</span>
                {amountNum > 0 && signal.entryPrice > 0 && (
                  <span className="font-mono text-[#c4c7c5] flex items-center gap-1">
                    <Coins className="w-3 h-3 text-[#fdd663]" />
                    折合现货: <strong className="text-white">{estimatedCoinQty.toFixed(4)}</strong> BTC
                  </span>
                )}
              </div>

              <div className="flex items-center gap-2">
                <div className="relative flex-1">
                  <span className="absolute inset-y-0 left-0 pl-2.5 flex items-center pointer-events-none text-[#81c995] font-mono font-bold text-xs">
                    $
                  </span>
                  <input
                    type="number"
                    min="1"
                    step="500"
                    value={investmentAmount}
                    onChange={(e) => setInvestmentAmount(e.target.value)}
                    placeholder="输入投入本金..."
                    className="w-full pl-6 pr-2.5 py-1.5 bg-[#171a21] border border-[#383e4c] focus:border-[#81c995] rounded-xl text-white font-mono text-xs focus:outline-none transition-all"
                  />
                </div>

                <button
                  type="button"
                  onClick={() => setInvestmentAmount(defaultSize.toString())}
                  title={`重置为底仓金额 ($${defaultSize.toLocaleString()})`}
                  className="px-2.5 py-1.5 rounded-xl bg-[#232834] hover:bg-[#2b313f] text-[#c4c7c5] border border-[#383e4c] text-[11px] font-mono flex items-center gap-1 transition-colors"
                >
                  <RotateCcw className="w-3 h-3" />
                  <span>重置</span>
                </button>
              </div>

              {/* Preset Amount Chips */}
              <div className="flex items-center gap-1.5 pt-0.5 overflow-x-auto pb-0.5">
                <span className="text-[10px] text-[#9aa0a6] shrink-0">快捷:</span>
                {presetAmounts.map((amt) => {
                  const isActive = amountNum === amt;
                  return (
                    <button
                      key={amt}
                      type="button"
                      onClick={() => setInvestmentAmount(amt.toString())}
                      className={`px-2 py-0.5 text-[10px] font-mono rounded-full border transition-all shrink-0 ${
                        isActive
                          ? 'bg-[#143820] text-[#81c995] border-[#2a6831] font-semibold'
                          : 'bg-[#171a21] text-[#9aa0a6] border-[#282d38] hover:text-white'
                      }`}
                    >
                      ${amt >= 1000 ? `${amt / 1000}k` : amt}
                    </button>
                  );
                })}
              </div>
            </div>

            {/* Estimated USD Profit & Loss Matrix */}
            <div className="grid grid-cols-3 gap-1.5 pt-1 border-t border-[#282d38]">
              {/* TP1 Profit */}
              <div className="p-2 rounded-lg bg-[#14231a] border border-[#1f4028]">
                <div className="text-[10px] text-[#81c995] flex items-center gap-0.5">
                  <ArrowUpRight className="w-3 h-3" />
                  <span>TP1 毛收益试算</span>
                </div>
                <div className="text-sm font-bold font-mono text-[#81c995] mt-0.5">
                  +${tp1ProfitUSD.toFixed(2)}
                </div>
                <div className="text-[9px] text-[#81c995]/70 font-mono">
                  本息 ${tp1TotalPayout.toFixed(2)}
                </div>
              </div>

              {/* TP2 Profit */}
              <div className="p-2 rounded-lg bg-[#122824] border border-[#1b433c]">
                <div className="text-[10px] text-[#4db6ac] flex items-center gap-0.5">
                  <ArrowUpRight className="w-3 h-3" />
                  <span>TP2 毛收益试算</span>
                </div>
                <div className="text-sm font-bold font-mono text-[#4db6ac] mt-0.5">
                  +${tp2ProfitUSD.toFixed(2)}
                </div>
                <div className="text-[9px] text-[#4db6ac]/70 font-mono">
                  本息 ${tp2TotalPayout.toFixed(2)}
                </div>
              </div>

              {/* SL Loss */}
              <div className="p-2 rounded-lg bg-[#231518] border border-[#4f2328]">
                <div className="text-[10px] text-[#f28b82] flex items-center gap-0.5">
                  <ArrowDownRight className="w-3 h-3" />
                  <span>SL 潜在风险</span>
                </div>
                <div className="text-sm font-bold font-mono text-[#f28b82] mt-0.5">
                  -${slLossUSD.toFixed(2)}
                </div>
                <div className="text-[9px] text-[#f28b82]/70 font-mono">
                  剩余 ${slRemainingPrincipal.toFixed(2)}
                </div>
              </div>
            </div>
          </div>

          {signal.tradeRules && <div className="p-3 rounded-xl bg-[#1c2029] border border-[#2b313f] text-xs text-[#c4c7c5] space-y-2">
            <p className="text-[#81c995]">该模型退出计划（规则模拟，不自动下单）</p>
            <p>TP1：退出初始仓位 {Math.round(signal.tradeRules.tp1Fraction * 100)}%；剩余仓位在 TP2 退出。若比例为 100%，TP2 仅作结构参考。</p>
            <p>{signal.tradeRules.exitRule}</p>
            <p>停止信号提醒不等于平仓；止损和目标价不保证实际成交。</p>
          </div>}

          {/* Model Reasoning & Analysis Metrics */}
          <div className="p-2.5 rounded-xl bg-[#1c2029] border border-[#282d38] space-y-1.5">
            <div className="text-[11px] font-semibold text-[#8ab4f8]">
              量化模型买入依据与评估
            </div>
            <p className="text-[11px] text-[#c4c7c5] leading-relaxed whitespace-pre-line">
              {signal.reasonZh}
            </p>

            <div className="pt-2 border-t border-[#282d38] grid grid-cols-2 sm:grid-cols-4 gap-1.5 text-[10px] font-mono text-[#9aa0a6]">
              <div>
                <span>RSI(14): </span>
                <span className="text-white">{metric(signal.analysis?.rsi14)}</span>
              </div>
              <div>
                <span>1m 量比: </span>
                <span className="text-[#fdd663]">{metric(signal.analysis?.volumeMultiplier, 'x')}</span>
              </div>
              <div>
                <span>盘口不平衡: </span>
                <span className="text-[#81c995]">{metric(signal.analysis?.orderFlowImbalance, '%')}</span>
              </div>
              <div>
                <span>波动百分位: </span>
                <span className="text-[#8ab4f8]">{metric(signal.analysis?.quantilePct, '%')}</span>
              </div>
            </div>
          </div>
        </div>

        {/* Modal Action Buttons */}
        <div className="p-3 bg-[#13161c] border-t border-[#282d38] flex items-center gap-2">
          <button
            disabled={checking || !!validityIssue || amountNum <= 0}
            onClick={addCheckedPosition}
            className="flex-1 py-2.5 px-3 rounded-full bg-[#34a853] hover:bg-[#2d9249] disabled:bg-[#383e4c] disabled:text-[#9aa0a6] disabled:cursor-not-allowed text-white font-medium text-xs flex items-center justify-center gap-1.5 transition-all active:scale-98 shadow-sm"
          >
            <PlusCircle className="w-3.5 h-3.5" />
            <span>{checking ? '正在复核价格…' : '复核并记入模拟持仓'}</span>
          </button>

          <button
            onClick={handleCopyParams}
            className="py-2.5 px-3 rounded-full bg-[#232834] hover:bg-[#2b313f] text-[#8ab4f8] font-medium text-xs flex items-center gap-1 transition-colors border border-[#383e4c] active:scale-98"
          >
            {copied ? <Check className="w-3.5 h-3.5 text-[#81c995]" /> : <Copy className="w-3.5 h-3.5" />}
            <span>{copied ? '已复制' : '复制参数'}</span>
          </button>
        </div>
      </div>
    </div>
  );
};
