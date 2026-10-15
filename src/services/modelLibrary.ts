import type { ExecutionFill } from './executionLedger';
/**
 * Phone-side copy and sync for the permanent model library.
 * The server files under /opt/shotcrypto/model_library/ are the archive.
 * This module never deletes a row.
 */

export const MODEL_LIBRARY_DIR = '/opt/shotcrypto/model_library';
export const MODEL_LIBRARY_FILES = {
  alerts: `${MODEL_LIBRARY_DIR}/alerts.jsonl`,
  userActions: `${MODEL_LIBRARY_DIR}/user_actions.jsonl`,
  outcomes: `${MODEL_LIBRARY_DIR}/outcomes.jsonl`,
  openTracks: `${MODEL_LIBRARY_DIR}/open_tracks.json`,
};

import { connection } from './serverConnection';
const LOCAL_KEY = 'shotcrypto_model_library_v1';
const QUEUE_KEY = 'shotcrypto_model_library_queue_v1';

export interface LibraryTrackStatus {
  alertId: string;
  outcomeWritten: boolean;
  pathStatus?: string;
  tp1Touched: boolean;
  tp2Touched: boolean;
  slTouched: boolean;
  firstTp1Ms?: number | null;
  firstSlMs?: number | null;
  maxHigh?: number;
  minLow?: number;
  lastPrice?: number;
  simBuy?: boolean;
  userClosed?: boolean;
  model?: string;
  deadlineMs?: number;
  maxHoldMinutes?: number;
  remainingFraction?: number;
  referenceNetPct?: number | null;
  observationGap?: boolean;
}

export interface LibraryAction {
  recordType: 'SIM_BUY' | 'USER_CLOSE' | 'BACKFILL_CLOSE' | 'STILL_HOLDING' | 'PHONE_RECEIVED' | 'PHONE_OPENED' | 'ENTRY_REJECTED' | 'MANUAL_FILL';
  eventId?: string;
  replacesEventId?: string;
  fill?: ExecutionFill;
  signalAtMs?: number;
  signalPrice?: number;
  quoteAtMs?: number;
  alertId: string;
  actedAtMs: number;
  entryPrice?: number;
  exitPrice?: number;
  positionSize?: number;
  exitSource?: 'APP_BUTTON' | 'BINANCE_BACKFILL' | 'TOUCH_PRICE_BACKFILL';
  strategy?: string;
  note?: string;
  approximate?: boolean;
}

export interface JournalEntry { action: LibraryAction & {eventId: string}; status: 'pending' | 'acked' | 'rejected'; error?: string }
export function effectiveExecutionRows(rows: JournalEntry[]) {
  const accepted = rows.filter(r=>r.action.fill && r.status !== 'rejected');
  const replaced = new Set(accepted.map(r=>r.action.replacesEventId).filter(Boolean));
  return accepted.filter(r=>!replaced.has(r.action.eventId));
}
const JOURNAL_KEY = 'shotcrypto_model_journal_v2';
let flushing: Promise<void> | null = null;
export function newEventId() { return crypto.randomUUID(); }
const EVENT_PREFIX = 'shotcrypto_model_event_v3:';
const MIGRATED_KEY = 'shotcrypto_model_events_migrated_v3';
function persist(rows: JournalEntry[]) {
  // Separate atomic keys prevent another tab's append from being overwritten by a queue snapshot.
  let changed = false;
  for (const row of rows) {
    const key = EVENT_PREFIX + row.action.eventId;
    const raw = localStorage.getItem(key);
    const existing = raw ? JSON.parse(raw) as JournalEntry : null;
    if (existing && JSON.stringify(existing.action) !== JSON.stringify(row.action)) throw new Error('记录编号冲突');
    if (existing && existing.status !== 'pending' && row.status === 'pending') continue;
    const encoded = JSON.stringify(row);
    if (encoded !== raw) { localStorage.setItem(key, encoded); changed = true; }
  }
  if (changed && typeof window !== 'undefined') window.dispatchEvent(new Event('library-journal-changed'));
}
export function libraryJournal(): JournalEntry[] {
  if (!localStorage.getItem(MIGRATED_KEY)) {
    let raw = localStorage.getItem(JOURNAL_KEY);
    if (raw === null) {
      const old = JSON.parse(localStorage.getItem(LOCAL_KEY) || '[]') as LibraryAction[];
      const pending = JSON.parse(localStorage.getItem(QUEUE_KEY) || '[]') as LibraryAction[];
      if (!Array.isArray(old) || !Array.isArray(pending)) throw new Error('旧记录存储异常');
      const queue = pending.map(action => JSON.stringify(action));
      const rows: JournalEntry[] = old.map(action => {
        const index = queue.indexOf(JSON.stringify(action));
        if (index >= 0) queue.splice(index, 1);
        return {action: {...action, eventId: action.eventId || newEventId()}, status: index >= 0 ? 'pending' : 'acked'};
      });
      for (const raw of queue) rows.push({action: {...JSON.parse(raw), eventId: newEventId()}, status: 'pending'});
      raw = JSON.stringify(rows);
      localStorage.setItem(JOURNAL_KEY, raw); // Stable migration IDs survive interruptions.
    }
    const rows = JSON.parse(raw);
    if (!Array.isArray(rows)) throw new Error('记录存储异常，请先导出备份');
    // No callbacks until the migration is complete.
    for (const row of rows) if (!localStorage.getItem(EVENT_PREFIX+row.action.eventId)) localStorage.setItem(EVENT_PREFIX+row.action.eventId, JSON.stringify(row));
    localStorage.setItem(MIGRATED_KEY, '1');
  }
  const rows: JournalEntry[] = [];
  for (let i=0; i<localStorage.length; i++) {
    const key = localStorage.key(i);
    if (key?.startsWith(EVENT_PREFIX)) {
      const row = JSON.parse(localStorage.getItem(key)!);
      if (!row?.action?.eventId || !['pending','acked','rejected'].includes(row.status)) throw new Error('记录存储异常，请先导出备份');
      rows.push(row);
    }
  }
  return rows.sort((a,b)=>a.action.actedAtMs-b.action.actedAtMs || a.action.eventId.localeCompare(b.action.eventId));
}
export function rememberAction(action: LibraryAction): string {
  const rows = libraryJournal();
  const eventId = action.eventId || newEventId();
  const existing = rows.find(row => row.action.eventId === eventId);
  if (existing) {
    if (JSON.stringify(existing.action) !== JSON.stringify({...action, eventId})) throw new Error('记录编号已用于不同内容');
    return eventId;
  }
  rows.push({action: {...action, eventId}, status: 'pending'});
  persist(rows);
  void flushLibraryQueue();
  return eventId;
}
export function flushLibraryQueue(): Promise<void> {
  if (flushing) return flushing;
  flushing = (async () => {
    // One writer across tabs where Web Locks is available, one in-flight request per app.
    const drain = async () => {
      if (!libraryJournal().some(row=>row.status==='pending')) return;
      const capabilityController = new AbortController();
      const capabilityTimer = setTimeout(()=>capabilityController.abort(),8000);
      try {
        const response = await fetch(`${connection().url}/model-library/capabilities`, {
          headers:{'X-Library-Token':connection().token}, signal:capabilityController.signal,
        });
        if (!response.ok || (await response.json()).userActionProtocol !== 2) return;
      } catch { return; }
      finally { clearTimeout(capabilityTimer); }
      const initial = libraryJournal().filter(row => row.status === 'pending');
      for (const {action} of initial) {
        const controller = new AbortController();
        const timer = setTimeout(() => controller.abort(), 8000);
        try {
          const res = await fetch(`${connection().url}/model-library/action`, {
            method: 'POST', headers: {'Content-Type': 'application/json', 'X-Library-Token': connection().token},
            body: JSON.stringify(action), signal: controller.signal,
          });
          const body = await res.json();
          const acked = res.ok && body.ok === true && body.eventId === action.eventId;
          const rejected = res.status === 400 && body.eventId === action.eventId;
          if (acked || rejected) {
            // Re-read: actions appended while fetch was pending must survive.
            persist(libraryJournal().map(row => row.action.eventId === action.eventId
              ? {...row, status: acked ? 'acked' : 'rejected', error: rejected ? String(body.error || '校验失败') : undefined} : row));
          }
        } catch { /* Keep the durable pending event, including on lost acknowledgments. */ }
        finally { clearTimeout(timer); }
      }
    };
    if (typeof navigator !== 'undefined' && navigator.locks) await navigator.locks.request('cryptog-library-sync', drain);
    else await drain();
  })().catch(error => { console.error('模型记录同步失败', error); }).finally(() => { flushing = null; });
  return flushing;
}

export async function fetchTrackStatus(alertId: string): Promise<LibraryTrackStatus | null> {
  if (!alertId) return null;
  try {
    const res = await fetch(
      `${connection().url}/model-library/status?alertId=${encodeURIComponent(alertId)}`,
      { headers: { 'X-Library-Token': connection().token } }
    );
    if (!res.ok) return null;
    const body = await res.json();
    return body?.track || null;
  } catch {
    return null;
  }
}

export async function fetchOpportunityArchive(alertId: string): Promise<unknown> {
  const controller = new AbortController();
  const timer = setTimeout(()=>controller.abort(), 8000);
  try {
    const res = await fetch(`${connection().url}/model-library/records?alertId=${encodeURIComponent(alertId)}`, {
      headers: {'X-Library-Token': connection().token}, signal: controller.signal,
    });
    if (!res.ok) throw new Error('服务器暂不可读或版本尚未更新');
    return await res.json();
  } finally { clearTimeout(timer); }
}

export async function fetchRecentOpportunities(): Promise<{alertId:string;atMs:number;model?:string;delivery:string;pathStatus:string}[]> {
  const controller = new AbortController(); const timer = setTimeout(()=>controller.abort(),8000);
  try {
    const res=await fetch(`${connection().url}/model-library/opportunities`,{headers:{'X-Library-Token':connection().token},signal:controller.signal});
    if(!res.ok) throw new Error('无法读取机会列表，请确认新版服务器已部署');
    const data=await res.json(); if(!Array.isArray(data.opportunities)) throw new Error('机会列表格式异常'); return data.opportunities;
  } finally {clearTimeout(timer);}
}

export function recordPhoneReceived(alertId: string, strategy?: string, signalAtMs?: number, signalPrice?: number, opened = false) {
  if (!alertId) return;
  rememberAction({
    recordType: opened ? 'PHONE_OPENED' : 'PHONE_RECEIVED',
    signalAtMs, signalPrice,
    alertId,
    actedAtMs: Date.now(),
    strategy,
    note: opened ? '用户点击通知；后台实际送达时间未知' : '前台推送回调时间，不等于用户看到的时间',
  });
}

export function recordSimBuy(input: {
  signalAtMs?: number;
  signalPrice?: number;
  alertId: string;
  entryPrice: number;
  positionSize: number;
  strategy?: string;
}) {
  rememberAction({
    recordType: 'SIM_BUY',
    signalAtMs: input.signalAtMs, signalPrice: input.signalPrice,
    alertId: input.alertId,
    actedAtMs: Date.now(),
    entryPrice: input.entryPrice,
    positionSize: input.positionSize,
    strategy: input.strategy,
    exitSource: 'APP_BUTTON',
    note: '用户点击记入持仓，按复核报价模拟买入；未下单',
  });
}

export function recordUserClose(input: {
  alertId: string;
  entryPrice: number;
  exitPrice: number;
  positionSize: number;
  note?: string;
}) {
  if (!input.alertId) return;
  rememberAction({
    recordType: 'USER_CLOSE',
    alertId: input.alertId,
    actedAtMs: Date.now(),
    entryPrice: input.entryPrice,
    exitPrice: input.exitPrice,
    positionSize: input.positionSize,
    exitSource: 'APP_BUTTON',
    note: input.note || '用户在 App 点击平仓',
  });
}

export function recordBackfillClose(input: {
  alertId: string;
  entryPrice: number;
  exitPrice: number;
  positionSize: number;
  actedAtMs: number;
  approximate: boolean;
  note?: string;
}) {
  if (!input.alertId) return;
  rememberAction({
    recordType: 'BACKFILL_CLOSE',
    alertId: input.alertId,
    actedAtMs: input.actedAtMs,
    entryPrice: input.entryPrice,
    exitPrice: input.exitPrice,
    positionSize: input.positionSize,
    exitSource: 'BINANCE_BACKFILL',
    approximate: input.approximate,
    note: input.note || '用户已在币安卖出，事后补记',
  });
}

export function recordStillHolding(alertId: string) {
  if (!alertId) return;
  rememberAction({
    recordType: 'STILL_HOLDING',
    alertId,
    actedAtMs: Date.now(),
    note: '用户确认仍在持有，尚未在币安卖出',
  });
}
