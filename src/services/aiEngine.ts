import { connection } from './serverConnection';
import { readStartupCache, writeStartupCache } from './startupCache';




export interface AIConfig {
  deleteKey?: boolean;
  connectionStatus?: string;
  savedAtMs?: number;
  verifiedAtMs?: number;
  revision?: number;
  enabled: boolean;
  apiKey: string;
  provider: 'GEMINI' | 'DEEPSEEK';
  model: string;
  intervalSeconds: number;
  enabled5m: boolean;
  enabledEventTrigger: boolean;
  eventCooldownSeconds: number;
}

export interface AIEvaluation {
  id: string;
  atMs: number;
  triggerReason: string;
  model: string;
  provider: string;
  isBuy: boolean;
  confidence: number;
  scenario: string;
  scenarioNameZh: string;
  summaryZh: string;
  entryMin?: number;
  entryMax?: number;
  targetTP1?: number;
  targetTP2?: number;
  stopLoss?: number;
  profitPercent1?: number;
  stopLossPercent?: number;
  riskRewardRatio?: number;
  timeHorizon?: string;
  maxHoldMinutes?: number;
  cardText?: string;
  expiresAt?: number;
}

export interface AISignal {
  id: string;
  atMs: number;
  symbol: string;
  signalType: string;
  source: string;
  provider: string;
  model: string;
  scenario: string;
  scenarioNameZh: string;
  entryMin: number;
  entryMax: number;
  entryPrice: number;
  targetTP1: number;
  targetTP2?: number;
  stopLoss: number;
  profitPercent1: number;
  stopLossPercent: number;
  riskRewardRatio: number;
  timeHorizon: string;
  summaryZh: string;
  expiresAt: number;
}

export interface AIState {
  cachedAtMs?: number;
  ok: boolean;
  hasApiKey: boolean;
  config: AIConfig;
  lastAnalysisMs: number;
  lastScheduledMs: number;
  lastEventMs: number;
  evalCount: number;
  buyCount: number;
  suggestedCount?: number;
  rejectedCount?: number;
  lastEvaluation: AIEvaluation | null;
  lastSignal: AISignal | null;
  recentEvaluations: AIEvaluation[];
  activeSignals: Record<string, AISignal>;
  error?: string;
  isLocalOnly?: boolean;
  trackedPlans?: Array<AISignal & { trackingMode?: string; trackingState?: string; trailingStop?: number; trackingHealth?: string }> ;
  retryAtMs?: number;
  nextDueMs?: number;
  isAnalyzing?: boolean;
}

export interface AITriggerResponse {
  ok: boolean;
  triggerReason?: string;
  atMs?: number;
  evaluation?: AIEvaluation;
  signalPushed?: boolean;
  error?: string;
}

let cloudState: AIState | null = null;
let cloudIdentity = '';
let cloudAt = 0;
let pendingAI: { identity: string; promise: Promise<AIState> } | null = null;
function identity() { const c = connection(); return c.url + c.token; }
export function getInitialAIState(): AIState | null {
  try {
    if (cloudIdentity === identity() && cloudState && Date.now() - cloudAt < 15000) return cloudState;
    const cached = readStartupCache<AIState>('ai', 86400000);
    if (!cached?.value.config || !Array.isArray(cached.value.recentEvaluations)) return null;
    return {...cached.value, ok: false, isLocalOnly: true, cachedAtMs: cached.at,
      isAnalyzing: false, lastEvaluation: null, lastSignal: null, activeSignals: {}, trackedPlans: []};
  } catch { return null; }
}

const LOCAL_CONFIG_KEY = 'cryptog_ai_config_v1';
const LOCAL_EVALS_KEY = 'cryptog_ai_evals_v1';

// The server owns the versioned AI prompt and validates every proposed trade.

export function getLocalConfig(): AIConfig {
  try {
    const raw = localStorage.getItem(LOCAL_CONFIG_KEY);
    if (raw) {
      const parsed = JSON.parse(raw);
      return {
        enabled: parsed.enabled ?? true,
        apiKey: parsed.apiKey || '',
        provider: parsed.provider || 'GEMINI',
        model: parsed.model || 'gemini-3.8-flash',
        intervalSeconds: parsed.intervalSeconds || 300,
        enabled5m: parsed.enabled5m ?? true,
        enabledEventTrigger: parsed.enabledEventTrigger ?? true,
        eventCooldownSeconds: parsed.eventCooldownSeconds || 180,
      };
    }
  } catch {}
  return {
    enabled: true,
    apiKey: '',
    provider: 'GEMINI',
    model: 'gemini-3.8-flash',
    intervalSeconds: 300,
    enabled5m: true,
    enabledEventTrigger: true,
    eventCooldownSeconds: 180,
  };
}

export function saveLocalConfig(cfg: AIConfig) {
  try {
    localStorage.setItem(LOCAL_CONFIG_KEY, JSON.stringify(cfg));
  } catch {}
}

export function getLocalState(): AIState {
  const cfg = getLocalConfig();
  let evals: AIEvaluation[] = [];
  try {
    const raw = localStorage.getItem(LOCAL_EVALS_KEY);
    if (raw) evals = JSON.parse(raw);
  } catch {}

  const lastEval = evals[0] || null;
  const buyCount = evals.filter((e) => e.isBuy).length;

  return {
    ok: false,
    error: "云端状态不可用，本机不执行自动分析",
    hasApiKey: Boolean(cfg.apiKey && cfg.apiKey.trim().length > 0),
    config: {
      ...cfg,
      apiKey: cfg.apiKey
        ? cfg.apiKey.length > 8
          ? cfg.apiKey.slice(0, 4) + '****' + cfg.apiKey.slice(-4)
          : '****'
        : '',
    },
    lastAnalysisMs: lastEval ? lastEval.atMs : 0,
    lastScheduledMs: 0,
    lastEventMs: 0,
    evalCount: evals.length,
    buyCount,
    lastEvaluation: null,
    lastSignal: null,
    recentEvaluations: evals.slice(0, 15),
    activeSignals: {},
    isLocalOnly: true,
  };
}

export function fetchAIState(): Promise<AIState> {
  let key: string;
  try { key = identity(); } catch { return Promise.resolve(getLocalState()); }
  if (pendingAI?.identity === key) return pendingAI.promise;
  if (cloudIdentity === key && cloudState && Date.now() - cloudAt < 1000) return Promise.resolve(cloudState);
  const promise = requestAIState(key).finally(() => { if (pendingAI?.promise === promise) pendingAI = null; });
  pendingAI = {identity: key, promise};
  return promise;
}

async function requestAIState(key: string): Promise<AIState> {
  try {
    const c = connection();
    if (!c.url || !c.token) {
      throw new Error('云端连接不可用');
    }
    const res = await fetch(`${c.url}/model-library/ai-state`, {
      headers: { 'X-Library-Token': c.token },
      signal: AbortSignal.timeout(4000),
      cache: 'no-store',
    });
    if (!res.ok) {
      throw new Error('云端连接不可用');
    }
    const data = await res.json();
    if (data && data.ok) {
      if (!data.config || !Array.isArray(data.recentEvaluations) || typeof data.evalCount !== "number") throw new Error("AI状态格式无效");
      if (identity() !== key) return getLocalState();
      cloudState = data;
      cloudIdentity = key;
      cloudAt = Date.now();
      writeStartupCache('ai', {...data, config: {...data.config, apiKey: ''}, lastSignal: null,
        lastEvaluation: null, activeSignals: {}, trackedPlans: []});
      return data;
    }
    throw new Error('云端状态不可用');
  } catch {
    if (cloudIdentity === key) cloudAt = 0;
    const cached = getInitialAIState();
    return cached ? {...cached, ok: false, isLocalOnly: true, error: '连接暂不可用，显示上次记录'} : getLocalState();
  }
}

export async function updateAIConfig(updates: Partial<AIConfig>): Promise<{ok:boolean;config:AIConfig}> {
  const c=connection();
  const res=await fetch(`${c.url}/model-library/ai-config`,{method:'POST',headers:{'Content-Type':'application/json','X-Library-Token':c.token},body:JSON.stringify(updates),signal:AbortSignal.timeout(10000)});
  const data=await res.json();
  if (!res.ok || !data?.ok) throw new Error(data?.error || '云端保存失败，输入内容已保留');
  saveLocalConfig({...data.config,apiKey:''});
  cloudAt = 0;
  return data;
}

export async function verifyAIConnection(): Promise<{ok:boolean; error?:string}> {
  const c=connection();
  const res=await fetch(`${c.url}/model-library/ai-verify`, {method:'POST',headers:{'Content-Type':'application/json','X-Library-Token':c.token},body:'{}',signal:AbortSignal.timeout(35000)});
  const data=await res.json();
  if (typeof data?.ok !== 'boolean') throw new Error('云端验证响应无效');
  return data;
}

export async function triggerAIAnalysis(reason: string = 'MANUAL_UI'): Promise<AITriggerResponse> {
  try {
    const c = connection();
    if (c.url && c.token) {
      const res = await fetch(`${c.url}/model-library/ai-trigger`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Library-Token': c.token,
        },
        body: JSON.stringify({ reason }),
        signal: AbortSignal.timeout(35000),
      });
      const data = await res.json().catch(() => null);
      if (data && typeof data.ok === "boolean") {
        return data;
      }
    }
  } catch {
    // Cloud server unreachable or unconfigured
  }

  // Autonomous fallback to local AI engine directly on client
  return { ok: false, error: "云端分析未确认完成，请刷新状态；未启动本地重复分析" };
}

export type AISchedulerListener = (event: 'START' | 'DONE' | 'TICK' | 'ERROR', data?: any) => void;

export class AIGlobalScheduler {
  private timer: any = null;
  private isAnalyzing: boolean = false;
  private listeners: Set<AISchedulerListener> = new Set();
  private started: boolean = false;
  private wakeLockSentinel: any = null;
  private wakeLockRequested: boolean = false;

  public start() {
    if (this.started) return;
    this.started = true;

    // Check if user previously requested screen wake lock
    if (this.isKeepScreenOn()) {
      this.wakeLockRequested = true;
      void this.requestWakeLock();
    }

    // 1. Initial tick on startup
    void this.tick('STARTUP_CHECK');

    // 2. High-frequency checking loop (every 5 seconds) to catch time thresholds promptly
    this.timer = setInterval(() => {
      void this.tick('TIMER_TICK');
    }, 5000);

    // 3. Document Visibility / Window Focus listener: catches phone unlock or app foreground switch
    if (typeof document !== 'undefined') {
      document.addEventListener('visibilitychange', this.handleVisibilityChange);
    }
    if (typeof window !== 'undefined') {
      window.addEventListener('focus', this.handleFocus);
    }
  }

  public stop() {
    this.started = false;
    if (this.timer) {
      clearInterval(this.timer);
      this.timer = null;
    }
    if (typeof document !== 'undefined') {
      document.removeEventListener('visibilitychange', this.handleVisibilityChange);
    }
    if (typeof window !== 'undefined') {
      window.removeEventListener('focus', this.handleFocus);
    }
    this.releaseWakeLock();
  }

  private handleVisibilityChange = () => {
    if (typeof document !== 'undefined' && document.visibilityState === 'visible') {
      if (this.wakeLockRequested) {
        void this.requestWakeLock();
      }
      void this.tick('RESUME_VISIBILITY_CATCHUP');
    }
  };

  private handleFocus = () => {
    void this.tick('RESUME_FOCUS_CATCHUP');
  };

  public async setKeepScreenOn(enable: boolean): Promise<boolean> {
    this.wakeLockRequested = enable;
    try {
      localStorage.setItem('cryptog_ai_wake_lock', enable ? '1' : '0');
    } catch {}
    if (enable) {
      return this.requestWakeLock();
    } else {
      this.releaseWakeLock();
      return false;
    }
  }

  public isKeepScreenOn(): boolean {
    try {
      return localStorage.getItem('cryptog_ai_wake_lock') === '1';
    } catch {
      return false;
    }
  }

  private async requestWakeLock(): Promise<boolean> {
    try {
      if ('wakeLock' in navigator && (navigator as any).wakeLock) {
        this.wakeLockSentinel = await (navigator as any).wakeLock.request('screen');
        this.wakeLockSentinel.addEventListener('release', () => {
          this.wakeLockSentinel = null;
        });
        return true;
      }
    } catch {}
    return false;
  }

  private releaseWakeLock() {
    try {
      if (this.wakeLockSentinel) {
        this.wakeLockSentinel.release();
        this.wakeLockSentinel = null;
      }
    } catch {}
  }

  public getNextDueMs(): number {
    return cloudState?.nextDueMs || Date.now();
  }

  public getRemainingSeconds(): number {
    const nextDue = this.getNextDueMs();
    const diff = Math.ceil((nextDue - Date.now()) / 1000);
    return Math.max(0, diff);
  }

  public getIsAnalyzing(): boolean {
    return this.isAnalyzing || Boolean(cloudState?.isAnalyzing);
  }

  public subscribe(listener: AISchedulerListener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  private notify(event: 'START' | 'DONE' | 'TICK' | 'ERROR', data?: any) {
    for (const listener of this.listeners) {
      try {
        listener(event, data);
      } catch {}
    }
  }

  public async tick(reason: string = 'TIMER_TICK') {
    // Cloud worker owns all autonomous scheduling.
    this.notify('TICK', { reason, skipped: 'CLOUD_SCHEDULED' });
    return;

  }

  public async triggerScheduledAnalysis(reason: string = 'SCHEDULED_5M') {
    if (this.isAnalyzing) return;
    this.isAnalyzing = true;
    this.notify('START', { reason });

    try {
      const res = await triggerAIAnalysis(reason);
      this.notify('DONE', { reason, res });
    } catch (err: any) {
      this.notify('ERROR', { reason, error: err.message });
    } finally {
      this.isAnalyzing = false;
      this.notify('TICK', { reason: 'POST_ANALYSIS', remainingSeconds: this.getRemainingSeconds() });
    }
  }

  /**
   * Layer 3 Event-Driven Trigger: Detect sudden flash drop or volume explosion
   */
  public async checkEventTrigger(_recentCandles1m: any[]) {
    // Cloud worker owns event detection.
  }
}

export const aiScheduler = new AIGlobalScheduler();

