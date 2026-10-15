"""Offline audit probes. Only filesystem/Firebase paths are redirected in memory.
Synthetic cases reproduce code behavior; they are not backtest returns.
"""
import ast
import copy
import json
import pathlib
import runpy
import sys
import tempfile
import time
import types

ROOT = pathlib.Path(__file__).resolve().parents[1]
TMP = pathlib.Path(tempfile.mkdtemp(prefix="cryptog-audit-"))
tree = ast.parse((ROOT / "scratch/remote_scanner_daemon.py").read_text(encoding="utf-8"))
redirect = {"LOG_DIR": str(TMP / "logs"), "LIBRARY_DIR": str(TMP / "library"), "FCM_KEY_PATH": str(TMP / "absent-key.json")}
for node in tree.body:
    if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
        if node.targets[0].id in redirect:
            node.value = ast.Constant(redirect[node.targets[0].id])
ast.fix_missing_locations(tree)
m = types.ModuleType("remote_scanner_daemon")
m.__file__ = str(ROOT / "scratch/remote_scanner_daemon.py")
sys.modules[m.__name__] = m
# Network is deliberately unavailable to these offline cases.
class OfflineSession:
    def __init__(self):
        self.headers = {}
    def get(self, *args, **kwargs):
        raise AssertionError("Network access is forbidden in offline audit")
requests_stub = types.ModuleType("requests")
requests_stub.Session = OfflineSession
sys.modules["requests"] = requests_stub
exec(compile(tree, m.__file__, "exec"), m.__dict__)

for name in ("test_remote_scanner.py", "test_model_library.py"):
    print("EXISTING SUITE", name)
    try:
        runpy.run_path(str(ROOT / "tests" / name), run_name="__main__")
    except SystemExit as e:
        print("SUITE EXIT", e.code)

now = int(time.time() * 1000)
def series(count, step, low=99.8, high=100.8):
    return [dict(time=now-(count-i)*step, close_time=now-(count-i-1)*step-1,
                 open=100.2 if i%2 else 100.3, close=100.3 if i%2 else 100.2,
                 high=high, low=low, volume=100., taker_buy_base=60., is_closed=True)
            for i in range(count)]
micro=series(48,60000,100.,100.5)
hourly=series(48,3600000)
regime=series(96,900000)
five=series(48,300000,100.,100.6)
five[-1].update(open=100.2,close=101.,high=101.05,low=100.,volume=200.,taker_buy_base=120.)
ticker=dict(symbol="BTCUSDT",price=100.4,change24h=0.,high24h=101.05,low24h=99.8)
book=dict(is_valid=True,spread=.01,imbalance=.1,bid_vol=110.,ask_vol=90.)
macro=dict(trend="BULLISH",is_bearish=False,is_strongly_bearish=False,ma20=100.,rsi=60.)
results={}
sig=m.scan_symbol("BTCUSDT",ticker,macro,micro,book,hourly,regime,five)
results["breakout_already_below_prior_high"]={"prior":100.6,"entry":ticker["price"],"strategy":sig and sig["strategy"]}
weak=copy.deepcopy(five)
weak[-1]["taker_buy_base"]=20.
sig2=m.scan_symbol("BTCUSDT",ticker,macro,micro,book,hourly,regime,weak)
results["fallback_bypasses_taker_gate"]={"strict_breakout":m._closed_breakout(weak,regime),"taker_ratio":.1,"strategy":sig2 and sig2["strategy"],"stop":sig2 and sig2["stop_loss"],"signal_candle_low":100.}
stale=copy.deepcopy(micro)
for c in stale:
    c["time"]-=86400000
    c["close_time"]-=86400000
results["day_old_micro_quality_gate"]=m.validate_market_data_quality(stale,ticker,book,hourly)
results["atr_target_below_user_profit_band"]=m.atr_horizon_targets(100.,.1,99.8)
results["near_resistance_blocks_structure_but_atr_passes"]={"structure":m.measured_targets(100.,99.8,[100.1,101.]),"atr":m.atr_horizon_targets(100.,.1,99.8)}

# Reuse the suite's immutable signal fixture, in a new isolated library.
fixture=runpy.run_path(str(ROOT / "tests/test_model_library.py"))
sample=dict(symbol="BTCUSDT",strategy="BURST_BREAKOUT",confirmation_time=42,timestamp=1000000,
            entry_price=100.,target_tp1=101.,target_tp2=102.,stop_loss=99.)
m.set_library_dir(str(TMP/"horizon"))
aid=m.record_model_alert(sample)
m.observe_model_price(100.,1000000+m.LIBRARY_HORIZON_MS-1)
m.observe_model_price(103.,1000000+m.LIBRARY_HORIZON_MS+3600000)
results["price_after_13h_counted_in_12h_outcome"]=m.read_track_status(aid)
action={"recordType":"SIM_BUY","alertId":aid,"actedAtMs":1000000}
m.apply_user_action(action)
m.apply_user_action(action)
results["duplicate_action_rows"]=len((TMP/"horizon/user_actions.jsonl").read_text().splitlines())
assert results["breakout_already_below_prior_high"]["strategy"] == "BURST_BREAKOUT"
assert results["fallback_bypasses_taker_gate"]["strict_breakout"] is None
assert results["fallback_bypasses_taker_gate"]["strategy"] == "BURST_BREAKOUT"
assert results["day_old_micro_quality_gate"][0]
assert results["atr_target_below_user_profit_band"]["tp1"] < 1
assert results["price_after_13h_counted_in_12h_outcome"]["tp2Touched"]
assert results["duplicate_action_rows"] == 2
output=ROOT/"audit/audit_probe_results.json"
output.write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding="utf-8")
print("AUDIT PROBE RESULTS",json.dumps(results,ensure_ascii=False,indent=2))
