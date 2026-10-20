import sys
from pathlib import Path
sys.path.insert(0, str(Path(r'd:\Crypto-Google\scratch')))
import sqlite3
import math
from datetime import datetime, timezone
from cryptog.kline_store import ResearchStore
from cryptog.baseline import evaluate_history, TRADE_MODULES, ALL_MODULES
from cryptog.engine_v2 import (
    MODULES, _tp2, build_context, detect_s1, detect_s2, detect_s3, detect_s4, detect_s5,
    environment, plan_issue, widen_stop
)

# Load data from stage-d-diagnostic.sqlite3 for the 6-month period (2026-04-20 to 2026-10-17)
# But note we need warmup before 2026-04-20 for 1D, 4H, 1H indicators
store = ResearchStore(r'data\stage-d-diagnostic.sqlite3')
data = {interval: store.klines("BTCUSDT", interval) for interval in ("1d", "4h", "1h", "15m", "5m")}
store.close()

# Filter to 6 months evaluation window
start_ts = int(datetime(2026, 4, 20, tzinfo=timezone.utc).timestamp() * 1000)
end_ts = int(datetime(2026, 10, 17, 23, 59, 59, tzinfo=timezone.utc).timestamp() * 1000)

print(f"Total bars in DB: 1d={len(data['1d'])}, 4h={len(data['4h'])}, 1h={len(data['1h'])}, 15m={len(data['15m'])}, 5m={len(data['5m'])}")

# Run evaluation on full data
report = evaluate_history(data)

print("\n=== OVERALL BASELINE REPORT ===")
for mod in ALL_MODULES:
    r = report['modules'][mod]
    print(f"Module {mod}:")
    print(f"  Candidates: {r.get('candidates')}")
    print(f"  Filled: {r.get('filled')}")
    if mod in TRADE_MODULES:
        oos = r.get('outOfSample', {})
        full = r.get('fullSample', {})
        print(f"  Full sample: trades={full.get('trades')}, winRate={full.get('winRate')}, exp={full.get('expectancyPct')}%, pf={full.get('profitFactor')}")
        print(f"  OOS sample: trades={oos.get('trades')}, winRate={oos.get('winRate')}, exp={oos.get('expectancyPct')}%, pf={oos.get('profitFactor')}")
        print(f"  Promotion pass: {r.get('promotion', {}).get('passes')}, gaps: {r.get('promotion', {}).get('gaps')}")
