"""Engine B. It reads Engine A and never writes a price or a strategy parameter.

Timeout, a missing key, or a malformed reply becomes PASS so the push is not blocked.
Anomaly notes, the daily review, and weekly hypotheses use the same research
`ai_reviews` table. A hypothesis that fails, or one that tries to move a hard
constraint, is stored and left unapplied.
"""
import json
import math
import re
import threading
import urllib.request
from datetime import datetime, timedelta, timezone

from .config import (
    V2_AI_TIMEOUT_S, V2_FRICTION_PCT, V2_FUNDING_EXTREME, V2_OI_DROP_1H_PCT, V2_RULE_VERSION,
    V2_S2_WICK_TO_BODY, V2_TAKER_SELL_MIN,
)

TAGS = ("结构不干净", "环境逆势", "止损过宽", "目标过近", "量能不足", "追价风险", "时段不利", "数据不足")
VERDICTS = {"PASS", "DOWNGRADE", "VETO"}
ZH = {"通过": "PASS", "降级为观察": "DOWNGRADE", "降级": "DOWNGRADE", "否决": "VETO"}
PRICE_RUN = re.compile(r"\d{3,}")
SYSTEM = (
    "你是 Crypto-G 的第二意见，只读引擎 A 已经算好的结构化字段。"
    "你不能给出、改写或暗示任何价格、价位、百分比数字。"
    "只返回 JSON：verdict 取 PASS、DOWNGRADE、VETO 之一；"
    "tags 从这些标签里选零个或多个：" + "、".join(TAGS) + "；"
    "confidence 为 0 到 1；note 为一句不超过 40 字的中文，句中不得出现连续 3 位数字。"
)


def fallback(reason: str, veto_enabled: bool = True) -> dict:
    return {"verdict": "PASS", "tags": [], "confidence": None, "note": "",
            "fallback": reason, "vetoEnabled": veto_enabled}


def brief(signal: dict) -> dict:
    """Percentages and labels only. Raw candles and absolute prices stay out."""
    v2 = signal.get("v2") or {}
    env = v2.get("env") or {}
    features = dict(v2.get("features") or {})
    features.pop("support", None)
    return {
        "module": signal.get("module"),
        "tier": signal.get("tier"),
        "states": env.get("states"),
        "envScore": env.get("score"),
        "stopPct": signal.get("stop_loss_pct"),
        "netTp1Pct": signal.get("net_tp1"),
        "netRr": signal.get("net_rr"),
        "spreadPct": v2.get("spreadPct"),
        "features": features,
        "derivatives": v2.get("derivatives") or {"status": "unavailable"},
    }


def parse_review(raw) -> dict | None:
    if not isinstance(raw, dict):
        return None
    verdict = ZH.get(raw.get("verdict"), raw.get("verdict"))
    tags = raw.get("tags") or []
    note = raw.get("note") if isinstance(raw.get("note"), str) else raw.get("note_zh")
    confidence = raw.get("confidence")
    if verdict not in VERDICTS or not isinstance(tags, list) or any(tag not in TAGS for tag in tags):
        return None
    if not isinstance(note, str) or len(note) > 40 or re.search(r'[0-9０-９%％\n\r]', note) or (note and not re.search(r'[\u4e00-\u9fff]',note)):
        return None
    if confidence is not None and (isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0 <= float(confidence) <= 1):
        return None
    return {"verdict": verdict, "tags": list(tags), "confidence": None if confidence is None else round(float(confidence), 4),
            "note": note, "fallback": None}


def _post(api_key: str, model: str, payload: dict) -> dict:
    body = {"model": model or "deepseek-chat", "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": SYSTEM},
                         {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}]}
    request = urllib.request.Request(
        "https://api.deepseek.com/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        method="POST")
    with urllib.request.urlopen(request, timeout=V2_AI_TIMEOUT_S) as response:
        text = json.loads(response.read().decode())["choices"][0]["message"]["content"]
    return json.loads(text)


def review_signal(signal: dict, post=None, enabled: bool = True, api_key: str = "",
                  model: str = "deepseek-chat", timeout: float = V2_AI_TIMEOUT_S,
                  veto_enabled: bool = True) -> dict:
    """Always returns a verdict. A failed call is PASS and does not raise."""
    if signal.get("rule_version") != V2_RULE_VERSION:
        return fallback("NOT_V2", veto_enabled)
    if not enabled:
        return fallback("DISABLED", veto_enabled)
    caller = post
    if caller is None:
        if not api_key:
            return fallback("MISSING_KEY", veto_enabled)
        caller = lambda payload: _post(api_key, model, payload)
    box = {}

    def run():
        try:
            box["raw"] = caller(brief(signal))
        except Exception as exc:
            box["error"] = type(exc).__name__

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    thread.join(timeout)
    if thread.is_alive():
        return fallback("TIMEOUT", veto_enabled)
    parsed = parse_review(box.get("raw"))
    if parsed is None:
        return fallback(box.get("error") or "FORMAT", veto_enabled)
    parsed["vetoEnabled"] = veto_enabled
    return parsed


class ReviewLog:
    """Stores the opinion beside the event journal. Prices in the note were already rejected."""

    def __init__(self, store):
        self.store = store
        with store.lock, store.db:
            store.db.executescript('''
            CREATE TABLE IF NOT EXISTS ai_reviews(
                id TEXT PRIMARY KEY, at_ms INTEGER NOT NULL, verdict TEXT NOT NULL,
                fallback TEXT, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS ai_evaluations(
                id TEXT PRIMARY KEY, at_ms INTEGER NOT NULL, trigger_reason TEXT NOT NULL,
                model TEXT NOT NULL, provider TEXT NOT NULL, is_buy INTEGER NOT NULL,
                confidence INTEGER, scenario TEXT, payload TEXT NOT NULL, summary TEXT);
            ''')

    def save(self, alert_id: str, at_ms: int, review: dict) -> None:
        with self.store.lock, self.store.db:
            self.store.db.execute("INSERT OR REPLACE INTO ai_reviews VALUES(?,?,?,?,?)",
                                  (alert_id, at_ms, review["verdict"], review.get("fallback"),
                                   json.dumps(review, ensure_ascii=False)))
            self.store.db.execute(
                "INSERT OR REPLACE INTO ai_evaluations(id,at_ms,trigger_reason,model,provider,is_buy,confidence,scenario,payload,summary) "
                "VALUES(?,?,?,?,?,?,?,?,?,?)",
                ("review:" + alert_id, at_ms, "V2_REVIEW", review.get("model") or "deepseek-chat", review.get("provider") or "DEEPSEEK",
                 0, None if review.get("confidence") is None else int(round(review["confidence"] * 100)),
                 review["verdict"], json.dumps(review, ensure_ascii=False), review.get("note") or review.get("fallback") or ""))


CST = timezone(timedelta(hours=8))
HYPOTHESES_PER_WEEK = 3
HYPOTHESIS_FEATURES = (
    "dropPct", "volumeMultiple", "wickToBody", "rsi15Min", "boxHeightPct",
    "oiChange1hPct", "fundingRate", "takerSellRatio", "derivativePoints",
    "stopPct", "netTp1Pct", "netRr", "envScore",
)
HYPOTHESIS_KEYS = {"module", "feature", "op", "value", "claim"}
LOSS_TEXT = {
    "STOP": "止损", "TIME_STOP": "时间止损", "MAX_HOLD": "持有到期", "TP1_MAX_HOLD": "持有到期",
    "EARLY_EXIT": "早于系统离场", "LATE_EXIT": "晚于系统离场", "SUBJECTIVE": "主观单",
    "SYSTEM_OPEN": "系统尚未出场", "ALIGNED": "与系统一致",
}
HYPOTHESIS_SYSTEM = (
    "你是 Crypto-G 的假设提案。每周最多 3 条，只返回 JSON："
    "{\"hypotheses\":[{\"module\":\"S1到S4\",\"feature\":\"已有特征名\",\"op\":\">=或<=或==\",\"value\":数字,\"claim\":\"不超过40字的中文\"}]}。"
    "你不能写价格，不能改成本、止损、持有时间和熔断，也不能要求直接改参数。"
    "引擎 A 会检验这些假设；检验不通过就不会被采用。"
)


def veto_blocks(review: dict) -> bool:
    """Veto power is off when the audit says the vetoes did not improve expectancy."""
    return review.get("verdict") == "VETO" and review.get("vetoEnabled", True)


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _fmt(value) -> str:
    text = f"{float(value):.4f}".rstrip("0").rstrip(".")
    return "0" if text in ("", "-0") else text


def _at_least(value, floor: float) -> bool:
    number = _number(value)
    return number is not None and number >= floor


def _at_most(value, ceiling: float) -> bool:
    number = _number(value)
    return number is not None and number <= ceiling


def _is_flush(signal: dict, features: dict) -> bool:
    if signal.get("flushActive") is True or signal.get("module") == "S1":
        return True
    drop, need = _number(features.get("dropPct")), _number(features.get("dropRequiredPct"))
    return drop is not None and need is not None and drop >= need


def detect_anomalies(signal: dict) -> dict:
    """Name a flush cascade, extreme funding, an OI drop, or a false break.

    Every flag is a comparison Engine A already published. Missing derivatives
    stay off. This does not open or block a trade.
    """
    signal = signal or {}
    v2 = signal.get("v2") or {}
    features = dict(v2.get("features") or signal.get("features") or {})
    deriv = dict(v2.get("derivatives") or signal.get("derivatives") or {})
    if deriv.get("status") == "unavailable":
        oi = funding = ratio = None
    else:
        oi, funding, ratio = deriv.get("oi_change_1h_pct"), deriv.get("funding_rate"), deriv.get("taker_sell_ratio")
    oi_drop = _at_most(oi, -V2_OI_DROP_1H_PCT)
    funding_extreme = _at_most(funding, V2_FUNDING_EXTREME)
    taker_sell = _at_least(ratio, V2_TAKER_SELL_MIN)
    flush = _is_flush(signal, features)
    false_break = bool(features.get("falseBreak")) or (
        bool(features.get("support")) and _at_least(features.get("wickToBody"), V2_S2_WICK_TO_BODY))
    flags = []
    if flush and oi_drop and taker_sell:
        flags.append("LIQUIDATION_FLUSH")
    if funding_extreme:
        flags.append("FUNDING_EXTREME")
    if oi_drop:
        flags.append("OI_DROP")
    if false_break:
        flags.append("FALSE_BREAK")
    cited = {}
    if features.get("dropPct") is not None and _number(features.get("dropPct")) is not None:
        cited["dropPct"] = _fmt(features["dropPct"])
    if oi_drop:
        cited["oiChange1hPct"] = _fmt(oi)
    if "LIQUIDATION_FLUSH" in flags:
        cited["takerSellRatio"] = _fmt(ratio)
    if funding_extreme:
        cited["fundingPct"] = _fmt(float(funding) * 100)  # exchange decimal, same unit as -0.01%
    if false_break and _number(features.get("wickToBody")) is not None:
        cited["wickToBody"] = _fmt(features["wickToBody"])
    if false_break and features.get("support"):
        cited["support"] = str(features["support"])
    return {
        "flags": flags, "liquidationFlush": "LIQUIDATION_FLUSH" in flags,
        "fundingExtreme": funding_extreme, "oiDrop": oi_drop, "falseBreak": false_break, "cited": cited,
    }


def explain_signal(signal: dict) -> str:
    """One sentence. Every number in it is copied from detect_anomalies."""
    found = detect_anomalies(signal)
    cited, flags = found["cited"], found["flags"]
    parts = []
    if "LIQUIDATION_FLUSH" in flags:
        parts.append(f"急跌伴随强平潮：OI一小时{cited['oiChange1hPct']}%，主动卖出比{cited['takerSellRatio']}")
    elif "dropPct" in cited and (signal.get("module") == "S1" or signal.get("flushActive")):
        parts.append(f"急跌{cited['dropPct']}%")
    if "FUNDING_EXTREME" in flags:
        parts.append(f"资金费率{cited['fundingPct']}%")
    if "OI_DROP" in flags and "LIQUIDATION_FLUSH" not in flags:
        parts.append(f"OI一小时下降{cited['oiChange1hPct']}%")
    if "FALSE_BREAK" in flags:
        wick = f"，影线实体比{cited['wickToBody']}" if "wickToBody" in cited else ""
        parts.append(f"关键位假破后收回{wick}")
    return _clip(parts)


def explain_exit(kind: str, source: dict) -> str:
    """Optional clause for a stop reminder. Empty when Engine A left no percent to cite."""
    source = source or {}
    cited = {}
    if _number(source.get("stop_loss_pct")) is not None:
        cited["stopPct"] = _fmt(source["stop_loss_pct"])
    elif _number(source.get("riskPct")) is not None:
        cited["stopPct"] = _fmt(source["riskPct"])
    if kind == "TIME_STOP_EXIT" and _number(source.get("time_stop_progress_r")) is not None:
        cited["progressR"] = _fmt(source["time_stop_progress_r"])
    parts = []
    if "stopPct" in cited:
        parts.append(f"止损距离{cited['stopPct']}%")
    if "progressR" in cited:
        parts.append(f"进度门槛+{cited['progressR']}R")
    if not parts:
        return ""
    return "（" + "，".join(parts) + "）"


def decorate_exit_message(kind: str, message: str, source: dict) -> str:
    """Push the reminder even when the commentary cannot be built."""
    try:
        extra = explain_exit(kind, source)
    except Exception:
        return message
    return message if not extra else message + extra


def attach_commentary(signal: dict, review: dict) -> dict:
    review = dict(review)
    try:
        review["anomalies"] = detect_anomalies(signal)
        review["explain"] = explain_signal(signal)
    except Exception:
        review.setdefault("anomalies", {"flags": []})
        review.setdefault("explain", "")
    return review


def _clip(parts) -> str:
    while parts:
        text = "，".join(parts)
        if not text.endswith("。"):
            text += "。"
        if len(text) <= 80:
            return text
        parts = parts[:-1]
    return ""


def cst_date(ms: int):
    return datetime.fromtimestamp(int(ms) / 1000, CST).date()


def day_bounds(ms: int):
    day = cst_date(ms)
    start = datetime(day.year, day.month, day.day, tzinfo=CST)
    start_ms = int(start.timestamp() * 1000)
    return start_ms, start_ms + 86_400_000


def week_key(ms: int) -> str:
    iso = cst_date(ms).isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def attribute_gap(user_net, system_net, user_at, system_at, system_reason, has_system: bool, system_closed: bool) -> str:
    """Why the user's exit and the system twin differ. Prices are not invented here."""
    if not has_system:
        return "SUBJECTIVE"
    if not system_closed or system_net is None or user_net is None:
        return "SYSTEM_OPEN"
    gap = user_net - system_net
    if abs(gap) < 0.01:
        return "ALIGNED"
    if system_at and user_net < system_net and user_at + 60_000 < system_at:
        return "EARLY_EXIT"
    if system_at and user_net < system_net and user_at > system_at + 60_000:
        return "LATE_EXIT"
    if (system_net < 0 or user_net < 0) and system_reason in LOSS_TEXT:
        return system_reason
    if user_net < system_net:
        return "EARLY_EXIT"
    return "ALIGNED"


def build_daily_review(bundle: dict, day: str) -> dict:
    """Paper versus system for one CST day, plus shadow closes. Nets are copied from the ledger."""
    trades = []
    systems = bundle.get("systems") or {}
    for paper in bundle.get("papers") or []:
        body = paper.get("body") or {}
        system = systems.get(paper.get("real_position_id"))
        system_body = {} if system is None else (system.get("body") or {})
        user_net = body.get("userNetPct")
        system_net = None if system is None else system_body.get("pnlPct")
        gap = None if user_net is None or system_net is None else round(float(user_net) - float(system_net), 4)
        reason = attribute_gap(
            user_net, system_net, paper.get("closed_ms"), None if system is None else system.get("closed_ms"),
            None if system is None else system.get("exit_reason"), system is not None,
            bool(system is not None and system.get("state", "CLOSED") == "CLOSED" and system.get("exit_reason")))
        trades.append({
            "positionId": paper.get("real_position_id"), "userNetPct": user_net, "userExit": paper.get("exit_reason"),
            "userExitPrice": paper.get("exit_price"), "systemNetPct": system_net,
            "systemExit": None if system is None else system.get("exit_reason"),
            "systemExitPrice": None if system is None else system.get("exit_price"),
            "gapPct": gap, "lossAttribution": reason,
        })
    shadows = []
    for row in bundle.get("shadows") or []:
        body = row.get("body") or {}
        shadows.append({
            "id": row.get("id"), "module": body.get("module"), "outcome": row.get("exit_reason"),
            "netPct": body.get("pnlPct"), "r": body.get("r"),
        })
    return {"kind": "DAILY", "day": day, "trades": trades, "shadows": shadows, "summary": _daily_summary(trades, shadows)}


def _daily_summary(trades, shadows) -> str:
    if not trades and not shadows:
        return "当日没有已平的实盘或影子仓。"
    parts = []
    if trades:
        parts.append(f"已平实盘{len(trades)}笔")
        for trade in trades:
            if trade.get("gapPct") is not None:
                parts.append(
                    f"用户净{_fmt(trade['userNetPct'])}%，系统净{_fmt(trade['systemNetPct'])}%，差距{_fmt(trade['gapPct'])}个百分点")
            text = LOSS_TEXT.get(trade.get("lossAttribution"))
            if text and trade.get("lossAttribution") not in ("ALIGNED", "SYSTEM_OPEN"):
                user_net = trade.get("userNetPct")
                system_net = trade.get("systemNetPct")
                prefix = "系统亏损归因" if system_net is not None and system_net < 0 and user_net is not None and user_net >= 0 else "亏损归因"
                parts.append(prefix + text)
    if shadows:
        parts.append(f"影子仓平仓{len(shadows)}笔")
    return _clip(parts) or "当日复盘已记录。"


def constraint_block(raw) -> str | None:
    """Extra keys are parameter writes. Hard-constraint violations are named separately."""
    if not isinstance(raw, dict) or not (set(raw) - HYPOTHESIS_KEYS):
        return None
    from .validation import unlearnable_gaps

    friction = raw.get("frictionPct", V2_FRICTION_PCT)
    view = {
        "symbol": raw.get("symbol", "BTCUSDT"), "side": raw.get("side", "BUY"),
        "aiWritesPrices": bool(raw.get("aiWritesPrices")),
        "frictionPct": V2_FRICTION_PCT if _number(friction) is None else float(friction),
        "stopPct": 0 if _number(raw.get("stopPct")) is None else float(raw["stopPct"]),
        "holdMinutes": 0 if _number(raw.get("holdMinutes")) is None else int(raw["holdMinutes"]),
        "breakerDisabled": bool(raw.get("breakerDisabled")), "bnbDiscount": bool(raw.get("bnbDiscount")),
    }
    return "UNLEARNABLE" if unlearnable_gaps(view) else "PARAMETER"


def parse_hypothesis(raw) -> dict | None:
    if not isinstance(raw, dict) or set(raw) - HYPOTHESIS_KEYS:
        return None
    module, feature, op, value, claim = raw.get("module"), raw.get("feature"), raw.get("op"), raw.get("value"), raw.get("claim")
    number = _number(value)
    if module not in ("S1", "S2", "S3", "S4") or feature not in HYPOTHESIS_FEATURES or op not in (">=", "<=", "=="):
        return None
    if number is None or not isinstance(claim, str) or not claim or len(claim) > 40 or PRICE_RUN.search(claim):
        return None
    return {"module": module, "feature": feature, "op": op, "value": number, "claim": claim}


def _matches(sample: dict, hypothesis: dict) -> bool:
    if sample.get("module") != hypothesis["module"]:
        return False
    left = _number((sample.get("features") or {}).get(hypothesis["feature"]))
    if left is None:
        return False
    right = hypothesis["value"]
    if hypothesis["op"] == ">=":
        return left >= right
    if hypothesis["op"] == "<=":
        return left <= right
    return math.isclose(left, right, rel_tol=0, abs_tol=1e-9)


def check_hypothesis(samples, hypothesis: dict) -> dict:
    """Measure one filter on Engine A labels. The result is never written back into the rules."""
    from .validation import promotion_decision, summarize_returns

    matched = [sample for sample in samples or [] if _matches(sample, hypothesis)]
    nets = [float(sample["netPct"]) for sample in matched if _number(sample.get("netPct")) is not None]
    opened = [int(sample["openedMs"]) for sample in matched if sample.get("openedMs")]
    closed = [int(sample["closedMs"]) for sample in matched if sample.get("closedMs")]
    span = max(max(closed) - min(opened), 1) if opened and closed else 86_400_000
    summary = summarize_returns(nets, span, n_trials=1)
    decision = promotion_decision(summary, n_trials=1, pbo_value=None)
    safe = dict(summary)
    if safe.get("profitFactor") == math.inf:
        safe["profitFactor"] = None
        safe["profitFactorInfinite"] = True
    status = "INSUFFICIENT" if not matched else ("PENDING_P4" if decision["passes"] else "CHECKED")
    return {"matched": len(matched), "summary": safe, "promotion": decision, "applied": False, "status": status}


def submit_hypotheses(ledger, items, now_ms: int) -> dict:
    """Keep at most three checked hypotheses per CST week. None of them edit parameters."""
    week = week_key(now_ms)
    stored = []
    used = ledger.hypothesis_count(week)
    for index, raw in enumerate(items or []):
        blocked = constraint_block(raw) if isinstance(raw, dict) else None
        if blocked:
            row = {"kind": "HYPOTHESIS", "week": week, "status": "REJECTED", "reason": blocked, "applied": False}
            ledger.save_note(f"hypothesis:{week}:rejected:{index}", f"hypothesis:{week}", now_ms, None, row)
            stored.append(row)
            continue
        parsed = parse_hypothesis(raw)
        if parsed is None:
            row = {"kind": "HYPOTHESIS", "week": week, "status": "FORMAT", "applied": False}
            ledger.save_note(f"hypothesis:{week}:format:{index}", f"hypothesis:{week}", now_ms, None, row)
            stored.append(row)
            continue
        if used >= HYPOTHESES_PER_WEEK:
            row = {**parsed, "kind": "HYPOTHESIS", "week": week, "status": "WEEKLY_CAP", "applied": False}
            ledger.save_note(f"hypothesis:{week}:cap:{index}", f"hypothesis:{week}", now_ms, None, row)
            stored.append(row)
            continue
        checked = check_hypothesis(ledger.research_samples(), parsed)
        used += 1
        row = {**parsed, **checked, "kind": "HYPOTHESIS", "week": week}
        ledger.save_note(f"hypothesis:{week}:{used}", f"hypothesis:{week}", now_ms, None, row)
        stored.append(row)
    return {"week": week, "stored": stored}


def propose_hypotheses(post, timeout: float = V2_AI_TIMEOUT_S) -> dict:
    """Ask for JSON hypotheses. Timeout or a bad payload yields none and does not raise."""
    box = {}

    def run():
        try:
            box["raw"] = post({"task": "HYPOTHESIS", "max": HYPOTHESES_PER_WEEK})
        except Exception as exc:
            box["error"] = type(exc).__name__

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    thread.join(timeout)
    if thread.is_alive():
        return {"hypotheses": [], "fallback": "TIMEOUT", "truncated": False}
    raw = box.get("raw")
    items = raw.get("hypotheses") if isinstance(raw, dict) else None
    if not isinstance(items, list):
        return {"hypotheses": [], "fallback": box.get("error") or "FORMAT", "truncated": False}
    parsed = [item for item in (parse_hypothesis(one) for one in items[:HYPOTHESES_PER_WEEK]) if item]
    if items and not parsed:
        return {"hypotheses": [], "fallback": "FORMAT", "truncated": len(items) > HYPOTHESES_PER_WEEK}
    return {"hypotheses": parsed, "fallback": None, "truncated": len(items) > HYPOTHESES_PER_WEEK}


def post_hypotheses(api_key: str, model: str, payload: dict) -> dict:
    body = {"model": model or "deepseek-chat", "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": HYPOTHESIS_SYSTEM},
                         {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}]}
    request = urllib.request.Request(
        "https://api.deepseek.com/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        method="POST")
    with urllib.request.urlopen(request, timeout=V2_AI_TIMEOUT_S) as response:
        text = json.loads(response.read().decode())["choices"][0]["message"]["content"]
    return json.loads(text)


def _daily_signature(day: str, bundle: dict):
    return (day, tuple(row["id"] for row in bundle["papers"]), tuple(row["id"] for row in bundle["shadows"]))


def restore_engine_b(ledger, now_ms: int, state: dict) -> dict:
    """Fill an empty memory clock from rows already stored, so a restart does not call DeepSeek again."""
    now_ms = int(now_ms)
    day = cst_date(now_ms).isoformat()
    week = week_key(now_ms)
    if "day" not in state:
        row = ledger._one("SELECT at_ms, payload FROM ai_reviews WHERE id=?", (f"daily:{day}",))
        if row:
            state["day"] = day
            state["daily_at"] = int(row["at_ms"])
            try:
                payload = json.loads(row["payload"])
            except (TypeError, json.JSONDecodeError):
                payload = {}
            if isinstance(payload.get("paperIds"), list) and isinstance(payload.get("shadowIds"), list):
                state["daily_sig"] = (day, tuple(payload["paperIds"]), tuple(payload["shadowIds"]))
    if "veto_day" not in state:
        row = ledger._one(
            "SELECT payload FROM ai_reviews WHERE id LIKE ? ORDER BY at_ms DESC LIMIT 1", (f"veto:{day}:%",))
        if row:
            try:
                payload = json.loads(row["payload"])
            except (TypeError, json.JSONDecodeError):
                payload = {}
            if isinstance(payload, dict) and "vetoEnabled" in payload:
                state["veto_day"] = day
                state["veto_flag"] = bool(payload.get("vetoEnabled"))
    if "week" not in state:
        row = ledger._one("SELECT id FROM ai_reviews WHERE id LIKE ? LIMIT 1", (f"hypothesis:{week}%",))
        if row:
            state["week"] = week
    return state


def maintain(ledger, audit, now_ms: int, post=None, state=None) -> dict:
    """Refresh today's review and the veto audit. Propose hypotheses once each CST week."""
    state = {} if state is None else state
    audit = audit or {}
    now_ms = int(now_ms)
    restore_engine_b(ledger, now_ms, state)
    day = cst_date(now_ms).isoformat()
    if state.get("day") != day or now_ms - int(state.get("daily_at") or 0) >= 60_000:
        start, end = day_bounds(now_ms)
        bundle = ledger.closed_twins(start, end)
        signature = _daily_signature(day, bundle)
        if state.get("daily_sig") != signature:
            review = build_daily_review(bundle, day)
            review["paperIds"] = list(signature[1])
            review["shadowIds"] = list(signature[2])
            ledger.save_note(f"daily:{day}", f"daily:{day}", now_ms, "REVIEW", review)
            state["daily_sig"] = signature
        state["day"] = day
        state["daily_at"] = now_ms
    flag = bool(audit.get("vetoEnabled", True))
    if state.get("veto_flag") != flag or state.get("veto_day") != day:
        ledger.save_note(
            f"veto:{day}:{int(flag)}", "veto-audit", now_ms, "VETO_AUDIT",
            {"kind": "VETO_AUDIT", "vetoEnabled": flag, "vetoed": audit.get("vetoed"), "passed": audit.get("passed"),
             "vetoedMeanR": audit.get("vetoedMeanR"), "passedMeanR": audit.get("passedMeanR")})
        state["veto_flag"] = flag
        state["veto_day"] = day
    week = week_key(now_ms)
    if post is not None and state.get("week") != week:
        proposed = propose_hypotheses(post)
        if proposed["hypotheses"]:
            submit_hypotheses(ledger, proposed["hypotheses"], now_ms)
        else:
            ledger.save_note(
                f"hypothesis:{week}:fallback", f"hypothesis:{week}", now_ms, None,
                {"kind": "HYPOTHESIS_FALLBACK", "week": week, "fallback": proposed.get("fallback"), "applied": False})
        state["week"] = week
    return state
