"""P5 continuity. Weekly hypotheses stay in ai_review and stay unapplied.

Once a CST month has closed, real fills produce a cost report. The working
cost is the greater of the measurement and the published floor. The floor
constant is not rewritten. Once a CST quarter has been closed for a full
6-hour hold, closed labels produce an environment-boundary report. The
cutoff stays inside one 1H weight of the published zero line, and it is
not written into the environment gates.
"""
import json
from datetime import datetime, timedelta, timezone

from .config import (
    V2_ENV_CUTOFF_SPAN, V2_ENV_CUTOFF_STEP, V2_ENV_MIN_SAMPLES, V2_ENV_MIN_SIDE, V2_ENV_PRIOR_CUTOFF,
    V2_MAX_HOLD_MINUTES,
)
from .cost_model import calibrate_month

CST = timezone(timedelta(hours=8))
HOLD_MS = V2_MAX_HOLD_MINUTES * 60_000
SCHEMA = """
CREATE TABLE IF NOT EXISTS cost_reports(
    id TEXT PRIMARY KEY,
    at_ms INTEGER NOT NULL,
    payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS environment_reports(
    id TEXT PRIMARY KEY,
    at_ms INTEGER NOT NULL,
    payload TEXT NOT NULL);
"""


def _dump(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def _num(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return number


def _cst(ms: int) -> datetime:
    return datetime.fromtimestamp(int(ms) / 1000, CST)


def month_key(ms: int) -> str:
    day = _cst(ms)
    return f"{day.year:04d}-{day.month:02d}"


def previous_month(ms: int) -> str:
    day = _cst(ms)
    year, month = day.year, day.month - 1
    if month == 0:
        year, month = year - 1, 12
    return f"{year:04d}-{month:02d}"


def quarter_key(ms: int) -> str:
    day = _cst(ms)
    return f"{day.year:04d}-Q{(day.month - 1) // 3 + 1}"


def previous_quarter(ms: int) -> str:
    day = _cst(ms)
    year, quarter = day.year, (day.month - 1) // 3
    if quarter == 0:
        year, quarter = year - 1, 4
    return f"{year:04d}-Q{quarter}"


def quarter_bounds(key: str) -> tuple:
    year, quarter = int(key[:4]), int(key[-1])
    start_month = (quarter - 1) * 3 + 1
    start = datetime(year, start_month, 1, tzinfo=CST)
    end_month = start_month + 3
    end_year = year + 1 if end_month == 13 else year
    end_month = 1 if end_month == 13 else end_month
    end = datetime(end_year, end_month, 1, tzinfo=CST)
    return int(start.timestamp() * 1000), int(end.timestamp() * 1000)


def cutoff_grid() -> tuple:
    return tuple(range(-V2_ENV_CUTOFF_SPAN, V2_ENV_CUTOFF_SPAN + 1, V2_ENV_CUTOFF_STEP))


def _fills_for_month(fills, month: str) -> list:
    chosen = []
    for row in fills or []:
        if not isinstance(row, dict):
            continue
        at = row.get("executedAtMs")
        if at is not None:
            if month_key(int(at)) == month:
                chosen.append({**row, "month": month})
            continue
        if row.get("month") == month:
            chosen.append(row)
    return chosen


def estimate_environment(samples) -> dict:
    """Pick a held cutoff. Fewer than 200 labeled scores stays on the prior with no cutoff."""
    rows = []
    for sample in samples or []:
        if not isinstance(sample, dict):
            continue
        features = sample.get("features") if isinstance(sample.get("features"), dict) else {}
        score = _num(features.get("envScore"))
        net = _num(sample.get("netPct"))
        if score is None or net is None:
            continue
        rows.append((score, net))
    report = {
        "kind": "ENVIRONMENT", "priorCutoff": V2_ENV_PRIOR_CUTOFF, "grid": list(cutoff_grid()),
        "samples": len(rows), "minSamples": V2_ENV_MIN_SAMPLES, "applied": False, "cutoff": None,
    }
    if len(rows) < V2_ENV_MIN_SAMPLES:
        report["status"] = "INSUFFICIENT"
        return report
    best = None
    for cutoff in cutoff_grid():
        above = [net for score, net in rows if score >= cutoff]
        below = [net for score, net in rows if score < cutoff]
        if len(above) < V2_ENV_MIN_SIDE or len(below) < V2_ENV_MIN_SIDE:
            continue
        above_mean = sum(above) / len(above)
        below_mean = sum(below) / len(below)
        rank = (above_mean - below_mean, -abs(cutoff - V2_ENV_PRIOR_CUTOFF))
        if best is None or rank > best[0]:
            best = (rank, cutoff, above_mean, below_mean, len(above), len(below))
    if best is None:
        report["status"] = "INSUFFICIENT"
        return report
    _, cutoff, above_mean, below_mean, n_above, n_below = best
    report.update(
        status="HELD", cutoff=cutoff, aboveMean=round(above_mean, 4), belowMean=round(below_mean, 4),
        above=n_above, below=n_below,
    )
    return report


def _view_cost(report) -> dict | None:
    if not report:
        return None
    return {
        "month": report.get("month"), "frictionPct": report.get("frictionPct"), "floorPct": report.get("floorPct"),
        "measuredPct": report.get("measuredPct"), "source": report.get("source"), "applied": False,
    }


def _view_environment(report) -> dict | None:
    if not report:
        return None
    return {
        "quarter": report.get("quarter"), "status": report.get("status"), "cutoff": report.get("cutoff"),
        "priorCutoff": report.get("priorCutoff", V2_ENV_PRIOR_CUTOFF), "samples": report.get("samples"),
        "minSamples": report.get("minSamples", V2_ENV_MIN_SAMPLES), "applied": False,
    }


class Continuity:
    def __init__(self, ledger):
        self.ledger = ledger
        with ledger.lock, ledger.store.db:
            ledger.store.db.executescript(SCHEMA)

    def _load(self, table: str, row_id: str):
        row = self.ledger._one(f"SELECT payload FROM {table} WHERE id=?", (row_id,))
        if row is None:
            return None
        try:
            return json.loads(row["payload"])
        except (TypeError, json.JSONDecodeError):
            return None

    def _store(self, table: str, row_id: str, now_ms: int, payload: dict) -> dict:
        with self.ledger.lock, self.ledger.store.db:
            self.ledger.store.db.execute(
                f"INSERT OR IGNORE INTO {table}(id, at_ms, payload) VALUES(?,?,?)",
                (row_id, int(now_ms), _dump(payload)))
            saved = self._load(table, row_id)
        return payload if saved is None else saved

    def _latest(self, table: str):
        row = self.ledger._one(f"SELECT payload FROM {table} ORDER BY at_ms DESC, id DESC LIMIT 1")
        if row is None:
            return None
        try:
            return json.loads(row["payload"])
        except (TypeError, json.JSONDecodeError):
            return None

    def _cost(self, month: str, now_ms: int, fills) -> dict:
        row_id = f"cost:{month}"
        existing = self._load("cost_reports", row_id)
        if existing is not None:
            existing["applied"] = False
            return existing
        report = calibrate_month(_fills_for_month(fills, month), month)
        report.update(kind="COST", applied=False, floorHeld=True)
        return self._store("cost_reports", row_id, now_ms, report)

    def _bounds(self, quarter: str, now_ms: int, samples) -> dict:
        start, end = quarter_bounds(quarter)
        if int(now_ms) < end + HOLD_MS:
            return {
                "kind": "ENVIRONMENT", "quarter": quarter, "status": "OPEN", "applied": False,
                "priorCutoff": V2_ENV_PRIOR_CUTOFF, "cutoff": None, "frozen": False,
            }
        row_id = f"env:{quarter}"
        existing = self._load("environment_reports", row_id)
        if existing is not None:
            existing["applied"] = False
            return existing
        window = []
        for sample in samples or []:
            if not isinstance(sample, dict) or sample.get("closedMs") is None:
                continue
            closed = int(sample["closedMs"])
            if start <= closed < end:
                window.append(sample)
        report = estimate_environment(window)
        report.update(quarter=quarter, frozen=True, applied=False)
        return self._store("environment_reports", row_id, now_ms, report)

    def maintain(self, now_ms: int, fills=None, samples=None) -> dict:
        """Close the previous month and, after the hold, the previous quarter. No rule writes."""
        now_ms = int(now_ms)
        if fills is None:
            fills = self.ledger.cost_fills()
        if samples is None:
            samples = self.ledger.research_samples()
        return {
            "cost": self._cost(previous_month(now_ms), now_ms, fills),
            "environment": self._bounds(previous_quarter(now_ms), now_ms, samples),
            "weeklyHypothesesApplied": False,
        }

    def status(self, now_ms: int | None = None) -> dict:
        with self.ledger.lock:
            cost = self._latest("cost_reports")
            environment = self._latest("environment_reports")
            promotions = self.ledger.store.db.execute("SELECT count(*) FROM promotions").fetchone()[0]
        pending = None
        if now_ms is not None:
            quarter = previous_quarter(int(now_ms))
            _, end = quarter_bounds(quarter)
            if int(now_ms) < end + HOLD_MS:
                pending = quarter
        return {
            "cost": _view_cost(cost),
            "environment": _view_environment(environment),
            "environmentOpen": pending,
            "promotions": promotions,
            "weeklyHypothesesApplied": False,
        }
