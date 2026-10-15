import { build } from 'esbuild';
import { unlink } from 'node:fs/promises';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
// Avoid tsx's OS account lookup in restricted Windows environments.
for (const input of process.argv.slice(2)) {
  const output = resolve(`${input}.generated.mjs`);
  await build({ entryPoints: [input], bundle: true, platform: 'node', format: 'esm', packages: 'external', outfile: output });
  try { await import(pathToFileURL(output).href); }
  finally { await unlink(output); }
}
