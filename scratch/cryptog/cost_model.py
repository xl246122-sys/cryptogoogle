"""Round-trip cost for short-horizon-v2.

The published floor is a hard constraint: calibration may raise the working
cost from real fills, and it may not lower it. BNB discount is off unless a
fill sample is explicitly marked as discounted.
"""
from typing import Optional, Sequence
import math

from .config import (
    V2_BNB_FRICTION_PCT, V2_FRICTION_PCT, V2_RISK_PER_TRADE_PCT, V2_SLIPPAGE_PCT, V2_TAKER_PCT,
)


def round_trip_pct(bnb_discount: bool = False) -> float:
    return V2_BNB_FRICTION_PCT if bnb_discount else V2_FRICTION_PCT


COST_VERSION = "cost-v2.1"


def cost_snapshot(at_ms: int, calibration: Optional[dict] = None) -> dict:
    """Immutable decision-time cost; discount requires explicit verified evidence.

    Reference-price simulation deducts the full cost on initial notional.
    Actual fills use cash flows instead. Spread is included in the aggregate
    slippage allowance, never added for a second time.
    """
    raw = calibration or {}
    applicable = raw.get("availableAtMs", at_ms) <= at_ms
    discounted = applicable and raw.get("bnbDiscount") is True and raw.get("bnbVerified") is True
    floor = round_trip_pct(discounted)
    measured = raw.get("frictionPct", floor) if applicable else floor
    if isinstance(measured, bool) or not isinstance(measured, (int, float)) or not math.isfinite(measured) or measured < 0:
        raise ValueError("INVALID_COST")
    return {"costModelVersion": COST_VERSION, "frictionPct": max(floor, measured), "floorPct": floor,
            "source": raw.get("source", "PRIOR") if applicable else "PRIOR", "applicableAtMs": at_ms,
            "availableAtMs": raw.get("availableAtMs", at_ms) if applicable else at_ms,
            "bnbDiscount": discounted, "bnbVerified": discounted,
            "executionModelVersion": "reference-price-v2.1", "feeTreatment": "IN_AGGREGATE_COST",
            "slippageTreatment": "IN_AGGREGATE_COST", "spreadTreatment": "IN_SLIPPAGE_ALLOWANCE",
            "priceTreatment": "REFERENCE_PRICE", "costBasis": "INITIAL_NOTIONAL"}


def signal_cost(signal: dict) -> dict:
    return cost_snapshot(int(signal.get("timestamp", signal.get("openedAt", 0))),
                         signal.get("cost_snapshot") or signal.get("costSnapshot") or
                         {"frictionPct": signal.get("friction_pct", V2_FRICTION_PCT)})


def position_fraction_pct(stop_distance_pct: float, friction_pct: Optional[float] = None,
                          risk_pct: float = V2_RISK_PER_TRADE_PCT) -> float:
    """Equity percent whose loss at the stop equals the risk budget.

    Quantity notionally = risk amount / (stop distance + cost). Both distances
    are in percent points, and the return value is percent of equity.
    """
    friction = V2_FRICTION_PCT if friction_pct is None else friction_pct
    denom = stop_distance_pct + friction
    if denom <= 0:
        return 0.0
    return min(100.0, risk_pct / denom * 100.0)


def _side_means(fills: Sequence[dict], side: str) -> Optional[dict]:
    rows = [row for row in fills if str(row.get("side", "")).upper() == side]
    if not rows:
        return None
    slips, fees = [], []
    for row in rows:
        quote, fill = float(row["quote"]), float(row["fill"])
        if quote <= 0 or fill <= 0:
            continue
        slips.append(abs(fill - quote) / quote * 100.0)
        fees.append(float(row.get("fee_pct") if row.get("fee_pct") is not None else V2_TAKER_PCT))
    if not slips:
        return None
    return {"slippagePct": sum(slips) / len(slips), "feePct": sum(fees) / len(fees), "n": len(slips)}


def calibrate(fills: Sequence[dict], bnb_discount: bool = False) -> dict:
    """Monthly (or any-window) cost from real fills.

    Each fill is {side, quote, fill, fee_pct}. fee_pct is percent of notional
    for that side (0.10 means 0.10%). Measured round trip is buy slippage +
    sell slippage + buy fee + sell fee. The working cost is the greater of
    that measurement and the published floor.
    """
    floor = round_trip_pct(bnb_discount)
    buy, sell = _side_means(fills, "BUY"), _side_means(fills, "SELL")
    if not buy or not sell:
        return {
            "frictionPct": floor, "floorPct": floor, "measuredPct": None, "source": "PRIOR",
            "bnbDiscount": bnb_discount, "buy": buy, "sell": sell,
            "published": {"takerPctPerSide": V2_TAKER_PCT, "slippagePctPerSide": V2_SLIPPAGE_PCT},
        }
    measured = buy["slippagePct"] + sell["slippagePct"] + buy["feePct"] + sell["feePct"]
    return {
        "frictionPct": max(floor, measured), "floorPct": floor, "measuredPct": round(measured, 6),
        "source": "FILLS" if measured > floor else "FLOOR", "bnbDiscount": bnb_discount,
        "buy": buy, "sell": sell,
        "published": {"takerPctPerSide": V2_TAKER_PCT, "slippagePctPerSide": V2_SLIPPAGE_PCT},
    }


def calibrate_month(fills: Sequence[dict], month: str, bnb_discount: bool = False) -> dict:
    chosen = [row for row in fills if row.get("month") == month]
    result = calibrate(chosen, bnb_discount)
    result["month"] = month
    return result
