"""One-time source-preserving extraction, guarded by the audited V1.12 digest."""
import ast
import hashlib
import pathlib
import zipfile

root = pathlib.Path(__file__).resolve().parents[1]
path = root / 'scratch/remote_scanner_daemon.py'
raw = path.read_bytes()
assert hashlib.sha256(raw).hexdigest() == '5b5917e0a70b82cfe8d4f65215598fedc4b8af25aa852268c2623b241d122e21'
backup = root / 'audit/baseline-v112.zip'
assert not backup.exists(), 'Do not overwrite baseline'
with zipfile.ZipFile(backup, 'x', zipfile.ZIP_DEFLATED) as archive:
    for directory in ('src', 'tests', 'scripts'):
        for p in (root / directory).rglob('*'):
            if p.is_file() and '__pycache__' not in p.parts and not p.name.endswith('.generated.mjs'):
                archive.write(p, p.relative_to(root))
    archive.write(path, path.relative_to(root))
    for name in ('package.json', 'android/app/build.gradle'):
        archive.write(root / name, name)
source = raw.decode('utf-8')
lines = source.splitlines(keepends=True)
tree = ast.parse(source)
nodes = {n.name: n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef))}
pkg = root / 'scratch/cryptog'
pkg.mkdir(exist_ok=True)
(pkg / '__init__.py').write_text('"""Crypto-G modular monitoring core. No trading API."""\n', encoding='utf-8')
config_start = source.index('# Symbols -')
config_end = source.index('SKIP_LOG_EVERY_SEC')
config = source[config_start:config_end].replace('ENGINE_VERSION = "Crypto-G V1.12"', 'ENGINE_VERSION = "Crypto-G stage1-dev"')
(pkg / 'config.py').write_text(config, encoding='utf-8')
groups = {
    'features': ['TechnicalIndicators', 'get_closed_candles'],
    'market_state': ['diagnose_macro_trend', 'diagnose_cascade_downtrend'],
    'cost_risk': ['entry_contract', 'entry_is_valid', 'model_targets'],
    'lifecycle': ['_advance_rule_track'],
    'strategy': ['validate_market_data_quality', 'verify_micro_range_reversal', '_closed_breakout', 'observed_resistances', 'stable_range_box', 'recent_crash_confirmed', 'scan_symbol'],
}
headers = {
    'features': '',
    'market_state': 'from .features import TechnicalIndicators, get_closed_candles\n',
    'cost_risk': '',
    'lifecycle': '',
    'strategy': 'from .features import TechnicalIndicators, get_closed_candles\nfrom .market_state import diagnose_cascade_downtrend\nfrom .cost_risk import entry_contract, model_targets\nfrom .diagnostics import reject as log_skip\n',
}
removed = set()
imports = []
for module, names in groups.items():
    chunks = []
    for name in names:
        n = nodes[name]
        chunks.append(''.join(lines[n.lineno-1:n.end_lineno]))
        removed.update(range(n.lineno-1, n.end_lineno))
    text = 'import math\nfrom typing import Dict, List, Optional, Tuple\nfrom .clock import clock as time\nfrom .config import *\n' + headers[module] + '\n\n' + '\n\n\n'.join(chunks) + '\n'
    (pkg / (module+'.py')).write_text(text, encoding='utf-8')
    imports.append('from cryptog.' + module + ' import ' + ', '.join(names))
new = ''.join(line for i,line in enumerate(lines) if i not in removed)
new = new[:new.index('# Symbols -')] + 'from cryptog.config import *\n' + '\n'.join(imports) + '\n\n' + new[new.index('SKIP_LOG_EVERY_SEC'):]
path.write_text(new, encoding='utf-8')
print('Baseline saved and five modules extracted without changing rule bodies.')
