"""P2 closed loop: real fills, the 500 USDT twin, shadow positions, and labels.

Real fills stay in the model-library journal. These seven tables live in the
research sqlite next to the klines, so a label can be joined to the path that
produced it. Exits reuse v2_tracker and barriers. Promotion is P4. Engine B
writes its second opinion, daily review, hypotheses, and veto audit into ai_reviews.
"""
import json
import threading
import time

from .barriers import label_v2
from .config import V2_ENGINE_VERSION, V2_FRICTION_PCT, V2_MAX_HOLD_MINUTES, V2_PAPER_NOTIONAL_USDT, V2_RULE_VERSION
from .cost_model import calibrate, cost_snapshot
from .kline_store import ResearchStore
from .v2_tracker import advance, open_state

FEATURE_VERSION = "features-v2"
SUBJECTIVE = "主观单"
TARGET_OUTCOMES = {"TP2", "TP1_BREAKEVEN", "TP1_TRAIL", "TP1_MAX_HOLD"}
VERDICTS = {"PASS", "DOWNGRADE", "VETO"}
HOLD_MS = V2_MAX_HOLD_MINUTES * 60_000

SCHEMA = """
CREATE TABLE IF NOT EXISTS candidates(
    id TEXT PRIMARY KEY,
    at_ms INTEGER NOT NULL,
    module TEXT NOT NULL,
    environment TEXT NOT NULL,
    plan TEXT NOT NULL,
    tier TEXT NOT NULL,
    ai_verdict TEXT,
    rule_version TEXT NOT NULL,
    model_version TEXT NOT NULL,
    expires_ms INTEGER,
    payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS features(
    id TEXT PRIMARY KEY,
    position_id TEXT NOT NULL,
    at_ms INTEGER NOT NULL,
    version TEXT NOT NULL,
    payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS shadow_positions(
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    candidate_id TEXT,
    real_position_id TEXT,
    opened_ms INTEGER NOT NULL,
    entry_price REAL NOT NULL,
    notional_usdt REAL NOT NULL,
    quantity REAL NOT NULL,
    closed_ms INTEGER,
    exit_price REAL,
    exit_reason TEXT,
    state TEXT NOT NULL,
    payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS labels(
    id TEXT PRIMARY KEY,
    position_id TEXT NOT NULL,
    candidate_id TEXT,
    barrier TEXT NOT NULL,
    label INTEGER NOT NULL,
    net_pct REAL,
    mfe_pct REAL,
    mae_pct REAL,
    tp1_minutes REAL,
    created_ms INTEGER NOT NULL,
    payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS label_replays(
    id TEXT PRIMARY KEY, original_label_id TEXT NOT NULL, execution_version TEXT NOT NULL,
    created_ms INTEGER NOT NULL, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS real_fills(
    fill_id TEXT PRIMARY KEY,
    position_id TEXT NOT NULL,
    side TEXT NOT NULL,
    price REAL NOT NULL,
    quantity REAL NOT NULL,
    executed_at_ms INTEGER NOT NULL,
    signal_id TEXT,
    paper_twin_id TEXT,
    subjective INTEGER NOT NULL,
    payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS model_registry(
    version TEXT PRIMARY KEY,
    rule_version TEXT NOT NULL,
    registered_ms INTEGER NOT NULL,
    status TEXT NOT NULL,
    report_json TEXT);
CREATE TABLE IF NOT EXISTS promotions(
    id TEXT PRIMARY KEY,
    model_version TEXT NOT NULL,
    at_ms INTEGER NOT NULL,
    action TEXT NOT NULL,
    report_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS ai_reviews(
    id TEXT PRIMARY KEY,
    candidate_id TEXT NOT NULL,
    at_ms INTEGER NOT NULL,
    verdict TEXT,
    payload TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_candidates_at ON candidates(at_ms);
"""


def _dump(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def _qty(price: float) -> float:
    return V2_PAPER_NOTIONAL_USDT / float(price)


def _tradable(signal: dict, entry: float) -> bool:
    try:
        stop, tp1, tp2 = float(signal["stop_loss"]), float(signal["target_tp1"]), float(signal["target_tp2"])
    except (KeyError, TypeError, ValueError):
        return False
    return stop > 0 and stop < entry < tp1 <= tp2


def _label_code(outcome: str, net) -> int:
    if outcome == "STOP":
        return -1
    if outcome in TARGET_OUTCOMES:
        return 1
    if outcome == "USER":
        if net is None or net == 0:
            return 0
        return 1 if net > 0 else -1
    return 0


def _exit_price(state: dict):
    legs = state.get("legs") or []
    return None if not legs else legs[-1]["price"]


def _tp1_minutes(state: dict):
    tp1 = state.get("tp1At")
    if not tp1:
        return None
    return (tp1 - state["openedAt"]) / 60_000


def build_features(signal, fill: dict, latency) -> dict:
    """Versioned open snapshot. Missing inputs stay null; the key set does not change."""
    signal = signal or {}
    v2 = signal.get("v2") or {}
    env = v2.get("env") or {}
    states = env.get("states") or {}
    gates = env.get("gates") or {}
    raw = v2.get("features") or {}
    deriv = v2.get("derivatives") or {}
    latency = latency or {}
    ref = fill.get("referencePrice")
    price = float(fill["price"])
    slip = None if ref in (None, 0) else (price - float(ref)) / float(ref) * 100
    age = None
    if fill.get("referenceAtMs") and fill.get("executedAtMs"):
        age = int(fill["executedAtMs"]) - int(fill["referenceAtMs"])
    features = {
        "envD1": states.get("d1"), "envH4": states.get("h4"), "envH1": states.get("h1"),
        "envScore": env.get("score"), "envLabel": env.get("label"),
        "gateS1": gates.get("S1"), "gateS2": gates.get("S2"), "gateS3": gates.get("S3"), "gateS4": gates.get("S4"),
        "module": signal.get("module"), "tier": signal.get("tier"),
        "dropPct": raw.get("dropPct"), "dropRequiredPct": raw.get("dropRequiredPct"),
        "volumeMultiple": raw.get("volumeMultiple"), "wickToBody": raw.get("wickToBody"),
        "rsi15Min": raw.get("rsi15Min"), "ema20": raw.get("ema20"),
        "boxHeightPct": raw.get("boxHeightPct"), "support": raw.get("support"),
        "entry": signal.get("entry_price"), "stop": signal.get("stop_loss"),
        "tp1": signal.get("target_tp1"), "tp2": signal.get("target_tp2"),
        "stopPct": signal.get("stop_loss_pct"), "netTp1Pct": signal.get("net_tp1"), "netRr": signal.get("net_rr"),
        "entryMin": signal.get("entry_min"), "entryMax": signal.get("entry_max"),
        "sessionUtcHour": v2.get("sessionUtcHour"), "structuralStop": v2.get("structuralStop"),
        "spreadPct": v2.get("spreadPct"), "imbalance": signal.get("order_flow_imbalance"),
        "oiChange1hPct": deriv.get("oi_change_1h_pct"), "fundingRate": deriv.get("funding_rate"),
        "takerSellRatio": deriv.get("taker_sell_ratio"), "derivativePoints": deriv.get("points"),
        "signalToEntryMs": latency.get("signalToEntryMs"), "receivedToEntryMs": latency.get("receivedToEntryMs"),
        "openedToEntryMs": latency.get("openedToEntryMs"), "benchmarkAgeMs": age,
        "quoteSlippagePct": None if slip is None else round(slip, 6),
        "aiVerdict": signal.get("ai_verdict"), "ruleVersion": signal.get("rule_version") or V2_RULE_VERSION,
    }
    return {"version": FEATURE_VERSION, "features": features}


def _check_fill(fill: dict) -> None:
    if not isinstance(fill, dict) or fill.get("side") not in ("BUY", "SELL"):
        raise ValueError("side")
    if not isinstance(fill.get("fillId"), str) or not isinstance(fill.get("positionId"), str):
        raise ValueError("id")
    if not (float(fill["price"]) > 0 and float(fill["quantity"]) > 0 and int(fill["executedAtMs"]) > 0):
        raise ValueError("price")


class Ledger:
    def __init__(self, path: str):
        self.store = ResearchStore(path)
        self.lock = threading.RLock()
        with self.lock, self.store.db:
            self.store.db.executescript(SCHEMA)
            from .funnel import SCHEMA as FUNNEL_SCHEMA
            self.store.db.executescript(FUNNEL_SCHEMA)
            from .execution_sync import SCHEMA as EXECUTION_SCHEMA
            self.store.db.executescript(EXECUTION_SCHEMA)
            self.store.db.execute(
                "INSERT OR IGNORE INTO model_registry(version, rule_version, registered_ms, status, report_json) VALUES(?,?,?,?,?)",
                (V2_ENGINE_VERSION, V2_RULE_VERSION, int(time.time() * 1000), "RESEARCH", None))

    def close(self) -> None:
        with self.lock:
            self.store.close()

    def _one(self, sql: str, args=()):
        cur = self.store.db.execute(sql, args)
        row = cur.fetchone()
        if row is None:
            return None
        return dict(zip([d[0] for d in cur.description], row))

    def _all(self, sql: str, args=()):
        cur = self.store.db.execute(sql, args)
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]

    @staticmethod
    def _with_body(row: dict) -> dict:
        item = dict(row)
        try:
            item["body"] = json.loads(item["payload"]) if item.get("payload") else {}
        except (TypeError, json.JSONDecodeError):
            item["body"] = {}
        return item

    def _candidate_signal(self, candidate_id: str):
        row = self._one("SELECT payload FROM candidates WHERE id=?", (candidate_id,))
        if row is None:
            return None
        return json.loads(row["payload"])

    def _position(self, position_id: str):
        row = self._one("SELECT * FROM shadow_positions WHERE id=?", (position_id,))
        if row and row.get("payload"):
            row["state_payload"] = json.loads(row["payload"])
        return row

    def record_candidate(self, signal: dict, verdict: str = "PASS") -> dict:
        """One engine candidate. Watch and veto both open a shadow; S5 does not."""
        if verdict not in VERDICTS:
            raise ValueError("verdict")
        cid = signal.get("alert_id") or signal.get("structure_key")
        if not isinstance(cid, str) or not cid:
            raise ValueError("candidate id")
        module = signal.get("module") or "UNKNOWN"
        at = int(signal.get("timestamp") or signal.get("confirmation_time") or 0)
        expires = signal.get("expires_at")
        v2 = signal.get("v2") or {}
        plan = {
            "entry": signal.get("entry_price"), "stop": signal.get("stop_loss"),
            "tp1": signal.get("target_tp1"), "tp2": signal.get("target_tp2"),
            "entryMin": signal.get("entry_min"), "entryMax": signal.get("entry_max"),
        }
        shadow_id = None
        opens_shadow = module != "S5" and signal.get("rule_version") in (None, V2_RULE_VERSION) and _tradable(signal, float(signal.get("entry_price") or 0))
        with self.lock, self.store.db:
            self.store.db.execute(
                """INSERT OR IGNORE INTO candidates(id, at_ms, module, environment, plan, tier, ai_verdict, rule_version, model_version, expires_ms, payload)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (cid, at, module, _dump(v2.get("env") or {}), _dump(plan), signal.get("tier") or "WATCH",
                 verdict, signal.get("rule_version") or V2_RULE_VERSION, V2_ENGINE_VERSION,
                 None if expires is None else int(expires), _dump(signal)))
            if opens_shadow:
                shadow_id = "shadow:" + cid
                state = open_state(signal, verdict)
                self.store.db.execute(
                    """INSERT OR IGNORE INTO shadow_positions(id, kind, candidate_id, real_position_id, opened_ms, entry_price,
                       notional_usdt, quantity, state, payload) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                    (shadow_id, "SHADOW", cid, None, state["openedAt"], state["entry"], V2_PAPER_NOTIONAL_USDT,
                     _qty(state["entry"]), "OPEN", _dump(state)))
        return {"id": cid, "shadowId": shadow_id}

    def record_research(self, item: dict) -> str | None:
        """S5 research row. No shadow and no BUY."""
        if item.get("module") != "S5" or item.get("anchor_time") is None:
            return None
        trigger = item.get("trigger") or {}
        at = int(trigger.get("close_time") or item["anchor_time"])
        cid = f"BTCUSDT_S5_{int(item['anchor_time'])}"
        with self.lock, self.store.db:
            self.store.db.execute(
                """INSERT OR IGNORE INTO candidates(id, at_ms, module, environment, plan, tier, ai_verdict, rule_version, model_version, expires_ms, payload)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (cid, at, "S5", "{}", _dump({}), "RESEARCH", None, V2_RULE_VERSION, V2_ENGINE_VERSION, None, _dump(item)))
        return cid

    def set_verdict(self, candidate_id: str, verdict: str) -> None:
        if verdict not in VERDICTS:
            raise ValueError("verdict")
        with self.lock, self.store.db:
            self.store.db.execute("UPDATE candidates SET ai_verdict=? WHERE id=?", (verdict, candidate_id))
            row = self._one("SELECT id, payload FROM shadow_positions WHERE id=?", ("shadow:" + candidate_id,))
            if not row:
                return
            state = json.loads(row["payload"])
            state["verdict"] = verdict
            self.store.db.execute("UPDATE shadow_positions SET payload=? WHERE id=?", (_dump(state), row["id"]))

    def save_note(self, review_id: str, candidate_id: str, at_ms: int, verdict, payload: dict) -> None:
        """One row in ai_reviews. Daily reviews and hypotheses use their own ids."""
        if not isinstance(review_id, str) or not review_id or not isinstance(candidate_id, str) or not candidate_id:
            raise ValueError("id")
        with self.lock, self.store.db:
            self.store.db.execute(
                "INSERT OR REPLACE INTO ai_reviews(id, candidate_id, at_ms, verdict, payload) VALUES(?,?,?,?,?)",
                (review_id, candidate_id, int(at_ms), verdict, _dump(payload)))

    def save_review(self, candidate_id: str, at_ms: int, review: dict) -> None:
        body = dict(review)
        body.setdefault("kind", "SECOND_OPINION")
        self.save_note(candidate_id, candidate_id, at_ms, review.get("verdict"), body)

    def hypothesis_count(self, week: str) -> int:
        counted = {"CHECKED", "PENDING_P4", "INSUFFICIENT"}
        with self.lock:
            rows = self._all("SELECT payload FROM ai_reviews")
        count = 0
        for row in rows:
            try:
                body = json.loads(row["payload"])
            except (TypeError, json.JSONDecodeError):
                continue
            if body.get("kind") == "HYPOTHESIS" and body.get("week") == week and body.get("status") in counted:
                count += 1
        return count

    def closed_twins(self, start_ms: int, end_ms: int) -> dict:
        """Paper exits in the window, the system twin of each, and shadow closes in the same window."""
        with self.lock:
            papers = self._all(
                """SELECT id, real_position_id, closed_ms, exit_price, exit_reason, state, payload
                   FROM shadow_positions WHERE kind='PAPER' AND state='CLOSED' AND closed_ms>=? AND closed_ms<?""",
                (int(start_ms), int(end_ms)))
            shadows = self._all(
                """SELECT id, candidate_id, closed_ms, exit_reason, state, payload
                   FROM shadow_positions WHERE kind='SHADOW' AND state='CLOSED' AND closed_ms>=? AND closed_ms<?""",
                (int(start_ms), int(end_ms)))
            ids = [row["real_position_id"] for row in papers if row.get("real_position_id")]
            systems = {}
            if ids:
                marks = ",".join("?" * len(ids))
                for row in self._all(
                    f"""SELECT real_position_id, closed_ms, exit_price, exit_reason, state, payload
                        FROM shadow_positions WHERE kind='SYSTEM' AND real_position_id IN ({marks})""",
                    ids):
                    systems[row["real_position_id"]] = row
        return {"papers": [self._with_body(row) for row in papers],
                "systems": {key: self._with_body(row) for key, row in systems.items()},
                "shadows": [self._with_body(row) for row in shadows]}

    def research_samples(self) -> list:
        """Closed shadow and system labels, with the features Engine A stored on the candidate."""
        with self.lock:
            rows = self._all(
                """SELECT l.net_pct AS net_pct, p.opened_ms AS opened_ms, p.closed_ms AS closed_ms,
                          c.module AS module, c.payload AS candidate_payload, l.payload AS label_payload
                   FROM labels l
                   JOIN shadow_positions p ON p.id = l.position_id
                   LEFT JOIN candidates c ON c.id = p.candidate_id
                   WHERE p.kind IN ('SHADOW','SYSTEM') AND l.net_pct IS NOT NULL
                     AND (p.real_position_id IS NULL OR p.real_position_id NOT IN (SELECT position_id FROM fill_corrections))""")
        samples = []
        for row in rows:
            label = json.loads(row["label_payload"])
            if label.get("eligibleForValidation") is not True:
                continue
            try:
                signal = json.loads(row["candidate_payload"]) if row.get("candidate_payload") else {}
            except (TypeError, json.JSONDecodeError):
                signal = {}
            v2 = signal.get("v2") or {}
            deriv = v2.get("derivatives") or {}
            env = v2.get("env") or {}
            features = dict(v2.get("features") or {})
            features.update({
                "oiChange1hPct": deriv.get("oi_change_1h_pct"), "fundingRate": deriv.get("funding_rate"),
                "takerSellRatio": deriv.get("taker_sell_ratio"), "derivativePoints": deriv.get("points"),
                "stopPct": signal.get("stop_loss_pct"), "netTp1Pct": signal.get("net_tp1"),
                "netRr": signal.get("net_rr"), "envScore": env.get("score"),
            })
            samples.append({
                "module": row.get("module") or signal.get("module"), "netPct": row["net_pct"],
                "openedMs": row.get("opened_ms"), "closedMs": row.get("closed_ms"), "features": features,
            })
        return samples

    def _match(self, fill: dict, signal_id):
        if signal_id:
            signal = self._candidate_signal(signal_id)
            if signal is not None and signal.get("module") != "S5":
                return signal, signal_id, False
        at = int(fill["executedAtMs"])
        row = self._one(
            """SELECT id FROM candidates
               WHERE at_ms<=? AND expires_ms>=? AND module!='S5'
               ORDER BY at_ms DESC LIMIT 1""",
            (at, at))
        if row is None:
            return None, None, True
        return self._candidate_signal(row["id"]), row["id"], False

    def _insert_fill(self, fill: dict, signal_id, paper_id: str, subjective: bool) -> None:
        body = {"fill": fill, "signal_id": signal_id, "paper_twin_id": paper_id, "subjective": subjective, "availableAtMs": int(time.time() * 1000)}
        self.store.db.execute(
            """INSERT OR IGNORE INTO real_fills(fill_id, position_id, side, price, quantity, executed_at_ms,
               signal_id, paper_twin_id, subjective, payload) VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (fill["fillId"], fill["positionId"], fill["side"], float(fill["price"]), float(fill["quantity"]),
             int(fill["executedAtMs"]), signal_id, paper_id, 1 if subjective else 0, _dump(body)))

    def _system_signal(self, signal: dict, fill: dict) -> dict:
        copied = dict(signal)
        copied["entry_price"] = float(fill["price"])
        copied["timestamp"] = int(fill["executedAtMs"])
        copied["alert_id"] = "system:" + fill["positionId"]
        return copied

    def record_buy(self, fill: dict, signal_id: str | None = None, latency=None) -> dict:
        """Same time and price as the real buy. 500 USDT paper, plus a system-exit twin when a plan matches."""
        _check_fill(fill)
        if fill["side"] != "BUY":
            raise ValueError("buy")
        paper_id = "paper:" + fill["positionId"]
        with self.lock, self.store.db:
            previous = self._one("SELECT payload FROM real_fills WHERE fill_id=?", (fill["fillId"],))
            if previous:
                return json.loads(previous["payload"]).get("result") or {"fillId": fill["fillId"], "duplicate": True}
            existing_paper = self._position(paper_id)
            if existing_paper is not None:
                linked = existing_paper.get("candidate_id")
                subjective = linked is None
                signal = None if subjective else self._candidate_signal(linked)
            else:
                signal, linked, subjective = self._match(fill, signal_id)
                if signal is not None and not _tradable(signal, float(fill["price"])):
                    signal, linked, subjective = None, None, True
            self._insert_fill(fill, linked, paper_id, subjective)
            price = float(fill["price"])
            at = int(fill["executedAtMs"])
            system_id = None
            if existing_paper is None:
                link = SUBJECTIVE if subjective else linked
                self.store.db.execute(
                    """INSERT INTO shadow_positions(id, kind, candidate_id, real_position_id, opened_ms, entry_price,
                       notional_usdt, quantity, state, payload) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                    (paper_id, "PAPER", linked, fill["positionId"], at, price, V2_PAPER_NOTIONAL_USDT, _qty(price),
                     "OPEN", _dump({"link": link, "entry": price, "notionalUsdt": V2_PAPER_NOTIONAL_USDT})))
                snapshot = build_features(signal, fill, latency)
                snapshot["subjective"] = subjective
                self.store.db.execute(
                    "INSERT OR IGNORE INTO features(id, position_id, at_ms, version, payload) VALUES(?,?,?,?,?)",
                    ("features:" + paper_id, paper_id, at, FEATURE_VERSION, _dump(snapshot)))
                if signal is not None:
                    system_id = "system:" + fill["positionId"]
                    state = open_state(self._system_signal(signal, fill), signal.get("ai_verdict") or "PASS")
                    self.store.db.execute(
                        """INSERT OR IGNORE INTO shadow_positions(id, kind, candidate_id, real_position_id, opened_ms, entry_price,
                           notional_usdt, quantity, state, payload) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                        (system_id, "SYSTEM", linked, fill["positionId"], state["openedAt"], state["entry"],
                         V2_PAPER_NOTIONAL_USDT, _qty(state["entry"]), "OPEN", _dump(state)))
            else:
                average = self._weighted(fill["positionId"], "BUY")
                if average:
                    body = dict(existing_paper.get("state_payload") or {})
                    body["entry"] = average
                    body["notionalUsdt"] = V2_PAPER_NOTIONAL_USDT
                    self.store.db.execute(
                        """UPDATE shadow_positions SET entry_price=?, quantity=?, notional_usdt=?, payload=? WHERE id=?""",
                        (average, _qty(average), V2_PAPER_NOTIONAL_USDT, _dump(body), paper_id))
                system = self._position("system:" + fill["positionId"])
                system_id = None if system is None else system["id"]
            result = {
                "fillId": fill["fillId"], "paperTwinId": paper_id, "systemTwinId": system_id,
                "signalId": linked, "subjective": subjective, "featureId": "features:" + paper_id,
                "link": SUBJECTIVE if subjective else linked, "notionalUsdt": V2_PAPER_NOTIONAL_USDT,
            }
            self.store.db.execute("UPDATE real_fills SET payload=? WHERE fill_id=?",
                                  (_dump({"fill": fill, "signal_id": linked, "paper_twin_id": paper_id,
                                          "subjective": subjective, "result": result, "availableAtMs": int(time.time() * 1000)}), fill["fillId"]))
            return result

    def _weighted(self, position_id: str, side: str):
        rows = self.store.db.execute(
            "SELECT price, quantity FROM real_fills WHERE position_id=? AND side=? AND fill_id NOT IN (SELECT old_fill_id FROM fill_corrections)", (position_id, side)).fetchall()
        total = weighted = 0.0
        for price, quantity in rows:
            qty = float(quantity)
            if qty <= 0:
                continue
            total += qty
            weighted += float(price) * qty
        return None if total <= 0 else round(weighted / total, 8)

    def _clip_bars(self, bars, start_ms: int, end_ms: int):
        if not bars:
            return []
        return [bar for bar in bars if start_ms <= int(bar.get("time", 0)) <= end_ms]

    def _fetch_klines(self, interval: str, start_ms: int, end_ms: int):
        import urllib.request
        url = ("https://data-api.binance.vision/api/v3/klines?symbol=BTCUSDT"
               f"&interval={interval}&startTime={int(start_ms)}&endTime={int(end_ms)}&limit=1000")
        request = urllib.request.Request(url, headers={"User-Agent": "cryptog-v2"})
        with urllib.request.urlopen(request, timeout=8) as response:
            rows = json.loads(response.read().decode())
        return [{
            "time": int(row[0]), "open": float(row[1]), "high": float(row[2]), "low": float(row[3]),
            "close": float(row[4]), "volume": float(row[5]), "close_time": int(row[6]),
            "taker_buy_base": float(row[9]), "is_closed": True,
        } for row in rows]

    def _fetch_hold_bars(self, start_ms: int, end_ms: int):
        try:
            minute = self._fetch_klines("1m", start_ms - 60_000, end_ms)
            quarter = self._fetch_klines("15m", start_ms - 130 * 900_000, end_ms)
        except Exception:
            return [], []
        if minute:
            try:
                self.store.upsert_klines("BTCUSDT", "1m", minute)
                if quarter:
                    self.store.upsert_klines("BTCUSDT", "15m", quarter)
            except Exception:
                pass
        return minute, quarter

    def _resolve_exit_bars(self, start_ms: int, end_ms: int, cache_1m, cache_15m):
        minute, quarter = self._bars_between(start_ms, end_ms)
        if minute:
            return minute, quarter
        cached = self._clip_bars(cache_1m, start_ms - 60_000, end_ms)
        if cached:
            return cached, self._clip_bars(cache_15m, start_ms - 130 * 900_000, end_ms)
        return self._fetch_hold_bars(start_ms, end_ms)

    def _bars_between(self, start_ms: int, end_ms: int):
        start, end = int(start_ms), int(end_ms)
        minute = self.store.klines("BTCUSDT", "1m", start - 60_000, end)
        if minute:
            return minute, self.store.klines("BTCUSDT", "15m", start - 130 * 900_000, end)
        return (self.store.klines("BTCUSDT", "5m", start - 300_000, end),
                self.store.klines("BTCUSDT", "15m", start - 130 * 900_000, end))

    def _write_label(self, position_id: str, candidate_id, outcome: str, net, mfe, mae, tp1_minutes, at_ms: int, payload: dict) -> str:
        label_id = "label:" + position_id
        self.store.db.execute(
            """INSERT OR IGNORE INTO labels(id, position_id, candidate_id, barrier, label, net_pct, mfe_pct, mae_pct,
               tp1_minutes, created_ms, payload) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (label_id, position_id, candidate_id, outcome, 0 if payload.get("pathStatus") == "PATH_UNCERTAIN" else _label_code(outcome, net), net, mfe, mae, tp1_minutes,
             int(at_ms), _dump(payload)))
        return label_id

    def _signal_from_position(self, position: dict) -> dict:
        state = position["state_payload"]
        return {
            "alert_id": state.get("id") or position["id"], "module": state.get("module"),
            "entry_price": state["entry"], "stop_loss": state["stop"], "target_tp1": state["tp1"],
            "target_tp2": state["tp2"], "timestamp": state["openedAt"], "cost_snapshot": state.get("costSnapshot"),
            "invalidation_price": state.get("invalidation", state["stop"]), "reclaim_price": state.get("reclaim"),
        }

    def _apply_v2_label(self, position: dict, labeled: dict) -> str:
        legs = labeled.get("legs") or []
        exit_price = None if not legs else legs[-1]["price"]
        self.store.db.execute(
            """UPDATE shadow_positions SET state='CLOSED', closed_ms=?, exit_price=?, exit_reason=?, payload=? WHERE id=?""",
            (labeled.get("closedAt"), exit_price, labeled.get("outcome"), _dump(labeled), position["id"]))
        return self._write_label(
            position["id"], position.get("candidate_id"), labeled.get("outcome"), labeled.get("pnlPct"),
            labeled.get("mfePct"), labeled.get("maePct"), labeled.get("tp1Minutes"), labeled.get("closedAt") or 0,
            {"outcome": labeled.get("outcome"), "pnlPct": labeled.get("pnlPct"), "r": labeled.get("r"),
             "mfePct": labeled.get("mfePct"), "maePct": labeled.get("maePct"),
             "tp1Minutes": labeled.get("tp1Minutes"), "legs": legs, "source": "v2", **{k: labeled.get(k) for k in ("executionModelVersion", "costSnapshot", "pathStatus", "uncertaintyReasons", "eligibleForValidation", "conservativePnlPct")}})

    def _close_tracked(self, position: dict, bars, m15) -> dict:
        state = position["state_payload"]
        if position["state"] == "CLOSED" or state.get("phase") == "CLOSED":
            return state
        advance(state, list(bars), list(m15))
        closed = state.get("phase") == "CLOSED"
        self.store.db.execute(
            """UPDATE shadow_positions SET state=?, closed_ms=?, exit_price=?, exit_reason=?, payload=? WHERE id=?""",
            ("CLOSED" if closed else "OPEN", state.get("closedAt"), _exit_price(state), state.get("outcome"),
             _dump(state), position["id"]))
        if closed:
            from .funnel import stage
            stage(self,position.get('candidate_id') or position['id'],state.get('closedAt') or 0,'SETTLED',state.get('outcome'),{'pathStatus':state.get('pathStatus'),'eligibleForValidation':state.get('eligibleForValidation')})
            self._write_label(
                position["id"], position.get("candidate_id"), state.get("outcome"), state.get("pnlPct"),
                state.get("mfePct"), state.get("maePct"), _tp1_minutes(state), state.get("closedAt") or 0,
                {"outcome": state.get("outcome"), "pnlPct": state.get("pnlPct"), "r": state.get("r"),
                 "mfePct": state.get("mfePct"), "maePct": state.get("maePct"),
                 "tp1Minutes": _tp1_minutes(state), "legs": state.get("legs"), "source": "v2", **{k: state.get(k) for k in ("executionModelVersion", "costSnapshot", "pathStatus", "uncertaintyReasons", "eligibleForValidation", "conservativePnlPct")}})
        return state

    def record_sell(self, fill: dict, bars_1m=None, bars_15m=None, inventory_closed: bool = True) -> dict:
        """Close the paper twin when the real inventory is flat, and label a system exit the path already reached."""
        _check_fill(fill)
        if fill["side"] != "SELL":
            raise ValueError("sell")
        paper_id = "paper:" + fill["positionId"]
        prepared = None
        with self.lock:
            system_open = self._position("system:" + fill["positionId"])
        if inventory_closed and system_open is not None and system_open["state"] != "CLOSED":
            start = int(system_open["opened_ms"])
            prepared = self._resolve_exit_bars(start, start + HOLD_MS + 60_000, bars_1m, bars_15m)
        with self.lock, self.store.db:
            paper = self._position(paper_id)
            if paper is None:
                return {"ok": False, "reason": "NO_PAPER"}
            linked = paper.get("candidate_id")
            subjective = linked is None
            self._insert_fill(fill, linked, paper_id, subjective)
            if not inventory_closed or paper["state"] == "CLOSED":
                return {"ok": True, "paperTwinId": paper_id, "closed": paper["state"] == "CLOSED", "labelId": None}
            price = float(fill["price"])
            at = int(fill["executedAtMs"])
            entry = self._weighted(fill["positionId"], "BUY") or float(paper["entry_price"])
            exit_price = self._weighted(fill["positionId"], "SELL") or price
            from .execution_accounting import execution_summary
            fills = [json.loads(r[0])["fill"] for r in self.store.db.execute("SELECT payload FROM real_fills WHERE position_id=? AND fill_id NOT IN (SELECT old_fill_id FROM fill_corrections)", (fill["positionId"],))]
            summary = execution_summary(fills)
            user_net = summary["wholeTradeNetPct"]
            if not summary["closed"]:
                return {"ok": True, "closed": False, "labelId": None, "executionSummary": summary}
            user_net = round(user_net, 4)
            payload = json.loads(paper["payload"])
            payload.update(entry=entry, exit=exit_price, userNetPct=round(user_net, 4), closedAt=at,
                           notionalUsdt=V2_PAPER_NOTIONAL_USDT, executionSummary=summary)
            self.store.db.execute(
                """UPDATE shadow_positions SET state='CLOSED', closed_ms=?, entry_price=?, exit_price=?, exit_reason='USER_EXIT',
                   notional_usdt=?, payload=? WHERE id=?""",
                (at, entry, exit_price, V2_PAPER_NOTIONAL_USDT, _dump(payload), paper_id))
            system = self._position("system:" + fill["positionId"])
            label_id = None
            if system is not None and system["state"] != "CLOSED":
                if prepared is None:
                    prepared = self._bars_between(int(system["opened_ms"]), int(system["opened_ms"]) + HOLD_MS + 60_000)
                path, quarter = prepared
                labeled = label_v2(self._signal_from_position(system), path or [], quarter or [])
                if labeled.get("outcome") not in (None, "SAMPLE_END"):
                    label_id = self._apply_v2_label(system, labeled)
            elif system is not None:
                label_id = "label:" + system["id"]
            if system is None:
                label_id = self._write_label(
                    paper_id, None, "USER", round(user_net, 4), None, None, None, at,
                    {"outcome": "USER", "pnlPct": round(user_net, 4), "source": "user", "link": SUBJECTIVE})
            return {
                "ok": True, "paperTwinId": paper_id, "systemTwinId": None if system is None else system["id"],
                "closed": True, "labelId": label_id, "userNetPct": round(user_net, 4),
                "link": SUBJECTIVE if subjective else linked,
            }

    def on_fill(self, fill: dict, signal_id: str | None = None, latency=None, inventory_closed: bool | None = None,
                bars_1m=None, bars_15m=None) -> dict:
        if fill.get("side") == "BUY":
            return self.record_buy(fill, signal_id=signal_id, latency=latency)
        return self.record_sell(fill, bars_1m=bars_1m, bars_15m=bars_15m,
                                inventory_closed=True if inventory_closed is None else inventory_closed)

    def settle(self, bars_1m, bars_15m) -> list:
        """Rule settlement for open shadows and system twins. Does not close a paper twin."""
        closed = []
        with self.lock, self.store.db:
            rows = self.store.db.execute(
                "SELECT id FROM shadow_positions WHERE state='OPEN' AND kind IN ('SHADOW','SYSTEM')").fetchall()
            for (position_id,) in rows:
                position = self._position(position_id)
                state = self._close_tracked(position, bars_1m, bars_15m)
                if state.get("phase") == "CLOSED":
                    closed.append({"id": position_id, "outcome": state.get("outcome"), "pnlPct": state.get("pnlPct")})
        return closed

    def cost_fills(self, at_ms=None) -> list:
        """Real fills that carry a reference price, oldest first. Extra keys are ignored by calibrate."""
        with self.lock:
            rows = self.store.db.execute(
                "SELECT executed_at_ms, payload FROM real_fills WHERE fill_id NOT IN (SELECT old_fill_id FROM fill_corrections) ORDER BY executed_at_ms, fill_id").fetchall()
        sample = []
        for executed_at_ms, raw in rows:
            body = json.loads(raw)
            if at_ms is not None and (body.get("availableAtMs") is None or body["availableAtMs"] > at_ms or executed_at_ms > at_ms):
                continue
            fill = body.get("fill") or {}
            if not fill.get("referencePrice"):
                continue
            notional = float(fill["price"]) * float(fill["quantity"])
            fee = fill.get("commission")
            asset = fill.get("commissionAsset")
            if fee is None or notional <= 0:
                fee_pct = None
            elif asset == "USDT":
                fee_pct = float(fee) / notional * 100
            elif asset == "BTC":
                fee_pct = float(fee) * float(fill["price"]) / notional * 100
            else:
                rate = fill.get("commissionAssetUsdtRate")
                fee_pct = None if not rate else float(fee) * float(rate) / notional * 100
            item = {
                "side": fill["side"], "quote": float(fill["referencePrice"]), "fill": float(fill["price"]),
                "executedAtMs": int(executed_at_ms),
            }
            if fee_pct is not None:
                item["fee_pct"] = fee_pct
            sample.append(item)
        return sample

    def working_cost(self, at_ms: int) -> dict:
        measured = calibrate(self.cost_fills(at_ms))
        measured["availableAtMs"] = at_ms
        return cost_snapshot(at_ms, measured)

    def measured_cost(self, bnb_discount: bool = False) -> dict:
        """Slippage and fee sample. The working cost cannot go under the published floor."""
        return calibrate(self.cost_fills(), bnb_discount)

    def position(self, position_id: str):
        with self.lock:
            return self._position(position_id)

    def label_for(self, position_id: str):
        with self.lock:
            row = self._one("SELECT * FROM labels WHERE position_id=?", (position_id,))
        if row and row.get("payload"):
            row["body"] = json.loads(row["payload"])
        return row

    def feature_for(self, position_id: str):
        with self.lock:
            row = self._one("SELECT * FROM features WHERE position_id=?", (position_id,))
        if row:
            row["body"] = json.loads(row["payload"])
        return row

    def write_promotion(self, promotion_id: str, at_ms: int, action: str, report: dict) -> None:
        """P4 release log. Callers write a row only when a module finishes a release stage or rolls back."""
        with self.lock, self.store.db:
            self.store.db.execute(
                """INSERT OR IGNORE INTO promotions(id, model_version, at_ms, action, report_json) VALUES(?,?,?,?,?)""",
                (promotion_id, V2_ENGINE_VERSION, int(at_ms), action, _dump(report)))

    def promotions(self) -> list:
        with self.lock:
            rows = self._all("SELECT id, model_version, at_ms, action, report_json FROM promotions ORDER BY at_ms, id")
        for row in rows:
            try:
                row["report"] = json.loads(row.pop("report_json") or "{}")
            except json.JSONDecodeError:
                row["report"] = {}
        return rows

    def replay_label(self, position_id: str, path, m15, at_ms: int) -> dict:
        import hashlib
        with self.lock, self.store.db:
            original = self.label_for(position_id)
            position = self._position(position_id)
            if not original or not position:
                raise ValueError("ORIGINAL_LABEL_MISSING")
            signal = self._signal_from_position(position)
            result = label_v2(signal, path, m15)
            body = {"originalLabelId": original["id"], "result": result,
                    "inputHash": hashlib.sha256(_dump([signal, path, m15]).encode()).hexdigest()}
            replay_id = "replay:" + hashlib.sha256(_dump(body).encode()).hexdigest()
            self.store.db.execute("INSERT OR IGNORE INTO label_replays VALUES(?,?,?,?,?)",
                                  (replay_id, original["id"], "settlement-v2.1", at_ms, _dump(body)))
            return dict(body, id=replay_id)

    def label_quality(self) -> dict:
        with self.lock:
            rows = [json.loads(r[0]) for r in self.store.db.execute("SELECT payload FROM labels")]
        uncertain = [r for r in rows if r.get("pathStatus") == "PATH_UNCERTAIN"]
        legacy = [r for r in rows if r.get("source") == "v2" and r.get("executionModelVersion") != "settlement-v2.1"]
        values = [(r["conservativePnlPct"] if r.get("conservativePnlPct") is not None else r["pnlPct"]) for r in rows if r.get("executionModelVersion") == "settlement-v2.1" and r.get("pnlPct") is not None]
        return {"total": len(rows), "uncertainCount": len(uncertain), "legacyCount": len(legacy),
                "uncertainFraction": len(uncertain)/len(rows) if rows else None,
                "conservativeMeanPct": sum(values)/len(values) if values else None,
                "eligibleCount": sum(r.get("eligibleForValidation") is True for r in rows)}

    def counts(self) -> dict:
        with self.lock:
            names = ("candidates", "features", "shadow_positions", "labels", "real_fills", "model_registry", "promotions", "ai_reviews")
            return {name: self.store.db.execute(f"SELECT count(*) FROM {name}").fetchone()[0] for name in names}
