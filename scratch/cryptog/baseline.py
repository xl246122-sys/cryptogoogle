"""S1–S5 baseline under the published short-horizon-v2 rules.

Each 15m close is judged once. A limit fills if a later 5m bar trades into the
entry band before the two-bar validity ends and before price runs 0.25% past
the band. The same module does not open again while that position is open.
Exits use the shared v2 ledger on 5m bars, and a bar that contains both the
stop and a target counts as a stop. S5 is recorded and never treated as a push.
"""
import json
import math
from bisect import bisect_left
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from .barriers import label_v2, r_multiple_take, triple_barrier
from .config import (
    V2_EMBARGO_MS, V2_ESCAPE_PCT, V2_FRICTION_PCT, V2_MAX_HOLD_MINUTES, V2_PAPER_NOTIONAL_USDT,
    V2_RECALL_MOVE_PCT, V2_RULE_VERSION,
)
from .engine_v2 import (
    MODULES, _tp2, build_context, detect_s1, detect_s2, detect_s3, detect_s4, detect_s5,
    environment, plan_issue, session_volumes, squeeze_threshold, widen_stop,
)
from .kline_store import ResearchStore
from .validation import assign_fold, early_recall, launch_decision, oos_cut, promotion_decision, summarize_returns, upward_waves

CST = timezone(timedelta(hours=8))
M5 = 300_000
M15 = 900_000
TRADE_MODULES = ("S1", "S2", "S3", "S4")
ALL_MODULES = TRADE_MODULES + ("S5",)


def limit_fill(setup: dict, bars: List[dict], valid_ms: int) -> Optional[dict]:
    """Buy limit across the entry band. A gap below the band is not a fill."""
    start = int(setup["trigger"]["close_time"])
    expires = start + valid_ms
    escape = max(setup["trigger"]["close"], setup["entry_max"]) * (1 + V2_ESCAPE_PCT / 100)
    for bar in bars:
        opened = int(bar["time"])
        if opened <= start:
            continue
        if opened > expires:
            break
        if bar["low"] <= setup["entry_max"] and bar["open"] >= setup["entry_min"]:
            price = min(bar["open"], setup["entry_max"])
            if setup["entry_min"] <= price <= setup["entry_max"]:
                return {"price": price, "time": opened}
        if bar["high"] > escape and bar["low"] > setup["entry_max"]:
            return None
    return None


def _window(bars: List[dict], times: List[int], now: int, count: int) -> List[dict]:
    end = bisect_left(times, now)
    return bars[max(0, end - count):end]


def _between(bars: List[dict], opens: List[int], start: int, end: int) -> List[dict]:
    left = bisect_left(opens, start)
    right = bisect_left(opens, end)
    return bars[left:right]


def _mean(values):
    return None if not values else sum(values) / len(values)


def _round(value):
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        return round(value, 6)
    return value


def _clean(summary: dict) -> dict:
    out = {key: _round(val) if not isinstance(val, dict) else val for key, val in summary.items()}
    if summary.get("profitFactor") == math.inf:
        out["profitFactor"] = None
        out["noLosses"] = True
    return out


def _empty(note: str, coverage: Optional[dict] = None) -> dict:
    return {
        "ruleVersion": V2_RULE_VERSION, "frictionPct": V2_FRICTION_PCT, "note": note,
        "paperNotionalUsdt": V2_PAPER_NOTIONAL_USDT, "coverage": coverage,
        "modules": {name: {"candidates": 0, "filled": 0} for name in ALL_MODULES},
    }


def evaluate_history(data: Dict[str, List[dict]], coverage: Optional[dict] = None) -> dict:
    d1, h4, h1 = data.get("1d") or [], data.get("4h") or [], data.get("1h") or []
    m15, m5 = data.get("15m") or [], data.get("5m") or []
    if len(m15) < 100 or len(m5) < 100 or len(d1) < 100:
        return _empty("K 线不足：日线至少 100 根，15 分钟和 5 分钟至少 100 根。", coverage)
    times = {"1d": [b["close_time"] for b in d1], "4h": [b["close_time"] for b in h4],
             "1h": [b["close_time"] for b in h1], "15m": [b["close_time"] for b in m15]}
    series = {"1d": d1, "4h": h4, "1h": h1, "15m": m15}
    m5_open = [b["time"] for b in m5]
    m5_close = [b["close_time"] for b in m5]
    m15_open = [b["time"] for b in m15]
    first_ms = None
    seen = set()
    busy_until = {name: 0 for name in TRADE_MODULES}
    candidates = {name: [] for name in ALL_MODULES}
    trades = {name: [] for name in TRADE_MODULES}
    diagnostic = {name: {multiple: [] for multiple in (0.5, 1.0, 2.0)} for name in TRADE_MODULES}

    def consider(module: str, setup: Optional[dict], bar: dict, ctx: dict, five_now: List[dict], fifteen_now: List[dict]):
        if not setup:
            return
        key = (module, setup.get("anchor_time") or int(bar["time"]), bool(setup.get("blocked")))
        if key in seen:
            return
        seen.add(key)
        trigger_ms = int(setup["trigger"]["close_time"]) if setup.get("trigger") else int(bar["close_time"])
        candidates[module].append({"time": trigger_ms, "blocked": bool(setup.get("blocked"))})
        if setup.get("blocked") or module not in MODULES:
            return
        setup = widen_stop(setup)
        if plan_issue(setup) or trigger_ms < busy_until[module]:
            return
        valid_ms = MODULES[module]["valid_ms"]
        filled = limit_fill(setup, _between(m5, m5_open, trigger_ms, trigger_ms + valid_ms + M5), valid_ms)
        if not filled:
            return
        tp2 = _tp2(setup, ctx)
        if tp2 <= filled["price"]:
            return
        horizon = filled["time"] + (V2_MAX_HOLD_MINUTES + 15) * 60_000
        path = _between(m5, m5_open, filled["time"], horizon)
        trail = _between(m15, m15_open, filled["time"] - 130 * M15, horizon)
        signal = {
            "alert_id": f"baseline_{module}_{setup['anchor_time']}", "module": module,
            "entry_price": filled["price"], "stop_loss": setup["stop"], "target_tp1": setup["tp1"],
            "target_tp2": tp2, "timestamp": filled["time"], "invalidation_price": setup["invalidation"],
            "reclaim_price": setup["entry_ref"],
        }
        labeled = label_v2(signal, path, trail if trail else fifteen_now)
        if labeled.get("pnlPct") is None:
            return
        busy_until[module] = int(labeled["closedAt"] or filled["time"])
        trades[module].append({
            "entryMs": filled["time"], "exitMs": labeled["closedAt"], "pnlPct": labeled["pnlPct"],
            "r": labeled["r"], "outcome": labeled["outcome"], "triggerMs": trigger_ms,
        })
        for multiple in (0.5, 1.0, 2.0):
            take = r_multiple_take(filled["price"], setup["stop"], multiple)
            if take is None:
                continue
            marked = triple_barrier(path, filled["price"], setup["stop"], take, filled["time"],
                                    V2_MAX_HOLD_MINUTES * 60_000)
            diagnostic[module][multiple].append(marked["netPct"])

    for index, bar in enumerate(m15):
        if index < 80:
            continue
        now = int(bar["close_time"]) + 1
        m15_ctx = _window(m15, times["15m"], now, 300)
        ctx = build_context(_window(d1, times["1d"], now, 300), _window(h4, times["4h"], now, 300),
                            _window(h1, times["1h"], now, 300), m15_ctx, now, with_squeeze=False)
        if ctx is None:
            continue
        if first_ms is None:
            first_ms = now
        env = environment(ctx, bar["close"], now)
        if env["gates"]["S4"]:
            ctx["m15SqueezeWidth"] = squeeze_threshold(m15_ctx)
        fifteen = m15[max(0, index - 120):index + 1]
        if env["gates"]["S1"]:
            consider("S1", detect_s1(fifteen, ctx, env), bar, ctx, [], fifteen)
        if env["gates"]["S2"]:
            consider("S2", detect_s2(fifteen, ctx, env), bar, ctx, [], fifteen)
        if env["gates"]["S4"]:
            consider("S4", detect_s4(fifteen, ctx, env), bar, ctx, [], fifteen)
        if env["gates"]["S3"]:
            nxt = int(m15[index + 1]["close_time"]) + 1 if index + 1 < len(m15) else now + M15
            for five_bar in _between(m5, m5_open, now, nxt):
                moment = int(five_bar["close_time"]) + 1
                five_tail = _window(m5, m5_close, moment, 80)
                fifteen_tail = _window(m15, times["15m"], moment, 80)
                consider("S3", detect_s3(five_tail, fifteen_tail, ctx, env), five_bar, ctx, five_tail, fifteen_tail)
        if index and index % 5000 == 0:
            print(f"baseline {index}/{len(m15)}", flush=True)

    s5_index = {int(bar["time"]): pos for pos, bar in enumerate(m15)}
    for item in session_volumes(m15):
        pos = s5_index.get(item["start"] + M15)
        if pos is None:
            continue
        found = detect_s5(m15[max(0, pos - 3000):pos + 1])
        if not found:
            continue
        entry_ms = int(found["trigger"]["close_time"])
        entry = found["features"]["windowClose"]
        forwards = {}
        for minutes in (30, 90, 360):
            future = _between(m5, m5_open, entry_ms, entry_ms + minutes * 60_000 + M5)
            if not future:
                continue
            exit_price = future[-1]["close"]
            forwards[str(minutes)] = (exit_price / entry - 1) * 100 - V2_FRICTION_PCT
        candidates["S5"].append({"time": entry_ms, "blocked": False, "forwardNetPct": forwards})

    start_ms = first_ms or int(m15[0]["time"])
    end_ms = int(m15[-1]["close_time"])
    cut = oos_cut(start_ms, end_ms)
    tradable = [bar for bar in m5 if bar["time"] >= start_ms]
    waves_15 = upward_waves(tradable, V2_RECALL_MOVE_PCT)
    waves_10 = upward_waves(tradable, 1.0)
    span_days = max((end_ms - start_ms) / 86_400_000, 1e-9)
    all_times = [row["time"] for name in ALL_MODULES for row in candidates[name]]
    modules = {}
    for name in ALL_MODULES:
        rows = candidates[name]
        if name == "S5":
            nets = [row["forwardNetPct"].get("360") for row in rows if row.get("forwardNetPct", {}).get("360") is not None]
            modules[name] = {
                "candidates": len(rows), "filled": 0, "push": False,
                "perDay": len(rows) / span_days,
                "forwardNetPct": {minutes: _mean([row["forwardNetPct"][minutes] for row in rows
                                                     if minutes in row.get("forwardNetPct", {})])
                                  for minutes in ("30", "90", "360")},
                "researchExpectancy360": None if not nets else sum(nets) / len(nets),
                "promotion": {"passes": False, "gaps": ["S5 只做研究，不进入交易级"]},
            }
            continue
        filled = trades[name]
        groups = {"IS": [], "OOS": [], "PURGED": [], "ALL": []}
        for trade in filled:
            fold = assign_fold(trade["entryMs"], trade["exitMs"], cut)
            groups[fold].append(trade["pnlPct"])
            groups["ALL"].append(trade["pnlPct"])
        oos_span = max(end_ms - cut, 1)
        is_span = max(cut - start_ms, 1)
        oos_raw = summarize_returns(groups["OOS"], oos_span, 1)
        oos = _clean(oos_raw)
        recall = early_recall(waves_15, [row["time"] for row in rows])
        modules[name] = {
            "candidates": len(rows),
            "blocked": sum(1 for row in rows if row["blocked"]),
            "filled": len(filled),
            "candidatesPerDay": len(rows) / span_days,
            "inSample": _clean(summarize_returns(groups["IS"], is_span, 1)),
            "outOfSample": oos,
            "all": _clean(summarize_returns(groups["ALL"], end_ms - start_ms, 1)),
            "purged": len(groups["PURGED"]),
            "diagnosticNetPct": {str(multiple): _round(_mean(diagnostic[name][multiple])) for multiple in (0.5, 1.0, 2.0)},
            "promotion": promotion_decision(oos_raw, n_trials=1, pbo_value=None),
            "launch": launch_decision(oos_raw, recall),
        }
    return {
        "ruleVersion": V2_RULE_VERSION,
        "frictionPct": V2_FRICTION_PCT,
        "nTrials": 1,
        "paperNotionalUsdt": V2_PAPER_NOTIONAL_USDT,
        "exitResolution": "5m",
        "fill": "限价在进场区间内，有效期为触发周期 2 根 K 线；价格离开区间上方 0.25% 不成交",
        "split": "样本跨度不少于 200 天时，最后 122 天为样本外，其前 6 小时为禁区；更短的样本用前 2/3 与后 1/3",
        "startMs": start_ms, "endMs": end_ms, "cutMs": cut,
        "start": datetime.fromtimestamp(start_ms / 1000, CST).isoformat(),
        "end": datetime.fromtimestamp(end_ms / 1000, CST).isoformat(),
        "waves": {
            "atLeast1Pct": len(waves_10), "perDay1Pct": len(waves_10) / span_days,
            "atLeast1_5Pct": len(waves_15), "perDay1_5Pct": len(waves_15) / span_days,
            "recall1_5Early": early_recall(waves_15, all_times),
        },
        "coverage": coverage,
        "modules": modules,
        "note": "单一先验参数，nTrials=1，因此 DSR 的「试参超过 20 组」门槛不适用，PBO 不计算。诊断用的 0.5R/1R/2R 不参与选择。",
    }


def render_markdown(report: dict) -> str:
    if "waves" not in report:
        return f"# short-horizon-v2 基线报告\n\n{report.get('note', '无数据')}\n"
    lines = [
        "# short-horizon-v2 基线报告",
        "",
        f"- 规则版本：`{report['ruleVersion']}`",
        f"- 区间：{report['start']} 至 {report['end']}",
        f"- 来回成本：{report['frictionPct']}%",
        f"- 成交假设：{report['fill']}",
        f"- 出场：{report['exitResolution']} K 线，同一根内先算止损",
        f"- 划分：{report['split']}",
        f"- 试参组数：{report['nTrials']}。{report['note']}",
        f"- 6 小时内 ≥1% 的上涨段：{report['waves']['atLeast1Pct']} 段，约 {report['waves']['perDay1Pct']:.2f} 段/天",
        f"- ≥1.5% 上涨段：{report['waves']['atLeast1_5Pct']} 段；前 1/3 段内出现任一候选的比例："
        f"{_pct(report['waves']['recall1_5Early'])}",
        "",
        "模拟仓名义 500 USDT 属于下一阶段的孪生账本，本报告不开仓。",
        "衍生品只在急跌收复上加分，不单独决定方向。资金费率、持仓量和主动买卖比从守护进程开始累积；这次价格基线没有把它们算进成交。",
        "",
        "| 形态 | 候选 | 成交 | 样本外笔数 | 样本外胜率 | 样本外期望值 | 样本外盈利因子 | 晋级 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for name, row in report["modules"].items():
        if name == "S5":
            exp = row.get("researchExpectancy360")
            lines.append(f"| S5 研究 | {row['candidates']} | — | — | — | 360 分钟 {_num(exp)}% | — | 不推送 |")
            continue
        oos = row["outOfSample"]
        lines.append(
            f"| {name} | {row['candidates']} | {row['filled']} | {oos['trades']} | {_pct(oos['winRate'])} | "
            f"{_num(oos['expectancyPct'])}% | {_num(oos['profitFactor'])} | "
            f"{'通过' if row['promotion']['passes'] else '未通过'} |"
        )
    lines.append("")
    for name, row in report["modules"].items():
        gaps = row.get("promotion", {}).get("gaps") or []
        if gaps:
            lines.append(f"- {name}：" + "；".join(gaps))
    lines.append("")
    lines.append("未通过晋级门槛的形态保持「观察级·未验证」。本报告不调整任何参数。")
    return "\n".join(lines) + "\n"


def _pct(value) -> str:
    return "—" if value is None else f"{value * 100:.1f}%"


def _num(value) -> str:
    return "—" if value is None else f"{value:.3f}"


def write_report(report: dict, out_dir: str) -> dict:
    from pathlib import Path
    dest = Path(out_dir)
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "short-horizon-v2.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (dest / "short-horizon-v2.md").write_text(render_markdown(report), encoding="utf-8")
    return report


def load_library(path: str) -> dict:
    store = ResearchStore(path)
    try:
        data = {interval: store.klines("BTCUSDT", interval) for interval in ("1d", "4h", "1h", "15m", "5m")}
        coverage = store.coverage()
    finally:
        store.close()
    return {"data": data, "coverage": coverage}


def main(argv=None):
    import argparse
    import sys
    import time
    from pathlib import Path

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="Build the short-horizon-v2 baseline report")
    parser.add_argument("--db", default="data/research.sqlite3")
    parser.add_argument("--out", default="model_library/baseline")
    parser.add_argument("--backfill", action="store_true")
    parser.add_argument("--intervals", default="1d,4h,1h,15m,5m,1m")
    args = parser.parse_args(argv)
    if args.backfill:
        from .kline_store import backfill
        Path(args.db).parent.mkdir(parents=True, exist_ok=True)
        end = int(time.time() * 1000)
        start = end - 730 * 24 * 3600 * 1000
        store = ResearchStore(args.db)
        try:
            print(backfill(store, start, end, [item for item in args.intervals.split(",") if item]), flush=True)
        finally:
            store.close()
    loaded = load_library(args.db)
    report = evaluate_history(loaded["data"], loaded["coverage"])
    write_report(report, args.out)
    print(render_markdown(report))


if __name__ == "__main__":
    main()
