import math
from typing import Dict, List, Optional, Tuple
from .clock import clock as time
from .config import *


def entry_contract(entry: float, tp1: float, stop: float, confirmation_ms: int,
                   breakout_level: Optional[float] = None, now_ms: Optional[int] = None,
                   reference_price: Optional[float] = None, min_net_tp1: float = MIN_NET_TP1,
                   invalidation_price: Optional[float] = None) -> Optional[dict]:
    """Bounded entry policy, not a fitted profitability claim. Keep original targets fixed."""
    now_ms = int(time.time() * 1000) if now_ms is None else now_ms
    if not all(math.isfinite(x) and x > 0 for x in (entry, tp1, stop, confirmation_ms)):
        return None
    if not stop < entry < tp1 or not 0 <= now_ms - confirmation_ms < SETUP_MAX_AGE_MS:
        return None
    if breakout_level is not None and (not math.isfinite(breakout_level) or entry <= breakout_level):
        return None
    reference_price = entry if reference_price is None else reference_price
    if not math.isfinite(reference_price) or reference_price <= 0:
        return None
    lower = max(max(entry, reference_price) * (1 - MAX_ENTRY_DEVIATION_PCT / 100), stop * (1 + 1e-8), breakout_level or 0, invalidation_price or 0)
    upper = min(min(entry, reference_price) * (1 + MAX_ENTRY_DEVIATION_PCT / 100),
                tp1 / (1 + (max(MIN_NET_TP1, min_net_tp1) + FRICTION_PCT) / 100),
                (tp1 + MIN_NET_RR * stop) / ((1 + FRICTION_PCT / 100) * (1 + MIN_NET_RR)))
    if not lower <= entry <= upper:
        return None
    return {"entry_min": lower, "entry_max": upper,
            "expires_at": min(now_ms + ALERT_TTL_MS, confirmation_ms + SETUP_MAX_AGE_MS),
            "breakout_level": breakout_level}



def entry_is_valid(sig: dict, quote: Optional[dict], now_ms: Optional[int] = None) -> bool:
    now_ms = int(time.time() * 1000) if now_ms is None else now_ms
    if not quote or quote.get("symbol") != "BTCUSDT":
        return False
    try:
        price = float(quote["ask_price"])
        age = now_ms - int(quote["timestamp"])
        level = sig.get("breakout_level")
        return (math.isfinite(price) and price > 0 and 0 <= age <= QUOTE_MAX_AGE_MS
                and sig["timestamp"] <= now_ms < sig["expires_at"]
                and sig["entry_min"] <= price <= sig["entry_max"]
                and sig["stop_loss"] < price < sig["target_tp1"]
                and (level is None or price > level)
                and price > sig.get("invalidation_price", sig["stop_loss"])
                and (sig["target_tp1"] / price - 1) * 100 - FRICTION_PCT >= sig.get("min_net_tp1", MIN_NET_TP1) - 1e-9
                and ((sig["target_tp1"] / price - 1) * 100 - FRICTION_PCT)
                / ((1 - sig["stop_loss"] / price) * 100 + FRICTION_PCT) >= MIN_NET_RR - 1e-9)
    except (KeyError, ValueError, TypeError, ZeroDivisionError):
        return False



def model_targets(model: str, entry: float, stop: float, resistances: List[float]) -> Optional[dict]:
    policy = TRADE_POLICIES.get(model)
    if not policy or not all(math.isfinite(x) and x > 0 for x in (entry, stop)) or stop >= entry:
        return None
    risk = (entry-stop)/entry*100
    if risk > policy['max_stop_pct']:
        return None  # Never tighten a structural stop to manufacture R:R.
    barriers = sorted({p for p in resistances if p is not None and math.isfinite(p) and p > entry})
    if not barriers:
        return None  # Including price discovery: no invented ATR target.
    targets = [math.floor(p*(1-TARGET_BUFFER_PCT/100)*100)/100 for p in barriers]
    cap = policy['max_net_target']
    if cap is not None:
        cap_price = math.floor(entry*(1+(cap+FRICTION_PCT)/100)*100)/100
        targets = [min(p, cap_price) for p in targets]  # Cap DOWN, never raise to the minimum.
    first = targets[0]
    second = targets[1] if len(targets) > 1 else first
    if not stop < entry < first <= second:
        return None
    gross = (first/entry-1)*100
    net = gross-FRICTION_PCT
    net_rr = net/(risk+FRICTION_PCT)
    if net < max(MIN_NET_TP1, policy['min_net_tp1']) - 1e-9 or net_rr < MIN_NET_RR - 1e-9:
        return None  # Do not skip the nearest resistance for a more appealing farther one.
    return {'sl': round(risk, 4), 'tp1': round(gross, 4), 'tp2': round((second/entry-1)*100, 4),
            'target_tp1': first, 'target_tp2': second, 'stop_loss': stop,
            'net_tp1': round(net, 4), 'net_tp2': round((second/entry-1)*100-FRICTION_PCT, 4),
            'net_rr': round(net_rr, 4), 'support': stop, 'kind': 'observed_resistance',
            'target_basis': '已确认局部高点/箱体中线等最近阻力前 0.05%；只向下限幅',
            'tp1_fraction': 1.0 if first == second else policy['tp1_fraction']}

