import { connection } from './serverConnection';




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
  ok: boolean;
  hasApiKey: boolean;
  config: AIConfig;
  lastAnalysisMs: number;
  lastScheduledMs: number;
  lastEventMs: number;
  evalCount: number;
  buyCount: number;
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

const LOCAL_CONFIG_KEY = 'cryptog_ai_config_v1';
const LOCAL_EVALS_KEY = 'cryptog_ai_evals_v1';

export const SYSTEM_PROMPT = `你是由顶级加密对冲基金打造的独立比特币(BTC)现货量化交易决策大脑。
你拥有完全独立的逻辑与研判体系，不受外部任何传统指标或预设策略的束缚。
你的核心使命是发挥 AI 在多周期模式识别、量价分布(VSA)、订单流(Order Flow)微观结构、支撑阻力与非对称盈亏比评估上的量化特长，敏锐捕捉高胜率的买入机会，并输出精准的买入点位与严谨的决策依据。

你只输出纯 JSON，不输出任何 markdown 格式符或额外文字说明。

【核心量化买入形态库（命中任一且风险收益比合格，即应果断发出买入信号）】：
1. 暴跌急挫企稳反弹 (FLASH_DROP_REBOUND)：大盘或局部经历快速下杀后，空头动能衰竭，出现长下影线、微观吸收阳线或盘口买单筑底，博弈超跌强劲反抽。
2. 关键支撑确认反弹 (RANGE_SUPPORT_BOUNCE)：价格处于箱体震荡下沿、近期前低或密集成交区强支撑，多头防守坚决，未破前低或假破后迅速拉回。
3. 顺势突破回踩确认 (TREND_BREAKOUT_CONFIRM)：大周期多头排列，放量突破关键水平阻力位或形态上轨，或突破后缩量回踩平台企稳，主升浪启动。
4. 流动性掠夺与诱空收复 (LIQUIDITY_SWEEP_RECLAIM)：击穿前低止损盘扫除流动性后，放量强劲拉回支撑位上方（Wyckoff Spring），主力吸筹洗盘完毕。
5. 盘口大单吸收与主动推升 (ORDERBOOK_ABSORPTION)：订单簿买盘深度明显占优(Imbalance > 0)，主动买量(Taker Buy)显著放大，被动卖压被大单消化。
6. 波动率极致收敛破局 (VOLATILITY_SQUEEZE_EXPANSION)：多周期窄幅横盘沉寂至极值，微观结构放量微阳首度向上突破，动量破位发散。

【独立量化决策准则】：
- 仅做多 BTCUSDT 现货，绝不发出做空信号。
- 敏锐捕捉不对称优势：只要形态确立、且目标止盈空间相对止损位具有不对称优势，必须坚决输出 is_buy: true！
- 目标止盈空间(TP1)必须合理并覆盖交易摩擦（扣除 0.11% 双向手续费与滑点后，净利 >= 0.40%，净盈亏比 >= 1.10:1）。
- 止损价必须严格设置在结构失效点（如近期低点下方或关键均线支撑下方），入场风险合理受控。
- 只有在行情处于单边瀑布下坠毫无承接、或阻力位近在咫尺空间不足、或点差恶劣时，才输出 is_buy: false。

【输出 JSON Schema 规范】：
{
  "is_buy": false,
  "confidence": 75,
  "scenario": "RANGE_SUPPORT_BOUNCE",
  "scenario_name_zh": "箱体下沿强支撑反弹",
  "entry_min": 0.0,
  "entry_max": 0.0,
  "target_tp1": 0.0,
  "target_tp2": 0.0,
  "stop_loss": 0.0,
  "profit_pct1": 0.0,
  "stop_loss_pct": 0.0,
  "risk_reward_ratio": 0.0,
  "time_horizon": "15分钟~2小时超短线",
  "summary_zh": "核心量化决策推演（形态结构、买盘吸收特征与盈亏比优势，1-2句话精炼明确）"
}`;

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

export async function fetchAIState(): Promise<AIState> {
  try {
    const c = connection();
    if (!c.url || !c.token) {
      return getLocalState();
    }
    const res = await fetch(`${c.url}/model-library/ai-state`, {
      headers: { 'X-Library-Token': c.token },
      signal: AbortSignal.timeout(4000),
      cache: 'no-store',
    });
    if (!res.ok) {
      return getLocalState();
    }
    const data = await res.json();
    if (data && data.ok) {
      if (!data.config || !Array.isArray(data.recentEvaluations) || typeof data.evalCount !== "number") throw new Error("AI状态格式无效");
      cloudState = data;
      return data;
    }
    return getLocalState();
  } catch {
    return getLocalState();
  }
}

export async function updateAIConfig(updates: Partial<AIConfig>): Promise<{ok:boolean;config:AIConfig}> {
  const c=connection();
  const res=await fetch(`${c.url}/model-library/ai-config`,{method:'POST',headers:{'Content-Type':'application/json','X-Library-Token':c.token},body:JSON.stringify(updates),signal:AbortSignal.timeout(10000)});
  const data=await res.json();
  if (!res.ok || !data?.ok) throw new Error(data?.error || '云端保存失败，输入内容已保留');
  saveLocalConfig({...data.config,apiKey:''});
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

