import fs from 'node:fs';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { ROOT } from './_lib.mjs';

export function run(cmd, args, { token, cwd = ROOT, env = {} } = {}) {
  const r = spawnSync(cmd, args, {
    cwd, encoding: 'utf8', env: { ...process.env, ...env },
    maxBuffer: 32 * 1024 * 1024,
  });
  const out = (r.stdout || '') + (r.stderr || '');
  return { ok: r.status === 0 && (!token || out.includes(token)), out, status: r.status };
}

// The field-encryption key from .env, so Python suites can decrypt fixtures the loader wrote.
export function dataKey() {
  if (process.env.TBX_DATA_KEY) return process.env.TBX_DATA_KEY;
  try {
    const m = fs.readFileSync(path.join(ROOT, '.env'), 'utf8').match(/^TBX_DATA_KEY=([0-9a-fA-F]{64})\s*$/m);
    return m ? m[1] : '';
  } catch { return ''; }
}
