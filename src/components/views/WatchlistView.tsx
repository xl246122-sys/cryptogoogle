import {QuickPaperPanel} from '../QuickPaperPanel';
import React, { useState, useEffect } from 'react';
import { MarketTicker, WatchlistItem } from '../../types/crypto';
import {
  BookmarkCheck,
  TrendingUp,
  TrendingDown,
  Target,
  ShieldAlert,
  Save,
  Check,
  RotateCcw,
  BellRing,
} from 'lucide-react';
import { BtcPositionDashboard } from '../BtcPositionDashboard';

interface WatchlistViewProps {
  watchlist: WatchlistItem[];
  tickers: Record<string, MarketTicker>;
  onUpdateWatchlist: (item: WatchlistItem) => void;
}

export const WatchlistView: React.FC<WatchlistViewProps> = ({
  watchlist,
  tickers,
  onUpdateWatchlist,
}) => {
  const btcTicker = tickers['BTCUSDT'];
  const livePrice = btcTicker?.price || 0;

  const btcItem = watchlist.find((w) => w.symbol === 'BTCUSDT') || {
    symbol: 'BTCUSDT',
    name: 'Bitcoin (比特币)',
    positionEntryPrice: livePrice > 0 ? livePrice : 83250,
    positionSize: 5000,
    alertAbovePrice: livePrice > 0 ? +(livePrice * 1.025).toFixed(2) : 85300,
    alertBelowPrice: livePrice > 0 ? +(livePrice * 0.988).toFixed(2) : 82250,
    addedAt: Date.now(),
  };

  const [alertHigh, setAlertHigh] = useState<string>(
    (btcItem.alertAbovePrice || (livePrice > 0 ? +(livePrice * 1.025).toFixed(2) : 85300)).toString()
  );
  const [alertLow, setAlertLow] = useState<string>(
    (btcItem.alertBelowPrice || (livePrice > 0 ? +(livePrice * 0.988).toFixed(2) : 82250)).toString()
  );
  const [savedSuccess, setSavedSuccess] = useState(false);

  useEffect(() => {
    const item = watchlist.find((w) => w.symbol === 'BTCUSDT');
    if (item && item.alertAbovePrice) {
      setAlertHigh(item.alertAbovePrice.toString());
      setAlertLow((item.alertBelowPrice || +(livePrice * 0.988).toFixed(2)).toString());
    } else if (livePrice > 0) {
      setAlertHigh((livePrice * 1.025).toFixed(2));
      setAlertLow((livePrice * 0.988).toFixed(2));
    }
  }, [livePrice, watchlist]);

  const numHigh = parseFloat(alertHigh) || 0;
  const numLow = parseFloat(alertLow) || 0;

  const isHitTP = numHigh > 0 && livePrice >= numHigh;
  const isHitSL = numLow > 0 && livePrice <= numLow;

  const handleSaveAlerts = () => {
    onUpdateWatchlist({
      ...btcItem,
      symbol: 'BTCUSDT',
      name: 'Bitcoin (比特币)',
      alertAbovePrice: numHigh,
      alertBelowPrice: numLow,
    });
    setSavedSuccess(true);
    setTimeout(() => setSavedSuccess(false), 2000);
  };

  return (
    <div className="space-y-3 pb-24">
      {/* Header */}
      <div className="px-1 flex items-center justify-between">
        <div>
          <h2 className="text-sm font-semibold text-white flex items-center gap-1.5">
            <BookmarkCheck className="w-4 h-4 text-[#8ab4f8]" />
            <span>BTC 模拟实验台</span>
          </h2>
          <p className="text-[10px] text-[#9aa0a6] mt-0.5">
            一键采集模拟交易；记录先保存在本机，再同步服务器。
          </p>
        </div>
      </div>

      <QuickPaperPanel ticker={btcTicker}/>
      <details className="text-xs text-gray-400"><summary className="py-2">实际成交补录与旧版持仓（展开）</summary>
      {/* Primary BTC Position Dashboard Component */}
      <BtcPositionDashboard
        btcTicker={btcTicker}
        btcWatchlistItem={btcItem}
        onUpdateWatchlist={onUpdateWatchlist}
      />

      </details>
      <details className="text-xs text-gray-400"><summary className="py-2">价格提醒设置（展开）</summary>
      {/* BTC Target Price Triggers & Alert Configuration */}
      <div className="p-3.5 rounded-2xl bg-[#1c2029] border border-[#2b313f] space-y-3 shadow-sm">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-1.5">
            <BellRing className="w-4 h-4 text-[#fdd663]" />
            <span className="text-xs font-semibold text-white">BTC 价格高低点声光预警线</span>
          </div>
          <span className="text-[10px] font-mono text-[#9aa0a6]">
            现价: <strong className="text-white">${livePrice > 0 ? livePrice.toLocaleString() : '连接中...'}</strong>
          </span>
        </div>

        {/* Live Alert Trigger Status Alerts */}
        {isHitTP && (
          <div className="p-2 rounded-xl bg-[#14231a] border border-[#2a6831] text-[11px] text-[#81c995] flex items-center gap-2 animate-pulse">
            <TrendingUp className="w-4 h-4 shrink-0" />
            <span>🎉 BTC 现价已突破上限预警线 ${numHigh.toLocaleString()}！建议及时止盈离场！</span>
          </div>
        )}

        {isHitSL && (
          <div className="p-2 rounded-xl bg-[#231518] border border-[#6b252b] text-[11px] text-[#f28b82] flex items-center gap-2 animate-pulse">
            <TrendingDown className="w-4 h-4 shrink-0" />
            <span>⚠️ BTC 现价已跌破下限预警线 ${numLow.toLocaleString()}！请注意防守，严格执行止损！</span>
          </div>
        )}

        {/* Inputs */}
        <div className="grid grid-cols-2 gap-2 text-xs font-mono">
          <div>
            <label className="text-[10px] text-[#81c995] block mb-1 flex items-center gap-1">
              <Target className="w-3 h-3" />
              <span>上涨触发价 (USD)</span>
            </label>
            <input
              type="number"
              step="10"
              value={alertHigh}
              onChange={(e) => setAlertHigh(e.target.value)}
              className="w-full px-2.5 py-1.5 bg-[#171a21] border border-[#383e4c] focus:border-[#81c995] rounded-xl text-white font-mono text-xs focus:outline-none"
            />
          </div>

          <div>
            <label className="text-[10px] text-[#f28b82] block mb-1 flex items-center gap-1">
              <ShieldAlert className="w-3 h-3" />
              <span>下破触发价 (USD)</span>
            </label>
            <input
              type="number"
              step="10"
              value={alertLow}
              onChange={(e) => setAlertLow(e.target.value)}
              className="w-full px-2.5 py-1.5 bg-[#171a21] border border-[#383e4c] focus:border-[#f28b82] rounded-xl text-white font-mono text-xs focus:outline-none"
            />
          </div>
        </div>

        {/* Quick Fill Buttons */}
        <div className="flex items-center justify-between pt-1">
          <div className="flex gap-1.5 text-[10px] font-mono">
            <button
              type="button"
              onClick={() => {
                if (livePrice > 0) {
                  setAlertHigh((livePrice * 1.025).toFixed(2));
                  setAlertLow((livePrice * 0.988).toFixed(2));
                }
              }}
              className="px-2 py-0.5 rounded-lg bg-[#252932] hover:bg-[#303642] text-[#c4c7c5] flex items-center gap-1 transition-colors"
            >
              <RotateCcw className="w-2.5 h-2.5" />
              <span>自动推荐预警位 (+2.5% / -1.2%)</span>
            </button>
          </div>

          <button
            type="button"
            onClick={handleSaveAlerts}
            className="flex items-center gap-1 px-3.5 py-1.5 rounded-full bg-[#1a73e8] hover:bg-[#1557b0] text-white font-medium text-xs shadow-sm active:scale-95 transition-all"
          >
            {savedSuccess ? (
              <>
                <Check className="w-3 h-3 text-[#81c995]" />
                <span>已保存</span>
              </>
            ) : (
              <>
                <Save className="w-3 h-3" />
                <span>保存预警设置</span>
              </>
            )}
          </button>
        </div>
      </div>
      </details>
    </div>
  );
};
