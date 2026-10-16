import React, { useState, useEffect } from 'react';
import {
  BrainCircuit,
  Bot,
  Sparkles,
  Zap,
  Settings2,
  RefreshCw,
  ShieldCheck,
  TrendingUp,
  AlertTriangle,
  ChevronDown,
  ChevronUp,
  Key,
  Copy,
  Check,
  Clock,
  Radio,
  Sliders,
  CheckCircle2,
  Activity,
  Layers,
  ArrowUpRight,
  ShieldAlert,
  Power,
  Sun,
} from 'lucide-react';
import {
  fetchAIState,
  verifyAIConnection,
  updateAIConfig,
  triggerAIAnalysis,
  aiScheduler,
  AIState,
  AIEvaluation,
  AIConfig,
} from '../../services/aiEngine';
import { binanceService } from '../../services/binanceService';
import { MarketTicker } from '../../types/crypto';

export const AIQuantView: React.FC = () => {
  // State from backend/local
  const [state, setState] = useState<AIState | null>(null);
  const [loading, setLoading] = useState(false);
  const [analyzing, setAnalyzing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showConfig, setShowConfig] = useState(false);
  const [showHistory, setShowHistory] = useState(false);
  const [copied, setCopied] = useState(false);

  // Live BTC Ticker
  const [btcTicker, setBtcTicker] = useState<MarketTicker | null>(null);

  // Config form state
  const [enabled, setEnabled] = useState(true);
  const [provider, setProvider] = useState<'GEMINI' | 'DEEPSEEK'>('GEMINI');
  const [model, setModel] = useState<string>('gemini-2.5-flash');
  const [apiKey, setApiKey] = useState<string>('');
  const [showApiKey, setShowApiKey] = useState(false);
  const [enabled5m, setEnabled5m] = useState(true);
  const [enabledEventTrigger, setEnabledEventTrigger] = useState(true);
  const [savingConfig, setSavingConfig] = useState(false);
  const [saveMessage, setSaveMessage] = useState<string | null>(null);

  // Global scheduler integration & live countdown
  const [countdownSec, setCountdownSec] = useState<number>(() => aiScheduler.getRemainingSeconds());
  const [keepScreenOn, setKeepScreenOn] = useState<boolean>(() => aiScheduler.isKeepScreenOn());

  // Subscribe to live BTC ticker
  useEffect(() => {
    const unsub = binanceService.onTickersUpdate((tickers) => {
      if (tickers['BTCUSDT']) {
        setBtcTicker(tickers['BTCUSDT']);
      }
    });
    return () => unsub();
  }, []);

  const loadState = async () => {
    try {
      const data = await fetchAIState();
      setState(data);
      setError(data.error || null);
      if (data.config && !showConfig) {
        setEnabled(data.config.enabled ?? true);
        setProvider(data.config.provider || 'GEMINI');
        setModel(data.config.model || 'gemini-2.5-flash');
        setEnabled5m(data.config.enabled5m ?? true);
        setEnabledEventTrigger(data.config.enabledEventTrigger ?? true);
      }
    } catch (e: any) {
      setError(e.message || '获取AI状态失败');
    }
  };

  useEffect(() => {
    loadState();
    const timer = setInterval(loadState, 15000);
    return () => clearInterval(timer);
  }, [showConfig]);

  // Subscribe to Global AI Scheduler events and smooth clock ticker
  useEffect(() => {
    const unsubscribe = aiScheduler.subscribe((event, data) => {
      if (event === 'START') {
        setAnalyzing(true);
      } else if (event === 'DONE') {
        setAnalyzing(false);
        void loadState();
      } else if (event === 'ERROR') {
        setAnalyzing(false);
        setError(data?.error || 'AI 分析异常');
        void loadState();
      } else if (event === 'TICK') {
        if (typeof data?.remainingSeconds === 'number') {
          setCountdownSec(data.remainingSeconds);
        }
      }
    });

    const clockTimer = setInterval(() => {
      setCountdownSec(aiScheduler.getRemainingSeconds());
      setAnalyzing(aiScheduler.getIsAnalyzing());
    }, 1000);

    return () => {
      unsubscribe();
      clearInterval(clockTimer);
    };
  }, []);

  const handleToggleWakeLock = async () => {
    const next = !keepScreenOn;
    setKeepScreenOn(next);
    await aiScheduler.setKeepScreenOn(next);
  };

  const handleToggleMasterSwitch = async () => {
    const nextEnabled = !state?.config?.enabled;
    setEnabled(nextEnabled);
    try {
      await updateAIConfig({ enabled: nextEnabled });
      await loadState();
    } catch (e: any) {
      setError(e.message || '更新开关失败');
    }
  };

  const handleTriggerAnalysis = async () => {
    setAnalyzing(true);
    setError(null);
    try {
      const res = await triggerAIAnalysis('MANUAL_UI');
      await loadState();
      if (!res.ok) {
        setError(res.error || 'AI推演未能生成有效结果');
      }
    } catch (e: any) {
      setError(e.message || '触发AI分析失败');
    } finally {
      setAnalyzing(false);
    }
  };

  const handleSaveConfig = async (e: React.FormEvent) => {
    e.preventDefault();
    setSavingConfig(true);
    setSaveMessage(null);
    try {
      const updates: Partial<AIConfig> = {
        enabled,
        provider,
        model,
        enabled5m,
        enabledEventTrigger,
      };
      if (apiKey.trim()) {
        updates.apiKey = apiKey.trim();
      }
      await updateAIConfig(updates);
      setApiKey('');
      setSaveMessage('云端已保存，正在验证所选模型…');
      const verification = await verifyAIConnection();
      setSaveMessage(verification.ok ? '云端已保存，API连接验证通过' : `云端已保存；验证失败：${verification.error}`);
      await loadState();

    } catch (e: any) {
      setSaveMessage(`❌ 保存失败: ${e.message}`);
    } finally {
      setSavingConfig(false);
    }
  };

  const pStr = (val?: number) =>
    val ? `$${val.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : '--';

  const copySignalParams = (evalData: AIEvaluation) => {
    const text = `【Crypto-G BTC AI量化买入预警】
场景: ${evalData.scenarioNameZh}
模型: ${evalData.provider} (${evalData.model}) | 信心度: ${evalData.confidence}%
建议买入区间: ${pStr(evalData.entryMin)} ~ ${pStr(evalData.entryMax)}
目标止盈 TP1: ${pStr(evalData.targetTP1)} (+${evalData.profitPercent1}%)
目标止盈 TP2: ${pStr(evalData.targetTP2)}
防守止损 SL: ${pStr(evalData.stopLoss)} (-${evalData.stopLossPercent}%)
预期持有期限: ${evalData.timeHorizon || '15分钟~2小时超短线'}
AI量化分析理由: ${evalData.summaryZh}`;
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const latestEval = state?.lastEvaluation;
  const isBuy = latestEval?.isBuy && Number(latestEval.expiresAt) > Date.now();
  const btcPrice = btcTicker?.price ?? 0;
  const btcChange = btcTicker?.change24h ?? 0;
  const isMasterEnabled = state?.config?.enabled ?? true;

  // Pretty model display name
  const getModelLabel = () => {
    const curModel = state?.config?.model || model;
    if (curModel.includes('3.8-flash')) return 'Gemini 3.8 Flash';
    if (curModel.includes('2.5-flash')) return 'Gemini 2.5 Flash';
    if (curModel.includes('2.5-pro')) return 'Gemini 2.5 Pro';
    if (curModel.includes('deepseek-chat')) return 'DeepSeek-V3';
    if (curModel.includes('deepseek-reasoner')) return 'DeepSeek-R1';
    return curModel;
  };

  return (
    <div className="space-y-3 pb-6 animate-fadeIn">
      <section className="rounded-2xl border border-indigo-500/25 bg-[#141824] p-3 space-y-2.5">
        <div className="flex items-center justify-between gap-2">
          <h1 className="flex items-center gap-2 text-sm font-semibold text-white min-w-0">
            <BrainCircuit className="w-4 h-4 shrink-0 text-indigo-400" />
            <span className="whitespace-nowrap">BTC AI 量化大脑</span>
          </h1>
          <button onClick={handleToggleMasterSwitch} aria-label={isMasterEnabled ? '暂停 AI 监控' : '开启 AI 监控'}
            className={`shrink-0 flex items-center gap-1.5 min-h-9 px-2 rounded-lg text-[11px] whitespace-nowrap border ${isMasterEnabled ? 'text-emerald-300 border-emerald-800 bg-emerald-950/40' : 'text-gray-400 border-gray-700 bg-gray-800'}`}>
            <span className={`w-1.5 h-1.5 rounded-full ${isMasterEnabled ? 'bg-emerald-400' : 'bg-gray-500'}`} />
            {isMasterEnabled ? '监控已开' : '监控暂停'}
          </button>
        </div>
        <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 text-[11px]">
          <span className="text-indigo-300">{getModelLabel()}</span>
          <div className="flex items-baseline gap-1.5 font-mono whitespace-nowrap">
            <span className="text-white font-semibold">{btcPrice > 0 ? `$${btcPrice.toLocaleString(undefined, {minimumFractionDigits:2, maximumFractionDigits:2})}` : '行情连接中'}</span>
            {btcPrice > 0 && <span className={btcChange >= 0 ? 'text-emerald-400' : 'text-rose-400'}>{btcChange >= 0 ? '+' : ''}{btcChange.toFixed(2)}%</span>}
          </div>
        </div>
        <div className="grid grid-cols-[1fr_auto] gap-2 border-t border-gray-800 pt-2.5">
          <button onClick={handleTriggerAnalysis} disabled={analyzing}
            className="flex items-center justify-center gap-1.5 min-h-10 px-3 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-xs font-medium text-white disabled:opacity-50">
            <Zap className={`w-3.5 h-3.5 ${analyzing ? 'animate-pulse' : ''}`} />
            {analyzing ? '正在分析…' : '立即分析'}
          </button>
          <button onClick={() => setShowConfig(!showConfig)} aria-expanded={showConfig}
            className="flex items-center justify-center gap-1.5 min-h-10 px-3 rounded-lg border border-gray-700 bg-[#1b2030] text-[11px] text-gray-300">
            <Settings2 className="w-3.5 h-3.5" />{showConfig ? '收起设置' : '模型设置'}
          </button>
        </div>
      </section>

      {/* Error Alert Bar */}
      {error && (
        <div className="flex items-center gap-2 p-2.5 rounded-xl bg-red-950/40 border border-red-800/50 text-red-300 text-xs shadow-sm">
          <AlertTriangle className="w-4 h-4 shrink-0 text-red-400" />
          <span className="flex-1 text-[11px] leading-snug">{error}</span>
          <button onClick={() => setError(null)} className="text-gray-400 hover:text-white text-xs px-1">
            ✕
          </button>
        </div>
      )}

      {/* 3. Inline Model & API Key Configuration Drawer */}
      {showConfig && (
        <form
          onSubmit={handleSaveConfig}
          className="rounded-2xl bg-[#141824] border border-indigo-500/30 p-4 space-y-3.5 text-xs text-gray-200 shadow-xl animate-fadeIn"
        >
          <div className="flex items-center justify-between border-b border-gray-800 pb-2">
            <span className="font-semibold text-white flex items-center gap-1.5 text-xs">
              <Sliders className="w-4 h-4 text-indigo-400" />
              AI 大脑模型与参数配置
            </span>
            <button
              type="button"
              onClick={() => setShowConfig(false)}
              className="text-gray-400 hover:text-white text-xs px-1.5 py-0.5 rounded"
            >
              ✕
            </button>
          </div>

          {/* Provider Selection */}
          <div>
            <label className="block text-[11px] text-gray-400 mb-1.5 font-medium">选择 AI 平台</label>
            <div className="grid grid-cols-2 gap-2">
              <button
                type="button"
                onClick={() => {
                  setApiKey('');
                  setProvider('GEMINI');
                  setModel('gemini-2.5-flash');
                }}
                className={`py-2 px-3 rounded-xl font-medium text-xs border text-center transition flex items-center justify-center gap-1.5 ${
                  provider === 'GEMINI'
                    ? 'bg-indigo-900/60 border-indigo-500 text-white font-semibold shadow-inner'
                    : 'bg-[#181d2c] border-gray-700/80 text-gray-400 hover:text-gray-200'
                }`}
              >
                <Sparkles className="w-3.5 h-3.5 text-indigo-400" />
                Google Gemini
              </button>
              <button
                type="button"
                onClick={() => {
                  setApiKey('');
                  setProvider('DEEPSEEK');
                  setModel('deepseek-chat');
                }}
                className={`py-2 px-3 rounded-xl font-medium text-xs border text-center transition flex items-center justify-center gap-1.5 ${
                  provider === 'DEEPSEEK'
                    ? 'bg-indigo-900/60 border-indigo-500 text-white font-semibold shadow-inner'
                    : 'bg-[#181d2c] border-gray-700/80 text-gray-400 hover:text-gray-200'
                }`}
              >
                <Bot className="w-3.5 h-3.5 text-blue-400" />
                DeepSeek (深度求索)
              </button>
            </div>
          </div>

          {/* Model Selection */}
          <div>
            <label className="block text-[11px] text-gray-400 mb-1.5 font-medium">量化推演模型</label>
            <select
              value={model}
              onChange={(e) => setModel(e.target.value)}
              className="w-full bg-[#10131d] border border-gray-700 rounded-xl px-3 py-2 text-xs text-white focus:outline-none focus:border-indigo-500"
            >
              {provider === 'GEMINI' ? (
                <>
                  <option value="gemini-2.5-flash">Gemini 3.8 Flash (推荐 · 极速毫秒级量化)</option>
                  <option value="gemini-2.5-flash">Gemini 2.5 Flash (短线平衡)</option>
                  <option value="gemini-2.5-pro">Gemini 2.5 Pro (深度大模型思考)</option>
                </>
              ) : (
                <>
                  <option value="deepseek-chat">DeepSeek-V3 / Chat (推荐 · 高性价比短线)</option>
                  <option value="deepseek-reasoner">DeepSeek-R1 / Reasoner (深度推理链)</option>
                </>
              )}
            </select>
          </div>

          {/* API Key Input */}
          <div>
            <div className="flex items-center justify-between mb-1.5">
              <label className="text-[11px] text-gray-400 font-medium flex items-center gap-1">
                <Key className="w-3.5 h-3.5 text-indigo-400" />
                <span>{provider === 'GEMINI' ? 'Gemini' : 'DeepSeek'} API Key</span>
              </label>
              {state?.config?.apiKey && provider === state.config.provider && (
                <span className="text-[10px] text-emerald-400 font-mono">
                  云端已保存: {state.config.apiKey}
                </span>
              )}
            </div>
            <div className="relative">
              <input
                type={showApiKey ? 'text' : 'password'}
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                placeholder={state?.hasApiKey ? '输入新密钥以替换；留空保留云端密钥' : '粘贴您的 API Key'}
                className="w-full bg-[#10131d] border border-gray-700 rounded-xl px-3 py-2 text-xs text-white placeholder-gray-500 focus:outline-none focus:border-indigo-500 pr-14 font-mono"
              />
              <button
                type="button"
                onClick={() => setShowApiKey(!showApiKey)}
                className="absolute right-2.5 top-2 text-[10px] text-gray-400 hover:text-white px-1"
              >
                {showApiKey ? '隐藏' : '显示'}
              </button>
            </div>
          </div>

          {/* Autonomous Scan Switches */}
          <div className="space-y-2 pt-1 border-t border-gray-800">
            <label className="flex items-center justify-between p-2 rounded-xl bg-[#10131d] border border-gray-800/80 cursor-pointer">
              <div className="pr-2">
                <span className="text-[11px] text-gray-200 font-medium block">5分钟周期常规扫描</span>
                <span className="text-[10px] text-gray-500">每根5分钟K线收盘后，AI自主独立量化推演</span>
              </div>
              <input
                type="checkbox"
                checked={enabled5m}
                onChange={(e) => setEnabled5m(e.target.checked)}
                className="w-4 h-4 rounded border-gray-700 text-indigo-600 focus:ring-0 cursor-pointer"
              />
            </label>
            <label className="flex items-center justify-between p-2 rounded-xl bg-[#10131d] border border-gray-800/80 cursor-pointer">
              <div className="pr-2">
                <span className="text-[11px] text-gray-200 font-medium block">突发行情加速唤醒</span>
                <span className="text-[10px] text-gray-500">急跌 ≥ 1% 或异常放量时提前唤醒分析 (防踏空)</span>
              </div>
              <input
                type="checkbox"
                checked={enabledEventTrigger}
                onChange={(e) => setEnabledEventTrigger(e.target.checked)}
                className="w-4 h-4 rounded border-gray-700 text-indigo-600 focus:ring-0 cursor-pointer"
              />
            </label>
          </div>

          <button type="button" className="text-xs text-red-300" onClick={async () => {
            if (!window.confirm('删除当前所选厂商的云端密钥？')) return;
            try { await updateAIConfig({provider, deleteKey:true}); setSaveMessage('云端密钥已删除'); await loadState(); }
            catch (e:any) { setSaveMessage(e.message); }
          }}>删除所选厂商云端密钥</button>

          {saveMessage && (
            <div className="text-xs p-2 rounded-xl bg-gray-900 border border-gray-700 text-center font-medium">
              {saveMessage}
            </div>
          )}

          <div className="flex gap-2 pt-1">
            <button
              type="submit"
              disabled={savingConfig}
              className="flex-1 bg-indigo-600 hover:bg-indigo-500 py-2 rounded-xl text-white font-medium text-xs transition disabled:opacity-50 shadow-md"
            >
              {savingConfig ? '正在应用...' : '保存并生效配置'}
            </button>
            <button
              type="button"
              onClick={() => setShowConfig(false)}
              className="px-4 py-2 rounded-xl bg-gray-800 text-gray-300 text-xs hover:bg-gray-700 transition"
            >
              取消
            </button>
          </div>
        </form>
      )}

      {/* 4. Main Decision Verdict Display (Buy Signal or Defense/Standby) */}
      {latestEval ? (
        isBuy ? (
          <div className="rounded-xl border border-emerald-700 bg-emerald-950/20 p-4 text-xs space-y-3">
            <strong>BTC 交易预警卡片</strong>
            <p className="whitespace-pre-line leading-7">{latestEval.cardText || '旧版信号，请重新分析'}</p>
            <p className="text-amber-300">入场有效至 {latestEval.expiresAt ? new Date(latestEval.expiresAt).toLocaleTimeString() : '未知'}；过期须重新复核。</p>
            <button onClick={() => navigator.clipboard.writeText(latestEval.cardText || '')}>复制卡片</button>
          </div>
        ) : (
          <div className="rounded-2xl border border-gray-800 bg-gradient-to-b from-[#141824] to-[#10131d] p-3.5 space-y-2 text-xs shadow-lg">
            <div className="flex flex-wrap items-center justify-between gap-2 text-gray-400">
              <span className="flex items-center gap-1.5 text-xs text-gray-200 font-medium">
                <Radio className="w-3.5 h-3.5 text-amber-400" />
                <span><strong className="text-amber-300">观望防守 · 无合规买点</strong></span>
              </span>
              <span className="text-[10px] font-mono text-gray-500">
                {new Date(latestEval.atMs).toLocaleTimeString()}
              </span>
            </div>
            <p className="text-[11px] text-gray-300 leading-relaxed bg-[#0c0f18] p-2.5 rounded-xl border border-gray-800/60">
              {latestEval.summaryZh || '大盘未达反弹企稳或突破确认门禁，规避下行飞刀杂波。'}
            </p>
          </div>
        )
      ) : !state?.hasApiKey ? (
        <div className="rounded-2xl border border-indigo-500/30 bg-gradient-to-b from-[#141828] to-[#0f121d] p-5 text-center space-y-3 shadow-xl">
          <div className="w-12 h-12 mx-auto rounded-2xl bg-indigo-500/20 border border-indigo-500/30 flex items-center justify-center text-indigo-400 shadow-inner">
            <Sparkles className="w-6 h-6" />
          </div>
          <div>
            <h3 className="text-sm font-bold text-white">BTC AI 量化大脑就绪</h3>
            <p className="text-[11px] text-gray-400 mt-1 max-w-xs mx-auto leading-relaxed">
              输入 Google Gemini 或 DeepSeek API Key 后，AI 将每 5 分钟在 K 线收盘后独立推演 BTC 买点。
            </p>
          </div>
          <button
            onClick={() => setShowConfig(true)}
            className="inline-flex items-center gap-1.5 px-4 py-2 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white font-semibold text-xs shadow-md transition"
          >
            <Key className="w-3.5 h-3.5" />
            <span>立即配置 API 密钥</span>
          </button>
        </div>
      ) : (
        <div className="rounded-2xl border border-gray-800 bg-[#121622] p-4 text-center space-y-1.5 text-xs text-gray-400 shadow-md">
          <Bot className="w-7 h-7 mx-auto text-indigo-400/80 mb-1" />
          <p className="text-white font-medium">AI 监控就绪</p>
          <p className="text-[11px] text-gray-500">
            等待下一个 5 分钟 K 线收盘自动推演，或点击上方“立即分析”。
          </p>
        </div>
      )}

      {!!state?.trackedPlans?.length && <details className="rounded-xl border border-gray-700 p-3 text-xs">
        <summary>AI 计划跟踪（不代表已买入）</summary>
        <p className="text-gray-400 my-2">按信号时刻观察结构与目标；实际持仓请以成交记录为准。</p>
        {state.trackedPlans.map(plan => <div key={plan.id} className="border-t border-gray-800 py-2">
          {plan.scenarioNameZh} · {{WATCHING:'观察中',STRUCTURE_BROKEN:'结构失效',TARGET_REACHED:'目标已触及',HORIZON_ENDED:'计划周期结束'}[plan.trackingState || ''] || '旧版计划'}
          <p>当前防守参考：{pStr(plan.trailingStop || plan.stopLoss)}{plan.trackingHealth === 'QUOTE_UNAVAILABLE' ? ' · 行情不可用，暂停更新' : ''}</p>
        </div>)}
      </details>}

      {/* 7. History & Stats Footer */}
      <div className="rounded-2xl border border-gray-800/80 bg-[#121520] p-3.5 space-y-2 shadow-md">
        <div className="flex items-center justify-between text-xs text-gray-400">
          <div className="flex items-center gap-3">
            <span>总推演: <strong className="text-white font-mono">{state?.evalCount ?? 0}</strong> 次</span>
            <span>买入机会: <strong className="text-emerald-400 font-mono">{state?.buyCount ?? 0}</strong> 次</span>
          </div>
          <button
            onClick={() => setShowHistory(!showHistory)}
            className="text-indigo-400 hover:text-indigo-300 flex items-center gap-1 font-medium transition"
          >
            <span>历史记录 ({state?.recentEvaluations?.length || 0})</span>
            {showHistory ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
          </button>
        </div>

        {/* History Evaluations Dropdown List */}
        {showHistory && (
          <div className="pt-2 border-t border-gray-800/80 space-y-2 max-h-56 overflow-y-auto pr-1">
            {state?.recentEvaluations && state.recentEvaluations.length > 0 ? (
              state.recentEvaluations.map((ev) => (
                <div
                  key={ev.id}
                  className={`p-2.5 rounded-xl border text-xs space-y-1 transition ${
                    ev.isBuy
                      ? 'border-emerald-700/50 bg-emerald-950/20 text-emerald-200'
                      : 'border-gray-800 bg-[#0d1018] text-gray-400'
                  }`}
                >
                  <div className="flex items-center justify-between text-[11px]">
                    <span className="font-semibold">
                      {ev.isBuy ? `🟢 ${ev.scenarioNameZh}` : '⚪ 观望防守'}
                    </span>
                    <span className="font-mono text-gray-500 text-[10px]">
                      {new Date(ev.atMs).toLocaleTimeString()} ({ev.triggerReason})
                    </span>
                  </div>
                  <p className="text-[11px] text-gray-300 truncate">{ev.summaryZh}</p>
                </div>
              ))
            ) : (
              <div className="text-center py-3 text-gray-500 text-xs">暂无历史推演记录</div>
            )}
          </div>
        )}
      </div>
      <details className="group rounded-xl border border-gray-800 bg-[#121622] text-xs">
        <summary className="flex cursor-pointer list-none items-center justify-between gap-2 p-3 text-gray-300 [&::-webkit-details-marker]:hidden">
          <span className="flex items-center gap-1.5"><Activity className="w-3.5 h-3.5 text-indigo-400" />运行状态</span>
          <span className="flex items-center gap-2 text-[10px]">
            <span className={error ? 'text-amber-300' : 'text-gray-400'}>{error ? '连接或分析异常' : !state ? '正在同步' : !state.hasApiKey ? '待配置密钥' : state.isAnalyzing ? '分析中' : !isMasterEnabled ? '监控暂停' : '计划已开启'}</span>
            <ChevronDown className="w-3.5 h-3.5 group-open:rotate-180 transition-transform" />
          </span>
        </summary>
        <div className="border-t border-gray-800 p-3 space-y-2.5">
          <p className="text-[11px] text-gray-400">{state?.config.connectionStatus === 'VERIFIED' ? 'API 已验证' : state?.hasApiKey ? '密钥已保存，连接待验证' : '尚未配置密钥'}</p>
          <button onClick={handleToggleWakeLock} className="min-h-9 px-2 rounded-lg border border-gray-700 text-[11px] text-gray-400">屏幕常亮：{keepScreenOn ? '开' : '关'}</button>
        {/* Live Countdown & Stats Strip */}
        <div className="grid grid-cols-2 gap-2 text-[11px] font-mono">
          <div className="rounded-xl bg-black/30 border border-gray-800/80 px-2.5 py-1.5 flex items-center justify-between">
            <span className="text-gray-400">⏱️ {Number(state?.retryAtMs) > Date.now() ? '失败后重试:' : '下次计划:'}</span>
            <span className="font-bold text-indigo-300">
              {analyzing ? (
                <span className="text-amber-400 animate-pulse">正在推演...</span>
              ) : isMasterEnabled && state?.hasApiKey ? (
                countdownSec <= 0 ? '00:00 (即将触发)' : `${Math.floor(countdownSec / 60).toString().padStart(2, '0')}:${(countdownSec % 60).toString().padStart(2, '0')}`
              ) : (
                '--:--'
              )}
            </span>
          </div>
          <div className="rounded-xl bg-black/30 border border-gray-800/80 px-2.5 py-1.5 flex items-center justify-between">
            <span className="text-gray-400">📊 累计分析:</span>
            <span className="font-bold text-white">{state?.evalCount || 0} 次</span>
          </div>
        </div>

        <p className="text-[11px] text-gray-400 leading-relaxed">
          {isMasterEnabled && state?.hasApiKey
            ? '云端按已收盘K线持续调度；异常时显示具体原因与重试时间。手机无需保持常亮。'
            : !state?.hasApiKey
            ? '请点击“模型与密钥配置”输入 Gemini 或 DeepSeek API Key 激活自主监控。'
            : 'AI 智能监控已手动暂停，点击上方“AI监控: 已暂停”开关可立即重新开启。'}
        </p>

        {latestEval && (
          <div className="flex items-center justify-between pt-1 border-t border-gray-800/80 text-[10px] text-gray-400 font-mono">
            <span>上次推演: {new Date(latestEval.atMs).toLocaleTimeString()} ({latestEval.triggerReason})</span>
            <span className={latestEval.isBuy ? 'text-emerald-400 font-bold' : 'text-gray-300'}>
              {latestEval.isBuy ? `🟢 ${latestEval.scenarioNameZh}` : '⚪ 观望防守'}
            </span>
          </div>
        )}
        </div>
      </details>

      <details className="group rounded-xl border border-gray-800 bg-[#121622] text-xs">
        <summary className="flex cursor-pointer list-none items-center justify-between p-3 text-gray-300 [&::-webkit-details-marker]:hidden">
          <span className="flex items-center gap-1.5"><Layers className="w-3.5 h-3.5 text-indigo-400" />扫描方式</span>
          <ChevronDown className="w-3.5 h-3.5 group-open:rotate-180 transition-transform" />
        </summary>
        <div className="border-t border-gray-800 p-3 space-y-2 text-[11px] text-gray-400 leading-relaxed">
          <p>实时监测：追踪 BTC 盘口与价格变化。</p>
          <p>定时分析：按已收盘的 5 分钟 K 线独立分析。</p>
          <p>突发加速：急跌或异常放量时提前唤醒分析。</p>
        </div>
      </details>
      <details className="group rounded-xl border border-gray-800 bg-[#121622] text-xs">
        <summary className="flex cursor-pointer list-none items-center justify-between p-3 text-gray-300 [&::-webkit-details-marker]:hidden">
          <span className="flex items-center gap-1.5"><ShieldCheck className="w-3.5 h-3.5 text-emerald-400" />买入复核规则</span>
          <ChevronDown className="w-3.5 h-3.5 group-open:rotate-180 transition-transform" />
        </summary>
        <div className="border-t border-gray-800 p-3 space-y-2 text-[11px] text-gray-400 leading-relaxed">
          <p>价格区间：最新卖一价未超过建议买入上限，超出即失效。</p>
          <p>止损结构：价格未跌破防守位，扣费净盈亏比 ≥ 1.10:1。</p>
          <p>交易成本：扣除 0.11% 手续费与滑点，净 TP1 ≥ 0.40%。</p>
        </div>
      </details>
    </div>
  );
};
