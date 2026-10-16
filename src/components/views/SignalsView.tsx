import {MessagePanel} from '../MessagePanel';
import {DecisionReasons} from '../DecisionReasons';
import React, { useState } from 'react';
import { TradeSignal, MacroTrendAnalysis } from '../../types/crypto';
import {
  Zap,
  Clock,
  Copy,
  PlusCircle,
  Flame,
  TrendingDown,
  Activity,
  Layers,
  TrendingUp,
  Compass,
  Check,
  ShieldCheck,
  Percent,
} from 'lucide-react';

interface SignalsViewProps {
  signals: TradeSignal[];
  macroTrend: MacroTrendAnalysis;
  onSelectSignal: (signal: TradeSignal) => void;
  onAddToPosition: (signal: TradeSignal) => void;
  onClearHistory: () => void;
  onSwitchTab?: (tab: any) => void;
}

export const SignalsView: React.FC<SignalsViewProps> = ({
  signals,
  macroTrend,
  onSelectSignal,
  onAddToPosition,
  onClearHistory,
  onSwitchTab,
}) => {
  const [filterStrategy, setFilterStrategy] = useState<string>('ALL');
  const [copiedId, setCopiedId] = useState<string | null>(null);

  const filterOptions: { id: string; label: string; icon: React.ReactNode }[] = [
    { id: 'ALL', label: '全部', icon: <Layers className="w-3.5 h-3.5" /> },
    { id: 'RANGE_OSCILLATION', label: '区间', icon: <Activity className="w-3.5 h-3.5 text-[#81c995]" /> },
    { id: 'TREND_PULLBACK_BUY', label: '回踩', icon: <TrendingUp className="w-3.5 h-3.5 text-[#81c995]" /> },
    { id: 'RSI_DIVERGENCE', label: '背离', icon: <Compass className="w-3.5 h-3.5 text-[#8ab4f8]" /> },
    { id: 'FLASH_CRASH_REBOUND', label: '反弹', icon: <TrendingDown className="w-3.5 h-3.5 text-[#4db6ac]" /> },
    { id: 'BURST_BREAKOUT', label: '突破', icon: <Flame className="w-3.5 h-3.5 text-[#fdd663]" /> },
    { id: 'VOLATILITY_MOMENTUM', label: '动量', icon: <Zap className="w-3.5 h-3.5 text-[#c58af9]" /> },
  ];

  const filteredSignals = signals.filter((s) => {
    if (filterStrategy !== 'ALL' && s.strategy !== filterStrategy) return false;
    return true;
  });

  const pStr = (val: number) => `$${val.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

  const handleCopy = (e: React.MouseEvent, sig: TradeSignal) => {
    e.stopPropagation();

    const netTp1Text = sig.analysis?.netProfitPct1 ? ` (扣费净利 +${sig.analysis.netProfitPct1}%)` : '';
    const netRRText = sig.analysis?.netRiskReward ? ` | 扣费净盈亏比: ${sig.analysis.netRiskReward}:1` : '';

    const text = `【Crypto-G 历史候选参数（非即时买入指令）】\n标的: ${sig.coinName} (${sig.symbol})\n生成时参考价: ${pStr(sig.entryPrice)}\n目标止盈 TP1: ${pStr(sig.targetTP1)} (+${sig.profitPercent1}%${netTp1Text})\n目标止盈 TP2: ${pStr(sig.targetTP2)} (+${sig.profitPercent2}%)\n防守止损 SL: ${pStr(sig.stopLoss)} (-${sig.stopLossPercent}%)\n周期: ${sig.timeHorizon} | 盈亏比: ${sig.riskRewardRatio}:1${netRRText}\n策略: ${sig.strategyNameZh}\n有效至: ${sig.expiresAt ? new Date(sig.expiresAt).toLocaleString() : "未提供"}；实际入场须重新复核\n分析: ${sig.reasonZh}`;

    navigator.clipboard.writeText(text);
    setCopiedId(sig.id);
    setTimeout(() => setCopiedId(null), 2000);
  };

  return (
    <div className="space-y-3 pb-24">
      <MessagePanel onSwitchTab={onSwitchTab} />
      {/* Top Filter & Clean Header */}
      <div className="flex items-center justify-between px-1">
        <div>
          <h2 className="text-sm font-semibold text-white flex items-center gap-1.5">
            <Zap className="w-4 h-4 text-[#81c995] fill-[#81c995]" />
            <span>BTC 量化买入信号库</span>
            <span className="text-[10px] font-mono px-1.5 py-0.2 rounded-full bg-[#1a3258] text-[#8ab4f8]">
              {signals.length} 笔记录
            </span>
          </h2>
          <p className="text-[10px] text-[#9aa0a6] mt-0.5">
            智能识别小/中/宽幅波动与顺势买点 · 严格扣除手续费与滑点门禁
          </p>
        </div>

        {signals.length > 0 && (
          <button
            onClick={onClearHistory}
            className="text-[11px] text-[#9aa0a6] hover:text-[#e2e2e8] transition-colors"
          >
            清空
          </button>
        )}
      </div>

      {/* Horizontal Strategy Filter Chips Scroll */}
      <div className="grid grid-cols-4 gap-1.5">
        {filterOptions.map((opt) => {
          const isSelected = filterStrategy === opt.id;
          return (
            <button
              key={opt.id}
              aria-pressed={isSelected}
              onClick={() => setFilterStrategy(opt.id)}
              className={`flex items-center justify-center gap-1 min-w-0 min-h-9 px-1 py-2 rounded-lg text-[11px] font-medium whitespace-nowrap transition-all ${
                isSelected
                  ? 'bg-[#1a3258] text-[#8ab4f8] border border-[#3b6bb0]/60 font-semibold shadow-sm'
                  : 'bg-[#1c2029] text-[#9aa0a6] hover:text-[#e2e2e8] border border-[#282d38]'
              }`}
            >
              {opt.icon}
              <span>{opt.label}</span>
              {opt.id !== 'ALL' && (
                <span className="text-[10px] font-mono opacity-60">
                  {signals.filter((s) => s.strategy === opt.id).length}
                </span>
              )}
            </button>
          );
        })}
      </div>

      {/* Signal Cards Feed */}
      <DecisionReasons market={macroTrend} />{filteredSignals.length === 0 ? (
        <div className="p-8 rounded-2xl bg-[#171a21] border border-[#282d38] text-center space-y-2">
          <Clock className="w-7 h-7 text-[#9aa0a6] mx-auto opacity-50" />
          <div className="text-xs font-semibold text-[#e2e2e8]">该分类暂无候选记录</div>
          <p className="text-[10px] text-[#9aa0a6]">
            点击“扫描依据”查看本轮判定与拒绝原因。
          </p>
        </div>
      ) : (
        <div className="space-y-2.5">
          {filteredSignals.map((sig) => {
            const isCopied = copiedId === sig.id;
            const netTp1 = sig.analysis?.netProfitPct1;
            const netRR = sig.analysis?.netRiskReward;
            const quantile = sig.analysis?.quantilePct;

            return (
              <div
                key={sig.id}
                onClick={() => onSelectSignal(sig)}
                className="p-3.5 rounded-2xl bg-[#1c2029] hover:bg-[#222733] border border-[#282d38] transition-all cursor-pointer space-y-2.5 shadow-sm active:scale-[0.99]"
              >
                {/* Header row */}
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-[#1e4620] text-[#81c995] border border-[#2a6831]/60">
                      历史候选 · 打开复核
                    </span>
                    <span className="text-xs font-bold text-white font-mono">
                      {sig.symbol}
                    </span>
                    {quantile !== undefined && (
                      <span className="text-[9.5px] font-mono px-1.5 py-0.2 rounded bg-[#1f293d] text-[#8ab4f8] border border-[#304468]">
                        Q={quantile}%
                      </span>
                    )}
                    {netTp1 && (
                      <span className="text-[9.5px] font-mono px-1.5 py-0.2 rounded bg-[#163321] text-[#81c995] border border-[#235832]">
                        净利 +{netTp1}%
                      </span>
                    )}
                  </div>

                  <div className="flex items-center gap-2">
                    <span className="text-[10px] font-mono text-[#9aa0a6]">
                      {new Date(sig.timestamp).toLocaleTimeString([], {
                        hour: '2-digit',
                        minute: '2-digit',
                        second: '2-digit',
                      })}
                    </span>
                    <button
                      onClick={(e) => handleCopy(e, sig)}
                      className="p-1 rounded-lg bg-[#252932] hover:bg-[#303642] text-[#9aa0a6] hover:text-white transition-colors"
                      title="复制参数"
                    >
                      {isCopied ? <Check className="w-3.5 h-3.5 text-[#81c995]" /> : <Copy className="w-3.5 h-3.5" />}
                    </button>
                  </div>
                </div>

                {/* Strategy title */}
                <div className="text-xs font-semibold text-[#8ab4f8] flex items-center gap-1">
                  <span>{sig.strategyNameZh}</span>
                </div>

                {/* Price targets grid */}
                <div className="grid grid-cols-3 gap-2 p-2 rounded-xl bg-[#141822] border border-[#252b3a] text-xs font-mono">
                  <div>
                    <span className="text-[10px] text-[#9aa0a6] block">建议买入</span>
                    <span className="text-sm font-bold text-white mt-0.5 block">
                      {pStr(sig.entryPrice)}
                    </span>
                  </div>
                  <div>
                    <span className="text-[10px] text-[#81c995] block">
                      TP1 {netTp1 ? `(净+${netTp1}%)` : `(+${sig.profitPercent1}%)`}
                    </span>
                    <span className="text-sm font-bold text-[#81c995] mt-0.5 block">
                      {pStr(sig.targetTP1)}
                    </span>
                  </div>
                  <div>
                    <span className="text-[10px] text-[#f28b82] block">
                      防守 SL (-{sig.stopLossPercent}%)
                    </span>
                    <span className="text-sm font-bold text-[#f28b82] mt-0.5 block">
                      {pStr(sig.stopLoss)}
                    </span>
                  </div>
                </div>

                {/* Metrics pill strip */}
                <div className="flex items-center gap-2 text-[10px] font-mono text-[#9aa0a6] flex-wrap">
                  <span className="px-2 py-0.5 rounded-md bg-[#171a21] border border-[#282d38]">
                    规则匹配: <span className="text-white font-semibold">{sig.ruleScore || sig.confidence}/100</span>
                  </span>
                  <span className="px-2 py-0.5 rounded-md bg-[#171a21] border border-[#282d38]">
                    盈亏比: <span className="text-[#81c995] font-semibold">{sig.riskRewardRatio}:1</span>
                    {netRR && <span className="text-[#8ab4f8] ml-1">(净 {netRR}:1)</span>}
                  </span>
                  <span className="px-2 py-0.5 rounded-md bg-[#171a21] border border-[#282d38]">
                    周期: <span className="text-white font-semibold">{sig.timeHorizon}</span>
                  </span>
                  {sig.analysis?.structureSupportPrice && (
                    <span className="px-2 py-0.5 rounded-md bg-[#171a21] border border-[#282d38]">
                      支撑: <span className="text-white font-semibold">{pStr(sig.analysis.structureSupportPrice)}</span>
                    </span>
                  )}
                </div>

                {/* Reasoning snippet */}
                <div className="text-[11px] text-[#c4c7c5] leading-relaxed line-clamp-2 bg-[#171a21] p-2 rounded-xl border border-[#282d38]">
                  {sig.reasonZh}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};

