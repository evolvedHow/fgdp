/**
 * Unified API client for fdensemble.
 *
 * In LIVE mode (Railway / local dev):   fetch('/api/...')
 * In STATIC mode (GitHub Pages build):  fetch('{BASE_URL}api/analysis/{id}.json')
 *
 * Set VITE_STATIC_MODE=1 at build time to enable static mode.
 */

export const STATIC_MODE = import.meta.env.VITE_STATIC_MODE === '1';

/** Base URL set by Vite (e.g. '/fgdp/' on GitHub Pages, '/' locally). */
const BASE = import.meta.env.BASE_URL ?? '/';

/** Railway URL for cross-linking from the static site. */
export const LIVE_SERVER_URL = 'https://fdensemble-production.up.railway.app';

export class StaticModeError extends Error {
  constructor() {
    super('This feature requires the live server');
    this.name = 'StaticModeError';
  }
}

// ── Static URL mapping ────────────────────────────────────────────────────────

function ensureTrailingSlash(s: string) {
  return s.endsWith('/') ? s : s + '/';
}

function staticUrl(apiPath: string, params: Record<string, string> = {}): string {
  const b = ensureTrailingSlash(BASE);
  if (apiPath === '/runs') {
    return `${b}api/runs.json`;
  }
  if (apiPath === '/analysis' && params.run) {
    return `${b}api/analysis/${encodeURIComponent(params.run)}.json`;
  }
  if (apiPath === '/analysis/correlations' && params.run) {
    return `${b}api/correlations/${encodeURIComponent(params.run)}.json`;
  }
  throw new Error(`No static mapping for ${apiPath}`);
}

// ── Public API ────────────────────────────────────────────────────────────────

export async function apiGet<T>(
  apiPath: string,
  params: Record<string, string> = {}
): Promise<T> {
  let url: string;
  if (STATIC_MODE) {
    url = staticUrl(apiPath, params);
  } else {
    const qs = Object.keys(params).length
      ? '?' + new URLSearchParams(params).toString()
      : '';
    url = `/api${apiPath}${qs}`;
  }
  const res = await fetch(url);
  if (!res.ok) throw new Error(`HTTP ${res.status}: ${url}`);
  return res.json() as Promise<T>;
}

export async function apiPost<T>(apiPath: string, body: unknown): Promise<T> {
  if (STATIC_MODE) throw new StaticModeError();
  const res = await fetch(`/api${apiPath}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => `HTTP ${res.status}`);
    throw new Error(text);
  }
  return res.json() as Promise<T>;
}

export async function apiDelete(apiPath: string): Promise<void> {
  if (STATIC_MODE) throw new StaticModeError();
  const res = await fetch(`/api${apiPath}`, { method: 'DELETE' });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
}
