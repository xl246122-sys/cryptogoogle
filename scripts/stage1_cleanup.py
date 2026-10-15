"""Remove superseded runtime paths; keep the archived baseline for reproducibility."""
import ast
import hashlib
import pathlib
import zipfile
root=pathlib.Path(__file__).resolve().parents[1]
p=root/'scratch/remote_scanner_daemon.py'
s=p.read_text(encoding='utf-8')
start=s.index('# Binance Direct Market Data Fetchers')
end=s.index('def main():',start)
s=s[:start]+s[end:]
s=s.replace('LOG_DIR = "/opt/shotcrypto/logs"', 'LOG_DIR = os.environ.get("CRYPTOG_LOG_DIR", "/opt/shotcrypto/logs")')
s=s.replace('LIBRARY_DIR = "/opt/shotcrypto/model_library"', 'LIBRARY_DIR = os.environ.get("CRYPTOG_LIBRARY_DIR", "/opt/shotcrypto/model_library")')
s=s.replace('BTC spot monitor daemon V1.12 (local candidate)','BTC spot monitor modular stage-one candidate')
p.write_text(s,encoding='utf-8',newline='\n')
p=root/'src/services/binanceService.ts';s=p.read_text(encoding='utf-8')
start=s.index('  private connectFinnhubWebSocket()')
end=s.index('  /**',start)
s=s[:start]+'''  private connectFinnhubWebSocket() {
    // No embedded third-party credentials or cross-source fallback.
    // Existing Binance REST/reconnect paths continue; unavailable data stays unavailable.
  }

'''+s[end:]
p.write_text(s,encoding='utf-8',newline='\n')
p=root/'src/services/notificationService.ts';s=p.read_text(encoding='utf-8')
s=s.replace("console.log('>>> [FCM Registration Token]:', token.value);", "console.info('FCM registration completed');")
p.write_text(s,encoding='utf-8',newline='\n')
# Portable frozen rule fixture contains no storage, credentials, or network initialization.
with zipfile.ZipFile(root/'audit/baseline-v112.zip') as z: raw=z.read('scratch/remote_scanner_daemon.py')
tree=ast.parse(raw.decode())
names={'TechnicalIndicators','get_closed_candles','validate_market_data_quality','verify_micro_range_reversal',
       'diagnose_cascade_downtrend','_closed_breakout','entry_contract','observed_resistances','stable_range_box',
       'recent_crash_confirmed','model_targets','scan_symbol'}
definitions='\n\n'.join(ast.get_source_segment(raw.decode(),n) for n in tree.body if isinstance(n,(ast.FunctionDef,ast.ClassDef)) and n.name in names)
fixture=root/'tests/fixtures/v112_rules.py';fixture.parent.mkdir(exist_ok=True)
fixture.write_text('# Frozen from audited V1.12; only declarations, executed by the parity test.\n'+definitions,encoding='utf-8',newline='\n')
(root/'tests/fixtures/v112_rules.sha256').write_text(hashlib.sha256(fixture.read_bytes()).hexdigest()+'\n',encoding='utf-8')
