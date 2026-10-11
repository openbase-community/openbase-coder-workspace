import { readFileSync, realpathSync } from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import { pathToFileURL } from 'node:url';

export async function waitForApi({ url, timeoutMs = 120000, intervalMs = 1000 } = {}) {
  const deadline = Date.now() + timeoutMs;
  let last = 'no response';
  while (Date.now() < deadline) {
    try {
      const response = await fetch(url, { signal: AbortSignal.timeout(Math.max(1, Math.min(2000, deadline - Date.now()))) });
      if (response.ok && (await response.json()).status === 'ok') return;
      last = `HTTP ${response.status} without the API health result`;
    } catch (error) { last = error.message; }
    await new Promise(resolve => setTimeout(resolve, Math.min(intervalMs, Math.max(0, deadline - Date.now()))));
  }
  throw new Error(`Openbase API did not become ready within ${timeoutMs / 1000}s (${last}). Check openbase-coder services logs django-cli.`);
}

export function apiHealthUrl(env = process.env) {
  let contents = '';
  try { contents = readFileSync(path.join(env.HOME || os.homedir(), '.openbase/.env'), 'utf8'); }
  catch (error) { if (error.code !== 'ENOENT') throw error; }
  const settings = Object.fromEntries([...contents.matchAll(/^\s*(OPENBASE_CODER_CLI_(?:HOST|PORT))\s*=\s*['"]?([^'"\s#]+)['"]?\s*(?:#.*)?$/gm)].map(m => [m[1], m[2]]));
  const host = env.OPENBASE_CODER_CLI_HOST || settings.OPENBASE_CODER_CLI_HOST || '127.0.0.1';
  const port = env.OPENBASE_CODER_CLI_PORT || settings.OPENBASE_CODER_CLI_PORT || '7999';
  const localHost = ['0.0.0.0', '::'].includes(host) ? '127.0.0.1' : host;
  return `http://${localHost.includes(':') ? `[${localHost}]` : localHost}:${port}/api/health/`;
}
if (process.argv[1] && import.meta.url === pathToFileURL(realpathSync(process.argv[1])).href) {
  await waitForApi({ url: apiHealthUrl() });
  console.log('Openbase API health check passed.');
}
