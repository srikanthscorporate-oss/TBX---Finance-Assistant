// G10: compiler cross-check, offline end-to-end pipeline, the ERROR path, and field encryption.
import { run, dataKey } from './_run.mjs';
import { pass, fail } from './_lib.mjs';

const PY = 'apps/api/.venv/bin/python';
const key = dataKey();
if (!key) fail('G10', 'TBX_DATA_KEY is neither in the environment nor in .env');
const env = { CH_HOST: 'localhost', CH_PORT: '18123',
              CH_ADMIN_USER: 'tbx_admin', CH_ADMIN_PASSWORD: 'change-me-admin', TBX_DATA_KEY: key };

const cross = run(PY, ['apps/api/tests/crosscheck.py'], { env, token: 'CROSSCHECK_PASS' });
if (!cross.ok) fail('G10', `crosscheck failed:\n${cross.out.slice(-1200)}`);
const m = cross.out.match(/(\d+)\/(\d+) checks passed/);
if (m && m[1] !== m[2]) fail('G10', `crosscheck did not pass all: ${m[0]}`);

const e2e = run(PY, ['apps/api/tests/e2e_offline.py'], { env, token: 'E2E_OFFLINE_PASS' });
if (!e2e.ok) fail('G10', `e2e failed:\n${e2e.out.slice(-1200)}`);
const states = [...e2e.out.matchAll(/state=(\w+)/g)].map(x => x[1]);
if (states.length < 10) fail('G10', `only ${states.length} e2e scenarios ran`);
const valid = new Set(['answer', 'clarification_required', 'data_unavailable', 'out_of_scope', 'error']);
for (const s of states) if (!valid.has(s)) fail('G10', `undefined state: ${s}`);

const err = run(PY, ['apps/api/tests/error_path.py'], { env, token: 'ERROR_PATH_PASS' });
if (!err.ok) fail('G10', `error-path failed:\n${err.out.slice(-800)}`);

const crypto = run(PY, ['apps/api/tests/crypto_roundtrip.py'], { env, token: 'CRYPTO_ROUNDTRIP_PASS' });
if (!crypto.ok) fail('G10', `crypto round-trip failed:\n${crypto.out.slice(-800)}`);

const rest = run(PY, ['apps/api/tests/encryption_at_rest.py'], { env, token: 'ENCRYPTION_AT_REST_PASS' });
if (!rest.ok) fail('G10', `encryption-at-rest failed:\n${rest.out.slice(-800)}`);

pass('G10', `crosscheck ${m ? m[0] : 'passed'}`, `e2e ${states.length} scenarios, all in defined states`,
     'error path refuses without a figure', 'cipher round-trips and blind index are stable',
     'stored account numbers and UTRs are ciphertext');
