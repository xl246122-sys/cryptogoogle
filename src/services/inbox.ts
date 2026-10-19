import { connection } from './serverConnection';
import {parseWaveMessage,waveTitle,waveBody} from './waveState';

export interface InboxMessage {
  id: string;
  title: string;
  body: string;
  at: number;
  category: string;
  read: boolean;
  extra?: any;
  revisions?: any[];
}

const KEY = 'cryptog_inbox_v1';
const PENDING_FOCUS_KEY = 'cryptog_pending_focus_id';
const CLEAR_KEY = 'cryptog_inbox_cleared_at';
const CYCLE_KEY = 'cryptog_inbox_cycle_start';
const DELETED_KEY = 'cryptog_inbox_deleted_ids';
function protectedMessage(m:InboxMessage,now=Date.now()) {
  return m.extra?.eventType==='WAVE_STATE_RESEARCH'||m.extra?.eventType==='POSITION_EXIT_NOTICE'
    ||(m.extra?.signalType==='BUY'&&Number(m.extra.expiresAt)>now);
}

export function clearAllMessages(now = Date.now()) {
  const old = JSON.parse(localStorage.getItem(KEY) || '[]') as InboxMessage[];
  const ids = new Set<string>(JSON.parse(localStorage.getItem(DELETED_KEY) || '[]'));
  const kept=old.filter(m=>protectedMessage(m,now));
  old.filter(m=>!protectedMessage(m,now)).forEach(m => ids.add(m.id));
  localStorage.setItem(DELETED_KEY, JSON.stringify([...ids]));
  localStorage.setItem(CLEAR_KEY, String(now));
  localStorage.setItem(CYCLE_KEY, String(now));
  localStorage.removeItem(PENDING_FOCUS_KEY);
  save(kept);
  if (typeof window !== 'undefined' && kept.length===0) window.dispatchEvent(new Event('cryptog-inbox-cleared'));
}

export function autoClearMessages(now = Date.now()) {
  // Kept as a compatibility hook for existing callers. No time-based deletion:
  // read history and still-valid plans must survive old three-hour cycles.
}

export function normalizedCategory(category: string, title='', extra: any={}): string {
  if(parseWaveMessage(extra))return '四阶段研究';
  if (extra?.eventType==='DIAGNOSTIC_TEST') return '推送测试';
  if (/测试|摘要/.test(title) || ['测试','观察','摘要'].includes(category)) return '';
  if (['AI','AI买入预警'].includes(category)) return 'AI买入预警';
  if (['阶段预警','接近','准备入场'].includes(category)) return '准备入场';
  if (['退出','离场'].includes(category)) return '离场';
  if (category==='失效') return extra?.eventType==='ENTRY_INVALIDATED' ? '离场' : '';
  return category==='入场' ? category : '';
}

export function messages(): InboxMessage[] {
  try {
    autoClearMessages();
    return (JSON.parse(localStorage.getItem(KEY) || '[]') as InboxMessage[]).map(m => {
      const category=normalizedCategory(m.category,m.title,m.extra);
      return {...m,category,...(category==='AI买入预警'?{title:'历史 AI 路径 · 已停用',body:'旧版 AI 来源记录，仅供回看，不是当前买入候选。请以云端 short-horizon-v2 计划及有效期为准。'}:{})};
    }).filter(m => !!m.category);
  } catch {
    return [];
  }
}

function save(rows: InboxMessage[]) {
  localStorage.setItem(KEY, JSON.stringify(rows));
  if (typeof window !== 'undefined') {
    window.dispatchEvent(new Event('cryptog-inbox'));
  }
}

export function ingestMessage(data: any) {
  if (!data) return;
  if(data.eventType==='WAVE_STATE_RESEARCH') {
    const wave=parseWaveMessage(data);if(!wave)return;
    const rows=messages();const index=rows.findIndex(r=>r.id===wave.eventId);const old=rows[index];
    if(old && (!parseWaveMessage(old.extra)||wave.revision<=Number(old.extra.revision)||wave.decisionTime<Number(old.extra.decisionTime)))return;
    const item:InboxMessage={id:wave.eventId,title:waveTitle(wave),body:waveBody(wave),at:wave.issuedAtMs,
      category:'四阶段研究',read:false,extra:wave,revisions:old?[...(old.revisions||[]),old.extra]:[]};
    if(index>=0)rows[index]=item;else rows.push(item);
    save(rows.sort((a,b)=>b.at-a.at));return;
  }
  const id =
    data.eventId ||
    data.id ||
    data.testId ||
    data.deliveryId ||
    (data.title ? `msg_${Date.now()}_${Math.random().toString(36).slice(2, 6)}` : null);
  if (typeof id !== 'string') return;
  autoClearMessages();
  if ((JSON.parse(localStorage.getItem(DELETED_KEY) || '[]') as string[]).includes(id)) return;

  // 1. Resolve Title
  const rawTitle = data.title || data.notification?.title || data.strategyNameZh || data.scenarioNameZh;
  let title = String(rawTitle && String(rawTitle).trim() ? rawTitle : '');
  if (!title) {
    if (data.eventType === 'AI_BUY_ALERT' || (data.source && String(data.source).includes('AI'))) {
      title = 'Crypto-G AI量化买入预警';
    } else if (data.signalType === 'BUY') {
      title = 'Crypto-G 买入信号候选';
    } else if (data.eventType === 'POSITION_EXIT_NOTICE') {
      title = 'Crypto-G 持仓退出预警';
    } else {
      title = 'Crypto-G 市场预警通知';
    }
  }

  // 2. Resolve Body & Structured Signal Parameters
  const p = data.aiData || data;
  let body = String(
    data.body ||
    data.notification?.body ||
    data.summaryZh ||
    data.summary ||
    data.message ||
    data.description ||
    data.reasonZh ||
    (Array.isArray(data.reasons) ? data.reasons.join('；') : '') ||
    ''
  ).trim();

  // If body is empty or equals the generic placeholder "请查看最新状态", reconstruct a rich signal body!
  if (!body || body === '请查看最新状态') {
    if (p.entryPrice || p.entryMin || p.targetTP1 || p.target_tp1) {
      const eMin = p.entryMin || p.entry_min || p.entryPrice;
      const eMax = p.entryMax || p.entry_max || p.entryPrice;
      const tp1 = p.targetTP1 || p.target_tp1;
      const sl = p.stopLoss || p.stop_loss;
      const profit = p.profitPercent1 || p.profit_pct1;
      const slPct = p.stopLossPercent || p.stop_loss_pct;
      const rr = p.riskRewardRatio || p.risk_reward_ratio;

      let paramSummary = `建议入场: $${Number(eMin).toFixed(2)}`;
      if (eMax && eMax !== eMin) paramSummary += ` ~ $${Number(eMax).toFixed(2)}`;
      if (tp1) paramSummary += ` | 目标TP1: $${Number(tp1).toFixed(2)}${profit ? ` (+${profit}%)` : ''}`;
      if (sl) paramSummary += ` | 止损SL: $${Number(sl).toFixed(2)}${slPct ? ` (-${slPct}%)` : ''}`;
      if (rr) paramSummary += ` | 盈亏比: ${rr}:1`;

      if (p.summaryZh) {
        paramSummary += `\n【量化推演】${p.summaryZh}`;
      }
      body = paramSummary;
    } else if (data.eventType === 'AI_BUY_ALERT') {
      body = 'BTC 出现高胜率 AI 量化买入共振形态，请进入【AI量化大脑】复核决策点位。';
    } else if (data.signalType === 'BUY') {
      body = 'BTC 触发多因子买入信号，请在雷达面板复核买价与有效性。';
    } else if (data.eventType === 'POSITION_EXIT_NOTICE') {
      body = '持仓结构止盈或止损防守触发，请核对当前仓位与执行状态。';
    } else if (data.eventType === 'OBSERVATION_NOTICE') {
      body = '盘口微观结构异动观察中，当前正在确认右侧支撑防守有效性。';
    } else {
      body = '盘面出现异动监测信号，请打开对应面板查看最新分析。';
    }
  }

  // 3. Resolve Category
  const category = normalizedCategory(
    data.eventType === 'AI_BUY_ALERT' ? 'AI买入预警' :
    data.eventType === 'PREPARE_ENTRY' || data.eventType === 'AI_STAGE_ALERT' ? '准备入场' :
    data.eventType === 'POSITION_EXIT_NOTICE' || data.eventType === 'ENTRY_INVALIDATED' ? '离场' :
    data.signalType === 'BUY' ? '入场' : /接近/.test(title) ? '准备入场' : '', title, data);

  const rows = messages();
  const existingIdx = rows.findIndex((r) => r.id === id);
  const at = Number(data.issuedAtMs || data.timestamp || Number(data.expiresAt) - 90000) || Date.now();
  if (!category || at <= Number(localStorage.getItem(CLEAR_KEY))) return;
  const updatedItem: InboxMessage = { id, title, body, at, category, read: false, extra: data };

  if (existingIdx >= 0) {
    // If existing message only had the vague placeholder "请查看最新状态", replace it with rich data!
    const existing = rows[existingIdx];
    if (data.lifecycle || existing.body === '请查看最新状态' || !existing.body || existing.title === 'Crypto-G 通知') {
      const nextRows = [...rows];
      nextRows[existingIdx] = { ...existing, title, body, category, extra: data };
      save(nextRows);
    }
    return;
  }

  save([updatedItem, ...rows].sort((a, b) => b.at - a.at));
}

export function readMessage(id: string) {
  save(messages().map((m) => (m.id === id ? { ...m, read: true } : m)));
}

export function markAllAsRead() {
  save(messages().map((m) => ({ ...m, read: true })));
}

export function clearReadMessages() {
  save(messages().filter((m) => !m.read||protectedMessage(m)));
}

export function deleteMessage(id: string) {
  if(messages().some(m=>m.id===id&&protectedMessage(m)))return;
  const ids = new Set<string>(JSON.parse(localStorage.getItem(DELETED_KEY) || '[]'));
  ids.add(id);
  localStorage.setItem(DELETED_KEY,JSON.stringify([...ids]));
  save(messages().filter((m) => m.id !== id));
}

export function isNoiseCategory(category: string, title = ''): boolean {
  return category === '观察' || category === '摘要' || category === '失效' || /观察|摘要|失效/.test(title);
}

export function isNoiseShieldEnabled(): boolean {
  try {
    const val = localStorage.getItem('cryptog_shield_noise_messages');
    return val === null ? true : val === 'true';
  } catch {
    return true;
  }
}

export function setNoiseShieldEnabled(enabled: boolean) {
  try {
    localStorage.setItem('cryptog_shield_noise_messages', String(enabled));
    if (typeof window !== 'undefined') {
      window.dispatchEvent(new Event('cryptog-inbox-filter'));
    }
  } catch {
    /* ignore */
  }
}

export function clearNoiseMessages() {
  save(messages().filter((m) => protectedMessage(m)||!isNoiseCategory(m.category, m.title)));
}

export function markNoiseAsRead() {
  save(messages().map((m) => (isNoiseCategory(m.category, m.title) ? { ...m, read: true } : m)));
}

export function focusMessage(id: string) {
  if (typeof window !== 'undefined') {
    localStorage.setItem(PENDING_FOCUS_KEY, id);
    window.dispatchEvent(new CustomEvent('cryptog-focus-message', { detail: { id } }));
  }
}

export function getAndClearPendingFocus(): string | null {
  if (typeof window === 'undefined') return null;
  const id = localStorage.getItem(PENDING_FOCUS_KEY);
  if(id&&!messages().some(m=>m.id===id))return null;
  if (id) {
    localStorage.removeItem(PENDING_FOCUS_KEY);
  }
  return id;
}

export async function syncInbox() {
  autoClearMessages();
  try {
    const c = connection();
    const response = await fetch(`${c.url}/model-library/market-state`, {
      headers: { 'X-Library-Token': c.token },
      signal: AbortSignal.timeout(7000),
    });
    if (!response.ok) return;
    const value = await response.json();
    if(c.cacheScope!==connection().cacheScope)return;
    for (const m of value.observationMessages || []) {
      ingestMessage(m);
    }
    if(value.waveResearch?.mode==='RESEARCH_ONLY'&&value.waveResearch.tradeEligible===false)
      for(const m of value.waveMessages||[])ingestMessage(m);
  } catch {
    /* Offline messages remain stored. */
  }
}
