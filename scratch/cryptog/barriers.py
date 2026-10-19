"""Triple-barrier labels and the v2 exit path.

A bar that touches the stop and the target in an unknown order is a stop.
The v2 path reuses the tracker's leg accounting so research and the live
shadow ledger share one exit definition: TP1 sells half, the stop moves to
breakeven plus cost, the rest trails, with the 90-minute and 6-hour clocks.
"""
from typing import List, Optional, Sequence

from .config import V2_FRICTION_PCT, V2_MAX_HOLD_MINUTES
from .v2_tracker import advance, open_state


def triple_barrier(bars: Sequence[dict], entry: float, stop: float, take: float, start_ms: int,
                   vertical_ms: int, friction_pct: float = V2_FRICTION_PCT) -> dict:
    """One position, one target. Label is 1, -1, or 0 for the vertical barrier."""
    mfe = mae = 0.0
    exit_price = entry
    exit_ms = start_ms + vertical_ms
    barrier = "VERTICAL"
    uncertain = False
    for bar in bars:
        if int(bar["close_time"]) < start_ms:
            continue
        end = int(bar["close_time"]) + 1
        if int(bar["time"]) < start_ms:
            uncertain = True
        if end > start_ms + vertical_ms:
            uncertain = True
            exit_ms = start_ms + vertical_ms
            break
        mfe = max(mfe, (bar["high"] / entry - 1) * 100)
        mae = min(mae, (bar["low"] / entry - 1) * 100)
        end = int(bar["close_time"]) + 1
        if bar["low"] <= stop:
            exit_price, exit_ms, barrier = stop, end, "STOP"
            break
        if bar["high"] >= take:
            exit_price, exit_ms, barrier = take, end, "TAKE"
            break
        exit_price = bar["close"]
        exit_ms = end
        if end >= start_ms + vertical_ms:
            barrier = "VERTICAL"
            break
    gross = (exit_price / entry - 1) * 100
    net = gross - friction_pct
    return {
        "label": 1 if barrier == "TAKE" else (-1 if barrier == "STOP" else 0),
        "barrier": barrier, "entry": entry, "exit": exit_price, "exitMs": exit_ms,
        "grossPct": gross, "netPct": net, "mfePct": mfe, "maePct": mae,
        "holdMinutes": max(0, (exit_ms - start_ms) / 60_000),
        "pathStatus": "PATH_UNCERTAIN" if uncertain else "BAR_CONSERVATIVE",
        "eligibleForValidation": not uncertain,
    }


def label_v2(signal: dict, path: Sequence[dict], m15: Sequence[dict]) -> dict:
    """Settle one filled v2 signal on the supplied closed bars."""
    state = open_state(signal)
    advance(state, list(path), list(m15))
    if state["phase"] != "CLOSED":
        last = [bar for bar in path if int(bar["time"]) >= state["fromBar"]]
        if last and state["remaining"] > 0:
            from .v2_tracker import _close, _leg, _uncertain
            _uncertain(state, "SAMPLE_END")
            end = int(last[-1]["close_time"]) + 1
            _leg(state, state["remaining"], last[-1]["close"], end, "SAMPLE_END")
            _close(state, end, "SAMPLE_END")
    tp1_at = state.get("tp1At")
    return {
        **state,
        "outcome": state.get("outcome"), "pnlPct": state.get("pnlPct"), "r": state.get("r"),
        "mfePct": state.get("mfePct"), "maePct": state.get("maePct"),
        "openedAt": state["openedAt"], "closedAt": state.get("closedAt"),
        "tp1Minutes": None if not tp1_at else (tp1_at - state["openedAt"]) / 60_000,
        "holdMinutes": None if not state.get("closedAt") else (state["closedAt"] - state["openedAt"]) / 60_000,
        "legs": state.get("legs"), "phase": state["phase"],
        "verticalMinutes": V2_MAX_HOLD_MINUTES,
        **{k: state.get(k) for k in ("executionModelVersion", "costSnapshot", "pathStatus", "uncertaintyReasons", "eligibleForValidation", "conservativePnlPct")},
    }


def r_multiple_take(entry: float, stop: float, multiple: float) -> Optional[float]:
    risk = entry - stop
    if risk <= 0:
        return None
    return entry + multiple * risk
