import sys
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.stderr.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, str(Path(r'd:\Crypto-Google\scratch')))
import json
import math
from datetime import datetime, timezone
import numpy as np
from cryptog.kline_store import ResearchStore
from cryptog.baseline import evaluate_history, TRADE_MODULES, ALL_MODULES
from cryptog.engine_v2 import (
    MODULES, _tp2, build_context, detect_s1, detect_s2, detect_s3, detect_s4, detect_s5,
    environment, plan_issue, widen_stop
)

store = ResearchStore(r'data\stage-d-diagnostic.sqlite3')
# We need data from ~2026-01 to 2026-10 to give enough warmup for 2026-04-20
raw_data = {interval: store.klines("BTCUSDT", interval) for interval in ("1d", "4h", "1h", "15m", "5m")}
store.close()

# Start of 6 months: 2026-04-20
start_6m_ts = int(datetime(2026, 4, 20, tzinfo=timezone.utc).timestamp() * 1000)
end_6m_ts = int(datetime(2026, 10, 17, 23, 59, 59, tzinfo=timezone.utc).timestamp() * 1000)

# Filter 1d bars for 6m stats
bars_1d = [b for b in raw_data['1d'] if start_6m_ts <= b['time'] <= end_6m_ts]
bars_15m = [b for b in raw_data['15m'] if start_6m_ts <= b['time'] <= end_6m_ts]

print("=== 6-MONTH BTC MARKET DATA SUMMARY ===")
print(f"Period: 2026-04-20 to 2026-10-17 ({len(bars_1d)} days)")
print(f"1D bars: {len(bars_1d)}, 15M bars: {len(bars_15m)}")
p_start = bars_1d[0]['open']
p_end = bars_1d[-1]['close']
p_min = min(b['low'] for b in bars_1d)
p_max = max(b['high'] for b in bars_1d)
print(f"Open: ${p_start:,.2f}, Close: ${p_end:,.2f}, Change: {((p_end/p_start)-1)*100:+.2f}%")
print(f"Low: ${p_min:,.2f}, High: ${p_max:,.2f}, Range: {((p_max/p_min)-1)*100:.2f}%")

# Run full baseline evaluation (which evaluates all data up to 2026-10-17)
report = evaluate_history(raw_data)

print("\n=== S1-S5 BASELINE RESULTS (HISTORICAL) ===")
summary_out = {}
for mod in ALL_MODULES:
    r = report['modules'][mod]
    summary_out[mod] = {
        'candidates': r.get('candidates'),
        'filled': r.get('filled'),
        'outOfSample': r.get('outOfSample'),
        'fullSample': r.get('fullSample'),
        'promotion': r.get('promotion')
    }
    print(f"\n--- Module {mod} ---")
    print(f"Candidates: {r.get('candidates')}, Filled: {r.get('filled')}")
    if mod in TRADE_MODULES:
        fs = r.get('fullSample') or {}
        oos = r.get('outOfSample') or {}
        print(f"Full Sample: Trades={fs.get('trades')}, WinRate={fs.get('winRate')}, Exp={fs.get('expectancyPct')}%, PF={fs.get('profitFactor')}")
        print(f"Out of Sample: Trades={oos.get('trades')}, WinRate={oos.get('winRate')}, Exp={oos.get('expectancyPct')}%, PF={oos.get('profitFactor')}")
        prom = r.get('promotion') or {}
        print(f"Passes Promotion: {prom.get('passes')}")
        if prom.get('gaps'):
            print("Gaps:", "; ".join(prom['gaps']))
    elif mod == 'S5':
        print(f"S5 360m Exp: {r.get('researchExpectancy360')}%")

Path("scratch/audit_report_data.json").write_text(json.dumps(summary_out, indent=2, ensure_ascii=False), encoding='utf-8')
print("\nSaved summary to scratch/audit_report_data.json")
