"""Load production logic with temporary storage and no network or credential access."""
import ast
import pathlib
import sys
import tempfile
import types
if hasattr(sys.stdout, 'reconfigure'): sys.stdout.reconfigure(encoding='utf-8')

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scratch'))
TMP = pathlib.Path(tempfile.mkdtemp(prefix='cryptog-test-'))
tree = ast.parse((ROOT / 'scratch/remote_scanner_daemon.py').read_text(encoding='utf-8'))
redirect = {'LOG_DIR': str(TMP / 'logs'), 'LIBRARY_DIR': str(TMP / 'library'), 'FCM_KEY_PATH': str(TMP / 'absent.json')}
for node in tree.body:
    if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) and node.targets[0].id in redirect:
        node.value = ast.Constant(redirect[node.targets[0].id])
ast.fix_missing_locations(tree)
class OfflineSession:
    def __init__(self): self.headers = {}
    def get(self, *args, **kwargs): raise AssertionError('Test network is disabled')
requests = types.ModuleType('requests')
requests.Session = OfflineSession
sys.modules['requests'] = requests
daemon = types.ModuleType('remote_scanner_daemon')
daemon.__file__ = str(ROOT / 'scratch/remote_scanner_daemon.py')
sys.modules[daemon.__name__] = daemon
exec(compile(tree, daemon.__file__, 'exec'), daemon.__dict__)
