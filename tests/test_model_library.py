#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The model library keeps every alert and still settles a path when the user never taps close."""

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scratch"))

from remote_scanner_daemon import (
    LIBRARY_HORIZON_MS,
    apply_user_action,
    observe_model_price,
    read_track_status,
    record_model_alert,
    set_library_dir,
)


def main():
    tmp = tempfile.mkdtemp(prefix="cg-library-")
    set_library_dir(tmp)
    sig = {
        "symbol": "BTCUSDT",
        "strategy": "BURST_BREAKOUT",
        "strategy_name_zh": "突破",
        "confirmation_time": 1000,
        "timestamp": 1_000_000,
        "entry_price": 100.0,
        "target_tp1": 101.0,
        "target_tp2": 102.0,
        "stop_loss": 99.0,
        "profit_pct1": 1.0,
        "profit_pct2": 2.0,
        "stop_loss_pct": 1.0,
        "net_tp1": 0.89,
        "net_tp2": 1.89,
        "net_rr": 1.2,
        "risk_reward": 1.0,
        "rule_score": 70,
        "rule_score_breakdown": "test",
        "time_horizon": "15m - 12h",
        "volatility_level": "MEDIUM",
        "quantile_pct": 50,
        "structure_support": 99.0,
        "reason_zh": "test",
        "regime": "BULLISH",
        "hourly_rsi": 60,
    }
    alert_id = record_model_alert(sig)
    again = record_model_alert(sig)
    assert alert_id == again
    alerts = open(os.path.join(tmp, "alerts.jsonl"), encoding="utf-8").read().strip().splitlines()
    assert len(alerts) == 1

    observe_model_price(101.2, now_ms=1_000_000 + 60_000)
    status = read_track_status(alert_id)
    assert status["tp1Touched"] is True
    assert status["outcomeWritten"] is False
    assert not os.path.exists(os.path.join(tmp, "outcomes.jsonl"))

    observe_model_price(98.5, now_ms=1_000_000 + LIBRARY_HORIZON_MS + 1)
    outcome = json.loads(open(os.path.join(tmp, "outcomes.jsonl"), encoding="utf-8").read().strip())
    assert outcome["pathStatus"] == "HORIZON_12H_TP1_TOUCHED"
    assert outcome["userExitStatus"] == "ALERT_ONLY"
    assert outcome["tp1Touched"] is True
    assert outcome["slTouched"] is False

    missed = {
        **sig,
        "confirmation_time": 2000,
        "timestamp": 2_000_000,
    }
    missed_id = record_model_alert(missed)
    apply_user_action({
        "recordType": "SIM_BUY",
        "alertId": missed_id,
        "entryPrice": 100,
        "positionSize": 5000,
        "actedAtMs": 2_000_000,
    })
    observe_model_price(100.2, now_ms=2_000_000 + LIBRARY_HORIZON_MS + 5)
    rows = [json.loads(line) for line in open(os.path.join(tmp, "outcomes.jsonl"), encoding="utf-8") if line.strip()]
    missed_outcome = next(row for row in rows if row["alertId"] == missed_id)
    assert missed_outcome["userExitStatus"] == "SIM_OPEN_UNREPORTED"
    apply_user_action({
        "recordType": "BACKFILL_CLOSE",
        "alertId": missed_id,
        "exitPrice": 101.5,
        "entryPrice": 100,
        "positionSize": 5000,
        "actedAtMs": 2_500_000,
        "approximate": True,
        "note": "sold on binance earlier",
    })
    actions = [json.loads(line) for line in open(os.path.join(tmp, "user_actions.jsonl"), encoding="utf-8") if line.strip()]
    assert [row["recordType"] for row in actions] == ["SIM_BUY", "BACKFILL_CLOSE"]
    assert actions[-1]["exitPrice"] == 101.5
    print("model library tests passed")
    print(tmp)


if __name__ == "__main__":
    main()
