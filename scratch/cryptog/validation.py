"""Walk-forward split, deflated Sharpe ratio, and probability of backtest overfitting.

These are the measurement tools for the promotion gates. They do not change a
live threshold. A single published rule set has one trial, so the DSR gate
(which applies only after more than 20 trials) is reported and not forced.
"""
import math
import random
from typing import List, Optional, Sequence

from .config import (
    V2_EMBARGO_MS, V2_FRICTION_PCT, V2_LAUNCH_MIN_WIN_RATE, V2_MAX_HOLD_MINUTES, V2_OOS_MS,
    V2_PROMOTE_DSR_TRIALS, V2_PROMOTE_MAX_PBO, V2_PROMOTE_MAX_PER_DAY, V2_PROMOTE_MIN_DSR,
    V2_PROMOTE_MIN_EXPECTANCY, V2_PROMOTE_MIN_PER_DAY, V2_PROMOTE_MIN_PROFIT_FACTOR,
    V2_PROMOTE_MIN_TRADES, V2_PROMOTE_MIN_WIN_RATE, V2_RECALL_EARLY_FRACTION, V2_RECALL_MIN,
    V2_STOP_MAX_PCT,
)

_EULER = 0.5772156649015329
_PPF_A = (-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
          1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00)
_PPF_B = (-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
          6.680131188771972e+01, -1.328068155288572e+01)
_PPF_C = (-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
          -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00)
_PPF_D = (7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00, 3.754408661907416e+00)


def norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def norm_ppf(p: float) -> float:
    """Acklam's inverse normal. Used by the expected-maximum Sharpe."""
    if not 0.0 < p < 1.0:
        raise ValueError("probability out of range")
    plow, phigh = 0.02425, 1.0 - 0.02425
    if p < plow:
        q = math.sqrt(-2.0 * math.log(p))
        return (((((_PPF_C[0] * q + _PPF_C[1]) * q + _PPF_C[2]) * q + _PPF_C[3]) * q + _PPF_C[4]) * q + _PPF_C[5]) / \
            ((((_PPF_D[0] * q + _PPF_D[1]) * q + _PPF_D[2]) * q + _PPF_D[3]) * q + 1.0)
    if p > phigh:
        q = math.sqrt(-2.0 * math.log(1.0 - p))
        return -(((((_PPF_C[0] * q + _PPF_C[1]) * q + _PPF_C[2]) * q + _PPF_C[3]) * q + _PPF_C[4]) * q + _PPF_C[5]) / \
            ((((_PPF_D[0] * q + _PPF_D[1]) * q + _PPF_D[2]) * q + _PPF_D[3]) * q + 1.0)
    q = p - 0.5
    r = q * q
    return (((((_PPF_A[0] * r + _PPF_A[1]) * r + _PPF_A[2]) * r + _PPF_A[3]) * r + _PPF_A[4]) * r + _PPF_A[5]) * q / \
        (((((_PPF_B[0] * r + _PPF_B[1]) * r + _PPF_B[2]) * r + _PPF_B[3]) * r + _PPF_B[4]) * r + 1.0)


def moments(values: Sequence[float]):
    n = len(values)
    if n == 0:
        return None, None, 0.0, 3.0
    mean = sum(values) / n
    if n < 2:
        return mean, None, 0.0, 3.0
    centered = [x - mean for x in values]
    var = sum(x * x for x in centered) / (n - 1)
    std = math.sqrt(var) if var > 0 else None
    c2 = sum(x * x for x in centered) / n
    if c2 <= 0 or n < 4:
        return mean, std, 0.0, 3.0
    c3 = sum(x ** 3 for x in centered) / n
    c4 = sum(x ** 4 for x in centered) / n
    return mean, std, c3 / (c2 ** 1.5), c4 / (c2 ** 2)


def sharpe_ratio(values: Sequence[float]) -> Optional[float]:
    mean, std, _, _ = moments(values)
    if mean is None or not std:
        return None
    return mean / std


def expected_maximum_sharpe(n_trials: int, variance: float = 1.0) -> float:
    """Expected maximum Sharpe under the null when n_trials independent rules were tried."""
    if n_trials <= 1:
        return 0.0
    p1 = 1.0 - 1.0 / n_trials
    p2 = 1.0 - 1.0 / (n_trials * math.e)
    return math.sqrt(variance) * ((1.0 - _EULER) * norm_ppf(p1) + _EULER * norm_ppf(p2))


def deflated_sharpe(values: Sequence[float], n_trials: int = 1, sr_variance: float = 1.0) -> Optional[float]:
    """Probability the observed Sharpe beats the selection-adjusted null."""
    if len(values) < 2:
        return None
    observed = sharpe_ratio(values)
    if observed is None:
        return None
    _, _, skew, kurt = moments(values)
    sr0 = expected_maximum_sharpe(n_trials, sr_variance)
    denom = math.sqrt(max(1e-12, 1.0 - skew * observed + ((kurt - 1.0) / 4.0) * observed * observed))
    z = (observed - sr0) * math.sqrt(len(values) - 1) / denom
    return norm_cdf(z)


def bootstrap_lower(values: Sequence[float], iterations: int = 2000, alpha: float = 0.05, seed: int = 20261017) -> Optional[float]:
    if not values:
        return None
    rng = random.Random(seed)
    n = len(values)
    means = []
    for _ in range(iterations):
        total = 0.0
        for _ in range(n):
            total += values[rng.randrange(n)]
        means.append(total / n)
    means.sort()
    return means[int(alpha * (iterations - 1))]


def pbo(columns: Sequence[Sequence[float]], slices: int = 8) -> Optional[float]:
    """CSCV probability of backtest overfitting.

    columns are equal-length return series, one per tried rule. Returns the
    fraction of splits whose in-sample winner lands in the worse half out of sample.
    """
    from itertools import combinations

    if slices < 2 or slices % 2 or not columns or len(columns) < 2:
        return None
    width = len(columns[0])
    if width < slices or any(len(col) != width for col in columns):
        return None
    if any(not isinstance(v, (int, float)) or not math.isfinite(v) for col in columns for v in col):
        return None
    if len({tuple(col) for col in columns}) < 2:
        return None
    size = width // slices
    if size < 2:
        return None
    groups = []
    for index in range(slices):
        start, stop = index * width // slices, (index + 1) * width // slices
        groups.append([col[start:stop] for col in columns])
    worse = total = 0
    half = slices // 2
    for chosen in combinations(range(slices), half):
        chosen_set = set(chosen)
        is_parts = [[] for _ in columns]
        oos_parts = [[] for _ in columns]
        for index, group in enumerate(groups):
            target = is_parts if index in chosen_set else oos_parts
            for strategy, piece in enumerate(group):
                target[strategy].extend(piece)
        is_scores = [sharpe_ratio(part) for part in is_parts]
        oos_scores = [sharpe_ratio(part) for part in oos_parts]
        if any(score is None for score in is_scores + oos_scores):
            continue
        winners = [i for i, score in enumerate(is_scores) if score == max(is_scores)]
        median = (len(columns) + 1) / 2.0
        for best in winners:
            rank = 1 + sum(score > oos_scores[best] for score in oos_scores)
            rank += (sum(score == oos_scores[best] for score in oos_scores)-1)/2
            worse += (1 if rank > median else .5 if rank == median else 0)/len(winners)
        total += 1
    return None if total == 0 else worse / total


def oos_cut(start_ms: int, end_ms: int) -> int:
    """Last four months when the sample is long enough; otherwise the last third."""
    span = end_ms - start_ms
    if span >= 200 * 24 * 3600 * 1000:
        return end_ms - V2_OOS_MS
    return int(start_ms + span * (8 / 12))


def assign_fold(entry_ms: int, exit_ms: Optional[int], cut_ms: int, embargo_ms: int = V2_EMBARGO_MS) -> str:
    """Purged walk-forward label. Trades whose outcome overlaps the embargo are neither fold."""
    if entry_ms >= cut_ms:
        return "OOS"
    if exit_ms is None or exit_ms > cut_ms - embargo_ms:
        return "PURGED"
    return "IS"


def summarize_returns(values: Sequence[float], span_ms: int, n_trials: int = 1) -> dict:
    pnls = list(values)
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    days = max(span_ms / 86_400_000, 1e-9)
    mean, _, _, _ = moments(pnls)
    if not losses:
        factor = None if not wins else math.inf
    else:
        factor = sum(wins) / abs(sum(losses))
    return {
        "trades": len(pnls),
        "winRate": None if not pnls else len(wins) / len(pnls),
        "expectancyPct": mean,
        "profitFactor": factor,
        "bootstrapLower95": bootstrap_lower(pnls),
        "sharpe": sharpe_ratio(pnls),
        "dsr": deflated_sharpe(pnls, n_trials),
        "perDay": len(pnls) / days,
        "nTrials": n_trials,
    }


def promotion_decision(summary: dict, n_trials: int = 1, pbo_value: Optional[float] = None) -> dict:
    """Section 9 gates. DSR applies once more than 20 configurations were tried."""
    gaps = []
    for key in ('trades', 'expectancyPct', 'bootstrapLower95', 'winRate', 'profitFactor', 'perDay', 'dsr'):
        value = summary.get(key)
        if value is not None and (not isinstance(value, (int, float)) or math.isnan(value)
                                  or (not math.isfinite(value) and not (key == 'profitFactor' and value == math.inf))):
            gaps.append('无效统计值: ' + key)
    if pbo_value is not None and (not isinstance(pbo_value, (int, float)) or not math.isfinite(pbo_value) or not 0 <= pbo_value <= 1):
        gaps.append('无效 PBO')
    if not isinstance(n_trials, int) or isinstance(n_trials, bool) or n_trials < 1:
        gaps.append('无效试验数量')
    if gaps:
        return {'passes': False, 'gaps': gaps, 'nTrials': n_trials, 'pbo': None}
    trades = summary.get("trades") or 0
    if trades < V2_PROMOTE_MIN_TRADES:
        gaps.append(f"样本外交易数 {trades} < {V2_PROMOTE_MIN_TRADES}")
    expectancy = summary.get("expectancyPct")
    if expectancy is None or expectancy < V2_PROMOTE_MIN_EXPECTANCY:
        shown = "无" if expectancy is None else f"{expectancy:.4f}%"
        gaps.append(f"扣费后期望值 {shown} < {V2_PROMOTE_MIN_EXPECTANCY:.2f}%")
    lower = summary.get("bootstrapLower95")
    if lower is None or lower <= 0:
        gaps.append("自助法 95% 下限未大于 0")
    win_rate = summary.get("winRate")
    if win_rate is None or win_rate < V2_PROMOTE_MIN_WIN_RATE:
        gaps.append(f"胜率低于 {V2_PROMOTE_MIN_WIN_RATE:.0%}")
    factor = summary.get("profitFactor")
    if factor is None or factor < V2_PROMOTE_MIN_PROFIT_FACTOR:
        gaps.append(f"盈利因子低于 {V2_PROMOTE_MIN_PROFIT_FACTOR:.2f}")
    if n_trials > V2_PROMOTE_DSR_TRIALS:
        dsr = summary.get("dsr")
        if dsr is None or dsr <= V2_PROMOTE_MIN_DSR:
            gaps.append(f"试参 {n_trials} 组时 DSR 未大于 {V2_PROMOTE_MIN_DSR:.2f}")
    if pbo_value is None or pbo_value >= V2_PROMOTE_MAX_PBO:
        shown = "缺失" if pbo_value is None else f"{pbo_value:.2f}"
        gaps.append(f"PBO {shown} 未低于 {V2_PROMOTE_MAX_PBO:.2f}")
    per_day = summary.get("perDay")
    if per_day is None or per_day < V2_PROMOTE_MIN_PER_DAY or per_day > V2_PROMOTE_MAX_PER_DAY:
        gaps.append(f"交易级频率不在 {V2_PROMOTE_MIN_PER_DAY:.1f}–{V2_PROMOTE_MAX_PER_DAY:.0f} 条/天")
    return {"passes": not gaps, "gaps": gaps, "nTrials": n_trials, "pbo": pbo_value}


def unlearnable_gaps(params: dict) -> List[str]:
    """Hard constraints learning is not allowed to move."""
    gaps = []
    if params.get("symbol", "BTCUSDT") != "BTCUSDT":
        gaps.append("只做 BTC")
    if params.get("side", "BUY") != "BUY":
        gaps.append("只做多")
    if params.get("aiWritesPrices"):
        gaps.append("AI 不写价格")
    floor = V2_FRICTION_PCT if not params.get("bnbDiscount") else 0.19
    if float(params.get("frictionPct", floor)) < floor - 1e-9:
        gaps.append("成本下限")
    if float(params.get("stopPct", 0)) > V2_STOP_MAX_PCT + 1e-9:
        gaps.append("止损 ≤ 1.2%")
    if int(params.get("holdMinutes", 0)) > V2_MAX_HOLD_MINUTES:
        gaps.append("持有 ≤ 6 小时")
    if params.get("breakerDisabled"):
        gaps.append("熔断")
    return gaps


def upward_waves(bars: Sequence[dict], min_pct: float, max_ms: int = V2_MAX_HOLD_MINUTES * 60_000) -> List[dict]:
    """Greedy non-overlapping rises. The next wave starts at the previous peak."""
    waves = []
    index = 0
    count = len(bars)
    while index < count - 1:
        start = bars[index]
        limit = start["time"] + max_ms
        peak_i, peak = index, start["low"]
        cursor = index + 1
        while cursor < count and bars[cursor]["time"] <= limit:
            if bars[cursor]["high"] > peak:
                peak = bars[cursor]["high"]
                peak_i = cursor
            cursor += 1
        if peak_i > index and start["low"] > 0 and peak >= start["low"] * (1 + min_pct / 100):
            waves.append({
                "start": int(start["time"]), "end": int(bars[peak_i]["time"]),
                "low": start["low"], "high": peak, "risePct": (peak / start["low"] - 1) * 100,
            })
            index = peak_i
        else:
            index += 1
    return waves


def early_recall(waves: Sequence[dict], times: Sequence[int], fraction: float = V2_RECALL_EARLY_FRACTION) -> Optional[float]:
    """Share of waves that have a candidate in the first fraction of the move."""
    if not waves:
        return None
    ordered = sorted(int(t) for t in times)
    hits = 0
    for wave in waves:
        cutoff = wave["start"] + (wave["end"] - wave["start"]) * fraction
        if any(wave["start"] <= stamp <= cutoff for stamp in ordered):
            hits += 1
    return hits / len(waves)


def launch_decision(summary: dict, recall: Optional[float]) -> dict:
    """Section 10 acceptance. The five-second stop SLO is a live property, not a backtest number."""
    win_rate = summary.get("winRate")
    expectancy = summary.get("expectancyPct")
    checks = {
        "winRate": win_rate is not None and win_rate >= V2_LAUNCH_MIN_WIN_RATE,
        "expectancy": expectancy is not None and expectancy >= V2_PROMOTE_MIN_EXPECTANCY,
        "recall": recall is not None and recall >= V2_RECALL_MIN,
    }
    return {"passes": all(checks.values()), "checks": checks, "recall": recall,
            "stopAlert": "止损分类在每次盘口更新时执行，历史 K 线不能测量 5 秒延迟"}
