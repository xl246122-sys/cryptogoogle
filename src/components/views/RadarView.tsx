import {DecisionReasons} from '../DecisionReasons';
import React from 'react';
import {TrendStrengthIndicator} from '../TrendStrengthIndicator';
import {ClosedContextCard} from '../ClosedContextCard';
import { MarketTicker, TradeSignal, MacroTrendAnalysis } from '../../types/crypto';
import {
  TrendingUp,
  TrendingDown,
  Zap,
  Clock,
  Radio,
  SlidersHorizontal,
  ChevronRight,
  Layers,
  Sparkles,
  Gauge,
  Activity,
  ShieldCheck,
  Percent,
} from 'lucide-react';


interface RadarViewProps {
  tickers: Record<string, MarketTicker>;
  latestSignals: TradeSignal[];
  scanIntervalSec: number;
  macroTrend: MacroTrendAnalysis;
  onSelectSignal: (signal: TradeSignal) => void;
  onSwitchTab: (tab: any) => void;
  onTriggerTestSignal: () => void;
}

export const RadarView: React.FC<RadarViewProps> = ({
  tickers,
  latestSignals,
  scanIntervalSec,
  macroTrend,
  onSelectSignal,
  onSwitchTab,
  onTriggerTestSignal,
}) => {
  const observed = tickers['BTCUSDT'];
  const btc = observed && Date.now()-observed.lastUpdate <= 10000 ? observed : undefined;
  const price = btc?.price || 0;
  const isUp = (btc?.change24h || 0) >= 0;
  const isBearish = macroTrend.hourlyTrend === 'BEARISH';
  const volRegime = macroTrend.volatility;

  const formatPrice = (val: number) => {
    if (val <= 0) return '连接中...';
    return `$${val.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  };

  const sma20 = macroTrend.hourlyMa20;

  return (
    <div className="space-y-3 pb-28">
      {/* 1. Android M3 Compact Scanner Status Pill */}
      <div className="px-3.5 py-2 rounded-xl bg-[#171a21] border border-[#282d38] flex flex-wrap items-center justify-between gap-2 text-xs shadow-sm">
        <div className="flex flex-wrap items-center gap-2">
          <span className="relative flex h-2 w-2">
            <span
              className={`animate-ping absolute inline-flex h-full w-full rounded-full opacity-75 ${
                !macroTrend.dataReady ? 'bg-gray-500' : isBearish ? 'bg-[#f28b82]' : 'bg-[#81c995]'
              }`}
            ></span>
            <span
              className={`relative inline-flex rounded-full h-2 w-2 ${
                !macroTrend.dataReady ? 'bg-gray-500' : isBearish ? 'bg-[#ea4335]' : 'bg-[#34a853]'
              }`}
            ></span>
          </span>
          <span className="font-semibold text-[#e2e2e8]">{macroTrend.dataReady && macroTrend.stateSource === 'SERVER' ? 'BTC 云端趋势已同步' : macroTrend.stateSource === 'CACHE' ? '上次趋势 · 正在同步' : '正在连接云端趋势'}</span>
          <span className="text-[#9aa0a6] font-mono text-[11px] px-1.5 py-0.2 rounded bg-[#1f242e]">
            行情刷新 {scanIntervalSec}s
          </span>
        </div>

        <button
          onClick={() => onSwitchTab('system')}
          className="flex items-center gap-1 text-[11px] font-semibold text-[#8ab4f8] hover:text-[#aecbfa] px-2.5 py-1 rounded-full bg-[#1a3258]/50 hover:bg-[#1a3258] transition-colors border border-[#3b6bb0]/30 active:scale-95"
        >
          <SlidersHorizontal className="w-3 h-3" />
          <span>参数</span>
        </button>
      </div>

      <TrendStrengthIndicator macroTrend={macroTrend} /><ClosedContextCard market={macroTrend}/><DecisionReasons market={macroTrend} />

      {/* 4. Live BTC Market Card */}
      <div className="p-3.5 rounded-2xl bg-[#1c2029] border border-[#2b313f] shadow-sm space-y-3">
        {/* Compact title and badges stay on separate rows on phones. */}
        <div className="space-y-2.5 border-b border-[#2b313f] pb-3">
          <div className="flex items-center justify-between gap-2">
            <div className="flex items-center gap-2 min-w-0">
              <div className="w-9 h-9 shrink-0 rounded-xl flex items-center justify-center font-bold text-lg border bg-[#fbbc04]/15 border-[#fbbc04]/30 text-[#fbbc04]">₿</div>
              <div className="min-w-0">
                <div className="text-sm font-semibold text-white whitespace-nowrap">Bitcoin <span className="text-xs font-normal text-[#9aa0a6]">比特币</span></div>
                <div className="text-[10px] font-mono text-[#9aa0a6] whitespace-nowrap mt-0.5">BTC/USDT</div>
              </div>
            </div>
            <div className={`shrink-0 flex items-center gap-1 px-2.5 py-1 rounded-lg text-xs font-mono font-semibold whitespace-nowrap border ${!btc ? 'bg-[#252932] text-[#9aa0a6] border-[#383e4c]' : isUp ? 'bg-[#143820] text-[#81c995] border-[#2a6831]' : 'bg-[#441717] text-[#f28b82] border-[#6b252b]'}`}>
              {btc && (isUp ? <TrendingUp className="w-3.5 h-3.5" /> : <TrendingDown className="w-3.5 h-3.5" />)}
              <span>{btc ? `${isUp ? '+' : ''}${btc.change24h.toFixed(2)}%` : '暂无行情'}</span>
            </div>
          </div>
          <div className="flex items-center justify-between gap-2 text-[10px] text-[#9aa0a6]">
            <span className="min-w-0 truncate" title={btc?.dataSource}>{btc ? (btc.dataSource?.includes('WebSocket') ? '币安 · 实时行情' : btc.dataSource || '币安行情') : '行情不可用或已过期'}</span>
            <div className="flex items-center gap-2 shrink-0 whitespace-nowrap">
              {btc && Number.isFinite(btc.latency) && <span className="font-mono">{btc.latency}ms</span>}
              <span className="px-2 py-0.5 rounded-md bg-[#252932] text-[#c4c7c5]">量化标的</span>
            </div>
          </div>
        </div>

        {/* Real-time Price Display */}
        <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-2 pt-1">
          <div>
            <div className="text-[11px] text-[#9aa0a6]">币安成交现价</div>
            <div className="text-2xl font-bold font-mono tracking-tight text-white mt-0.5">
              {formatPrice(price)}
            </div>
          </div>

          {btc && price > 0 && (
            <div className="text-right text-[11px] font-mono text-[#9aa0a6] space-y-0.5">
              <div>
                24h 高: <span className="text-white font-medium">{formatPrice(btc.high24h)}</span>
              </div>
              <div>
                24h 低: <span className="text-white font-medium">{formatPrice(btc.low24h)}</span>
              </div>
            </div>
          )}
        </div>

        {/* Compact Sparkline Trend */}
        {btc?.sparkline && btc.sparkline.length > 2 && (
          <div className="pt-1">
            <p className="text-[10px] text-gray-400 mb-1">最近 {btc.sparkline.length} 次报价 · 涨绿 / 跌红 / 平灰</p>
            <div className="h-8 w-full flex items-end gap-0.5 p-1 bg-[#13161c] rounded-lg border border-[#282d38]">
              {btc.sparkline.map((val, i) => {
                const min = Math.min(...btc.sparkline!);
                const max = Math.max(...btc.sparkline!);
                const heightPct = Math.max(15, Math.min(100, ((val - min) / (max - min || 1)) * 100));
                return (
                  <div
                    key={i}
                    className={`flex-1 rounded-t-xs transition-all ${
                      i === 0 || val === btc.sparkline![i - 1] ? 'bg-gray-500/70' : val < btc.sparkline![i - 1] ? 'bg-[#f28b82]/70' : 'bg-[#81c995]/70'
                    }`}
                    style={{ height: `${heightPct}%` }}
                  ></div>
                );
              })}
            </div>
          </div>
        )}

        <p className="text-[10px] text-gray-500">报价柱非 K 线、非买入信号；1H 收盘趋势与短线涨跌可能不同。</p>
        {/* Key Indicators Grid */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-1.5 pt-1 text-[11px] font-mono">
          <div className="p-2 rounded-xl bg-[#171a21] border border-[#282d38]">
            <div className="text-[10px] text-[#9aa0a6]">1H MA20 趋势位</div>
            <div className={`font-semibold mt-0.5 ${price < sma20 ? 'text-[#f28b82]' : 'text-[#81c995]'}`}>
              {formatPrice(sma20)}
            </div>
          </div>
          <div className="p-2 rounded-xl bg-[#171a21] border border-[#282d38]">
            <div className="text-[10px] text-[#f28b82]">1H 布林上轨 (20,2)</div>
            <div className="font-semibold text-[#f28b82] mt-0.5">{(macroTrend.dataReady || macroTrend.stateSource === 'CACHE') && macroTrend.hourlyBollinger ? formatPrice(macroTrend.hourlyBollinger.upper) : '等待完整收盘数据'}</div>
          </div>
          <div className="p-2 rounded-xl bg-[#171a21] border border-[#282d38]">
            <div className="text-[10px] text-[#81c995]">1H 布林下轨 (20,2)</div>
            <div className="font-semibold text-[#81c995] mt-0.5">{(macroTrend.dataReady || macroTrend.stateSource === 'CACHE') && macroTrend.hourlyBollinger ? formatPrice(macroTrend.hourlyBollinger.lower) : '等待完整收盘数据'}</div>
          </div>
          <div className="p-2 rounded-xl bg-[#171a21] border border-[#282d38]">
            <div className="text-[10px] text-[#8ab4f8]">策略状态</div>
            <div className={`font-semibold mt-0.5 ${isBearish ? 'text-[#fdd663]' : 'text-[#81c995]'}`}>
              {!macroTrend.dataReady && macroTrend.stateSource !== 'CACHE' ? '等待行情' : isBearish ? '防守观察' : '等待买入确认'}
            </div>
          </div>
        </div>
      </div>

      {/* 5. Real-time Risk Metrics Card */}
      <div className="p-3 text-xs text-gray-400">风险收益预测尚未验证，暂不展示模型预测数值。</div>

      {/* 6. Latest Quantitative Signals List */}
      <div className="space-y-2 pt-1">
        <div className="flex items-center justify-between px-1">
          <div className="flex items-center gap-1.5">
            <Zap className="w-3.5 h-3.5 text-[#81c995] fill-[#81c995]" />
            <h3 className="text-xs font-semibold text-white tracking-tight">BTC 最新量化买入预警</h3>
          </div>
          <button
            onClick={() => onSwitchTab('signals')}
            className="text-[11px] text-[#8ab4f8] hover:text-[#aecbfa] flex items-center gap-0.5 font-medium"
          >
            <span>查看全部</span>
            <ChevronRight className="w-3 h-3" />
          </button>
        </div>

        {latestSignals.length === 0 ? (
          <div className="p-5 rounded-2xl bg-[#171a21] border border-[#282d38] text-center space-y-2.5">
            <div className="w-9 h-9 rounded-full bg-[#1c2029] border border-[#2b313f] flex items-center justify-center mx-auto text-[#fdd663]">
              <Radio className="w-4 h-4 animate-pulse" />
            </div>
            <div>
              <div className="text-xs font-semibold text-white">{macroTrend.dataReady || macroTrend.stateSource === 'CACHE' ? '当前没有可复核的买入提醒' : '服务器状态未知 · 等待恢复'}</div>
              <p className="text-[11px] text-[#9aa0a6] max-w-sm mx-auto mt-1 leading-relaxed">
                {isBearish
                  ? `1小时为空头时，云端只有在跌幅达到 5% 并且止跌门禁通过后才会给出买入候选。手机不再单独生成买入弹窗。`
                  : `手机只展示行情和1小时状态。正式买入候选只来自云端，而且必须通过同一套止跌、结构和摩擦门禁。`}
              </p>
            </div>
            <div className="pt-1">
              <button
                onClick={onTriggerTestSignal}
                className="px-3.5 py-1.5 rounded-full bg-[#1a3258] hover:bg-[#204070] border border-[#3b6bb0]/60 text-[#8ab4f8] font-medium text-xs transition-all active:scale-95"
              >
                试听提示音（不会生成买入信号）
              </button>
            </div>
          </div>
        ) : (
          <div className="space-y-2">
            {latestSignals.slice(0, 3).map((sig) => (
              <div
                key={sig.id}
                onClick={() => onSelectSignal(sig)}
                className="p-3 rounded-2xl bg-[#1c2029] hover:bg-[#222733] border border-[#282d38] cursor-pointer transition-all active:scale-[0.99] space-y-2 shadow-sm"
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-1.5">
                    <span className="text-[10px] font-bold px-1.5 py-0.5 rounded-full bg-[#1e4620] text-[#81c995] border border-[#2a6831]/60">
                      历史候选 · 打开复核
                    </span>
                    <span className="text-xs font-bold text-white font-mono">{sig.symbol}</span>
                    {sig.analysis?.quantilePct !== undefined && (
                      <span className="text-[9.5px] font-mono px-1 py-0.2 rounded bg-[#1a2b42] text-[#8ab4f8]">
                        Q={sig.analysis.quantilePct}%
                      </span>
                    )}
                  </div>
                  <span className="text-[10px] text-[#9aa0a6] font-mono">
                    {new Date(sig.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
                  </span>
                </div>

                <div className="flex items-baseline justify-between text-xs font-mono">
                  <div>
                    <span className="text-[10px] text-[#9aa0a6] block">生成时参考价</span>
                    <span className="text-sm font-bold text-white mt-0.5 block">{formatPrice(sig.entryPrice)}</span>
                  </div>
                  <div className="text-right">
                    <span className="text-[10px] text-[#9aa0a6] block">
                      目标 TP1 {sig.analysis?.netProfitPct1 ? `(净 +${sig.analysis.netProfitPct1}%)` : ''}
                    </span>
                    <span className="text-xs font-bold text-[#81c995] mt-0.5 block">
                      {formatPrice(sig.targetTP1)} (+{sig.profitPercent1}%)
                    </span>
                  </div>
                  <div className="text-right">
                    <span className="text-[10px] text-[#9aa0a6] block">防守 SL</span>
                    <span className="text-xs font-bold text-[#f28b82] mt-0.5 block">
                      {formatPrice(sig.stopLoss)} (-{sig.stopLossPercent}%)
                    </span>
                  </div>
                </div>

                <div className="text-[11px] text-[#9aa0a6] line-clamp-2 leading-relaxed bg-[#13161c] p-2 rounded-xl border border-[#242933]">
                  {sig.reasonZh}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};



