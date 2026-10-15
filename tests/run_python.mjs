import { spawnSync } from 'node:child_process';
import { existsSync } from 'node:fs';
import { join } from 'node:path';
const bundled = join(process.env.USERPROFILE || '', '.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe');
const candidates = [process.env.CRYPTOG_PYTHON, existsSync(bundled) ? bundled : undefined, 'python3', 'python'].filter(Boolean);
const executable = candidates.find(p => spawnSync(p, ['--version'], { windowsHide: true }).status === 0);
if (!executable) throw new Error('Install Python 3 or set CRYPTOG_PYTHON to its executable.');
const result = spawnSync(executable, ['tests/run_python_offline.py'], { stdio: 'inherit', windowsHide: true });
process.exitCode = result.status ?? 1;
