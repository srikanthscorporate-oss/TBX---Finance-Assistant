// G10: compiler cross-check, offline end-to-end pipeline, and the ERROR path.
import { run } from './_run.mjs';
import { pass, fail } from './_lib.mjs';

const PY = 'apps/api/.venv/bin/python';
const env = { CH_HOST: 'localhost', CH_PORT: '18123',
              CH_ADMIN_USER: 'tbx_admin', CH_ADMIN_PASSWORD: 'change-me-admin' };

const cross = run(PY, ['apps/api/tests/crosscheck.py'], { env });
if (!cross.ok) fail('G10', `crosscheck failed:\n${cross.out.slice(-1200)}`);
const m = cross.out.match(/(\d+)\/(\d+) checks passed/);
if (!m || m[1] !== m[2]) fail('G10', `crosscheck did not pass all: ${m && m[0]}`);

const e2e = run(PY, ['apps/api/tests/e2e_offline.py'], { env });
if (!e2e.ok) fail('G10', `e2e failed:\n${e2e.out.slice(-1200)}`);
const states = [...e2e.out.matchAll(/state=(\w+)/g)].map(x => x[1]);
if (states.length < 10) fail('G10', `only ${states.length} e2e scenarios ran`);
const valid = new Set(['answer','clarification_required','data_unavailable','out_of_scope','error']);
for (const s of states) if (!valid.has(s)) fail('G10', `undefined state: ${s}`);

const err = run(PY, ['apps/api/tests/error_path.py'], { token: 'ERROR_PATH_PASS' });
if (!err.ok) fail('G10', `error-path failed:\n${err.out.slice(-800)}`);

pass('G10', `crosscheck ${m[0]}`, `e2e ${states.length} scenarios, all in defined states`,
     'error path refuses without a figure');
