import runpy
from offline_daemon import ROOT
for name in ('test_remote_scanner.py', 'test_model_library.py', 'test_signal_validity.py', 'test_trade_rules.py', 'test_execution_records.py', 'test_stage1.py', 'test_positions.py', 'test_positions_v2.py', 'test_exit_delivery.py', 'test_research.py', 'test_session_research.py', 'test_strategy_settings.py', 'test_observations.py', 'test_ai_engine.py', 'test_ai_policy.py', 'test_ai_fast.py', 'test_ai_delivery_contract.py', 'test_strategy_statistics.py', 'test_startup_status.py', 'test_short_horizon.py', 'test_engine_v2.py', 'test_ai_review.py', 'test_v2_tracker.py', 'test_cost_model.py', 'test_barriers.py', 'test_ledger.py', 'test_validation.py', 'test_evolution.py', 'test_continuity.py', 'test_kline_store.py', 'test_derivatives.py', 'test_stop_monitor.py', 'test_s5.py', 'test_baseline.py', 'test_audit_stage_a.py', 'test_audit_stage_b.py', 'test_audit_stage_c.py', 'test_audit_stage_d.py', 'test_audit_stage_e.py'):
    try:
        runpy.run_path(str(ROOT / 'tests' / name), run_name='__main__')
    except SystemExit as exc:
        if exc.code not in (None, 0): raise

try:
    runpy.run_path(str(ROOT / 'tests' / 'test_wave_integration.py'), run_name='__main__')
except SystemExit as exc:
    if exc.code not in (None, 0): raise

