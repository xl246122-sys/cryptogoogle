"""Virtual outcomes for short-horizon-v2 signals, the circuit breaker and the AI veto audit.

Every signal is tracked as if filled at its pushed ask. Within one 1m bar the stop is
checked before any target, and a breakeven exit is never taken in the bar that hit TP1,
so the ledger errs on the losing side when the bar order is unknown.
"""
import json
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from .config import (V2_BREAKER_DAILY_R, V2_BREAKER_PAUSE_MS, V2_BREAKER_STOPS, V2_FRICTION_PCT,
                     V2_MAX_HOLD_MINUTES, V2_TIME_STOP_MINUTES, V2_TIME_STOP_PROGRESS_R, V2_TP1_FRACTION)
from .indicators import ema

CST = timezone(timedelta(hours=8))
M1 = 60_000
M15 = 900_000
VETO_AUDIT_MIN = 100


def open_state(signal: dict, verdict: str = "PASS") -> dict:
    entry = float(signal["entry_price"])
    stop = float(signal["stop_loss"])
    opened = int(signal["timestamp"])
    return {
        "id": signal["alert_id"], "module": signal.get("module"), "verdict": verdict,
        "entry": entry, "stop": stop, "tp1": float(signal["target_tp1"]), "tp2": float(signal["target_tp2"]),
        "breakeven": entry * (1 + V2_FRICTION_PCT / 100),
        "riskPct": (1 - stop / entry) * 100,
        "openedAt": opened, "fromBar": opened - opened % M1,
        "phase": "OPEN", "remaining": 1.0, "legs": [], "tp1At": None,
        "timeChecked": False, "lastBar": 0, "mfePct": 0.0, "maePct": 0.0,
        "outcome": None, "closedAt": None, "pnlPct": None, "r": None,
        "invalidation": float(signal.get("invalidation_price") or stop),
        "reclaim": signal.get("reclaim_price"), "watch": None, "watchAt": None,
    }


def _leg(state: dict, fraction: float, price: float, at: int, kind: str) -> None:
    state["legs"].append({"fraction": fraction, "price": price, "at": at, "kind": kind})
    state["remaining"] = round(state["remaining"] - fraction, 9)


def _close(state: dict, at: int, outcome: str) -> dict:
    pnl = sum(l["fraction"] * ((l["price"] / state["entry"] - 1) * 100 - V2_FRICTION_PCT) for l in state["legs"])
    state.update(phase="CLOSED", outcome=outcome, closedAt=at, pnlPct=round(pnl, 4),
                 r=round(pnl / (state["riskPct"] + V2_FRICTION_PCT), 4))
    return state


def _trail_break(state: dict, m15: List[dict], at: int) -> Optional[float]:
    """Close of the newest 15m bar that finished after TP1, if it is below EMA20."""
    done = [b for b in m15 if b["close_time"] < at and b["close_time"] > (state["tp1At"] or 0)]
    if not done or done[-1]["close_time"] <= state.get("trailChecked", 0):
        return None
    last = done[-1]
    state["trailChecked"] = last["close_time"]
    closes = [b["close"] for b in m15 if b["close_time"] <= last["close_time"]]
    level = ema(closes[-120:], 20)
    return last["close"] if level is not None and last["close"] < level else None


def advance(state: dict, m1: List[dict], m15: List[dict]) -> dict:
    """Feed closed 1m bars (oldest first) and the closed 15m bars known at the same time."""
    if state["phase"] == "CLOSED":
        return state
    entry = state["entry"]
    for bar in m1:
        t = int(bar["time"])
        if t < state["fromBar"] or t <= state["lastBar"]:
            continue
        state["lastBar"] = t
        end = int(bar["close_time"]) + 1
        state["mfePct"] = max(state["mfePct"], (bar["high"] / entry - 1) * 100)
        state["maePct"] = min(state["maePct"], (bar["low"] / entry - 1) * 100)
        if state["phase"] == "OPEN":
            if bar["low"] <= state["stop"]:
                _leg(state, 1.0, state["stop"], end, "STOP")
                return _close(state, end, "STOP")
            if bar["high"] >= state["tp1"]:
                _leg(state, V2_TP1_FRACTION, state["tp1"], end, "TP1")
                state.update(phase="TP1", tp1At=end)
                if bar["high"] >= state["tp2"]:
                    _leg(state, state["remaining"], state["tp2"], end, "TP2")
                    return _close(state, end, "TP2")
                continue
            if not state["timeChecked"] and end >= state["openedAt"] + V2_TIME_STOP_MINUTES * M1:
                state["timeChecked"] = True
                progress = (bar["close"] - entry) / (entry - state["stop"])
                if progress < V2_TIME_STOP_PROGRESS_R:
                    _leg(state, 1.0, bar["close"], end, "TIME_STOP")
                    return _close(state, end, "TIME_STOP")
        else:
            if bar["low"] <= state["breakeven"]:
                _leg(state, state["remaining"], state["breakeven"], end, "BREAKEVEN")
                return _close(state, end, "TP1_BREAKEVEN")
            if bar["high"] >= state["tp2"]:
                _leg(state, state["remaining"], state["tp2"], end, "TP2")
                return _close(state, end, "TP2")
            if end % M15 == 0:
                broke = _trail_break(state, m15, end)
                if broke is not None:
                    _leg(state, state["remaining"], broke, end, "TRAIL")
                    return _close(state, end, "TP1_TRAIL")
        if end >= state["openedAt"] + V2_MAX_HOLD_MINUTES * M1:
            _leg(state, state["remaining"], bar["close"], end, "MAX_HOLD")
            return _close(state, end, "TP1_MAX_HOLD" if state["phase"] == "TP1" else "MAX_HOLD")
    return state


def breaker_state(closed: List[dict], now_ms: int) -> dict:
    """Pushed outcomes only. Two stops in a row, or -2R in the CST day, pause pushes for 4h."""
    rows = sorted((o for o in closed if o["verdict"] != "VETO" and o.get("closedAt")), key=lambda o: o["closedAt"])
    streak = 0
    for o in reversed(rows):
        if o["outcome"] != "STOP":
            break
        streak += 1
    day = datetime.fromtimestamp(now_ms / 1000, CST).date()
    today = [o for o in rows if datetime.fromtimestamp(o["closedAt"] / 1000, CST).date() == day]
    day_r = round(sum(o["r"] for o in today), 4)
    view = {"consecutiveStops": streak, "dayR": day_r, "pausedUntil": 0, "reason": None}
    if streak >= V2_BREAKER_STOPS:
        view.update(pausedUntil=rows[-1]["closedAt"] + V2_BREAKER_PAUSE_MS, reason=f"连续 {streak} 笔止损")
    elif today and day_r <= V2_BREAKER_DAILY_R:
        view.update(pausedUntil=today[-1]["closedAt"] + V2_BREAKER_PAUSE_MS, reason=f"当日累计 {day_r:.2f}R")
    if view["pausedUntil"] <= now_ms:
        view.update(pausedUntil=0, reason=None)
    return view


def veto_audit(closed: List[dict]) -> dict:
    """After 100 vetoed outcomes, the veto stays on only if vetoed signals did worse than passed ones."""
    vetoed = [o["r"] for o in closed if o["verdict"] == "VETO"]
    passed = [o["r"] for o in closed if o["verdict"] != "VETO"]
    mean = lambda xs: round(sum(xs) / len(xs), 4) if xs else None
    view = {"vetoed": len(vetoed), "passed": len(passed), "vetoedMeanR": mean(vetoed), "passedMeanR": mean(passed),
            "vetoEnabled": True}
    if len(vetoed) >= VETO_AUDIT_MIN and passed and view["vetoedMeanR"] >= view["passedMeanR"]:
        view["vetoEnabled"] = False
    return view


class V2Tracker:
    """Persists virtual outcomes beside the event journal, using the store's connection and lock."""

    def __init__(self, store):
        self.store = store
        with store.lock, store.db:
            store.db.execute('''CREATE TABLE IF NOT EXISTS v2_outcomes(id TEXT PRIMARY KEY, opened_ms INTEGER NOT NULL,
                state TEXT NOT NULL, verdict TEXT NOT NULL, outcome TEXT, closed_ms INTEGER, r REAL, payload TEXT NOT NULL)''')

    def open(self, signal: dict, verdict: str = "PASS") -> bool:
        state = open_state(signal, verdict)
        with self.store.lock, self.store.db:
            cur = self.store.db.execute(
                "INSERT OR IGNORE INTO v2_outcomes(id,opened_ms,state,verdict,payload) VALUES(?,?,?,?,?)",
                (state["id"], state["openedAt"], "OPEN", verdict, json.dumps(state, ensure_ascii=False)))
            return cur.rowcount == 1

    def set_verdict(self, alert_id: str, verdict: str) -> None:
        with self.store.lock, self.store.db:
            row = self.store.db.execute("SELECT payload FROM v2_outcomes WHERE id=?", (alert_id,)).fetchone()
            if not row:
                return
            state = json.loads(row[0])
            state["verdict"] = verdict
            self.store.db.execute("UPDATE v2_outcomes SET verdict=?,payload=? WHERE id=?",
                                  (verdict, json.dumps(state, ensure_ascii=False), alert_id))

    def step(self, m1: List[dict], m15: List[dict]) -> List[dict]:
        closed = []
        with self.store.lock, self.store.db:
            rows = self.store.db.execute("SELECT id,payload FROM v2_outcomes WHERE state='OPEN'").fetchall()
            for alert_id, raw in rows:
                state = advance(json.loads(raw), m1, m15)
                done = state["phase"] == "CLOSED"
                self.store.db.execute(
                    "UPDATE v2_outcomes SET state=?,outcome=?,closed_ms=?,r=?,payload=? WHERE id=?",
                    ("CLOSED" if done else "OPEN", state["outcome"], state["closedAt"], state["r"],
                     json.dumps(state, ensure_ascii=False), alert_id))
                if done:
                    closed.append(state)
        return closed

    def closed(self, limit: int = 500) -> List[dict]:
        with self.store.lock:
            rows = self.store.db.execute(
                "SELECT payload FROM v2_outcomes WHERE state='CLOSED' ORDER BY closed_ms DESC LIMIT ?", (limit,)).fetchall()
        return [json.loads(r[0]) for r in reversed(rows)]

    def open_count(self) -> int:
        with self.store.lock:
            return self.store.db.execute("SELECT count(*) FROM v2_outcomes WHERE state='OPEN'").fetchone()[0]

    def watch(self, bid, now_ms: int, series=None) -> List[dict]:
        """Second-level reminder for open shadow positions. Does not settle the ledger."""
        from .ai_review import decorate_exit_message
        from .stop_monitor import classify_exit

        if isinstance(bid, bool) or not isinstance(bid, (int, float)) or bid <= 0:
            return []
        series = series or {}
        events = []
        with self.store.lock, self.store.db:
            rows = self.store.db.execute("SELECT id,payload FROM v2_outcomes WHERE state='OPEN'").fetchall()
            for alert_id, raw in rows:
                state = json.loads(raw)
                found = classify_exit(
                    bid, now_ms, state["entry"], state["openedAt"], state["stop"], state["tp1"], state["tp2"],
                    state.get("invalidation", state["stop"]), state.get("reclaim"), state["breakeven"],
                    state["phase"] == "TP1", V2_MAX_HOLD_MINUTES, V2_TIME_STOP_MINUTES, V2_TIME_STOP_PROGRESS_R,
                    series.get("1m"), series.get("15m"), series.get("1h"), True)
                kind = None if found is None else found[0]
                if kind == state.get("watch"):
                    continue
                state["watch"] = kind
                state["watchAt"] = now_ms
                self.store.db.execute("UPDATE v2_outcomes SET payload=? WHERE id=?",
                                      (json.dumps(state, ensure_ascii=False), alert_id))
                if found:
                    events.append({"id": alert_id, "kind": found[0],
                                   "message": decorate_exit_message(found[0], found[1], state),
                                   "at": now_ms, "bid": bid})
        return events

    def breaker(self, now_ms: int) -> dict:
        return breaker_state(self.closed(), now_ms)

    def audit(self) -> dict:
        return veto_audit(self.closed(5000))

    def status(self, now_ms: int) -> dict:
        rows = self.closed()
        wins = [o for o in rows if o["r"] > 0]
        return {
            "open": self.open_count(), "closed": len(rows),
            "winRate": round(len(wins) / len(rows), 4) if rows else None,
            "meanR": round(sum(o["r"] for o in rows) / len(rows), 4) if rows else None,
            "breaker": breaker_state(rows, now_ms), "veto": veto_audit(rows),
            "recent": [{k: o[k] for k in ("id", "module", "verdict", "outcome", "r", "openedAt", "closedAt")} for o in rows[-10:]],
        }
