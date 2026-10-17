/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import React, { useEffect, useState, useRef, useCallback } from 'react';
import { MarketTicker, TradeSignal, WatchlistItem, ScannerConfig, MacroTrendAnalysis } from './types/crypto';
import { binanceService } from './services/binanceService';
import { fetchMarketState, unknownMarket } from './services/marketState';
import { soundService } from './services/soundService';
import { notificationService } from './services/notificationService';
import {recordExitPush,flushExitReceipts} from './services/exitPush';
import { flushLibraryQueue, recordPhoneReceived, recordSimBuy, rememberAction } from './services/modelLibrary';
import { focusMessage, autoClearMessages } from './services/inbox';

import { parseCloudSignal, entryIssue, signalTimeIssue, fetchEntryQuote, aiEntryAllowed } from './services/signalValidity';

import { Header } from './components/Header';
import { BottomNav, TabType } from './components/BottomNav';
import { SignalAlertModal } from './components/SignalAlertModal';
import { PWAInstallModal } from './components/PWAInstallModal';

import { RadarView } from './components/views/RadarView';
import { SignalsView } from './components/views/SignalsView';
import { AIQuantView } from './components/views/AIQuantView';
import { WatchlistView } from './components/views/WatchlistView';
import { SystemGuardView } from './components/views/SystemGuardView';
import { aiScheduler, fetchAIState } from './services/aiEngine';
import { getInitialMarketState } from './services/marketState';

const DEFAULT_CONFIG: ScannerConfig = {
  scanIntervalMs: 2000,
  soundEnabled: true,
  soundVolume: 0.8,
  pushEnabled: true,
  autoPopupEnabled: true,
  minConfidence: 75,
  minProfitTarget: 0.40,
  maxHoldingHours: 2,
  activeStrategies: {
    FLASH_CRASH_REBOUND: true,
    BURST_BREAKOUT: true,
    RANGE_OSCILLATION: true,
    VOLATILITY_MOMENTUM: false,
    VWAP_MEAN_REVERSION: false,
    RSI_DIVERGENCE: false,
    TREND_PULLBACK_BUY: false,
  },
  monitoredSymbols: ['BTCUSDT'],
  activeDataProvider: 'BINANCE',
};

export default function App() {
  const [aiCard, setAiCard] = useState<{text:string;expiresAt:number}|null>(null);
  const aiSeen = useRef(new Set<string>());
  useEffect(() => {
    if (!aiCard) return;
    const timer = window.setTimeout(() => setAiCard(null),Math.max(0,aiCard.expiresAt-Date.now()));
    return () => window.clearTimeout(timer);
  },[aiCard]);
  useEffect(() => {
    const clearDelivered = () => { void notificationService.clearDelivered().catch(() => {}); };
    const check = () => autoClearMessages();
    window.addEventListener('cryptog-inbox-cleared', clearDelivered);
    document.addEventListener('visibilitychange', check);
    check();
    const timer = window.setInterval(check, 1000);
    return () => {
      window.clearInterval(timer);
      window.removeEventListener('cryptog-inbox-cleared', clearDelivered);
      document.removeEventListener('visibilitychange', check);
    };
  }, []);
  const [activeTab, setActiveTab] = useState<TabType>('radar');
  const [tickers, setTickers] = useState<Record<string, MarketTicker>>({});
  const [signals, setSignals] = useState<TradeSignal[]>([]);
  const [activeModalSignal, setActiveModalSignal] = useState<TradeSignal | null>(null);
  const [macroTrend, setMacroTrend] = useState<MacroTrendAnalysis>(getInitialMarketState);

  const [watchlist, setWatchlist] = useState<WatchlistItem[]>(() => {
    try {
      const saved = localStorage.getItem('shotcrypto_btc_watchlist_v1');
      if (saved) {
        const parsed = JSON.parse(saved);
        if (Array.isArray(parsed) && parsed.length > 0) return parsed;
      }
    } catch {
      // keep the empty position below
    }
    return [
      {
        symbol: 'BTCUSDT',
        name: 'Bitcoin (比特币)',
        positionEntryPrice: 0,
        positionSize: 5000,
        alertAbovePrice: 0,
        alertBelowPrice: 0,
        addedAt: Date.now(),
      },
    ];
  });
  const [config, setConfig] = useState<ScannerConfig>(DEFAULT_CONFIG);
  const [unreadCount, setUnreadCount] = useState<number>(0);
  const [isInstallable, setIsInstallable] = useState(false);
  const [deferredPrompt, setDeferredPrompt] = useState<any>(null);
  const [showInstallModal, setShowInstallModal] = useState(false);
  const [hasNotificationPermission, setHasNotificationPermission] = useState(false);
  const [checkingNotificationPermission, setCheckingNotificationPermission] = useState(true);

  useEffect(() => {
    try {
      localStorage.setItem('shotcrypto_btc_watchlist_v1', JSON.stringify(watchlist));
    } catch {
      // storage unavailable
    }
  }, [watchlist]);

  useEffect(() => {
    void flushLibraryQueue();
    const timer = window.setInterval(() => void flushLibraryQueue(), 20000);
    return () => window.clearInterval(timer);
  }, []);

  const lastSignalRef = useRef<Record<string, { time: number; strategy: string; price: number }>>({});
  const triggeredSetupsRef = useRef<Set<string>>(new Set());
  const isScanningRef = useRef(false);
  const titleFlashIntervalRef = useRef<any>(null);

  // Clear Title Flash on Window Focus or Click
  const clearTitleFlash = useCallback(() => {
    if (titleFlashIntervalRef.current) {
      clearInterval(titleFlashIntervalRef.current);
      titleFlashIntervalRef.current = null;
    }
    document.title = 'Crypto-G - BTC 现货量化买入雷达 (V1.17)';
  }, []);

  const flashTitle = useCallback((text1: string, text2: string) => {
    if (titleFlashIntervalRef.current) {
      clearInterval(titleFlashIntervalRef.current);
    }
    let flag = false;
    titleFlashIntervalRef.current = setInterval(() => {
      document.title = flag ? text1 : text2;
      flag = !flag;
    }, 900);
  }, []);

  // Dispatch signal handler - STRICTLY FOR BUY SIGNALS ONLY!
  const handleTriggerSignal = useCallback(
    (signal: TradeSignal) => {
      if (signal.signalType !== 'BUY') return;

      const now = Date.now();
      const setupKey = `${signal.symbol}_${signal.strategy}_${signal.confirmationTime || Math.floor(signal.entryPrice)}`;

      // 1. Setup Deduplication: Exact same candle confirmation/setup key is never alerted twice
      if (triggeredSetupsRef.current.has(setupKey)) {
        return;
      }

      const last = lastSignalRef.current[signal.symbol];

      // 90-second cooldown applies to cloud pushes as well. Strategy name changes do not skip it.
      if (last) {
        const timeElapsed = now - last.time;
        if (timeElapsed < 90000) {
          return;
        }
      }

      triggeredSetupsRef.current.add(setupKey);
      lastSignalRef.current[signal.symbol] = {
        time: now,
        strategy: signal.strategy,
        price: signal.entryPrice,
      };

      setSignals((prev) => [signal, ...prev.slice(0, 49)]);
      setUnreadCount((c) => c + 1);

      // 1. Play Bullish Buy Chime immediately
      soundService.playBuySignalChime();

      // 2. Flash Browser Tab Title for instant peripheral awareness
      flashTitle(
        `🚨【买入预警! $${signal.entryPrice.toLocaleString()}】`,
        `💰【止盈目标 +${signal.profitPercent1}%】`
      );

      // 3. Send System Push Notification
      notificationService.sendPushNotification(
        `🚀 [Crypto-G ${signal.symbol} 买入预警]`,
        `建议买入: $${signal.entryPrice} | 止盈: +${signal.profitPercent1}% | 策略: ${signal.strategyNameZh}`
      );

      // 4. Trigger High-Priority Modal
      if (config.autoPopupEnabled) {
        setActiveModalSignal(signal);
      }
    },
    [config.autoPopupEnabled, flashTitle]
  );

  // Initialize Audio, Notification, and User Gesture Unlock
  useEffect(() => {
    soundService.setEnabled(config.soundEnabled);
    soundService.setVolume(config.soundVolume);

    // Register Authoritative Cloud Signal Handler from FCM Topic Push
    let disposed = false;
    const refreshPermission = async () => {
      try {
        const granted = await notificationService.refreshPermission();
        if (!disposed) {setHasNotificationPermission(granted);setCheckingNotificationPermission(false);}
      } catch {if (!disposed)setCheckingNotificationPermission(true);}
    };
    void notificationService.initNativePush().then(refreshPermission);
    const resumePermission = () => {if(document.visibilityState==='visible')void refreshPermission();};
    document.addEventListener('visibilitychange',resumePermission);
    const permissionTimer=window.setInterval(resumePermission,10000);
    const unsubscribeSignal = notificationService.onSignalReceived(async (data: any, origin?: 'received' | 'opened') => {
      if (data?.eventType === 'AI_BUY_ALERT') {
        const id=String(data.eventId || '');
        const expires=Number(data.expiresAt);
        if (!id || aiSeen.current.has(id) || !Number.isFinite(expires) || expires<=Date.now()) return;
        const quote=await fetchEntryQuote();
        if(disposed || !aiEntryAllowed(data,quote)) return;
        aiSeen.current.add(id);
        setAiCard({text:String(data.cardText),expiresAt:expires});
        soundService.playBuySignalChime();
        return;
      }
      if (data?.eventType==='POSITION_EXIT_NOTICE') {
        setActiveTab('system');
        try {await recordExitPush(data,origin==='opened'?'opened':'received');await flushExitReceipts();}
        catch {window.dispatchEvent(new CustomEvent('cryptog-exit-receipt-error'));}
        return;
      }
      if (origin === 'opened') {
        setActiveTab('signals');
        const msgId = data?.eventId || data?.id || data?.testId || data?.deliveryId;
        if (msgId) focusMessage(String(msgId));
      }
      const signal = parseCloudSignal(data);
      if (!signal) return; // Legacy/incomplete pushes cannot become fresh BUY signals.
      recordPhoneReceived(signal.id, signal.strategy, signal.timestamp, signal.entryPrice, origin === 'opened');
      const timeIssue = signalTimeIssue(signal);
      const quote = timeIssue ? null : await fetchEntryQuote();
      if (disposed) return;
      const issue = timeIssue || entryIssue(signal, quote);
      if (issue) {
        rememberAction({recordType: 'ENTRY_REJECTED', alertId: signal.id, actedAtMs: Date.now(), signalAtMs: signal.timestamp, signalPrice: signal.entryPrice, note: issue});
        setSignals(prev => prev.some(s => s.id === signal.id) ? prev : [{ ...signal, decisionStatus: 'BLOCK_ENTRY', actionBadgeZh: '失效 / 待复核', validityReason: issue }, ...prev.slice(0, 49)]);
        return;
      }
      handleTriggerSignal({ ...signal, decisionStatus: 'BUY_CANDIDATE', actionBadgeZh: '有效买入候选' });
    });

    // Instant unlock Web Audio context on any user touch/click/key
    const handleUnlockAudio = () => {
      soundService.unlockAudio();
    };
    window.addEventListener('pointerdown', handleUnlockAudio, { once: true });
    window.addEventListener('keydown', handleUnlockAudio, { once: true });

    // Focus & click clear tab title flash
    window.addEventListener('focus', clearTitleFlash);
    window.addEventListener('click', clearTitleFlash);

    const handleBeforeInstallPrompt = (e: Event) => {
      e.preventDefault();
      setDeferredPrompt(e);
      setIsInstallable(true);
    };
    window.addEventListener('beforeinstallprompt', handleBeforeInstallPrompt);

    return () => {
      disposed = true;
      document.removeEventListener('visibilitychange',resumePermission);
      window.clearInterval(permissionTimer);
      unsubscribeSignal();
      window.removeEventListener('pointerdown', handleUnlockAudio);
      window.removeEventListener('keydown', handleUnlockAudio);
      window.removeEventListener('focus', clearTitleFlash);
      window.removeEventListener('click', clearTitleFlash);
      window.removeEventListener('beforeinstallprompt', handleBeforeInstallPrompt);
    };
  }, [config.soundEnabled, config.soundVolume, clearTitleFlash, handleTriggerSignal]);

  // Only the server snapshot describes strategy state. A local price is not server health.
  useEffect(() => {
    let disposed = false;
    let busy = false;
    const refresh = async () => {
      if (busy) return;
      busy = true;
      try {
        const state = await fetchMarketState();
        if (!disposed) setMacroTrend(state);
      } catch { if (!disposed) setMacroTrend(unknownMarket()); }
      finally { busy = false; }
    };
    void refresh();
    void fetchAIState();
    const resume = () => {
      if (document.visibilityState !== 'visible') return;
      setMacroTrend(getInitialMarketState());
      void refresh();
      void fetchAIState();
    };
    document.addEventListener('visibilitychange', resume);
    const syncReceipts=()=>void flushExitReceipts().catch(()=>{});
    syncReceipts();
    const receiptTimer=window.setInterval(syncReceipts,15000);
    const timer = window.setInterval(() => void refresh(), 3000);
    return () => { disposed = true; document.removeEventListener('visibilitychange', resume); window.clearInterval(timer);window.clearInterval(receiptTimer); };
  }, []);

  // Global 24/7 AI Quantitative Scheduler (Active across all tabs)
  useEffect(() => {
    aiScheduler.start();
    return () => {
      aiScheduler.stop();
    };
  }, []);

  // Subscribe to Binance Stream & start scanner
  useEffect(() => {
    binanceService.startScanning(config.scanIntervalMs);

    const unsubscribe = binanceService.onTickersUpdate((updatedTickers) => {
      setTickers(updatedTickers);
      const btc = updatedTickers['BTCUSDT'];
      if (btc && btc.sparkline && btc.sparkline.length >= 5) {
        // Construct lightweight pseudo-candles for Layer 3 rapid drop detection
        const recentCandles = btc.sparkline.slice(-5).map((price, i) => ({
          open: price,
          high: price,
          low: price,
          close: price,
          volume: 1,
        }));
        void aiScheduler.checkEventTrigger(recentCandles);
      }
    });

    return () => {
      unsubscribe();
      binanceService.stopScanning();
    };
  }, [config.scanIntervalMs]);


  // Sound check only. This used to invent a BUY alert that had not passed the risk gates.
  const handleTriggerTestSignal = () => {
    soundService.playRadarTestPing();
  };


  const handleToggleSound = () => {
    const next = !config.soundEnabled;
    setConfig((c) => ({ ...c, soundEnabled: next }));
    soundService.setEnabled(next);
    if (next) soundService.playRadarTestPing();
  };

  const handleRequestPush = async () => {
    const granted = await notificationService.requestPermission();
    setHasNotificationPermission(granted);
    if (granted) {
      notificationService.sendPushNotification(
        '🔔 Crypto-G 买入通知已激活',
        '买入候选将推送至设备，打开后复核有效期与当前价格'
      );
    }
  };

  const handleInstallApp = async () => {
    if (deferredPrompt) {
      deferredPrompt.prompt();
      const { outcome } = await deferredPrompt.userChoice;
      if (outcome === 'accepted') {
        setIsInstallable(false);
        setDeferredPrompt(null);
      }
    }
  };

  const handleAddToPosition = (sig: TradeSignal, customAmount?: number, checkedPrice?: number) => {
    if (signalTimeIssue(sig) || !checkedPrice) return;
    if (watchlist.some(w=>w.symbol===sig.symbol && (w.positionEntryPrice || 0)>0)) { window.alert('已有模拟持仓，请先记录退出，避免覆盖原机会'); return; }
    const defaultSize = 5000;
    const existingSize = watchlist.find((w) => w.symbol === sig.symbol)?.positionSize || defaultSize;
    const finalSize = customAmount && customAmount > 0 ? customAmount : existingSize;
    try {
    recordSimBuy({
      alertId: sig.id,
      entryPrice: checkedPrice,
      positionSize: finalSize,
      strategy: sig.strategy,
      signalAtMs: sig.timestamp, signalPrice: sig.entryPrice,
    });
    } catch { window.alert('本机记录未保存，未创建模拟持仓'); return; }
    setWatchlist((prev) => {
      const exists = prev.some((w) => w.symbol === sig.symbol);
      const updatedItem: WatchlistItem = {
        symbol: sig.symbol,
        name: sig.coinName,
        positionEntryPrice: checkedPrice,
        positionSize: finalSize,
        alertAbovePrice: sig.targetTP1,
        alertBelowPrice: sig.stopLoss,
        addedAt: Date.now(),
        linkedAlertId: sig.id,
        linkedStrategy: sig.strategy,
        linkedTp1: sig.targetTP1,
        linkedTp2: sig.targetTP2,
        linkedSl: sig.stopLoss,
        linkedEngine: sig.engineVersion,
        linkedTradeRules: sig.tradeRules,
        positionDeadlineMs: sig.tradeRules ? Date.now() + sig.tradeRules.maxHoldMinutes * 60000 : undefined,
      };
      if (exists) {
        return prev.map((w) => (w.symbol === sig.symbol ? updatedItem : w));
      }
      return [...prev, updatedItem];
    });
    setActiveTab('watchlist');
  };

  return (
    <div className="min-h-screen bg-[#0f1115] text-[#e2e2e8] flex flex-col font-sans">
      {/* Top Header */}
      <Header
        soundEnabled={config.soundEnabled}
        onToggleSound={handleToggleSound}
        scanIntervalSec={config.scanIntervalMs / 1000}
        onTriggerTestSignal={handleTriggerTestSignal}
        onOpenInstallModal={() => setShowInstallModal(true)}
        isInstallable={isInstallable}
      />

      {/* Instant Notification Permission Prompt Strip */}
      {(checkingNotificationPermission || !hasNotificationPermission) && (
        <div className="bg-[#211a14] border-b border-[#3d2f21] px-3.5 py-1.5 text-xs text-[#fdd663] flex items-center justify-between gap-2 max-w-md mx-auto w-full">
          <div className="flex items-center gap-1.5 truncate">
            <span className="w-1.5 h-1.5 rounded-full bg-[#fdd663] animate-ping shrink-0"></span>
            <span className="truncate text-[11px]">
              {checkingNotificationPermission?'正在核验系统通知权限…':'系统通知未授权；请开启后进行锁屏推送测试'}
            </span>
          </div>
          <button
            disabled={checkingNotificationPermission}
            onClick={handleRequestPush}
            className="shrink-0 px-2.5 py-0.5 bg-[#fdd663] text-[#1c1803] font-semibold rounded-full text-[10px] hover:bg-[#ffe58f] transition-colors"
          >
            {checkingNotificationPermission?'核验中':'开启推送'}
          </button>
        </div>
      )}

      {/* Main Viewport Container (Optimized for Android Mobile Form Factor) */}
      <main className="flex-1 max-w-md w-full mx-auto px-3.5 pt-2 pb-6">
        {activeTab === 'radar' && (
          <RadarView
            tickers={tickers}
            latestSignals={signals}
            scanIntervalSec={config.scanIntervalMs / 1000}
            macroTrend={macroTrend}
            onSelectSignal={(s) => setActiveModalSignal(s)}
            onSwitchTab={setActiveTab}
            onTriggerTestSignal={handleTriggerTestSignal}
          />
        )}

        {activeTab === 'signals' && (
          <SignalsView
            signals={signals}
            macroTrend={macroTrend}
            onSelectSignal={(s) => setActiveModalSignal(s)}
            onAddToPosition={handleAddToPosition}
            onClearHistory={() => {
              setSignals([]);
              setUnreadCount(0);
            }}
            onSwitchTab={setActiveTab}
          />
        )}

        {activeTab === 'ai' && <AIQuantView macroTrend={macroTrend} />}

        {activeTab === 'watchlist' && (
          <WatchlistView
            watchlist={watchlist}
            tickers={tickers}
            onUpdateWatchlist={(item) =>
              setWatchlist((prev) =>
                prev.some((w) => w.symbol === item.symbol)
                  ? prev.map((w) => (w.symbol === item.symbol ? item : w))
                  : [...prev, item]
              )
            }
          />
        )}

        {(activeTab === 'system' || activeTab === 'strategy' || activeTab === 'server') && (
          <SystemGuardView
            config={config}
            macroTrend={macroTrend}
            onUpdateConfig={(updates) => setConfig((c) => ({ ...c, ...updates }))}
            onRequestNotificationPermission={handleRequestPush}
            hasNotificationPermission={hasNotificationPermission}
          />
        )}
      </main>

      {/* Fixed Bottom Ergonomic Thumb Tab Navigation */}
      <BottomNav
        activeTab={activeTab}
        onChangeTab={(tab) => {
          setActiveTab(tab);
          if (tab === 'signals') {
            setUnreadCount(0);
          }
        }}
        unreadSignalsCount={unreadCount}
      />

      {/* High-Priority Instant Signal Alert Modal Popup */}
      {aiCard && <div className="fixed inset-0 z-[100] bg-black/75 flex items-center justify-center p-4" role="dialog" aria-modal="true" aria-label="BTC买入机会">
        <div className="w-full max-w-md rounded-2xl border border-emerald-600 bg-[#121622] p-5">
          <p className="text-emerald-300 font-semibold mb-3">BTC 买入机会</p>
          <p className="whitespace-pre-line text-sm text-gray-100 leading-7">{aiCard.text}</p>
          <button className="mt-4 w-full rounded-lg bg-emerald-700 p-3 text-white" onClick={() => setAiCard(null)}>知道了</button>
        </div>
      </div>}
      <SignalAlertModal
        signal={activeModalSignal}
        onClose={() => setActiveModalSignal(null)}
        onAddToPosition={handleAddToPosition}
        watchlist={watchlist}
        defaultInvestmentAmount={
          watchlist.find((w) => w.symbol === (activeModalSignal?.symbol || 'BTCUSDT'))?.positionSize || 5000
        }
      />

      {/* PWA Install Guidance Modal */}
      <PWAInstallModal
        isOpen={showInstallModal}
        onClose={() => setShowInstallModal(false)}
        onInstall={handleInstallApp}
        isInstallable={isInstallable}
      />
    </div>
  );
}



