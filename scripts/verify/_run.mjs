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
