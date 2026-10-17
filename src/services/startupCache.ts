import { connection } from './serverConnection';

// Display snapshots only: never use these records to authorize a trade.
export function readStartupCache<T>(name: string, maxAge: number): { at: number; value: T } | null {
  try {
    const scope = connection().cacheScope;
    const entry = JSON.parse(localStorage.getItem(`cryptog_startup_${name}`) || 'null');
    const age = Date.now() - entry?.at;
    return scope && entry?.scope === scope && age >= 0 && age <= maxAge ? entry : null;
  } catch { return null; }
}

export function writeStartupCache(name: string, value: unknown) {
  try {
    const scope = connection().cacheScope;
    if (scope) localStorage.setItem(`cryptog_startup_${name}`, JSON.stringify({ scope, at: Date.now(), value }));
  } catch { /* Storage failure must not interrupt live updates. */ }
}
