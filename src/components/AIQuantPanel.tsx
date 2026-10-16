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
} from 'lucide-react';
import {
  fetchAIState,
  updateAIConfig,
  triggerAIAnalysis,
  AIState,
  AIEvaluation,
  AIConfig,
} from '../services/aiEngine';

export const AIQuantPanel: React.FC = () => {
  const [state, setState] = useState<AIState | null>(null);
  const [loading, setLoading] = useState(false);
  const [analyzing, setAnalyzing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showConfig, setShowConfig] = useState(false);
  const [showHistory, setShowHistory] = useState(false);
  const [copied, setCopied] = useState(false);

  // Config form state
  const [provider, setProvider] = useState<'GEMINI' | 'DEEPSEEK'>('GEMINI');
  const [model, setModel] = useState<string>('gemini-2.5-flash');
  const [apiKey, setApiKey] = useState<string>('');
  const [showApiKey, setShowApiKey] = useState(false);
  const [enabled5m, setEnabled5m] = useState(true);
  const [enabledEventTrigger, setEnabledEventTrigger] = useState(true);
  const [savingConfig, setSavingConfig] = useState(false);
  const [saveMessage, setSaveMessage] = useState<string | null>(null);

  const loadState = async () => {
    try {
      const data = await fetchAIState();
      setState(data);
      setError(data.error || null);
      if (data.config) {
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
    const timer = setInterval(loadState, 15000); // refresh every 15s
    return () => clearInterval(timer);
  }, []);

  const handleTriggerAnalysis = async () => {
    setAnalyzing(true);
    setError(null);
    try {
      const res = await triggerAIAnalysis();
      await loadState();
      if (!res.ok) {
        setError(res.error || 'AI分析未能生成有效结果');
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
      setSaveMessage('✅ AI参数配置已成功同步并生效！');
      await loadState();
      setTimeout(() => {
        setSaveMessage(null);
        setShowConfig(false);
      }, 1500);
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
  const isBuy = latestEval?.isBuy;

  return (
    <div className="rounded-xl border border-indigo-500/30 bg-[#121620] p-3 space-y-2.5 shadow-md">
      {/* Top Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <div className="p-1.5 rounded-lg bg-indigo-500/20 text-indigo-400">
            <BrainCircuit className="w-4 h-4" />
          </div>
          <div>
            <div className="flex items-center gap-1.5">
              <span className="text-xs font-semibold text-white">BTC AI 量化大脑</span>
              <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-indigo-900/60 text-indigo-300 font-mono">
                {state?.config?.provider === 'DEEPSEEK' ? 'DeepSeek' : 'Gemini'}{' '}
                {state?.config?.model ? state.config.model.replace('gemini-', '').replace('deepseek-', '') : '3.8 Flash'}
              </span>
              {state?.hasApiKey ? (
                <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-emerald-900/60 text-emerald-300">
                  已配置密钥
                </span>
              ) : (
                <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-amber-900/60 text-amber-300">
                  未配置Key
                </span>
              )}
            </div>
            <p className="text-[10px] text-gray-400">
              5分钟周期完整分析 · 突发行情事件加速 · 买入前快速复核防跑飞
            </p>
          </div>
        </div>

        <div className="flex items-center gap-1">
          <button
            onClick={() => setShowConfig(!showConfig)}
            className="p-1.5 rounded-lg bg-gray-800 text-gray-300 hover:text-white hover:bg-gray-700 transition"
            title="配置模型与API Key"
          >
            <Settings2 className="w-3.5 h-3.5" />
          </button>
          <button
            onClick={handleTriggerAnalysis}
            disabled={analyzing}
            className={`flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-[11px] font-medium transition ${
              analyzing
                ? 'bg-indigo-700/60 text-indigo-200 cursor-not-allowed'
                : 'bg-indigo-600 hover:bg-indigo-500 text-white shadow-sm'
            }`}
          >
            <Zap className={`w-3.5 h-3.5 ${analyzing ? 'animate-spin' : ''}`} />
            <span>{analyzing ? '深度分析中...' : '立即分析'}</span>
          </button>
        </div>
      </div>

      {/* Error or Alert Bar */}
      {error && (
        <div className="flex items-center gap-1.5 p-2 rounded-lg bg-red-950/40 border border-red-800/50 text-red-300 text-[11px]">
          <AlertTriangle className="w-3.5 h-3.5 shrink-0" />
          <span className="truncate">{error}</span>
        </div>
      )}

      {/* Configuration Drawer/Modal Inline */}
      {showConfig && (
        <form
          onSubmit={handleSaveConfig}
          className="rounded-lg bg-[#181d2a] border border-gray-700 p-3 space-y-2.5 text-xs text-gray-200"
        >
          <div className="flex items-center justify-between border-b border-gray-700 pb-1.5">
            <span className="font-semibold text-white flex items-center gap-1">
              <Settings2 className="w-3.5 h-3.5 text-indigo-400" />
              AI 量化大脑参数配置
            </span>
            <button
              type="button"
              onClick={() => setShowConfig(false)}
              className="text-gray-400 hover:text-white"
            >
              ✕
            </button>
          </div>

          {/* Provider Selection */}
          <div>
            <label className="block text-[11px] text-gray-400 mb-1">AI 厂商与引擎</label>
            <div className="grid grid-cols-2 gap-2">
              <button
                type="button"
                onClick={() => {
                  setProvider('GEMINI');
                  setModel('gemini-2.5-flash');
                }}
                className={`py-1.5 px-2 rounded-lg font-medium text-xs border text-center transition ${
                  provider === 'GEMINI'
                    ? 'bg-indigo-900/60 border-indigo-500 text-white'
                    : 'bg-gray-800 border-gray-700 text-gray-400'
                }`}
              >
                Google Gemini
              </button>
              <button
                type="button"
                onClick={() => {
                  setProvider('DEEPSEEK');
                  setModel('deepseek-chat');
                }}
                className={`py-1.5 px-2 rounded-lg font-medium text-xs border text-center transition ${
                  provider === 'DEEPSEEK'
                    ? 'bg-indigo-900/60 border-indigo-500 text-white'
                    : 'bg-gray-800 border-gray-700 text-gray-400'
                }`}
              >
                DeepSeek (深度求索)
              </button>
            </div>
          </div>

          {/* Model Selection */}
          <div>
            <label className="block text-[11px] text-gray-400 mb-1">选择量化模型</label>
            <select
              value={model}
              onChange={(e) => setModel(e.target.value)}
              className="w-full bg-[#121620] border border-gray-700 rounded-lg px-2.5 py-1.5 text-xs text-white focus:outline-none focus:border-indigo-500"
            >
              {provider === 'GEMINI' ? (
                <>
                  <option value="gemini-2.5-flash">Gemini 3.8 Flash (推荐·极速云端分析)</option>
                  <option value="gemini-2.5-flash">Gemini 2.5 Flash (短线平衡)</option>
                  <option value="gemini-2.5-pro">Gemini 2.5 Pro (深度长程思考)</option>
                </>
              ) : (
                <>
                  <option value="deepseek-chat">DeepSeek-V3 / Chat (推荐短线)</option>
                  <option value="deepseek-reasoner">DeepSeek-R1 / Reasoner (深度推理链)</option>
                </>
              )}
            </select>
          </div>

          {/* API Key Input */}
          <div>
            <div className="flex items-center justify-between mb-1">
              <label className="text-[11px] text-gray-400 flex items-center gap-1">
                <Key className="w-3 h-3 text-indigo-400" />
                <span>{provider} API Key</span>
              </label>
              {state?.config?.apiKey && (
                <span className="text-[10px] text-gray-400 font-mono">
                  当前: {state.config.apiKey}
                </span>
              )}
            </div>
            <div className="relative">
              <input
                type={showApiKey ? 'text' : 'password'}
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                placeholder={state?.hasApiKey ? '留空则保留原密钥' : '输入您的 API Key'}
                className="w-full bg-[#121620] border border-gray-700 rounded-lg px-2.5 py-1.5 text-xs text-white placeholder-gray-500 focus:outline-none focus:border-indigo-500 pr-12 font-mono"
              />
              <button
                type="button"
                onClick={() => setShowApiKey(!showApiKey)}
                className="absolute right-2 top-1.5 text-[10px] text-gray-400 hover:text-white"
              >
                {showApiKey ? '隐藏' : '显示'}
              </button>
            </div>
          </div>

          {/* Toggles */}
          <div className="space-y-1.5 pt-1">
            <label className="flex items-center justify-between p-1.5 rounded-lg bg-[#121620] cursor-pointer">
              <span className="text-[11px]">每5分钟AI自主完整分析 (K线收盘)</span>
              <input
                type="checkbox"
                checked={enabled5m}
                onChange={(e) => setEnabled5m(e.target.checked)}
                className="rounded border-gray-700 text-indigo-600 focus:ring-0"
              />
            </label>
            <label className="flex items-center justify-between p-1.5 rounded-lg bg-[#121620] cursor-pointer">
              <span className="text-[11px]">突发行情加速分析 (急跌≥1%/爆量)</span>
              <input
                type="checkbox"
                checked={enabledEventTrigger}
                onChange={(e) => setEnabledEventTrigger(e.target.checked)}
                className="rounded border-gray-700 text-indigo-600 focus:ring-0"
              />
            </label>
          </div>

          {saveMessage && (
            <div className="text-[11px] p-1.5 rounded bg-gray-900 border border-gray-700 text-center">
              {saveMessage}
            </div>
          )}

          <div className="flex gap-2 pt-1">
            <button
              type="submit"
              disabled={savingConfig}
              className="flex-1 bg-indigo-600 hover:bg-indigo-500 py-1.5 rounded-lg text-white font-medium text-xs transition disabled:opacity-50"
            >
              {savingConfig ? '正在保存...' : '保存并应用配置'}
            </button>
            <button
              type="button"
              onClick={() => setShowConfig(false)}
              className="px-3 py-1.5 rounded-lg bg-gray-700 text-gray-300 text-xs hover:bg-gray-600 transition"
            >
              取消
            </button>
          </div>
        </form>
      )}

      {/* Main Signal Display */}
      {latestEval ? (
        isBuy ? (
          <div className="rounded-lg border border-emerald-500/40 bg-emerald-950/20 p-3 space-y-2">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-1.5">
                <span className="px-2 py-0.5 rounded bg-emerald-600 text-white font-bold text-xs tracking-wide">
                  AI 量化买入
                </span>
                <span className="text-xs font-semibold text-emerald-300">
                  {latestEval.scenarioNameZh}
                </span>
              </div>
              <div className="flex items-center gap-1 text-[11px] font-mono text-emerald-400">
                <ShieldCheck className="w-3.5 h-3.5" />
                <span>置信度 {latestEval.confidence}%</span>
              </div>
            </div>

            {/* Core Price Levels Grid */}
            <div className="grid grid-cols-2 gap-2 p-2 rounded-lg bg-[#0e161c]/80 border border-emerald-900/40 text-xs">
              <div>
                <span className="text-[10px] text-gray-400 block">建议买入区间</span>
                <span className="font-mono text-emerald-300 font-semibold">
                  {pStr(latestEval.entryMin)} ~ {pStr(latestEval.entryMax)}
                </span>
              </div>
              <div>
                <span className="text-[10px] text-gray-400 block">目标止盈 TP1 (扣费净利)</span>
                <span className="font-mono text-white font-semibold">
                  {pStr(latestEval.targetTP1)}{' '}
                  <span className="text-emerald-400 text-[10px]">
                    (+{latestEval.profitPercent1 ?? '--'}%)
                  </span>
                </span>
              </div>
              <div>
                <span className="text-[10px] text-gray-400 block">防守止损 SL (结构位)</span>
                <span className="font-mono text-rose-400 font-semibold">
                  {pStr(latestEval.stopLoss)}{' '}
                  <span className="text-[10px]">(-{latestEval.stopLossPercent ?? '--'}%)</span>
                </span>
              </div>
              <div>
                <span className="text-[10px] text-gray-400 block">净盈亏比 (RR) & 持有期限</span>
                <span className="font-mono text-gray-200">
                  {latestEval.riskRewardRatio ?? '--'}:1 ·{' '}
                  <span className="text-[10px] text-gray-400">{latestEval.timeHorizon}</span>
                </span>
              </div>
            </div>

            {/* AI Reasoning Summary */}
            <p className="text-[11px] text-gray-300 leading-relaxed bg-[#111622] p-2 rounded-lg border border-gray-800">
              <strong className="text-indigo-300">量化推理: </strong>
              {latestEval.summaryZh}
            </p>

            <div className="flex items-center justify-between pt-1">
              <span className="text-[10px] text-gray-400 flex items-center gap-1">
                <Clock className="w-3 h-3" />
                {new Date(latestEval.atMs).toLocaleTimeString()} ({latestEval.triggerReason})
              </span>
              <button
                onClick={() => copySignalParams(latestEval)}
                className="flex items-center gap-1 text-[11px] text-indigo-300 hover:text-white"
              >
                {copied ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
                <span>{copied ? '已复制策略参数' : '复制AI买入参数'}</span>
              </button>
            </div>
          </div>
        ) : (
          <div className="rounded-lg border border-gray-800 bg-[#161a24] p-2.5 space-y-1.5 text-xs">
            <div className="flex items-center justify-between text-gray-400">
              <span className="flex items-center gap-1 text-[11px]">
                <Radio className="w-3 h-3 text-amber-400" />
                <span>AI当前判定: <strong>观望防守 · 无合规买点</strong></span>
              </span>
              <span className="text-[10px] font-mono">
                {new Date(latestEval.atMs).toLocaleTimeString()}
              </span>
            </div>
            <p className="text-[11px] text-gray-300 leading-snug">
              {latestEval.summaryZh || '大盘未达反弹企稳或突破确认门禁，规避下行飞刀杂波。'}
            </p>
          </div>
        )
      ) : (
        <div className="rounded-lg border border-dashed border-gray-700 p-3 text-center text-xs text-gray-400 space-y-1">
          <Bot className="w-6 h-6 mx-auto text-indigo-400/80 mb-1" />
          <p>BTC AI 量化大脑就绪</p>
          <p className="text-[10px] text-gray-500">
            {state?.hasApiKey
              ? '等待下一个5分钟K线收盘分析，或点击上方“立即分析”'
              : '请点击右上角设置图标输入 Gemini 或 DeepSeek API Key 激活'}
          </p>
        </div>
      )}

      {/* Summary Stats & History Toggle */}
      <div className="flex items-center justify-between text-[10px] text-gray-400 border-t border-gray-800 pt-2">
        <div className="flex items-center gap-3">
          <span>总评估: <strong>{state?.evalCount ?? 0}</strong> 次</span>
          <span>买入生成: <strong className="text-emerald-400">{state?.buyCount ?? 0}</strong> 次</span>
        </div>
        <button
          onClick={() => setShowHistory(!showHistory)}
          className="text-indigo-400 hover:text-indigo-300 flex items-center gap-0.5"
        >
          <span>历史评估 ({state?.recentEvaluations?.length || 0})</span>
          {showHistory ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
        </button>
      </div>

      {/* Recent Evaluations List */}
      {showHistory && state?.recentEvaluations && state.recentEvaluations.length > 0 && (
        <div className="space-y-1.5 pt-1 max-h-48 overflow-y-auto pr-1">
          {state.recentEvaluations.map((ev) => (
            <div
              key={ev.id}
              className={`p-2 rounded-lg border text-[11px] space-y-1 ${
                ev.isBuy
                  ? 'border-emerald-700/50 bg-emerald-950/20 text-emerald-200'
                  : 'border-gray-800 bg-[#141822] text-gray-400'
              }`}
            >
              <div className="flex items-center justify-between text-[10px]">
                <span className="font-semibold">
                  {ev.isBuy ? `🟢 ${ev.scenarioNameZh}` : '⚪ 观望'}
                </span>
                <span className="font-mono">
                  {new Date(ev.atMs).toLocaleTimeString()} ({ev.triggerReason})
                </span>
              </div>
              <p className="truncate text-gray-300">{ev.summaryZh}</p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};
