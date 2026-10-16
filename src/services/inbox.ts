import { connection } from './serverConnection';

export interface InboxMessage {
  id: string;
  title: string;
  body: string;
  at: number;
  category: string;
  read: boolean;
  extra?: any;
}

const KEY = 'cryptog_inbox_v1';
const PENDING_FOCUS_KEY = 'cryptog_pending_focus_id';

export function messages(): InboxMessage[] {
  try {
    return JSON.parse(localStorage.getItem(KEY) || '[]');
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
  const id =
    data.eventId ||
    data.id ||
    data.testId ||
    data.deliveryId ||
    (data.title ? `msg_${Date.now()}_${Math.random().toString(36).slice(2, 6)}` : null);
  if (typeof id !== 'string') return;

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
  const category =
    data.eventType === 'AI_BUY_ALERT' || (data.source && String(data.source).includes('AI'))
      ? 'AI'
      : data.signalType === 'BUY'
      ? '入场'
      : data.eventType === 'POSITION_EXIT_NOTICE'
      ? '退出'
      : /测试/.test(title)
      ? '测试'
      : /失效/.test(title)
      ? '失效'
      : /摘要/.test(title)
      ? '摘要'
      : /接近/.test(title)
      ? '接近'
      : '观察';

  const rows = messages();
  const existingIdx = rows.findIndex((r) => r.id === id);
  const at = Number(data.issuedAtMs || data.timestamp || Number(data.expiresAt) - 90000) || Date.now();
  const updatedItem: InboxMessage = { id, title, body, at, category, read: false, extra: data };

  if (existingIdx >= 0) {
    // If existing message only had the vague placeholder "请查看最新状态", replace it with rich data!
    const existing = rows[existingIdx];
    if (existing.body === '请查看最新状态' || !existing.body || existing.title === 'Crypto-G 通知') {
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
  save(messages().filter((m) => !m.read));
}

export function deleteMessage(id: string) {
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
  save(messages().filter((m) => !isNoiseCategory(m.category, m.title)));
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
  if (id) {
    localStorage.removeItem(PENDING_FOCUS_KEY);
  }
  return id;
}

export async function syncInbox() {
  try {
    const c = connection();
    const response = await fetch(`${c.url}/model-library/market-state`, {
      headers: { 'X-Library-Token': c.token },
      signal: AbortSignal.timeout(7000),
    });
    if (!response.ok) return;
    const value = await response.json();
    for (const m of value.observationMessages || []) {
      ingestMessage(m);
    }
  } catch {
    /* Offline messages remain stored. */
  }
}
