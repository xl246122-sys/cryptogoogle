"""Independent BTC AI Quantitative Analysis & Alert Engine.

Supports Gemini 3.8/2.5 Flash and DeepSeek V4 pro/chat.
Operates strictly independently from baseline and shadow strategies.
Follows the 3-layer architecture:
  Layer 1: Continuous market monitoring (zero LLM calls).
  Layer 2: Autonomous full LLM analysis every 5 minutes on closed 5m bars.
  Layer 3: Event-driven rapid LLM trigger on sudden shock/breakout with 3-minute cooldown.
Enforces real-time fresh Ask quote re-verification before push dispatch.
"""

import json
import logging
import math
import os
import threading
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from cryptography.fernet import Fernet
from .config import MIN_GROSS_TP1, MIN_NET_TP1
from .ai_policy import MODULES, rolling_windows, trade_plan, same_opportunity, alert_card, advance_plan

logger = logging.getLogger("crypto-g.ai-engine")

DEFAULT_AI_CONFIG = {
    "enabled": True,
    "enabled5m": True,
    "enabledEventTrigger": True,
    "provider": "GEMINI",
    "apiKey": "",
    "model": "gemini-2.5-flash",
    "intervalSeconds": 300,
    "eventTriggerEnabled": True,
    "eventCooldownSeconds": 180,
    "maxHoldMinutes": 360,
    "minNetTp1": MIN_NET_TP1,
    "minNetRR": 1.10,
    "assumedFrictionPct": 0.11,
}

SYSTEM_PROMPT = """你是 BTCUSDT 现货买入分析引擎。只使用输入的币安现货数据。
手机短线持有 10 分钟到 4 小时。价格、止损和目标由输入里的 shortHorizon 契约计算，你不能改价。
买入时 scenario 只能是契约给出的 module：FLUSH_RECLAIM（急跌收回）或 PULLBACK_RECLAIM（回踩收回）。
契约为 null，或你判断结构冲突、证据不足时，is_buy=false，scenario=NONE。
不要输出秒级急跌、也不要自己发明入场价。summary_zh 用 1~25 字说明原因。
仅返回 JSON。is_buy 必须是真布尔值。confidence 是自评分，不是胜率。"""


def build_ai_prompt(snapshot):
    """Build a rich, feature-dense multi-timeframe quantitative prompt from snapshot."""
    ticker = snapshot.get("ticker", {})
    series = snapshot.get("series", {})
    book = snapshot.get("book", {})

    price = ticker.get("bid_price", 0.0)
    ask = ticker.get("ask_price", 0.0)
    spread_pct = ((ask - price) / price * 100) if price > 0 else 0.0
    change24h = ticker.get("change24h", 0.0)
    high24h = ticker.get("high24h", 0.0)
    low24h = ticker.get("low24h", 0.0)

    # Calculate book imbalance top 10
    bids = book.get("bids", [])[:10]
    asks = book.get("asks", [])[:10]
    bid_vol = sum(float(b[1]) for b in bids) if bids else 0.0
    ask_vol = sum(float(a[1]) for a in asks) if asks else 0.0
    total_vol = bid_vol + ask_vol
    imbalance = float(book.get("imbalance", ((bid_vol - ask_vol) / total_vol) if total_vol > 0 else 0.0))

    # 5m candles (recent 16) & calculate technical metrics
    m5 = series.get("5m", [])[-16:]
    m5_closes = [c["close"] for c in m5] if m5 else []
    ema7 = m5_closes[0] if m5_closes else price
    for close in m5_closes[1:]:
        ema7 += (close - ema7) * 0.25
    m5_recent_vol = sum(c["volume"] for c in m5[-3:]) if len(m5) >= 3 else 1.0
    m5_recent_buy_vol = sum(c.get("taker_buy_base", 0) for c in m5[-3:]) if len(m5) >= 3 else 0.0
    taker_buy_ratio = (m5_recent_buy_vol / m5_recent_vol * 100) if m5_recent_vol > 0 else 50.0

    m5_str = "\n".join(
        f"  - 5m[{i}]: O={c['open']:.2f}, H={c['high']:.2f}, L={c['low']:.2f}, C={c['close']:.2f}, Vol={c['volume']:.2f}, BuyVol={c.get('taker_buy_base', 0):.2f}"
        for i, c in enumerate(m5)
    )

    # 15m candles (recent 8)
    m15 = series.get("15m", [])[-8:]
    m15_high = max((c["high"] for c in m15), default=price)
    m15_low = min((c["low"] for c in m15), default=price)
    m15_range_pct = ((m15_high - m15_low) / m15_low * 100) if m15_low > 0 else 0.0

    m15_str = "\n".join(
        f"  - 15m[{i}]: O={c['open']:.2f}, H={c['high']:.2f}, L={c['low']:.2f}, C={c['close']:.2f}, Vol={c['volume']:.2f}"
        for i, c in enumerate(m15)
    )

    # 1h candles (recent 6)
    h1 = series.get("1h", [])[-6:]
    h1_str = "\n".join(
        f"  - 1h[{i}]: O={c['open']:.2f}, H={c['high']:.2f}, L={c['low']:.2f}, C={c['close']:.2f}"
        for i, c in enumerate(h1)
    )

    h4_str = "\n".join(f"O={c['open']:.2f}, H={c['high']:.2f}, L={c['low']:.2f}, C={c['close']:.2f}" for c in series.get("4h", [])[-6:])

    # 1m candles (recent 5 for micro momentum)
    m1 = series.get("1m", [])[-5:]
    m1_str = "\n".join(
        f"  - 1m[{i}]: O={c['open']:.2f}, H={c['high']:.2f}, L={c['low']:.2f}, C={c['close']:.2f}, Vol={c['volume']:.2f}"
        for i, c in enumerate(m1)
    )

    prompt = f"""【BTC 实时行情与量化盘口快照】
- 标的: BTC/USDT 现货
- 最新买卖价: Bid={price:.2f} | Ask={ask:.2f} | 点差={spread_pct:.4f}%
- 24h行情: 涨跌幅={change24h:.2f}% | 最高={high24h:.2f} | 最低={low24h:.2f}
- 盘口深度失衡比 (缓存聚合盘口): {imbalance:+.3f} (正数=买盘挂单占优，负数=卖盘挂单占优)
- 短线特征参考: 5m EMA7={ema7:.2f} | 近3根5m主动吃单买入占比={taker_buy_ratio:.1f}% | 15m振幅区间={m15_low:.2f}~{m15_high:.2f} ({m15_range_pct:.2f}%)

【1分钟超短线微结构 (最新5根)】:
{m1_str}

【5分钟核心K线序列 (最新16根已收盘)】:
{m5_str}

【15分钟波段结构 (最新8根已收盘)】:
{m15_str}

【1小时宏观背景趋势 (最新6根已收盘)】:
{h1_str}

【4小时背景 (已收盘)】：
{h4_str}

【独立量化决策指令】：
请充分发挥 AI 量化大脑的自主判断与模式识别特长，对多周期量价形态与盘口订单流进行全局综合推理。
如果发现符合待验证买入形态（如止跌反弹、支撑企稳、顺势突破回踩、诱空收复或大单吸收），且具备非对称盈亏比，证据充分且满足模块计划时才输出买入 (is_buy: true)，并给出包含最新 Ask 报价的精准建议买入区间 [entry_min, entry_max]、目标止盈与结构止损。
若当前处于纯单边下坠无承接或空间不足，请输出 is_buy: false。直接返回纯 JSON 对象。"""
    from .short_horizon import setup_from_snapshot
    prompt += "\nshortHorizon契约（价格已计算，只能同意或否决）：" + json.dumps(setup_from_snapshot(snapshot, snapshot.get("atMs") or 0), ensure_ascii=False, default=str)
    prompt += "\n滚动现货窗口（分钟）：" + json.dumps(rolling_windows(snapshot), ensure_ascii=False)
    prompt += "\n可引用结构K线：" + json.dumps({tf:[{k:b[k] for k in ("time","low","high","close")} for b in bars[-48:]] for tf,bars in series.items()},ensure_ascii=False)
    return prompt


class AIEngine:
    def __init__(self, store, cache, send_fcm_alert, stop_event):
        self.store = store
        self.cache = cache
        self.send_fcm_alert = send_fcm_alert
        self.stop = stop_event
        self.lock = threading.Lock()
        self.delivery_lock = threading.Lock()
        self.signal_lock = threading.RLock()
        self.last_analysis_ms = 0
        self.last_scheduled_ms = 0
        self.last_event_ms = 0
        self.last_evaluation = None
        self.last_signal = None
        self.active_signals = {}
        self._init_db()
        db_path = self.store.db.execute('PRAGMA database_list').fetchone()[2]
        key_path = Path(db_path).with_suffix('.ai-key')
        try:
            fd = os.open(str(key_path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            pass
        else:
            with os.fdopen(fd,'wb') as f: f.write(Fernet.generate_key())
        self.cipher = Fernet(key_path.read_bytes())
        with self.store.lock, self.store.db:
            self.store.db.execute('CREATE TABLE IF NOT EXISTS ai_credentials(provider TEXT PRIMARY KEY,secret TEXT NOT NULL)')
            row = self.store.db.execute('SELECT payload FROM ai_config WHERE id=1').fetchone()
            if row:
                legacy = json.loads(row[0])
                secret = legacy.pop('apiKey','')
                if secret:
                    self.store.db.execute('INSERT OR IGNORE INTO ai_credentials VALUES(?,?)',(legacy.get('provider','GEMINI'),self.cipher.encrypt(secret.encode()).decode()))
                    self.store.db.execute('UPDATE ai_config SET payload=? WHERE id=1',(json.dumps(legacy),))
        self.last_error = None
        self.retry_at = 0
        self.failures = 0
        self.last_attempt_ms = 0
        self.last_bar = 0
        with self.store.lock, self.store.db:
            self.store.db.execute("CREATE TABLE IF NOT EXISTS ai_runtime(id INTEGER PRIMARY KEY,payload TEXT)")
            self.store.db.execute("CREATE TABLE IF NOT EXISTS ai_delivery(id TEXT PRIMARY KEY, attempts INTEGER NOT NULL DEFAULT 0, due INTEGER NOT NULL DEFAULT 0, last_error TEXT, accepted_ms INTEGER)")
            self.store.db.execute("CREATE TABLE IF NOT EXISTS ai_stages(id TEXT PRIMARY KEY,payload TEXT NOT NULL,state TEXT NOT NULL,due INTEGER NOT NULL,expires INTEGER NOT NULL)")
            self.store.db.execute("CREATE TABLE IF NOT EXISTS ai_inputs(id TEXT PRIMARY KEY,payload TEXT NOT NULL)")
            row = self.store.db.execute("SELECT payload FROM ai_runtime WHERE id=1").fetchone()
            if row:
                for k, v in json.loads(row[0]).items():
                    setattr(self, k, v)
            self.store.db.execute("UPDATE observation_queue SET state='MIGRATED' WHERE id LIKE 'AI_%' AND state='PENDING'")
            rows = self.store.db.execute("SELECT payload FROM ai_signals WHERE state IN ('PENDING','FCM_ACCEPTED') ORDER BY at_ms").fetchall()
            for row in rows:
                sig = json.loads(row[0])
                if sig.get('trackingState', 'WATCHING') == 'WATCHING':
                    self.active_signals[sig['id']] = sig
                self.last_signal = sig
            row = self.store.db.execute("SELECT payload FROM ai_evaluations ORDER BY at_ms DESC LIMIT 1").fetchone()
            if row and 'isBuy' in json.loads(row[0]):
                self.last_evaluation = json.loads(row[0])
                self.last_analysis_ms = self.last_evaluation['atMs']

    def save_runtime(self):
        data = {k: getattr(self, k) for k in ('last_bar','last_attempt_ms','retry_at','failures','last_error','last_scheduled_ms','last_event_ms')}
        with self.store.lock, self.store.db:
            self.store.db.execute("INSERT OR REPLACE INTO ai_runtime VALUES(1,?)", (json.dumps(data),))

    def _init_db(self):
        with self.store.lock, self.store.db:
            self.store.db.executescript("""
            CREATE TABLE IF NOT EXISTS ai_config(id INTEGER PRIMARY KEY, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS ai_evaluations(
                id TEXT PRIMARY KEY,
                at_ms INTEGER NOT NULL,
                trigger_reason TEXT NOT NULL,
                model TEXT NOT NULL,
                provider TEXT NOT NULL,
                is_buy INTEGER NOT NULL,
                confidence INTEGER,
                scenario TEXT,
                payload TEXT NOT NULL,
                summary TEXT
            );
            CREATE TABLE IF NOT EXISTS ai_signals(
                id TEXT PRIMARY KEY,
                at_ms INTEGER NOT NULL,
                scenario TEXT NOT NULL,
                entry_min REAL NOT NULL,
                entry_max REAL NOT NULL,
                target_tp1 REAL NOT NULL,
                stop_loss REAL NOT NULL,
                state TEXT NOT NULL,
                payload TEXT NOT NULL,
                expires_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS observation_queue(
                id TEXT PRIMARY KEY,
                payload TEXT NOT NULL,
                state TEXT NOT NULL,
                due INTEGER NOT NULL,
                expires INTEGER NOT NULL
            );
            """)

    def get_config(self):
        with self.store.lock:
            row = self.store.db.execute("SELECT payload FROM ai_config WHERE id=1").fetchone()
            if row:
                try:
                    cfg = json.loads(row[0])
                    merged = dict(DEFAULT_AI_CONFIG)
                    if "enabledEventTrigger" not in cfg:
                        cfg["enabledEventTrigger"] = cfg.get("eventTriggerEnabled", True)
                    merged.update(cfg)
                    # These are server policy constants, never stale saved preferences.
                    for key in ('minNetTp1','minNetRR','assumedFrictionPct','maxHoldMinutes'):
                        merged[key]=DEFAULT_AI_CONFIG[key]
                    merged["apiKey"] = self.provider_key(merged["provider"])
                    return merged
                except Exception:
                    pass
            # Fallback to env
            cfg = dict(DEFAULT_AI_CONFIG)
            cfg["apiKey"] = self.provider_key(cfg["provider"])
            return cfg

    def provider_key(self, provider):
        row = self.store.db.execute('SELECT secret FROM ai_credentials WHERE provider=?',(provider,)).fetchone()
        return self.cipher.decrypt(row[0].encode()).decode() if row else os.environ.get('DEEPSEEK_API_KEY' if provider=='DEEPSEEK' else 'GEMINI_API_KEY','')

    def set_config(self, updates):
        if not self.lock.acquire(blocking=False):
            raise ValueError('AI_BUSY: 分析中，请完成后重试保存；输入内容已保留')
        try:
            return self._set_config(updates)
        finally:
            self.lock.release()

    def _set_config(self, updates):
        current = self.get_config()
        allowed = {"enabled", "enabled5m", "enabledEventTrigger", "provider", "model", "apiKey", "intervalSeconds", "eventCooldownSeconds", "deleteKey"}
        if set(updates) - allowed:
            raise ValueError("UNKNOWN_CONFIG_FIELD")
        for key in ("enabled", "enabled5m", "enabledEventTrigger"):
            if key in updates and type(updates[key]) is not bool:
                raise ValueError("INVALID_CONFIG_BOOLEAN")
        for key, minimum in (("intervalSeconds", 300), ("eventCooldownSeconds", 180)):
            if key in updates and (type(updates[key]) is not int or not minimum <= updates[key] <= 86400):
                raise ValueError("INVALID_CONFIG_INTERVAL")
        for key in ("provider", "model", "apiKey"):
            if key in updates and (not isinstance(updates[key], str) or len(updates[key]) > 512):
                raise ValueError("INVALID_CONFIG_STRING")
        if "provider" in updates and updates["provider"] not in ("GEMINI", "DEEPSEEK"):
            raise ValueError("INVALID_PROVIDER")
        changed = any(updates.get(k,current.get(k)) != current.get(k) for k in ('provider','model','apiKey'))
        if 'deleteKey' in updates and type(updates['deleteKey']) is not bool:
            raise ValueError('INVALID_DELETE_KEY')
        changed = changed or updates.get('deleteKey', False)
        current.update(updates)
        current.pop('deleteKey',None)
        secret = updates.get('apiKey','').strip()
        current.pop('apiKey',None)
        current['revision'] = int(current.get('revision',0))+1
        current['savedAtMs'] = int(time.time()*1000)
        if changed:
            current['connectionStatus'] = 'UNVERIFIED'
            current['verifiedAtMs'] = 0
        with self.store.lock, self.store.db:
            if updates.get('deleteKey'):
                self.store.db.execute('DELETE FROM ai_credentials WHERE provider=?',(current['provider'],))
            if secret and not updates.get('deleteKey'):
                self.store.db.execute('INSERT OR REPLACE INTO ai_credentials VALUES(?,?)',(current['provider'],self.cipher.encrypt(secret.encode()).decode()))
            self.store.db.execute("INSERT OR REPLACE INTO ai_config VALUES(1, ?)", (json.dumps(current),))
        if changed:
            self.retry_at = self.failures = self.last_attempt_ms = 0
            self.last_error = None
            self.save_runtime()
        return self.status()["config"]

    def verify_connection(self):
        if not self.lock.acquire(blocking=False):
            return {'ok':False,'error':'AI_BUSY: 分析正在进行'}
        try:
            cfg=self.get_config()
            if not cfg['apiKey']:
                return {'ok':False,'error':'MISSING_API_KEY: 请保存当前厂商密钥'}
            try:
                fn=self.call_deepseek if cfg['provider']=='DEEPSEEK' else self.call_gemini
                fn(cfg['apiKey'],cfg['model'],'连接测试：忽略交易任务，仅返回 JSON {"is_buy":false}')
                error=None
            except Exception as exc:
                error=self.api_error(exc)
            cfg.pop('apiKey',None)
            cfg['connectionStatus']='FAILED' if error else 'VERIFIED'
            cfg['verifiedAtMs']=int(time.time()*1000)
            with self.store.lock,self.store.db:
                self.store.db.execute('UPDATE ai_config SET payload=? WHERE id=1',(json.dumps(cfg),))
            self.last_error=error
            self.retry_at = int(time.time()*1000)+900000 if error else 0
            self.failures = 1 if error else 0
            self.last_attempt_ms=0
            self.save_runtime()
            return {'ok':not error,'error':error,'config':self.status()['config']}
        finally:
            self.lock.release()

    @staticmethod
    def api_error(exc):
        if isinstance(exc,urllib.error.HTTPError):
            messages={401:'密钥无效或已撤销',402:'账户额度不足',403:'账户或地区访问受限',404:'模型或接口不存在',429:'请求限流，请稍后重试'}
            return f'API_HTTP_{exc.code}: '+messages.get(exc.code,'模型服务请求失败')
        return 'API_NETWORK_OR_RESPONSE_ERROR: 网络超时或响应格式异常'

    def call_gemini(self, api_key, model, prompt):
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
        body = {
            "contents": [{"parts": [{"text": SYSTEM_PROMPT + "\n\n" + prompt}]}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "temperature": 0.2,
            },
        }
        req = urllib.request.Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=25) as response:
            res_data = json.loads(response.read().decode("utf-8"))
            text = res_data["candidates"][0]["content"]["parts"][0]["text"]
            return json.loads(text)

    def call_deepseek(self, api_key, model, prompt):
        url = "https://api.deepseek.com/chat/completions"
        body = {
            "model": model or "deepseek-chat",
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.2,
        }
        req = urllib.request.Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=25) as response:
            res_data = json.loads(response.read().decode("utf-8"))
            text = res_data["choices"][0]["message"]["content"]
            return json.loads(text)

    def execute_analysis(self, trigger_reason="SCHEDULED_5M"):
        if not self.lock.acquire(blocking=False):
            return {"ok": False, "error": "AI_BUSY"}
        try:
            now = int(time.time()*1000)
            if now < self.retry_at or now-self.last_attempt_ms < 30000:
                return {"ok": False, "error": "AI_COOLDOWN: 等待失败重试，更新密钥后可重新验证", "retryAtMs": self.retry_at}
            self.last_attempt_ms = now
            self.save_runtime()
            try:
                result = self._execute_analysis(trigger_reason)
            except (ValueError, TypeError, KeyError, OverflowError) as exc:
                result = {"ok": False, "error": "INVALID_MODEL_RESPONSE:"+type(exc).__name__}
            if result.get('ok'):
                self.failures = 0
                self.retry_at = 0
                self.last_error = None
            else:
                self.failures += 1
                self.retry_at = now + min(900000, 30000 * 2**min(self.failures,5))
                self.last_error = result.get('error')
            self.save_runtime()
            return result
        finally:
            self.lock.release()

    def _execute_analysis(self, trigger_reason="SCHEDULED_5M"):
        """Perform one single-threaded LLM analysis, record outcome, and push if valid."""
        if True:
            cfg = self.get_config()
            if not cfg.get("enabled"):
                return {"ok": False, "error": "AI_ENGINE_DISABLED"}

            api_key = cfg.get("apiKey") or os.environ.get("DEEPSEEK_API_KEY" if cfg.get("provider") == "DEEPSEEK" else "GEMINI_API_KEY")
            if not api_key:
                return {"ok": False, "error": "MISSING_API_KEY"}

            now_ms = int(time.time() * 1000)
            snapshot = self.cache.snapshot(now_ms)
            if not snapshot.get("healthy"):
                return {"ok": False, "error": "MARKET_SNAPSHOT_UNHEALTHY"}

            prompt = build_ai_prompt(snapshot)
            provider = cfg.get("provider", "GEMINI").upper()
            model = cfg.get("model", "gemini-2.5-flash")

            start_t = time.time()
            try:
                if provider == "DEEPSEEK":
                    decision = self.call_deepseek(api_key, model, prompt)
                else:
                    decision = self.call_gemini(api_key, model, prompt)
            except Exception as e:
                logger.error("LLM API call failed: %s", type(e).__name__)
                return {"ok": False, "error": self.api_error(e)}

            duration_ms = int((time.time() - start_t) * 1000)
            if not isinstance(decision, dict) or type(decision.get("is_buy")) is not bool:
                return {"ok": False, "error": "INVALID_MODEL_RESPONSE"}
            is_buy = decision["is_buy"]
            if is_buy and decision.get('scenario') == 'FLASH_REBOUND_FAST':
                return {'ok':False,'error':'FAST_MODULE_REQUIRES_REALTIME_DETECTOR'}
            if is_buy and decision.get("scenario") in ("FLUSH_RECLAIM", "PULLBACK_RECLAIM"):
                from .short_horizon import setup_from_snapshot
                setup = setup_from_snapshot(snapshot, now_ms)
                if not setup or setup["module"] != decision.get("scenario"):
                    is_buy = False
                    decision["is_buy"] = False
                    decision["summary_zh"] = "结构契约未确认该形态"
                else:
                    decision["contract_locked"] = True
                    decision.update(entry_min=setup["entry"], entry_max=setup["entry"], target_tp1=setup["target"],
                                    target_tp2=setup["target"], stop_loss=setup["stop"], hold_minutes=setup["hold"],
                                    anchor_timeframe="30m", anchor_time_ms=setup["anchor_time_ms"],
                                    scenario_name_zh=setup["name_zh"], min_net=setup["min_net"],
                                    expires_at=setup["expires_at"], structure_key=setup["structure_key"])
            eval_id = str(uuid.uuid4())

            # Audit record
            eval_record = {
                "id": eval_id,
                "evalId": eval_id,
                "atMs": now_ms,
                "durationMs": duration_ms,
                "triggerReason": trigger_reason,
                "provider": provider,
                "model": model,
                "isBuy": is_buy,
                "confidence": decision.get("confidence", 0),
                "scenario": decision.get("scenario", "NONE"),
                "scenarioNameZh": decision.get("scenario_name_zh", "观望无机会"),
                "summaryZh": decision.get("summary_zh") or decision.get("reason") or "模型未提供观望原因",
                "decision": decision,
            }

            with self.store.lock, self.store.db:
                self.store.db.execute('INSERT INTO ai_inputs VALUES(?,?)',(eval_id,json.dumps({'snapshot':snapshot,'prompt':prompt,'systemPrompt':SYSTEM_PROMPT,'policyVersion':'short-opportunities-v2','decision':decision})))
                self.store.db.execute(
                    "INSERT INTO ai_evaluations VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (
                        eval_id,
                        now_ms,
                        trigger_reason,
                        model,
                        provider,
                        1 if is_buy else 0,
                        decision.get("confidence", 0),
                        decision.get("scenario", "NONE"),
                        json.dumps(decision),
                        decision.get("summary_zh", ""),
                    ),
                )

            eval_record["verificationStatus"] = "NO_BUY"
            self.last_analysis_ms = now_ms
            if trigger_reason.startswith("SCHEDULED"):
                self.last_scheduled_ms = now_ms
            elif trigger_reason.startswith("EVENT"):
                self.last_event_ms = now_ms
            self.last_evaluation = eval_record

            # Pre-dispatch verification
            if is_buy:
                accepted = self.verify_and_push_signal(eval_record, decision, now_ms)
                eval_record["isBuy"] = accepted
                eval_record["modelSuggestedBuy"] = True
                eval_record["verificationStatus"] = "ACCEPTED" if accepted else "REJECTED"
                if not accepted:
                    eval_record["summaryZh"] = "【拦截】" + eval_record.get("rejectionReason", "报价、成本或去重复核不通过")

            if eval_record["isBuy"] and self.last_signal:
                eval_record.update({k: v for k, v in self.last_signal.items() if k not in ("id", "atMs")})
            with self.store.lock, self.store.db:
                self.store.db.execute("UPDATE ai_evaluations SET is_buy=?,payload=? WHERE id=?", (int(eval_record["isBuy"]), json.dumps(eval_record), eval_id))
            if not eval_record['isBuy'] and decision.get('stage') in ('MARKET_EVENT','STABILIZING'):
                self.publish_stage('LLM_'+str(now_ms//900000),decision['stage'],str(eval_record['summaryZh'])[:100],now_ms)
            return {"ok": True, "evaluation": eval_record}

    def verify_and_push_signal(self, eval_record, decision, now_ms):
        with self.signal_lock:
            return self._verify_and_push_signal(eval_record, decision, now_ms)

    def _push_locked_contract(self, eval_record, decision, now_ms):
        """AI may only agree with a short-horizon contract. It does not choose prices."""
        eval_record["rejectionReason"] = "报价已离开短线契约"
        fresh = self.cache.snapshot(int(time.time() * 1000))
        if not fresh.get("healthy"):
            return False
        ask = float(fresh["ticker"].get("ask_price") or 0)
        stop = float(decision["stop_loss"])
        target = float(decision["target_tp1"])
        planned = float(decision["entry_min"])
        if not (stop < ask < target) or abs(ask - planned) / planned > 0.0015:
            return False
        net = (target / ask - 1) * 100 - 0.11
        risk = (1 - stop / ask) * 100
        floor = float(decision.get("min_net") or 0.59)
        if risk <= 0 or net < floor - 1e-9 or net / (risk + 0.11) < 1.10:
            eval_record["rejectionReason"] = f"净目标{net:.3f}%不足"
            return False
        scenario = decision["scenario"]
        sig_id = f"AI_{scenario}_{decision.get('structure_key', now_ms)}"
        expires_at = int(decision.get("expires_at") or now_ms + 30 * 60 * 1000)
        sig_data = {
            "id": sig_id, "atMs": now_ms, "symbol": "BTCUSDT", "signalType": "BUY", "source": "AI_ENGINE",
            "provider": eval_record.get("provider"), "model": eval_record.get("model"), "scenario": scenario,
            "scenarioNameZh": decision.get("scenario_name_zh", "短线收回"),
            "entryMin": planned * 0.9985, "entryMax": planned * 1.0015, "entryPrice": ask,
            "targetTP1": target, "targetTP2": target, "stopLoss": stop,
            "profitPercent1": round(net, 2), "grossProfitPercent1": round(net + 0.11, 2),
            "stopLossPercent": round(risk, 2), "riskRewardRatio": round(net / (risk + 0.11), 2),
            "timeHorizon": f"{int(decision.get('hold_minutes') or 45)}分钟",
            "summaryZh": (decision.get("summary_zh") or "契约确认")[:25],
            "expiresAt": expires_at, "minNetTp1": floor, "structureLow": stop,
            "holdMinutes": int(decision.get("hold_minutes") or 45),
            "targetPolicyVersion": "short-horizon-v1", "module": scenario,
            "trackingMode": "PLAN_ONLY", "trackingState": "WATCHING", "trailingStop": stop,
        }
        from .ai_policy import alert_card, same_opportunity
        for old in list(self.active_signals.values()):
            if same_opportunity(old, sig_data):
                eval_record["rejectionReason"] = "同一结构机会已提醒"
                return False
        sig_data["cardText"] = alert_card(sig_data)
        with self.store.lock, self.store.db:
            self.store.db.execute(
                "INSERT OR IGNORE INTO ai_signals VALUES(?,?,?,?,?,?,?,?,?,?)",
                (sig_id, now_ms, scenario, sig_data["entryMin"], sig_data["entryMax"], target, stop, "PENDING", json.dumps(sig_data), expires_at),
            )
            self.store.db.execute(
                "INSERT OR IGNORE INTO observation_queue VALUES(?,?,?,?,?)",
                (sig_id, json.dumps({"title": "Crypto-G AI买入预警 · " + sig_data["scenarioNameZh"], "body": sig_data["cardText"],
                                     "eventType": "AI_BUY_ALERT", "eventId": sig_id, "signalType": "BUY", "cardText": sig_data["cardText"]}),
                 "AI_ARCHIVE", now_ms, expires_at),
            )
        self.active_signals[sig_id] = sig_data
        self.last_signal = sig_data
        eval_record.pop("rejectionReason", None)
        return True

    def _verify_and_push_signal(self, eval_record, decision, now_ms):
        """Re-verify fresh quote, stop loss and bounds before dispatching alert."""
        if decision.get("contract_locked"):
            return self._push_locked_contract(eval_record, decision, now_ms)
        eval_record["rejectionReason"] = "报价、价格顺序或结构复核不通过"
        fresh_snapshot = self.cache.snapshot(int(time.time() * 1000))
        if not fresh_snapshot.get("healthy"):
            logger.warning("AI buy signal rejected: fresh quote unhealthy")
            return False

        ticker = fresh_snapshot["ticker"]
        ask = ticker.get("ask_price", 0.0)
        spread = ((ask - ticker.get("bid_price", 0.0)) / ask * 100) if ask > 0 else 1.0

        entry_min = float(decision.get("entry_min", 0.0))
        entry_max = float(decision.get("entry_max", 0.0))
        target_tp1 = float(decision.get("target_tp1", 0.0))
        target_tp2 = float(decision.get("target_tp2", target_tp1))
        stop_loss = float(decision.get("stop_loss", 0.0))

        if not all(math.isfinite(v) and v > 0 for v in (ask, entry_min, entry_max, target_tp1, target_tp2, stop_loss)):
            return False
        if not stop_loss < entry_min <= ask <= entry_max < target_tp1 <= target_tp2:
            return False

        # Re-check 1: Spread must be clean
        if not math.isfinite(spread) or not 0 < spread <= 0.02:
            logger.info("AI buy signal blocked: spread %.4f%% > 0.02%%", spread)
            return False

        # Re-check 2: Ask must not have escaped above allowed entry range
        if entry_max > 0 and ask > entry_max:
            logger.info("AI buy signal blocked: price %.2f already above max entry %.2f", ask, entry_max)
            return False

        # Re-check 3: Stop loss must not be broken
        if stop_loss > 0 and ask <= stop_loss:
            logger.info("AI buy signal blocked: price %.2f below stop loss %.2f", ask, stop_loss)
            return False

        # Re-check 4: Net profit and risk/reward
        net_tp1 = ((target_tp1 / ask - 1) * 100 - 0.11) if ask > 0 else 0
        risk_pct = ((1 - stop_loss / ask) * 100) if ask > 0 else 1
        net_rr = net_tp1 / (risk_pct + 0.11) if (risk_pct + 0.11) > 0 else 0
        if net_tp1 < MIN_NET_TP1 - 1e-9 or net_rr < 1.10:
            eval_record["rejectionReason"] = f"净目标{net_tp1:.3f}% / 净盈亏比{net_rr:.2f}不足"
            logger.info("AI buy signal blocked: netTP1 %.2f%% or netRR %.2f below gate", net_tp1, net_rr)
            return False

        try:
            plan = trade_plan(decision, fresh_snapshot, ask)
        except (ValueError, TypeError, KeyError) as exc:
            eval_record['rejectionReason'] = str(exc)
            return False
        scenario = decision['scenario']
        sig_id = f"AI_{scenario}_{now_ms}"
        expires_at = now_ms + (10000 if scenario=='FLASH_REBOUND_FAST' else 90000)

        sig_data = {
            "id": sig_id,
            "atMs": now_ms,
            "symbol": "BTCUSDT",
            "signalType": "BUY",
            "source": "AI_ENGINE",
            "provider": eval_record["provider"],
            "model": eval_record["model"],
            "scenario": scenario,
            "scenarioNameZh": decision.get("scenario_name_zh", "AI量化买入"),
            "entryMin": entry_min or ask,
            "entryMax": entry_max or ask,
            "entryPrice": ask,
            "targetTP1": target_tp1,
            "targetTP2": target_tp2,
            "stopLoss": stop_loss,
            "profitPercent1": round(net_tp1, 2),
            "stopLossPercent": round(risk_pct, 2),
            "riskRewardRatio": round(net_rr, 2),
            "timeHorizon": decision.get("time_horizon", "15分钟~2小时超短线"),
            "summaryZh": decision.get("summary_zh", ""),
            "expiresAt": expires_at,
        }

        sig_data.update(plan)
        for key, old in list(self.active_signals.items()):
            if old.get('trackingState', 'WATCHING') != 'WATCHING' or now_ms >= old["atMs"] + old.get("holdSeconds",old.get("holdMinutes",720)*60)*1000 or ask <= old.get("trailingStop",old.get("stopLoss",0)):
                del self.active_signals[key]
                continue
            if same_opportunity(old, sig_data):
                eval_record["rejectionReason"] = "同一结构机会已提醒"
                return False
        sig_data['cardText'] = alert_card(sig_data)
        with self.store.lock, self.store.db:
            self.store.db.execute(
                "INSERT INTO ai_signals VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    sig_id,
                    now_ms,
                    scenario,
                    entry_min or ask,
                    entry_max or ask,
                    target_tp1,
                    stop_loss,
                    "PENDING",
                    json.dumps(sig_data),
                    expires_at,
                ),
            )
            # Also enqueue to observation_queue for mobile inbox display under 'AI' category
            obs_payload = {
                "title": f"Crypto-G AI买入预警 · {sig_data['scenarioNameZh']}",
                "body": f"建议入场: ${sig_data['entryMin']:.2f}~${sig_data['entryMax']:.2f} | 目标止盈: ${sig_data['targetTP1']:.2f} (+{sig_data['profitPercent1']}%) | 止损: ${sig_data['stopLoss']:.2f} | {sig_data['summaryZh']}",
                "eventType": "AI_BUY_ALERT",
                "eventId": sig_id,
                "signalType": "BUY",
                "issuedAtMs": now_ms,
                "expiresAt": str(expires_at),
                "aiData": sig_data,
                "cardText": sig_data["cardText"],
            }
            obs_payload["body"] = sig_data["cardText"]
            self.store.db.execute(
                "INSERT INTO observation_queue VALUES(?,?,?,?,?)",
                (sig_id, json.dumps(obs_payload), "AI_ARCHIVE", now_ms, expires_at),
            )

        self.active_signals[sig_id] = sig_data
        self.last_signal = sig_data
        eval_record.pop("rejectionReason", None)

        return True

    def track_plans(self):
        with self.signal_lock:
            self._track_plans()

    def _track_plans(self):
        now = int(time.time()*1000)
        snapshot = self.cache.snapshot(now)
        with self.store.lock, self.store.db:
            rows = self.store.db.execute("SELECT id,payload FROM ai_signals WHERE state IN ('PENDING','FCM_ACCEPTED') ORDER BY at_ms DESC LIMIT 200").fetchall()
            for identity, raw in rows:
                plan = json.loads(raw)
                if 'holdMinutes' not in plan:
                    continue
                updated = advance_plan(plan, snapshot, now)
                if updated != plan:
                    self.store.db.execute('UPDATE ai_signals SET payload=? WHERE id=?',(json.dumps(updated),identity))
                if updated.get('trackingState') == 'WATCHING':
                    self.active_signals[identity] = updated
                else:
                    self.active_signals.pop(identity, None)

    def dispatch_pending(self):
        if not self.delivery_lock.acquire(blocking=False):
            return
        try:
            self._dispatch_pending()
            self.dispatch_stages()
        finally:
            self.delivery_lock.release()

    def publish_stage(self,key,stage,reason,now):
        # Unstructured LLM stage text and raw crashes are diagnostic only.
        # Qualified preparations come from the common, risk-checked observation pipeline.
        return False

    def dispatch_stages(self):
        with self.store.lock,self.store.db:
            self.store.db.execute("UPDATE ai_stages SET state='CANCELLED' WHERE state='PENDING'")

    def _dispatch_pending(self):
        now = int(time.time()*1000)
        with self.store.lock:
            rows = self.store.db.execute("SELECT s.id,s.payload,s.expires_at FROM ai_signals s LEFT JOIN ai_delivery d ON s.id=d.id WHERE s.state='PENDING' AND (s.expires_at<=? OR COALESCE(d.due,0)<=?) ORDER BY s.at_ms LIMIT 10",(now,now)).fetchall()
        for identity, raw, expires in rows:
            now = int(time.time()*1000)
            sig = json.loads(raw)
            state = 'EXPIRED' if now >= expires else None
            if state is None and not self.get_config().get('enabled'):
                state = 'CANCELLED'
            if state is None and sig.get('targetPolicyVersion') not in ('ai-resistance-v2', 'short-horizon-v1'):
                state = 'INVALIDATED'
            if state is None and sig.get('trackingState','WATCHING') != 'WATCHING':
                state = 'INVALIDATED'
            snapshot = self.cache.snapshot(now)
            if state is None and not snapshot.get('healthy'):
                continue
            if state is None:
                q = snapshot['ticker']; ask = q['ask_price']; bid = q['bid_price']
                net = (sig['targetTP1']/ask-1)*100-.11
                risk = (1-sig['stopLoss']/ask)*100+.11
                floor = float(sig.get('minNetTp1') or MIN_NET_TP1)
                valid = (sig['entryMin'] <= ask <= sig['entryMax'] and sig['stopLoss'] < ask < sig['targetTP1']
                         and 0 < (ask-bid)/ask*100 <= .02 and net >= floor - 1e-9 and risk > 0 and net/risk >= 1.10)
                if not valid:
                    state = 'INVALIDATED'
                else:
                    title = 'Crypto-G AI买入预警 · '+sig['scenarioNameZh']
                    body = f"入场 ${sig['entryMin']:.2f}~${sig['entryMax']:.2f} | TP1 {sig['targetTP1']:.2f} | SL {sig['stopLoss']:.2f} | 打开复核有效期"
                    body = sig.get('cardText', body)
                    payload = {k:str(v) for k,v in sig.items()}
                    payload.update(eventId=identity,eventType='AI_BUY_ALERT',title=title,body=body,timestamp=str(sig['atMs']))
                    with self.store.lock, self.store.db:
                        self.store.db.execute('INSERT OR IGNORE INTO ai_delivery(id) VALUES(?)',(identity,))
                        self.store.db.execute('UPDATE ai_delivery SET attempts=attempts+1,due=?,last_error=? WHERE id=?',(now+30000,'ATTEMPT_IN_PROGRESS',identity))
                    error = None
                    try:
                        state = 'FCM_ACCEPTED' if self.send_fcm_alert(title,body,payload) else None
                        if state is None: error = 'FCM_NOT_ACCEPTED'
                    except Exception as exc:
                        error = type(exc).__name__
                    with self.store.lock, self.store.db:
                        self.store.db.execute('UPDATE ai_delivery SET due=?,last_error=?,accepted_ms=? WHERE id=?',(now+5000,error,now if state else None,identity))
                        if state:
                            self.store.db.execute('UPDATE ai_signals SET state=? WHERE id=?',(state,identity))
            if state:
                with self.store.lock, self.store.db:
                    self.store.db.execute("UPDATE ai_signals SET state=? WHERE id=?", (state,identity))
                if state in ('EXPIRED','INVALIDATED','CANCELLED'):
                    self.active_signals.pop(identity, None)

    def status(self):
        cfg = self.get_config()
        with self.store.lock:
            eval_count = self.store.db.execute("SELECT count(*) FROM ai_evaluations").fetchone()[0]
            buy_count = self.store.db.execute("SELECT count(*) FROM ai_signals").fetchone()[0]
            rejected_count = self.store.db.execute("SELECT count(*) FROM ai_evaluations WHERE json_extract(payload,'$.verificationStatus')='REJECTED'").fetchone()[0]
            suggested_count = self.store.db.execute("SELECT count(*) FROM ai_evaluations WHERE json_extract(payload,'$.decision.is_buy')=1").fetchone()[0]
            recent_evals = [
                json.loads(r[0]) if "isBuy" in json.loads(r[0]) else {"id":r[1],"atMs":r[2],"triggerReason":r[3],"model":r[4],"provider":r[5],"isBuy":False,"scenarioNameZh":"旧版本评估（未复核）","summaryZh":json.loads(r[0]).get("summary_zh",""),"confidence":json.loads(r[0]).get("confidence",0)}
                for r in self.store.db.execute("SELECT payload,id,at_ms,trigger_reason,model,provider FROM ai_evaluations ORDER BY at_ms DESC LIMIT 10").fetchall()
            ]

        # Mask API key for security
        masked_cfg = dict(cfg)
        raw_key = masked_cfg.get("apiKey", "")
        if len(raw_key) > 8:
            masked_cfg["apiKey"] = raw_key[:4] + "****" + raw_key[-4:]
        elif raw_key:
            masked_cfg["apiKey"] = "****"

        return {
            "ok": True,
            "config": masked_cfg,
            "hasApiKey": bool(raw_key),
            "error": self.last_error,
            "retryAtMs": self.retry_at,
            "isAnalyzing": self.lock.locked(),
            "nextDueMs": max(self.retry_at, (int(time.time()*1000)//300000+1)*300000),
            "lastAnalysisMs": self.last_analysis_ms,
            "lastEvaluation": ({**self.last_evaluation, "isBuy": False, "summaryZh": "【已过入场有效期】"+self.last_evaluation["summaryZh"]} if self.last_evaluation and self.last_evaluation.get("isBuy") and int(time.time()*1000)>=self.last_evaluation.get("expiresAt",0) else self.last_evaluation),
            "lastSignal": self.last_signal,
            "evalCount": eval_count,
            "totalEvaluations": eval_count,
            "buyCount": buy_count,
            "suggestedCount":suggested_count,
            "rejectedCount":rejected_count,
            "lastScheduledMs": self.last_scheduled_ms,
            "lastEventMs": self.last_event_ms,
            "activeSignals": self.active_signals,
            "trackedPlans": list(self.active_signals.values())[-20:],
            "totalBuySignals": buy_count,
            "recentEvaluations": recent_evals,
        }


class AIDeliveryWorker(threading.Thread):
    """At-least-once delivery independent of model latency; stable event IDs on retry."""
    def __init__(self, ai_engine, stop_event):
        super().__init__(name='btc-ai-delivery', daemon=True)
        self.ai, self.stop = ai_engine, stop_event
        self.heartbeat_ms, self.error = 0, None

    def run(self):
        while not self.stop.is_set():
            self.heartbeat_ms = int(time.time()*1000)
            try:
                self.ai.dispatch_pending()
                self.error = None
            except Exception as exc:
                self.error = type(exc).__name__
                logger.error('AI delivery failed: %s', self.error)
            self.stop.wait(.5)


class AIAnalystWorker(threading.Thread):
    """Background autonomous daemon for 5-minute scheduled + 3-minute event triggers."""

    def __init__(self, ai_engine, stop_event):
        super().__init__(name="btc-ai-analyst", daemon=True)
        self.ai = ai_engine
        self.stop = stop_event
        self.heartbeat_ms = 0
        self.error = None

    def detect_event_shock(self, snapshot):
        """Layer 3: Detect sudden shock (drop >= 1% in 3m) or breakout to trigger early AI wake-up."""
        series = snapshot.get("series", {})
        bars = series.get("1m", [])
        if len(bars) < 5:
            return None

        # Check 3-minute drop
        recent3 = bars[-3:]
        high3 = max(c["high"] for c in recent3)
        low3 = min(c["low"] for c in recent3)
        drop_pct = (high3 - low3) / high3 * 100 if high3 > 0 else 0
        if drop_pct >= 1.0 and recent3[-1]["close"] < recent3[0]["open"]:
            return f"EVENT_FLASH_DROP_{drop_pct:.2f}%"

        # Check volume surge + price expansion
        last = bars[-1]
        prev4 = bars[-5:-1]
        avg_vol = sum(c["volume"] for c in prev4) / len(prev4) if prev4 else 1.0
        if avg_vol > 0 and last["volume"] >= 3.5 * avg_vol:
            # High volume surge
            if abs(last["close"] - last["open"]) / last["open"] * 100 >= 0.5:
                return "EVENT_VOLUME_BREAKOUT"

        return None

    def run(self):
        while not self.stop.is_set():
            now_ms = int(time.time() * 1000)
            self.heartbeat_ms = now_ms

            try:
                cfg = self.ai.get_config()
                if cfg.get("enabled"):
                    interval_ms = int(cfg.get("intervalSeconds", 300)) * 1000
                    cooldown_ms = int(cfg.get("eventCooldownSeconds", 180)) * 1000

                    time_since_scheduled = now_ms-self.ai.last_scheduled_ms
                    self.ai.track_plans()
                    if not getattr(self.ai, 'originate_buys', True):
                        self.stop.wait(1)
                        continue
                    snapshot = self.ai.cache.snapshot(now_ms)
                    bars = snapshot.get('series',{}).get('5m',[])
                    bar = bars[-1]['close_time'] if bars else 0
                    if snapshot.get('healthy') and now_ms >= self.ai.retry_at:
                        if cfg.get('enabled5m',True) and bar > self.ai.last_bar and (not self.ai.last_scheduled_ms or bar//interval_ms > self.ai.last_bar//interval_ms):
                            result = self.ai.execute_analysis('SCHEDULED_5M')
                            if result.get('ok'):
                                self.ai.last_bar = bar
                                self.ai.save_runtime()
                        elif cfg.get('enabledEventTrigger',True) and now_ms-self.ai.last_attempt_ms >= cooldown_ms:
                            event = self.detect_event_shock(snapshot)
                            if event:
                                self.ai.execute_analysis(event)

                self.error = None
            except Exception as exc:
                self.error = type(exc).__name__
                logger.error("AIAnalystWorker iteration error: %s", self.error)

            self.stop.wait(15)
