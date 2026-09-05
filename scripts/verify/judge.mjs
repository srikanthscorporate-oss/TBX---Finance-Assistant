// G23: judge behaviour, offline with the stub and over HTTP for the zero-call paths.
import { run } from './_run.mjs';
import { post, pass, fail } from './_lib.mjs';

const PY = 'apps/api/.venv/bin/python';
const off = run(PY, ['apps/api/tests/judge_offline.py'],
  { env: { REDIS_URL: 'redis://127.0.0.1:16379/0', CH_PORT: '18123' }, token: 'JUDGE_OFFLINE_PASS' });
if (!off.ok) fail('G23', `offline judge suite failed:\n${off.out.slice(-1500)}`);

const r = await post('/api/v1/chat', { message: 'tell me a joke about cats' });
if (r.state !== 'out_of_scope') fail('G23', `irrelevant -> ${r.state}`);
if ((r.model_usage ?? []).length !== 0) fail('G23', `irrelevant input made ${r.model_usage.length} model calls`);

const q = 'How much did we spend with Acme Technologies last month?';
const a = await post('/api/v1/chat', { message: q });
const b = await post('/api/v1/chat', { message: q });
if (b.state !== 'answer') fail('G23', `repeat question state=${b.state} (${b.message || ''}); first was ${a.state}`);
if ((b.model_usage ?? []).length !== 0) fail('G23', `repeat question made ${b.model_usage.length} model calls; cache did not hit`);
if (a.state === 'answer' && b.answer !== a.answer) fail('G23', 'cached answer differs from the original');

pass('G23', ...off.out.split('\n').filter(l => l.startsWith('  ')).slice(-8),
     'HTTP: irrelevant input -> 0 model calls', 'HTTP: repeat question -> 0 model calls (cached)');
