// Offline concurrency reproduction. No requests leave this process.
import fs from 'node:fs';
import { transformSync } from 'esbuild';
const memory = new Map();
globalThis.localStorage = {
  getItem: key => memory.get(key) ?? null,
  setItem: (key, value) => memory.set(key, value),
};
const pending = [];
globalThis.fetch = (_url, options) => new Promise(resolve => pending.push({ resolve, action: JSON.parse(options.body) }));
const source = fs.readFileSync(new URL('../src/services/modelLibrary.ts', import.meta.url), 'utf8');
const js = transformSync(source, { loader: 'ts', format: 'esm' }).code;
const lib = await import('data:text/javascript;base64,' + Buffer.from(js).toString('base64'));
const tick = () => new Promise(resolve => setImmediate(resolve));
lib.rememberAction({ recordType: 'SIM_BUY', alertId: 'A', actedAtMs: 1 });
lib.rememberAction({ recordType: 'USER_CLOSE', alertId: 'B', actedAtMs: 2 });
pending[1].resolve({ ok: false });
await tick();
pending[2].resolve({ ok: false });
await tick();
const before = JSON.parse(memory.get('shotcrypto_model_library_queue_v1'));
pending[0].resolve({ ok: true });
await tick();
const after = JSON.parse(memory.get('shotcrypto_model_library_queue_v1'));
const result = { failedQueueBeforeOlderFlush: before.map(x => x.alertId), queueAfterOlderFlush: after.map(x => x.alertId), lostUnsyncedB: !after.some(x => x.alertId === 'B') };
if (!result.lostUnsyncedB) throw new Error('Expected audit reproduction did not occur');
fs.writeFileSync(new URL('./queue_probe_results.json', import.meta.url), JSON.stringify(result, null, 2));
console.log(JSON.stringify(result));
