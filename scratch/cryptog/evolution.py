"""P4 release pipeline. L1 may propose a bounded adjustment; it does not edit S1–S5.

A module stays on the watch tier until its out-of-sample summary passes the
section 9 gates. Shadow then keeps pushing that watch card for 14 days, labeled
观察级·影子验证. Trial pushes for 14 days marked 试运行, and only then becomes
trade tier. Promotions rows are written when shadow or trial finishes, or when
the book rolls back.
"""
import json
import math

from .config import (
    V2_ENGINE_VERSION, V2_L1_ENTRY_OFFSET_MAX_PCT, V2_L1_ENTRY_OFFSET_MIN_PCT, V2_L1_MIN_SAMPLES,
    V2_L1_P_MAX, V2_L1_P_MIN, V2_L1_STOP_BUFFER_MAX_PCT, V2_L1_STOP_BUFFER_MIN_PCT,
    V2_PROMOTE_DSR_TRIALS, V2_PROMOTE_MAX_PBO, V2_PROMOTE_MAX_PER_DAY, V2_PROMOTE_MIN_DSR,
    V2_PROMOTE_MIN_EXPECTANCY, V2_PROMOTE_MIN_PER_DAY, V2_PROMOTE_MIN_PROFIT_FACTOR,
    V2_PROMOTE_MIN_TRADES, V2_PROMOTE_MIN_WIN_RATE, V2_ROLLBACK_MAX_DRAWDOWN_R, V2_ROLLBACK_TRADES,
    V2_SHADOW_MS, V2_TIER_LABEL, V2_TIER_TRADE, V2_TIER_TRADE_LABEL, V2_TIER_TRIAL, V2_TIER_TRIAL_LABEL,
    V2_TIER_WATCH, V2_TRIAL_MS,
)
from .validation import assign_fold, oos_cut, promotion_decision, summarize_returns, unlearnable_gaps, launch_decision, pbo

MODULES = ("S1", "S2", "S3", "S4")
STAGES = ("RESEARCH", "SHADOW", "TRIAL", "LIVE")
STAGE_ZH = {"RESEARCH": "研究", "SHADOW": "影子", "TRIAL": "试运行", "LIVE": "正式"}
SHADOW_WATCH_LABEL = "观察级·影子验证"
FEATURE_NAMES = ("envScore", "stopPct", "netRr", "volumeMultiple", "wickToBody", "rsi15Min", "derivativePoints")
P_GRID = (0.50, 0.55, 0.60, 0.65, 0.70)
RELEASE_SCHEMA = """
CREATE TABLE IF NOT EXISTS release_modules(
    module TEXT PRIMARY KEY,
    stage TEXT NOT NULL,
    stage_started_ms INTEGER NOT NULL,
    records INTEGER NOT NULL,
    report_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS l1_reports(
    id TEXT PRIMARY KEY,
    at_ms INTEGER NOT NULL,
    payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS release_candidates(
    module TEXT NOT NULL, stage_started_ms INTEGER NOT NULL, candidate_id TEXT NOT NULL,
    PRIMARY KEY(module, stage_started_ms, candidate_id));
"""


def _dump(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def drawdown_r(values) -> float:
    """Peak-to-trough drop of a cumulative R path. Empty input is zero."""
    equity = peak = worst = 0.0
    for value in values:
        equity += float(value)
        peak = max(peak, equity)
        worst = max(worst, peak - equity)
    return worst


def rollback_reason(trades) -> str | None:
    """Last 30 nets below zero, or a path that gives back more than 6R."""
    trades = list(trades or [])
    rs = [float(trade["r"]) for trade in trades if trade.get("r") is not None]
    if drawdown_r(rs) > V2_ROLLBACK_MAX_DRAWDOWN_R:
        return "回撤超过 6R"
    if len(trades) >= V2_ROLLBACK_TRADES:
        nets = [float(trade["netPct"]) for trade in trades[-V2_ROLLBACK_TRADES:] if trade.get("netPct") is not None]
        if len(nets) >= V2_ROLLBACK_TRADES and sum(nets) / len(nets) < 0:
            return "最近 30 笔期望值小于 0"
    return None


def accept_adjustment(params: dict) -> dict:
    """Hold every learned change. Hard-constraint violations are named and still not applied."""
    gaps = unlearnable_gaps(params or {})
    if gaps:
        return {"applied": False, "status": "REJECTED", "reason": "UNLEARNABLE", "gaps": gaps}
    return {"applied": False, "status": "HELD", "reason": "提案留在报告里，不改 S1–S5"}


def push_policy(stage: str, module: str = "S1") -> dict:
    """What a push is allowed to say. Research and shadow both stay on the watch tier."""
    if module == "S5":
        return {"module": module, "stage": "RESEARCH", "push": False,
                "tier": V2_TIER_WATCH, "tierLabel": V2_TIER_LABEL}
    if stage == "SHADOW":
        return {"module": module, "stage": "SHADOW", "push": True,
                "tier": V2_TIER_WATCH, "tierLabel": SHADOW_WATCH_LABEL}
    if stage == "TRIAL":
        return {"module": module, "stage": "TRIAL", "push": True, "tier": V2_TIER_TRIAL, "tierLabel": V2_TIER_TRIAL_LABEL}
    if stage == "LIVE":
        return {"module": module, "stage": "LIVE", "push": True, "tier": V2_TIER_TRADE, "tierLabel": V2_TIER_TRADE_LABEL}
    return {"module": module, "stage": "RESEARCH", "push": True, "tier": V2_TIER_WATCH, "tierLabel": V2_TIER_LABEL}


def _stamp(signal: dict, policy: dict) -> dict:
    stamped = dict(signal)
    label = policy["tierLabel"]
    name = stamped.get("strategy_name_zh") or ""
    if name.startswith("【") and "】" in name:
        name = name.split("】", 1)[1]
    stamped["tier"] = policy["tier"]
    stamped["tier_label"] = label
    stamped["strategy_name_zh"] = f"【{label}】{name}"
    v2 = dict(stamped.get("v2") or {})
    v2.update(tier=policy["tier"], tierLabel=label, releaseStage=policy["stage"])
    stamped["v2"] = v2
    return stamped


def apply_release(signal, policy: dict, trade_paused: bool = False):
    """Return the signal to enqueue. Shadow still pushes its watch card. Trade tier can be paused."""
    if not signal:
        return None, None
    module = signal.get("module")
    if module == "S5":
        return None, "S5 只做研究，不推送"
    if not policy.get("push"):
        return None, "影子记录，不推送"
    if policy.get("tier") == V2_TIER_TRADE and trade_paused:
        return None, "交易级暂停，熔断中"
    if policy.get("stage") != "SHADOW" and policy.get("tier") not in (V2_TIER_TRIAL, V2_TIER_TRADE):
        return signal, None
    return _stamp(signal, policy), None


def _sigmoid(value: float) -> float:
    if value >= 0:
        return 1 / (1 + math.exp(-value))
    exp = math.exp(value)
    return exp / (1 + exp)


def _solve(matrix, vector):
    size = len(vector)
    rows = [list(row) + [vector[index]] for index, row in enumerate(matrix)]
    for col in range(size):
        pivot = max(range(col, size), key=lambda row: abs(rows[row][col]))
        if abs(rows[pivot][col]) < 1e-12:
            return None
        rows[col], rows[pivot] = rows[pivot], rows[col]
        scale = rows[col][col]
        for index in range(col, size + 1):
            rows[col][index] /= scale
        for row in range(size):
            if row == col:
                continue
            factor = rows[row][col]
            for index in range(col, size + 1):
                rows[row][index] -= factor * rows[col][index]
    return [row[size] for row in rows]


def _fit_logistic(rows, labels):
    count = len(rows)
    width = len(rows[0])
    means = [sum(row[col] for row in rows) / count for col in range(width)]
    scales = []
    for col in range(width):
        variance = sum((row[col] - means[col]) ** 2 for row in rows) / count
        scales.append(math.sqrt(variance) if variance > 1e-12 else 0.0)
    used = [col for col, scale in enumerate(scales) if scale > 0]
    weights = [0.0] * (len(used) + 1)
    for _ in range(25):
        gradient = [0.0] * len(weights)
        hessian = [[0.0] * len(weights) for _ in weights]
        for row, label in zip(rows, labels):
            score = weights[0]
            scaled = [(row[col] - means[col]) / scales[col] for col in used]
            for index, value in enumerate(scaled):
                score += weights[index + 1] * value
            prob = _sigmoid(score)
            weight = prob * (1 - prob)
            error = prob - label
            gradient[0] += error
            hessian[0][0] += weight
            for index, value in enumerate(scaled):
                gradient[index + 1] += error * value
                hessian[0][index + 1] += weight * value
                hessian[index + 1][0] += weight * value
                for other, second in enumerate(scaled):
                    hessian[index + 1][other + 1] += weight * value * second
        for index in range(1, len(weights)):
            hessian[index][index] += 1.0
            gradient[index] += weights[index]
        step = _solve(hessian, gradient)
        if step is None:
            break
        for index, value in enumerate(step):
            weights[index] -= value
    return {"weights": weights, "means": means, "scales": scales, "used": used}


def _predict(model, row) -> float:
    score = model["weights"][0]
    for index, col in enumerate(model["used"]):
        score += model["weights"][index + 1] * ((row[col] - model["means"][col]) / model["scales"][col])
    return _sigmoid(score)


def _vector(features: dict) -> list:
    def num(key, default=0.0):
        try:
            value = float(features.get(key))
        except (TypeError, ValueError):
            return default
        return default if not math.isfinite(value) else value

    return [
        num("envScore") / 100, num("stopPct"), num("netRr"), num("volumeMultiple"), num("wickToBody"),
        num("rsi15Min", 50) / 100, num("derivativePoints") / 24,
    ]


def _weight(model, name: str) -> float:
    try:
        column = FEATURE_NAMES.index(name)
        slot = model["used"].index(column)
    except ValueError:
        return 0.0
    return model["weights"][slot + 1]


def fit_meta_label(samples) -> dict:
    """Logistic meta-label on Engine A features. The proposal is never applied."""
    rows = [sample for sample in samples or [] if sample.get("netPct") is not None and sample.get("openedMs") and sample.get("closedMs")]
    base = {"applied": False, "samples": len(rows), "minSamples": V2_L1_MIN_SAMPLES, "features": list(FEATURE_NAMES)}
    if len(rows) < V2_L1_MIN_SAMPLES:
        return {**base, "status": "INSUFFICIENT"}
    start = min(int(sample["openedMs"]) for sample in rows)
    end = max(int(sample["closedMs"]) for sample in rows)
    cut = oos_cut(start, end)
    folds = {"IS": [], "OOS": []}
    for sample in rows:
        fold = assign_fold(int(sample["openedMs"]), int(sample["closedMs"]), cut)
        if fold in folds:
            folds[fold].append(sample)
    if len(folds["IS"]) < 30 or len(folds["OOS"]) < 30:
        return {**base, "status": "INSUFFICIENT", "reason": "清洗前推后样本不足"}
    labels = [1 if float(sample["netPct"]) > 0 else 0 for sample in folds["IS"]]
    if len(set(labels)) < 2:
        return {**base, "status": "INSUFFICIENT", "reason": "训练集只有一种结果"}
    model = _fit_logistic([_vector(sample.get("features") or {}) for sample in folds["IS"]], labels)
    scored = [(sample, _predict(model, _vector(sample.get("features") or {}))) for sample in folds["IS"]]
    best_threshold, best_mean, seen = V2_L1_P_MIN, None, False
    for threshold in P_GRID:
        chosen = [float(sample["netPct"]) for sample, prob in scored if prob >= threshold]
        if len(chosen) < 20:
            continue
        mean = sum(chosen) / len(chosen)
        if not seen or mean > best_mean:
            best_threshold, best_mean, seen = threshold, mean, True
    oos_probs = [_predict(model, _vector(sample.get("features") or {})) for sample in folds["OOS"]]
    oos_hits = sum(1 for sample, prob in zip(folds["OOS"], oos_probs) if (prob >= 0.5) == (float(sample["netPct"]) > 0))
    stop_buffer = V2_L1_STOP_BUFFER_MIN_PCT if _weight(model, "stopPct") <= 0 else 0.05
    entry_offset = V2_L1_ENTRY_OFFSET_MIN_PCT / 2 if _weight(model, "netRr") < 0 else 0.0
    proposal = {
        "pThreshold": _clamp(best_threshold, V2_L1_P_MIN, V2_L1_P_MAX),
        "entryOffsetPct": _clamp(entry_offset, V2_L1_ENTRY_OFFSET_MIN_PCT, V2_L1_ENTRY_OFFSET_MAX_PCT),
        "stopBufferPct": _clamp(stop_buffer, V2_L1_STOP_BUFFER_MIN_PCT, V2_L1_STOP_BUFFER_MAX_PCT),
    }
    return {
        **base, "status": "FIT", "applied": False, "proposal": proposal,
        "hold": accept_adjustment({"frictionPct": 0.24, "stopPct": proposal["stopBufferPct"], "holdMinutes": 360}),
        "oosAccuracy": round(oos_hits / len(folds["OOS"]), 4), "oosCount": len(folds["OOS"]), "isCount": len(folds["IS"]),
        "bounds": {
            "pThreshold": [V2_L1_P_MIN, V2_L1_P_MAX],
            "entryOffsetPct": [V2_L1_ENTRY_OFFSET_MIN_PCT, V2_L1_ENTRY_OFFSET_MAX_PCT],
            "stopBufferPct": [V2_L1_STOP_BUFFER_MIN_PCT, V2_L1_STOP_BUFFER_MAX_PCT],
        },
    }


def stage_review(module, stage, started, now, book, evidence):
    """Elapsed time is necessary, never sufficient. No automatic caller supplies evidence.

    Evidence must describe a reviewed, frozen independent experiment and actual
    comparable trial columns; stage returns are recomputed from unique closed trades.
    """
    gaps = []
    evidence = evidence or {}
    if (evidence.get('module') != module or evidence.get('stage') != stage
            or evidence.get('stageStartedMs') != started or evidence.get('asOfMs') != now
            or evidence.get('independent') is not True or evidence.get('dataQualityPassed') is not True
            or not evidence.get('experimentId') or not evidence.get('manifestSha256')):
        gaps.append('缺少与本阶段及复核时点一致的独立试验/数据质量证据')
    unique = {}
    for trade in book:
        key = trade.get('candidateId')
        if (not key or key in unique or trade.get('eligibleForValidation') is not True
                or not isinstance(trade.get('netPct'), (int, float)) or not math.isfinite(trade['netPct'])
                or not started <= (trade.get('openedMs') or 0) < (trade.get('closedMs') or 0) <= now):
            gaps.append('阶段交易存在重复、时间越界、无效收益或不确定路径')
            continue
        unique[key] = trade
    columns = evidence.get('trialReturns') or []
    trial_ids = evidence.get('trialIds') or []
    timeline = evidence.get('timelineMs') or []
    n_trials = evidence.get('nTrials')
    matrix_ok = (isinstance(n_trials, int) and not isinstance(n_trials, bool) and n_trials >= 2
                 and len(columns) == n_trials == len(trial_ids) == len(set(trial_ids))
                 and len(timeline) >= 16 and all(isinstance(t, int) for t in timeline)
                 and all(a < b for a, b in zip(timeline, timeline[1:]))
                 and all(len(c) == len(timeline) and all(isinstance(v, (int, float)) and math.isfinite(v) for v in c) for c in columns))
    pbo_value = pbo(columns) if matrix_ok else None
    if not matrix_ok:
        gaps.append('缺少全部实际试验在同一时间轴上的收益矩阵')
    summary = summarize_returns([t['netPct'] for t in unique.values()], now-started,
                                n_trials if isinstance(n_trials, int) and n_trials > 0 else 1)
    decision = promotion_decision(summary, summary['nTrials'], pbo_value)
    gaps.extend(decision['gaps'])
    if stage == 'TRIAL' and not launch_decision(summary, evidence.get('recall'))['passes']:
        gaps.append('正式上线胜率/期望/波段召回未通过')
    # JSON reports must not serialize infinity for an all-winning sample.
    if summary['profitFactor'] == math.inf:
        summary['profitFactor'] = None
        summary['noLosses'] = True
    return {'passes': not gaps, 'gaps': list(dict.fromkeys(gaps)), 'summary': summary,
            'pbo': pbo_value, 'experimentId': evidence.get('experimentId')}


def module_summary(samples, n_trials: int = 1):
    """Out-of-sample nets for one module. None when the purged test fold is empty."""
    usable = [sample for sample in samples or [] if sample.get("module") and sample.get("netPct") is not None
              and sample.get("openedMs") and sample.get("closedMs")]
    if not usable:
        return None
    start = min(int(sample["openedMs"]) for sample in usable)
    end = max(int(sample["closedMs"]) for sample in usable)
    cut = oos_cut(start, end)
    oos = [sample for sample in usable if assign_fold(int(sample["openedMs"]), int(sample["closedMs"]), cut) == "OOS"]
    if not oos:
        return None
    span = max(int(sample["closedMs"]) for sample in oos) - min(int(sample["openedMs"]) for sample in oos)
    return summarize_returns([float(sample["netPct"]) for sample in oos], max(span, 1), n_trials)


class Pipeline:
    def __init__(self, ledger):
        self.ledger = ledger
        with ledger.lock, ledger.store.db:
            ledger.store.db.executescript(RELEASE_SCHEMA)
        self._day = self._stored_day()

    def _stored_day(self):
        """UTC day of the newest L1 report. A restart reads this instead of writing another."""
        row = self.ledger._one("SELECT MAX(at_ms) AS at_ms FROM l1_reports")
        if row is None or row["at_ms"] is None:
            return None
        return int(row["at_ms"]) // 86_400_000

    def _row(self, module: str):
        return self.ledger._one("SELECT module, stage, stage_started_ms, records, report_json FROM release_modules WHERE module=?", (module,))

    def _save(self, module: str, stage: str, started: int, records: int, report: dict) -> None:
        self.ledger.store.db.execute(
            """INSERT INTO release_modules(module, stage, stage_started_ms, records, report_json) VALUES(?,?,?,?,?)
               ON CONFLICT(module) DO UPDATE SET stage=excluded.stage, stage_started_ms=excluded.stage_started_ms,
               records=excluded.records, report_json=excluded.report_json""",
            (module, stage, int(started), int(records), _dump(report)))

    def _promote(self, module: str, action: str, now_ms: int, report: dict) -> None:
        """Insert while the caller already holds the ledger lock and transaction."""
        self.ledger.store.db.execute(
            """INSERT OR IGNORE INTO promotions(id, model_version, at_ms, action, report_json) VALUES(?,?,?,?,?)""",
            (f"{module}:{action}:{int(now_ms)}", V2_ENGINE_VERSION, int(now_ms), action, _dump({"module": module, **report})))

    def stage_of(self, module: str) -> str:
        if module not in MODULES:
            return "RESEARCH"
        with self.ledger.lock:
            row = self._row(module)
        return "RESEARCH" if row is None else row["stage"]

    def policy(self, module: str) -> dict:
        return push_policy(self.stage_of(module), module)

    def consider(self, module: str, summary, now_ms: int, n_trials: int = 1, pbo_value=None) -> dict:
        """Enter shadow only from research, and only when the gates pass. No promotions row yet."""
        if module not in MODULES:
            return {"module": module, "stage": "RESEARCH", "entered": False, "reason": "S5 不进入发布流程"}
        decision = promotion_decision(summary or {}, n_trials=n_trials, pbo_value=pbo_value)
        with self.ledger.lock, self.ledger.store.db:
            row = self._row(module)
            stage = "RESEARCH" if row is None else row["stage"]
            if stage != "RESEARCH" or not decision["passes"]:
                return {"module": module, "stage": stage, "entered": False, "promotion": decision}
            self._save(module, "SHADOW", now_ms, 0, {"enteredFrom": "RESEARCH", "promotion": decision})
        return {"module": module, "stage": "SHADOW", "entered": True, "promotion": decision}

    def note(self, module: str, now_ms: int, candidate_id: str = None) -> None:
        """Count a candidate seen while the module is in its shadow window."""
        if module not in MODULES or not candidate_id:
            return
        with self.ledger.lock, self.ledger.store.db:
            row = self._row(module)
            if row is None or row["stage"] != "SHADOW":
                return
            if int(now_ms) < int(row["stage_started_ms"]):
                return
            try:
                report = json.loads(row["report_json"] or "{}")
            except json.JSONDecodeError:
                report = {}
            self.ledger.store.db.execute(
                'INSERT OR IGNORE INTO release_candidates VALUES(?,?,?)',
                (module, row['stage_started_ms'], candidate_id))
            count = self.ledger.store.db.execute(
                'SELECT count(*) FROM release_candidates WHERE module=? AND stage_started_ms=?',
                (module, row['stage_started_ms'])).fetchone()[0]
            self._save(module, "SHADOW", row["stage_started_ms"], count, report)

    def _trades(self, module: str, started: int) -> list:
        rows = self.ledger._all(
            """SELECT l.net_pct AS net_pct, l.payload AS payload, p.closed_ms AS closed_ms,
                      p.opened_ms AS opened_ms, p.candidate_id AS candidate_id
               FROM labels l
               JOIN shadow_positions p ON p.id = l.position_id
               JOIN candidates c ON c.id = p.candidate_id
               WHERE c.module=? AND p.kind='SHADOW' AND p.state='CLOSED' AND p.opened_ms>=?
               ORDER BY p.closed_ms""",
            (module, int(started)))
        trades = []
        for row in rows:
            try:
                body = json.loads(row["payload"] or "{}")
            except json.JSONDecodeError:
                body = {}
            trades.append({"netPct": row["net_pct"], "r": body.get("r"), "closedMs": row["closed_ms"],
                           "openedMs": row['opened_ms'], "candidateId": row['candidate_id'],
                           "eligibleForValidation": body.get('eligibleForValidation') is True})
        return trades

    def tick(self, module: str, now_ms: int, trades=None, evidence=None) -> dict:
        """Advance the clock. Shadow completion is the first promotions write for that module."""
        if module not in MODULES:
            return {"module": module, "stage": "RESEARCH", "changed": False}
        with self.ledger.lock, self.ledger.store.db:
            row = self._row(module)
            if row is None:
                return {"module": module, "stage": "RESEARCH", "changed": False}
            stage = row["stage"]
            started = int(row["stage_started_ms"])
            book = self._trades(module, started) if trades is None else list(trades)
            reason = rollback_reason(book) if stage in ("TRIAL", "LIVE") else None
            if reason:
                self._save(module, "RESEARCH", now_ms, 0, {"rolledBackFrom": stage, "reason": reason})
                self._promote(module, "ROLLBACK", now_ms, {"from": stage, "reason": reason})
                return {"module": module, "stage": "RESEARCH", "changed": True, "action": "ROLLBACK", "reason": reason}
            duration = V2_SHADOW_MS if stage == 'SHADOW' else V2_TRIAL_MS if stage == 'TRIAL' else None
            if duration is not None and int(now_ms)-started >= duration:
                review = stage_review(module, stage, started, int(now_ms), book, evidence)
                if not review['passes']:
                    report = json.loads(row['report_json'] or '{}')
                    report['promotion'] = review
                    self._save(module, stage, started, row['records'], report)
                    return {'module': module, 'stage': stage, 'changed': False,
                            'reason': '阶段到期，验证证据不足或未通过', 'review': review}
            if stage == "SHADOW" and int(now_ms) - started >= V2_SHADOW_MS:
                if int(row["records"]) < 1:
                    return {"module": module, "stage": "SHADOW", "changed": False, "reason": "影子期已满但没有记录"}
                report = {"from": "SHADOW", "records": int(row["records"]), "shadowMs": int(now_ms) - started}
                report['review'] = review
                self._save(module, "TRIAL", now_ms, 0, report)
                self._promote(module, "SHADOW_COMPLETE", now_ms, report)
                return {"module": module, "stage": "TRIAL", "changed": True, "action": "SHADOW_COMPLETE"}
            if stage == "TRIAL" and int(now_ms) - started >= V2_TRIAL_MS:
                report = {"from": "TRIAL", "trialMs": int(now_ms) - started}
                report['review'] = review
                self._save(module, "LIVE", now_ms, 0, report)
                self._promote(module, "TRIAL_COMPLETE", now_ms, report)
                return {"module": module, "stage": "LIVE", "changed": True, "action": "TRIAL_COMPLETE"}
        return {"module": module, "stage": stage, "changed": False}

    def tick_all(self, now_ms: int) -> list:
        return [self.tick(module, now_ms) for module in MODULES]

    def store_l1(self, samples, now_ms: int) -> dict:
        report = fit_meta_label(samples)
        with self.ledger.lock, self.ledger.store.db:
            self.ledger.store.db.execute(
                "INSERT OR REPLACE INTO l1_reports(id, at_ms, payload) VALUES(?,?,?)",
                (f"l1:{int(now_ms)}", int(now_ms), _dump(report)))
        return report

    def maintain(self, samples, now_ms: int) -> None:
        """Once each UTC day, score research modules and refresh L1. The clock still advances every call elsewhere."""
        day = int(now_ms) // 86_400_000
        stored = self._stored_day()
        if stored is not None and (self._day is None or stored > self._day):
            self._day = stored
        if self._day == day:
            return
        self._day = day
        grouped = {}
        for sample in samples or []:
            grouped.setdefault(sample.get("module"), []).append(sample)
        for module in MODULES:
            if self.stage_of(module) == "RESEARCH":
                summary = module_summary(grouped.get(module) or [])
                if summary is not None:
                    self.consider(module, summary, now_ms)
        self.store_l1(samples or [], now_ms)
        self.tick_all(now_ms)

    def _latest_l1(self):
        row = self.ledger._one("SELECT payload FROM l1_reports ORDER BY at_ms DESC LIMIT 1")
        if row is None:
            return {"status": "INSUFFICIENT", "applied": False, "samples": 0, "minSamples": V2_L1_MIN_SAMPLES}
        try:
            return json.loads(row["payload"])
        except json.JSONDecodeError:
            return {"status": "INSUFFICIENT", "applied": False, "samples": 0, "minSamples": V2_L1_MIN_SAMPLES}

    def _notes(self):
        daily = self.ledger._one(
            "SELECT payload FROM ai_reviews WHERE id LIKE 'daily:%' ORDER BY at_ms DESC LIMIT 1")
        veto = self.ledger._one(
            "SELECT payload FROM ai_reviews WHERE id LIKE 'veto:%' ORDER BY at_ms DESC LIMIT 1")
        hypotheses = self.ledger._all(
            """SELECT payload FROM ai_reviews WHERE id LIKE 'hypothesis:%' AND id NOT LIKE '%:fallback'
               ORDER BY at_ms DESC LIMIT 12""")

        def load(row):
            if not row:
                return None
            try:
                return json.loads(row["payload"])
            except (TypeError, json.JSONDecodeError):
                return None

        loaded = [item for item in (load(row) for row in hypotheses) if isinstance(item, dict)]
        pending = [{
            "module": item.get("module"), "feature": item.get("feature"), "op": item.get("op"),
            "claim": item.get("claim"), "status": item.get("status"), "applied": False,
        } for item in loaded if item.get("kind") == "HYPOTHESIS"][:6]
        daily_body = load(daily) or {}
        veto_body = load(veto) or {}
        return {
            "daily": None if not daily_body else {"day": daily_body.get("day"), "summary": daily_body.get("summary")},
            "veto": None if not veto_body else {
                "vetoEnabled": veto_body.get("vetoEnabled"), "vetoed": veto_body.get("vetoed"),
                "passed": veto_body.get("passed"), "vetoedMeanR": veto_body.get("vetoedMeanR"),
                "passedMeanR": veto_body.get("passedMeanR"),
            },
            "hypotheses": pending,
        }

    def status(self, now_ms: int) -> dict:
        modules = []
        with self.ledger.lock:
            for module in MODULES:
                row = self._row(module)
                stage = "RESEARCH" if row is None else row["stage"]
                started = None if row is None else int(row["stage_started_ms"])
                records = 0 if row is None else int(row["records"])
                window = V2_SHADOW_MS if stage == "SHADOW" else V2_TRIAL_MS if stage == "TRIAL" else None
                remaining = None if window is None or started is None else max(0, started + window - int(now_ms))
                policy = push_policy(stage, module)
                try:
                    report = {} if row is None else json.loads(row["report_json"] or "{}")
                except json.JSONDecodeError:
                    report = {}
                modules.append({
                    "module": module, "stage": stage, "label": STAGE_ZH[stage], "push": policy["push"],
                    "tier": policy["tier"], "tierLabel": policy["tierLabel"], "startedMs": started,
                    "records": records, "remainingMs": remaining,
                    "gaps": (report.get("promotion") or {}).get("gaps") or [],
                })
            l1 = self._latest_l1()
            notes = self._notes()
            count = self.ledger.store.db.execute("SELECT count(*) FROM promotions").fetchone()[0]
        return {
            "engineVersion": V2_ENGINE_VERSION,
            "modules": modules,
            "l1": {"status": l1.get("status"), "applied": False, "samples": l1.get("samples"),
                   "minSamples": V2_L1_MIN_SAMPLES, "proposal": l1.get("proposal"), "oosAccuracy": l1.get("oosAccuracy")},
            "promotions": count,
            "gates": {
                "minTrades": V2_PROMOTE_MIN_TRADES, "minExpectancyPct": V2_PROMOTE_MIN_EXPECTANCY,
                "minWinRate": V2_PROMOTE_MIN_WIN_RATE, "minProfitFactor": V2_PROMOTE_MIN_PROFIT_FACTOR,
                "maxPbo": V2_PROMOTE_MAX_PBO, "minDsr": V2_PROMOTE_MIN_DSR, "dsrTrials": V2_PROMOTE_DSR_TRIALS,
                "perDay": [V2_PROMOTE_MIN_PER_DAY, V2_PROMOTE_MAX_PER_DAY],
            },
            **notes,
        }
