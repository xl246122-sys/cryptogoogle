import { SwipeMessageRow } from './SwipeMessageRow';
import { WaveMessageDetails } from './WaveMessageDetails';
import React, { useEffect, useState, useMemo } from 'react';
import {
  Bell,
  Bot,
  Zap,
  Eye,
  LogOut,
  XCircle,
  FileText,
  CheckCheck,
  Trash2,
  ChevronDown,
  ChevronUp,
  Copy,
  Check,
  Clock,
  Sparkles,
  Info,
  Layers,
} from 'lucide-react';
import {
  messages,
  readMessage,
  markAllAsRead,
  clearReadMessages,
  deleteMessage,
  syncInbox,
  getAndClearPendingFocus,
  InboxMessage,
  isNoiseCategory,
  clearAllMessages,
} from '../services/inbox';

export function extractSignalParams(msg: InboxMessage) {
  const ex = msg.extra || {};
  const ai = ex.aiData || {};

  const entryMin =
    ex.entryMin || ex.entry_min || ai.entryMin || ai.entry_min || ex.entryPrice || ex.entry_price;
  const entryMax =
    ex.entryMax || ex.entry_max || ai.entryMax || ai.entry_max || ex.entryPrice || ex.entry_price;
  const targetTP1 = ex.targetTP1 || ex.target_tp1 || ai.targetTP1 || ai.target_tp1;
  const targetTP2 = ex.targetTP2 || ex.target_tp2 || ai.targetTP2 || ai.target_tp2;
  const stopLoss = ex.stopLoss || ex.stop_loss || ai.stopLoss || ai.stop_loss;
  const profitPct1 = ex.profitPercent1 || ex.profit_pct1 || ai.profitPercent1 || ai.profit_pct1;
  const stopLossPct = ex.stopLossPercent || ex.stop_loss_pct || ai.stopLossPercent || ai.stop_loss_pct;
  const rr = ex.riskRewardRatio || ex.risk_reward_ratio || ai.riskRewardRatio || ai.risk_reward_ratio;
  const summaryZh = ex.summaryZh || ai.summaryZh || ex.summary || ex.reasonZh;
  const scenarioNameZh = ex.scenarioNameZh || ai.scenarioNameZh || ex.strategyNameZh;

  const hasParams = Boolean(entryMin || targetTP1 || stopLoss);
  const isAI =
    msg.category === 'AI买入预警' ||
    ex.eventType === 'AI_BUY_ALERT' ||
    (ex.source && String(ex.source).includes('AI买入预警'));

  return {
    entryMin: entryMin ? Number(entryMin) : undefined,
    entryMax: entryMax ? Number(entryMax) : undefined,
    targetTP1: targetTP1 ? Number(targetTP1) : undefined,
    targetTP2: targetTP2 ? Number(targetTP2) : undefined,
    stopLoss: stopLoss ? Number(stopLoss) : undefined,
    profitPct1: profitPct1 ? Number(profitPct1) : undefined,
    stopLossPct: stopLossPct ? Number(stopLossPct) : undefined,
    rr: rr ? Number(rr) : undefined,
    summaryZh,
    scenarioNameZh,
    hasParams,
    isAI,
  };
}

export function MessagePanel({ onSwitchTab }: { onSwitchTab?: (tab: string) => void } = {}) {
  const [open, setOpen] = useState(false);
  const [rows, setRows] = useState<InboxMessage[]>(messages);
  const [activeTab, setActiveTab] = useState<'unread' | 'history'>('unread');
  const [selectedCategory, setSelectedCategory] = useState<string>('全部');
  const [readingIds, setReadingIds] = useState<Set<string>>(() => new Set());
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [focusedModalItem, setFocusedModalItem] = useState<InboxMessage | null>(null);
  const [copiedId, setCopiedId] = useState<string | null>(null);

  // Sync and listen for inbox updates
  useEffect(() => {
    const refresh = () => {
      setRows(messages());
      setFocusedModalItem((old) => (old ? messages().find((m) => m.id === old.id) || old : null));
    };
    window.addEventListener('cryptog-inbox', refresh);
    void syncInbox();
    const timer = setInterval(() => {
      refresh();
      void syncInbox();
    }, 12000);
    return () => {
      clearInterval(timer);
      window.removeEventListener('cryptog-inbox', refresh);
    };
  }, []);

  // Handle focus from push notification or background launch
  useEffect(() => {
    const handleFocusId = (targetId: string) => {
      setOpen(true);
      const current = messages();
      const found = current.find((m) => m.id === targetId);
      if (found) {
        setActiveTab('history');
        setExpandedId(found.id);
        setFocusedModalItem(found);
        if (!found.read) {
          readMessage(found.id);
        }
        setSelectedCategory('全部');
      }
    };

    // Check cold launch pending ID
    const tryPending = () => {
      const pendingId = getAndClearPendingFocus();
      if (pendingId) handleFocusId(pendingId);
    };
    tryPending();
    window.addEventListener('cryptog-inbox', tryPending);

    // Listen for runtime custom events
    const handleEvent = (e: Event) => {
      const targetId = (e as CustomEvent)?.detail?.id;
      if (targetId) {
        handleFocusId(targetId);
      }
    };
    window.addEventListener('cryptog-focus-message', handleEvent);
    return () => {
      window.removeEventListener('cryptog-focus-message', handleEvent);
      window.removeEventListener('cryptog-inbox', tryPending);
    };
  }, []);

  // Compute unread counts per category
  const unreadRows = useMemo(() => rows.filter((m) => !m.read), [rows]);
  const historyRows = useMemo(() => rows.filter((m) => m.read), [rows]);
  const totalUnread = unreadRows.length;

  const categories = useMemo(() => {
    const list = ['全部', '四阶段研究', '推送测试', 'AI买入预警', '准备入场', '入场', '离场'];
    return list.map((cat) => {
      let count = 0;
      let total = 0;
      if (cat === '全部') {
        count = unreadRows.length;
        total = rows.length;
      } else {
        count = unreadRows.filter((m) => m.category === cat).length;
        total = rows.filter((m) => m.category === cat).length;
      }
      return {
        id: cat,
        name: cat,
        unreadCount: count,
        totalCount: total,
      };
    });
  }, [rows, unreadRows]);

  // Filter messages based on active tab and selected category
  const currentList = useMemo(() => {
    const pool =
      activeTab === 'unread'
        ? rows.filter((m) => !m.read || readingIds.has(m.id))
        : historyRows;
    if (selectedCategory === '全部') {
      return pool;
    }
    return pool.filter((m) => m.category === selectedCategory);
  }, [activeTab, rows, readingIds, historyRows, selectedCategory]);

  // Drawer click handler: Click to expand, click again to close!
  const handleCardClick = (msg: InboxMessage) => {
    if (expandedId === msg.id) {
      setExpandedId(null);
    } else {
      setExpandedId(msg.id);
      if (!msg.read) {
        setReadingIds((ids) => new Set([...ids, msg.id]));
        readMessage(msg.id);
      }
    }
  };

  // Immediate, optimistic deletion handler
  const handleDelete = (id: string) => {
    setRows((prev) => prev.filter((m) => m.id !== id));
    if (expandedId === id) setExpandedId(null);
    if (focusedModalItem?.id === id) setFocusedModalItem(null);
    deleteMessage(id);
  };

  // Batch clear handlers
  const handleClearNormal = () => {
    clearAllMessages();
    setRows(messages());
    setExpandedId(null);
  };

  const handleClearRead = () => {
    clearReadMessages();
    setRows(messages());
    setExpandedId(null);
  };

  const handleCopy = (e: React.MouseEvent, msg: InboxMessage) => {
    e.stopPropagation();
    const p = extractSignalParams(msg);
    let copyText = `【${msg.title}】\n时间: ${new Date(msg.at).toLocaleString()}\n`;
    if (p.hasParams) {
      if (p.entryMin)
        copyText += `建议入场: $${p.entryMin.toFixed(2)}${
          p.entryMax && p.entryMax !== p.entryMin ? ` ~ $${p.entryMax.toFixed(2)}` : ''
        }\n`;
      if (p.targetTP1)
        copyText += `目标止盈: $${p.targetTP1.toFixed(2)}${
          p.profitPct1 ? ` (+${p.profitPct1}%)` : ''
        }\n`;
      if (p.stopLoss)
        copyText += `防守止损: $${p.stopLoss.toFixed(2)}${
          p.stopLossPct ? ` (-${p.stopLossPct}%)` : ''
        }\n`;
      if (p.rr) copyText += `盈亏比: ${p.rr}:1\n`;
    }
    copyText += `内容: ${msg.body}`;
    navigator.clipboard.writeText(copyText);
    setCopiedId(msg.id);
    setTimeout(() => setCopiedId(null), 2000);
  };

  const pStr = (val?: number) =>
    val
      ? `$${val.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
      : '--';

  const formatTime = (ts: number) => {
    const d = new Date(ts);
    const now = Date.now();
    const diffMin = Math.floor((now - ts) / 60000);
    if (diffMin < 1) return '刚刚';
    if (diffMin < 60) return `${diffMin}分钟前`;
    const diffHours = Math.floor(diffMin / 60);
    if (diffHours < 24) return `${diffHours}小时前`;
    return d.toLocaleString([], {
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    });
  };

  const getCategoryMeta = (cat: string) => {
    switch (cat) {
      case '四阶段研究':
        return {
          icon: <Layers className="w-3.5 h-3.5 text-cyan-400" />,
          label: '四阶段研究',
          bg: 'bg-cyan-950/40 border-cyan-500/50 text-cyan-300',
          accent: 'text-cyan-400',
          borderActive: 'border-cyan-500/70',
        };
      case '推送测试':
        return {
          icon: <Bell className="w-3.5 h-3.5 text-slate-400" />,
          label: '推送测试',
          bg: 'bg-slate-800/60 border-slate-700 text-slate-300',
          accent: 'text-slate-400',
          borderActive: 'border-slate-600',
        };
      case 'AI买入预警':
        return {
          icon: <Bot className="w-3.5 h-3.5 text-purple-400" />,
          label: 'AI买入预警',
          bg: 'bg-purple-950/40 border-purple-500/50 text-purple-300',
          accent: 'text-purple-400',
          borderActive: 'border-purple-500/80',
        };
      case '入场':
        return {
          icon: <Zap className="w-3.5 h-3.5 text-emerald-400" />,
          label: '入场信号',
          bg: 'bg-emerald-950/40 border-emerald-500/50 text-emerald-300',
          accent: 'text-emerald-400',
          borderActive: 'border-emerald-500/80',
        };
      case '准备入场':
        return {
          icon: <Sparkles className="w-3.5 h-3.5 text-amber-400" />,
          label: '准备入场',
          bg: 'bg-amber-950/40 border-amber-500/50 text-amber-300',
          accent: 'text-amber-400',
          borderActive: 'border-amber-500/80',
        };
      case '观察':
        return {
          icon: <Eye className="w-3.5 h-3.5 text-blue-400" />,
          label: '机会观察',
          bg: 'bg-blue-950/40 border-blue-500/50 text-blue-300',
          accent: 'text-blue-400',
          borderActive: 'border-blue-500/80',
        };
      case '离场':
        return {
          icon: <LogOut className="w-3.5 h-3.5 text-rose-400" />,
          label: '离场提示',
          bg: 'bg-rose-950/40 border-rose-500/50 text-rose-300',
          accent: 'text-rose-400',
          borderActive: 'border-rose-500/80',
        };
      case '失效':
        return {
          icon: <XCircle className="w-3.5 h-3.5 text-gray-400" />,
          label: '观察失效',
          bg: 'bg-gray-800/60 border-gray-700 text-gray-400',
          accent: 'text-gray-400',
          borderActive: 'border-gray-600',
        };
      case '摘要':
        return {
          icon: <FileText className="w-3.5 h-3.5 text-indigo-400" />,
          label: '定期摘要',
          bg: 'bg-indigo-950/40 border-indigo-500/50 text-indigo-300',
          accent: 'text-indigo-400',
          borderActive: 'border-indigo-500/80',
        };
      default:
        return {
          icon: <Info className="w-3.5 h-3.5 text-gray-400" />,
          label: cat,
          bg: 'bg-gray-800/80 border-gray-700 text-gray-300',
          accent: 'text-gray-300',
          borderActive: 'border-gray-600',
        };
    }
  };

  return (
    <>
      <section
        className="rounded-2xl border border-gray-800/80 bg-[#121622] shadow-xl overflow-hidden transition-all duration-200"
        aria-label="消息通知中心"
      >
        {/* Top Header Card - Material 3 Refined Surface */}
        <div className="p-3 bg-gradient-to-r from-[#171d2b] via-[#141824] to-[#121622] border-b border-gray-800/80">
          <div className="flex items-center justify-between gap-2">
            <button
              onClick={() => setOpen(!open)}
              className="flex items-center gap-2.5 text-left focus:outline-none group flex-1 min-w-0"
              aria-expanded={open}
            >
              <div
                className={`relative p-2 rounded-xl transition shrink-0 ${
                  totalUnread > 0
                    ? 'bg-blue-600/20 text-blue-400 ring-1 ring-blue-500/40 shadow-sm shadow-blue-900/40'
                    : 'bg-gray-800/90 text-gray-400'
                }`}
              >
                <Bell className={`w-4 h-4 ${totalUnread > 0 ? 'animate-bounce' : ''}`} />
                {totalUnread > 0 && (
                  <span className="absolute -top-1 -right-1 flex h-3.5 w-3.5 items-center justify-center rounded-full bg-rose-500 text-[9px] font-bold text-white shadow-sm ring-2 ring-[#121622]">
                    {totalUnread > 99 ? '99+' : totalUnread}
                  </span>
                )}
              </div>

              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2 flex-wrap">
                  <h3 className="text-sm font-semibold text-white tracking-wide flex items-center gap-1.5">
                    预警消息通知
                  </h3>
                  {totalUnread > 0 ? (
                    <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-blue-500/20 border border-blue-500/40 text-blue-300">
                      {totalUnread} 条未读
                    </span>
                  ) : (
                    <span className="px-1.5 py-0.5 rounded-full text-[10px] font-medium text-gray-400 bg-gray-800/90 border border-gray-700/50">
                      全部已读
                    </span>
                  )}
                </div>
                <p className="text-[10px] text-gray-400 mt-0.5 truncate">
                  BTC量化预警 · 阶段研究 · 实时结构通知
                </p>
              </div>
            </button>

            {/* Header Quick Action Tools */}
            <div className="flex items-center gap-1.5 shrink-0">
              {open && totalUnread > 0 && (
                <button
                  type="button"
                  onClick={() => markAllAsRead()}
                  className="flex items-center gap-1 px-2 py-1.5 rounded-lg bg-blue-950/40 hover:bg-blue-900/60 border border-blue-600/30 text-blue-300 text-[11px] font-medium transition active:scale-95"
                  title="全部标记为已读"
                >
                  <CheckCheck className="w-3.5 h-3.5 text-blue-400" />
                  <span className="hidden sm:inline">已读</span>
                </button>
              )}

              {open && (
                <button
                  type="button"
                  onClick={activeTab === 'history' ? handleClearRead : handleClearNormal}
                  className="flex items-center gap-1 px-2 py-1.5 rounded-lg bg-gray-800/80 hover:bg-rose-950/40 border border-gray-700/60 hover:border-rose-800/50 text-gray-400 hover:text-rose-300 text-[11px] font-medium transition active:scale-95"
                  title={activeTab === 'history' ? '清空历史消息' : '清理普通消息（保留持仓与有效计划）'}
                >
                  <Trash2 className="w-3.5 h-3.5 text-rose-400/80" />
                  <span className="hidden sm:inline">清理</span>
                </button>
              )}

              <button
                type="button"
                onClick={() => setOpen(!open)}
                className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg bg-gray-800/90 hover:bg-gray-700 text-gray-300 text-xs transition active:scale-95"
              >
                <span>{open ? '收起' : '展开'}</span>
                {open ? (
                  <ChevronUp className="w-3.5 h-3.5 text-blue-400" />
                ) : (
                  <ChevronDown className="w-3.5 h-3.5 text-blue-400" />
                )}
              </button>
            </div>
          </div>

          {/* Segmented Tab: 未读消息 vs 消息历史 */}
          {open && (
            <div className="flex items-center gap-2 mt-3 pt-2.5 border-t border-gray-800/60">
              <button
                type="button"
                onClick={() => {
                  setReadingIds(new Set());
                  setExpandedId(null);
                  setActiveTab('unread');
                }}
                className={`flex-1 flex items-center justify-center gap-1.5 py-1.5 rounded-xl text-xs font-semibold transition-all ${
                  activeTab === 'unread'
                    ? 'bg-blue-600 text-white shadow-md shadow-blue-900/40 font-bold'
                    : 'bg-[#181d2a] text-gray-400 hover:text-gray-200 border border-gray-800/80'
                }`}
              >
                <Bell className="w-3.5 h-3.5" />
                <span>未读消息</span>
                {totalUnread > 0 && (
                  <span className="px-1.5 py-0.2 rounded-full text-[10px] bg-rose-500 text-white font-bold leading-none">
                    {totalUnread}
                  </span>
                )}
              </button>
              <button
                type="button"
                onClick={() => {
                  setReadingIds(new Set());
                  setExpandedId(null);
                  setActiveTab('history');
                }}
                className={`flex-1 flex items-center justify-center gap-1.5 py-1.5 rounded-xl text-xs font-semibold transition-all ${
                  activeTab === 'history'
                    ? 'bg-blue-600 text-white shadow-md shadow-blue-900/40 font-bold'
                    : 'bg-[#181d2a] text-gray-400 hover:text-gray-200 border border-gray-800/80'
                }`}
              >
                <Clock className="w-3.5 h-3.5" />
                <span>消息历史</span>
                <span className="text-[10px] font-mono opacity-80">({historyRows.length})</span>
              </button>
            </div>
          )}
        </div>

        {/* Expanded Content Area */}
        {open && (
          <div className="p-3 space-y-3">
            {/* Horizontal Category Chips (Material 3 Filter Chips) */}
            <div className="flex items-center gap-1.5 overflow-x-auto pb-1 scrollbar-thin">
              {categories.map((cat) => {
                const isSelected = selectedCategory === cat.id;
                const badgeCount =
                  activeTab === 'unread' ? cat.unreadCount : cat.totalCount;
                return (
                  <button
                    key={cat.id}
                    type="button"
                    onClick={() => setSelectedCategory(cat.id)}
                    className={`flex items-center gap-1 px-2.5 py-1.5 rounded-full text-xs font-medium whitespace-nowrap transition-all shrink-0 ${
                      isSelected
                        ? 'bg-blue-600 text-white shadow-md shadow-blue-950 font-bold'
                        : 'bg-[#181d2a] text-gray-400 hover:text-gray-200 border border-gray-800/80'
                    }`}
                  >
                    <span>{cat.name}</span>
                    {badgeCount > 0 ? (
                      <span
                        className={`ml-0.5 px-1.5 py-0.2 rounded-full text-[10px] font-bold ${
                          isSelected
                            ? 'bg-white text-blue-700'
                            : activeTab === 'unread'
                            ? 'bg-rose-500 text-white'
                            : 'bg-gray-700 text-gray-300'
                        }`}
                      >
                        {badgeCount}
                      </span>
                    ) : (
                      <span className="text-[10px] text-gray-600 font-mono">0</span>
                    )}
                  </button>
                );
              })}
            </div>

            {/* Message Cards List with Smooth Accordion Drawer */}
            <div className="space-y-2 max-h-[480px] overflow-y-auto pr-0.5">
              {currentList.length > 0 ? (
                currentList.map((msg) => {
                  const meta = getCategoryMeta(msg.category);
                  const isExpanded = expandedId === msg.id;
                  const isUnread = !msg.read;
                  const p = extractSignalParams(msg);

                  return (
                    <SwipeMessageRow
                      key={msg.id}
                      onDelete={() => handleDelete(msg.id)}
                    >
                      <article
                        className={`rounded-2xl border transition-all duration-200 overflow-hidden ${
                          isExpanded
                            ? `bg-gradient-to-b from-[#181f30] to-[#131722] ${meta.borderActive} shadow-lg ring-1 ring-blue-500/20`
                            : isUnread
                            ? 'bg-[#151c2a] border-blue-500/40 hover:border-blue-400/60 shadow-sm'
                            : 'bg-[#11151f]/90 border-gray-800/80 hover:border-gray-700 opacity-90 hover:opacity-100'
                        }`}
                      >
                        {/* Drawer Trigger Header (Click anywhere to expand/collapse) */}
                        <div
                          role="button"
                          tabIndex={0}
                          aria-expanded={isExpanded}
                          aria-label={`阅读消息：${msg.title}`}
                          onClick={() => handleCardClick(msg)}
                          onKeyDown={(e) => {
                            if (e.key === 'Enter' || e.key === ' ') {
                              e.preventDefault();
                              handleCardClick(msg);
                            }
                          }}
                          className="p-3 cursor-pointer select-none space-y-1.5 focus:outline-none"
                        >
                          <div className="flex items-center justify-between gap-2">
                            <div className="flex items-center gap-1.5 min-w-0 flex-1">
                              {/* Unread indicator pulse dot */}
                              {isUnread && (
                                <span
                                  className="w-2 h-2 rounded-full bg-blue-400 shadow-md shadow-blue-400 ring-2 ring-blue-400/30 animate-pulse shrink-0"
                                  title="未读消息"
                                />
                              )}

                              {/* Category pill */}
                              <span
                                className={`flex items-center gap-1 px-1.5 py-0.5 rounded-md text-[10px] font-bold border shrink-0 ${meta.bg}`}
                              >
                                {meta.icon}
                                <span>{meta.label}</span>
                              </span>

                              {/* Title */}
                              <h4
                                className={`text-xs truncate ${
                                  isUnread ? 'font-bold text-white' : 'font-medium text-gray-300'
                                }`}
                              >
                                {msg.title}
                              </h4>
                            </div>

                            {/* Right tools: Time, Direct Trash Icon & Animated Chevron Drawer Indicator */}
                            <div className="flex items-center gap-1.5 text-[10px] text-gray-400 shrink-0 font-mono">
                              <Clock className="w-3 h-3 text-gray-500" />
                              <time>{formatTime(msg.at)}</time>

                              {/* Dedicated 1-Tap Delete Button right on the card header */}
                              <button
                                type="button"
                                aria-label="删除此消息"
                                title="删除此消息"
                                onClick={(e) => {
                                  e.stopPropagation();
                                  handleDelete(msg.id);
                                }}
                                className="p-1 rounded-md text-gray-500 hover:text-rose-400 hover:bg-rose-500/15 active:bg-rose-500/25 transition-colors"
                              >
                                <Trash2 className="w-3.5 h-3.5" />
                              </button>

                              <span
                                className={`p-0.5 rounded-md transition-colors ${
                                  isExpanded
                                    ? 'bg-blue-600/20 text-blue-400'
                                    : 'text-gray-500 hover:text-gray-300'
                                }`}
                              >
                                <ChevronDown
                                  className={`w-3.5 h-3.5 transform transition-transform duration-300 ${
                                    isExpanded ? 'rotate-180 text-blue-400' : 'text-gray-400'
                                  }`}
                                />
                              </span>
                            </div>
                          </div>

                          {/* Collapsed Brief Preview (Only shown when drawer is closed) */}
                          {!isExpanded && (
                            <p className="text-[11px] text-gray-400 line-clamp-1 pl-0.5 leading-snug">
                              {msg.body}
                            </p>
                          )}
                        </div>

                        {/* Smooth Drawer Body (Expanded View) */}
                        <div
                          className={`transition-all duration-300 ease-in-out overflow-hidden ${
                            isExpanded ? 'block opacity-100' : 'hidden'
                          }`}
                        >
                          <div className="px-3 pb-3 pt-1 border-t border-gray-800/80 bg-[#121622]/95 space-y-3">
                            <WaveMessageDetails data={msg.extra} />

                            {/* Key Quantitative Trading Metrics 4-Grid Card (If parameters exist) */}
                            {p.hasParams && (
                              <div className="grid grid-cols-2 gap-2 text-xs font-mono pt-1">
                                <div className="rounded-xl bg-[#0b0e16] border border-gray-800/90 p-2.5 space-y-0.5">
                                  <span className="text-[10px] text-gray-400">建议入场区间</span>
                                  <div className="font-bold text-white text-[12px] truncate">
                                    {p.entryMin === p.entryMax
                                      ? pStr(p.entryMin)
                                      : `${pStr(p.entryMin)} ~ ${pStr(p.entryMax)}`}
                                  </div>
                                </div>
                                <div className="rounded-xl bg-[#0b0e16] border border-gray-800/90 p-2.5 space-y-0.5">
                                  <span className="text-[10px] text-emerald-400">目标止盈 (TP1)</span>
                                  <div className="font-bold text-emerald-400 text-[12px] truncate">
                                    {pStr(p.targetTP1)} {p.profitPct1 ? `(+${p.profitPct1}%)` : ''}
                                  </div>
                                </div>
                                <div className="rounded-xl bg-[#0b0e16] border border-gray-800/90 p-2.5 space-y-0.5">
                                  <span className="text-[10px] text-rose-400">防守止损 (SL)</span>
                                  <div className="font-bold text-rose-400 text-[12px] truncate">
                                    {pStr(p.stopLoss)} {p.stopLossPct ? `(-${p.stopLossPct}%)` : ''}
                                  </div>
                                </div>
                                <div className="rounded-xl bg-[#0b0e16] border border-gray-800/90 p-2.5 space-y-0.5">
                                  <span className="text-[10px] text-indigo-300">净盈亏比 (RR)</span>
                                  <div className="font-bold text-indigo-300 text-[12px]">
                                    {p.rr ? `${p.rr}:1` : '--'}
                                  </div>
                                </div>
                              </div>
                            )}

                            {/* Structured Decision & Full Text Content */}
                            <div className="text-xs text-gray-200 leading-relaxed whitespace-pre-wrap bg-[#0b0e16] p-3 rounded-xl border border-gray-800/90 font-sans select-text">
                              {msg.body}
                            </div>

                            {/* Drawer Action Toolbar */}
                            <div className="flex flex-wrap items-center justify-between gap-2 pt-1 border-t border-gray-800/60">
                              <div className="flex items-center gap-1.5 text-[10px] text-gray-400 font-mono">
                                <Clock className="w-3 h-3 text-gray-500" />
                                <span>{new Date(msg.at).toLocaleString()}</span>
                              </div>

                              <div className="flex items-center gap-1.5">
                                <button
                                  type="button"
                                  onClick={(e) => handleCopy(e, msg)}
                                  className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg bg-gray-800 hover:bg-gray-700 text-indigo-300 hover:text-white text-xs transition active:scale-95"
                                >
                                  {copiedId === msg.id ? (
                                    <>
                                      <Check className="w-3.5 h-3.5 text-emerald-400" />
                                      <span>已复制</span>
                                    </>
                                  ) : (
                                    <>
                                      <Copy className="w-3.5 h-3.5" />
                                      <span>复制详情</span>
                                    </>
                                  )}
                                </button>

                                {onSwitchTab && (p.isAI || msg.category === 'AI买入预警') && (
                                  <button
                                    type="button"
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      onSwitchTab('ai-quant');
                                    }}
                                    className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg bg-purple-900/60 hover:bg-purple-800 border border-purple-500/40 text-purple-200 text-xs font-semibold transition active:scale-95"
                                  >
                                    <Bot className="w-3.5 h-3.5" />
                                    <span>AI量化大脑</span>
                                  </button>
                                )}

                                {onSwitchTab &&
                                  (msg.category === '入场' || msg.category === '准备入场') && (
                                    <button
                                      type="button"
                                      onClick={(e) => {
                                        e.stopPropagation();
                                        onSwitchTab('radar');
                                      }}
                                      className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg bg-blue-900/60 hover:bg-blue-800 border border-blue-500/40 text-blue-200 text-xs font-semibold transition active:scale-95"
                                    >
                                      <Zap className="w-3.5 h-3.5" />
                                      <span>雷达看板</span>
                                    </button>
                                  )}

                                {/* Explicit Delete Button in Drawer Toolbar */}
                                <button
                                  type="button"
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    handleDelete(msg.id);
                                  }}
                                  className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg bg-rose-950/40 hover:bg-rose-900/60 border border-rose-800/40 text-rose-300 text-xs font-medium transition active:scale-95"
                                  title="删除当前消息"
                                >
                                  <Trash2 className="w-3.5 h-3.5 text-rose-400" />
                                  <span>删除</span>
                                </button>

                                {/* Explicit Close Drawer Button */}
                                <button
                                  type="button"
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    setExpandedId(null);
                                  }}
                                  className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg bg-gray-800 hover:bg-gray-700 text-gray-400 hover:text-white text-xs transition active:scale-95"
                                  title="收起当前详情抽屉"
                                >
                                  <ChevronUp className="w-3.5 h-3.5" />
                                  <span>收起</span>
                                </button>
                              </div>
                            </div>
                          </div>
                        </div>
                      </article>
                    </SwipeMessageRow>
                  );
                })
              ) : (
                <div className="p-8 text-center text-xs text-gray-500 space-y-2 bg-[#0e121a]/50 rounded-2xl border border-dashed border-gray-800">
                  <Bell className="w-6 h-6 mx-auto text-gray-600 mb-1 opacity-60" />
                  <p>
                    {activeTab === 'unread'
                      ? `「${selectedCategory}」分类下暂无未读消息`
                      : `「${selectedCategory}」分类下暂无已读历史`}
                  </p>
                  {activeTab === 'unread' && historyRows.length > 0 && (
                    <button
                      type="button"
                      onClick={() => {
                        setReadingIds(new Set());
                        setExpandedId(null);
                        setActiveTab('history');
                      }}
                      className="text-blue-400 hover:underline text-[11px]"
                    >
                      查看已读历史记录 ({historyRows.length})
                    </button>
                  )}
                </div>
              )}
            </div>
          </div>
        )}
      </section>

      {/* Floating Modal for Notification Click Deep-Link */}
      {focusedModalItem && (() => {
        const p = extractSignalParams(focusedModalItem);

        return (
          <div
            role="dialog"
            aria-label="新消息详情"
            className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-md animate-fadeIn"
            onClick={() => setFocusedModalItem(null)}
          >
            <div
              className="w-full max-w-sm rounded-2xl bg-[#141824] border border-indigo-500/40 shadow-2xl p-4 space-y-3.5 max-h-[90vh] overflow-y-auto"
              onClick={(e) => e.stopPropagation()}
            >
              <div className="flex items-center justify-between border-b border-gray-800 pb-2.5">
                <div className="flex items-center gap-2">
                  <span
                    className={`p-1.5 rounded-xl ${
                      p.isAI
                        ? 'bg-purple-950/80 text-purple-400 border border-purple-700/50'
                        : 'bg-blue-950/80 text-blue-400 border border-blue-700/50'
                    }`}
                  >
                    {p.isAI ? <Bot className="w-4 h-4" /> : <Sparkles className="w-4 h-4" />}
                  </span>
                  <div>
                    <h3 className="text-xs font-bold text-white tracking-wide">
                      {p.isAI ? 'BTC AI 量化买入预警' : '预警消息详情'}
                    </h3>
                    <p className="text-[10px] text-gray-400 font-mono">
                      {new Date(focusedModalItem.at).toLocaleString()}
                    </p>
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => setFocusedModalItem(null)}
                  className="p-1 rounded-lg text-gray-400 hover:text-white hover:bg-gray-800 text-sm transition"
                >
                  ✕
                </button>
              </div>

              <div className="space-y-1">
                <div className="flex items-center gap-1.5 flex-wrap">
                  <span
                    className={`px-2 py-0.5 rounded-full text-[10px] font-bold ${
                      p.isAI
                        ? 'bg-purple-950/90 text-purple-300 border border-purple-700/60'
                        : focusedModalItem.category === '入场'
                        ? 'bg-emerald-950/90 text-emerald-300 border border-emerald-700/60'
                        : 'bg-blue-950/90 text-blue-300 border border-blue-700/60'
                    }`}
                  >
                    {focusedModalItem.category}
                  </span>
                  <h4 className="text-sm font-bold text-white flex-1">
                    {focusedModalItem.title}
                  </h4>
                </div>
              </div>

              {/* Key Trading Metrics Grid (If trading parameters exist) */}
              <WaveMessageDetails data={focusedModalItem.extra} />
              {p.hasParams && (
                <div className="grid grid-cols-2 gap-2 text-xs font-mono">
                  <div className="rounded-xl bg-[#0e121a] border border-gray-800/80 p-2.5 space-y-0.5">
                    <span className="text-[10px] text-gray-400">建议入场区间</span>
                    <div className="font-bold text-white text-[12px] truncate">
                      {p.entryMin === p.entryMax
                        ? pStr(p.entryMin)
                        : `${pStr(p.entryMin)} ~ ${pStr(p.entryMax)}`}
                    </div>
                  </div>
                  <div className="rounded-xl bg-[#0e121a] border border-gray-800/80 p-2.5 space-y-0.5">
                    <span className="text-[10px] text-emerald-400">目标止盈 (TP1)</span>
                    <div className="font-bold text-emerald-400 text-[12px] truncate">
                      {pStr(p.targetTP1)} {p.profitPct1 ? `(+${p.profitPct1}%)` : ''}
                    </div>
                  </div>
                  <div className="rounded-xl bg-[#0e121a] border border-gray-800/80 p-2.5 space-y-0.5">
                    <span className="text-[10px] text-rose-400">防守止损 (SL)</span>
                    <div className="font-bold text-rose-400 text-[12px] truncate">
                      {pStr(p.stopLoss)} {p.stopLossPct ? `(-${p.stopLossPct}%)` : ''}
                    </div>
                  </div>
                  <div className="rounded-xl bg-[#0e121a] border border-gray-800/80 p-2.5 space-y-0.5">
                    <span className="text-[10px] text-indigo-300">盈亏比 (RR)</span>
                    <div className="font-bold text-indigo-300 text-[12px]">
                      {p.rr ? `${p.rr}:1` : '--'}
                    </div>
                  </div>
                </div>
              )}

              {/* Decision Rationale / Description Box */}
              <div className="bg-[#0b0e14] p-3 rounded-xl border border-gray-800 text-xs text-gray-200 leading-relaxed whitespace-pre-wrap select-text max-h-48 overflow-y-auto">
                {focusedModalItem.body}
              </div>

              {/* Action Buttons */}
              <div className="space-y-2 pt-1">
                {p.isAI ? (
                  <button
                    type="button"
                    onClick={() => {
                      readMessage(focusedModalItem.id);
                      setFocusedModalItem(null);
                      if (onSwitchTab) onSwitchTab('ai');
                    }}
                    className="w-full flex items-center justify-center gap-1.5 py-2.5 rounded-xl bg-gradient-to-r from-purple-600 to-indigo-600 hover:from-purple-500 hover:to-indigo-500 text-white font-semibold text-xs shadow-lg shadow-purple-950/50 transition active:scale-[0.98]"
                  >
                    <Bot className="w-4 h-4" />
                    <span>前往【BTC AI量化大脑】查看决策报告</span>
                  </button>
                ) : focusedModalItem.category === '入场' ? (
                  <button
                    type="button"
                    onClick={() => {
                      readMessage(focusedModalItem.id);
                      setFocusedModalItem(null);
                      if (onSwitchTab) onSwitchTab('radar');
                    }}
                    className="w-full flex items-center justify-center gap-1.5 py-2.5 rounded-xl bg-gradient-to-r from-emerald-600 to-teal-600 hover:from-emerald-500 hover:to-teal-500 text-white font-semibold text-xs shadow-lg shadow-emerald-950/50 transition active:scale-[0.98]"
                  >
                    <Zap className="w-4 h-4" />
                    <span>前往【雷达看板】复核最新盘口买价</span>
                  </button>
                ) : null}

                <div className="flex gap-2">
                  <button
                    type="button"
                    onClick={(e) => handleCopy(e, focusedModalItem)}
                    className="flex-1 flex items-center justify-center gap-1.5 py-2 rounded-xl bg-gray-800 hover:bg-gray-700 text-indigo-300 font-medium text-xs transition active:scale-95"
                  >
                    {copiedId === focusedModalItem.id ? (
                      <>
                        <Check className="w-3.5 h-3.5 text-emerald-400" />
                        <span>已复制参数</span>
                      </>
                    ) : (
                      <>
                        <Copy className="w-3.5 h-3.5" />
                        <span>复制完整内容</span>
                      </>
                    )}
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      readMessage(focusedModalItem.id);
                      setFocusedModalItem(null);
                    }}
                    className="flex-1 py-2 rounded-xl bg-blue-600 hover:bg-blue-500 text-white font-semibold text-xs transition shadow-md shadow-blue-950 active:scale-95"
                  >
                    我知道了 (已读)
                  </button>
                </div>
              </div>
            </div>
          </div>
        );
      })()}
    </>
  );
}
