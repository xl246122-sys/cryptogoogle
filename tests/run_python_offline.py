import runpy
from offline_daemon import ROOT
for name in ('test_remote_scanner.py', 'test_model_library.py', 'test_signal_validity.py', 'test_trade_rules.py', 'test_execution_records.py', 'test_stage1.py', 'test_positions.py', 'test_exit_delivery.py', 'test_research.py'):
    try:
        runpy.run_path(str(ROOT / 'tests' / name), run_name='__main__')
    except SystemExit as exc:
        if exc.code not in (None, 0): raise

