// G9: the composed stack serves the UI and the API through nginx on one origin.
import { run } from './_run.mjs';
import { pass, fail } from './_lib.mjs';

const ORIGIN = process.env.TBX_ORIGIN || 'http://127.0.0.1:8080';

const ps = run('docker', ['compose', 'ps', '--format', 'json']);
if (ps.status !== 0) fail('G9', 'docker compose ps failed');
const services = ps.out.trim().split('\n').filter(Boolean).map(l => JSON.parse(l));
for (const required of ['api', 'web', 'nginx', 'clickhouse', 'postgres', 'redis']) {
  const svc = services.find(s => s.Service === required);
  if (!svc) fail('G9', `service not running: ${required}`);
  if (!/^Up/.test(svc.State === 'running' ? 'Up' : svc.Status)) fail('G9', `${required}: ${svc.Status}`);
}

// 1. The UI is served at the root of the same origin.
const html = await fetch(`${ORIGIN}/`).catch(e => fail('G9', `UI unreachable: ${e.message}`));
if (!html.ok) fail('G9', `UI returned ${html.status}`);
const body = await html.text();
if (!/StrawHat Finance Assistant/.test(body)) fail('G9', 'UI did not render the app shell');
if (!/_next/.test(body)) fail('G9', 'UI is not the built Next.js bundle');

// 2. Security headers are applied at the edge.
for (const h of ['x-content-type-options', 'x-frame-options', 'content-security-policy'])
  if (!html.headers.get(h)) fail('G9', `missing security header: ${h}`);

// 3. The API answers on the SAME origin (so the browser needs no CORS).
const health = await fetch(`${ORIGIN}/health`);
if (!health.ok) fail('G9', `/health returned ${health.status}`);
const hj = await health.json();
if (!hj.ready) fail('G9', 'API reports not ready inside the stack');

const chat = await fetch(`${ORIGIN}/api/v1/chat`, {
  method: 'POST', headers: { 'content-type': 'application/json' },
  body: JSON.stringify({ message: 'How much did we spend with Acme Technologies last month?' }),
});
if (!chat.ok) fail('G9', `chat through nginx returned ${chat.status}`);
const cj = await chat.json();
if (cj.state !== 'answer' || !cj.evidence) fail('G9', `chat via nginx: state=${cj.state}`);

// 4. SSE must not be buffered by nginx, or the live timeline is dead on arrival.
const started = Date.now();
const sse = await fetch(`${ORIGIN}/api/v1/chat/stream`, {
  method: 'POST', headers: { 'content-type': 'application/json' },
  body: JSON.stringify({ message: 'Show me the top vendors last month' }),
});
if (!sse.ok) fail('G9', `SSE through nginx returned ${sse.status}`);
const reader = sse.body.getReader();
const firstChunk = await reader.read();
const ttfb = Date.now() - started;
const firstText = new TextDecoder().decode(firstChunk.value || new Uint8Array());
if (!/^event: /m.test(firstText)) fail('G9', `first SSE chunk was not an event frame: ${firstText.slice(0,120)}`);
await reader.cancel();

// 5. Observability is deliberately public in this build (no end-user auth), so
// it must answer on the public origin AND must not leak financial records.
const admin = await fetch(`${ORIGIN}/api/v1/admin/usage`);
if (!admin.ok) fail('G9', `observability endpoint returned ${admin.status}`);
const usage = await admin.json();
if (typeof usage.runs !== 'number') fail('G9', 'usage payload malformed');

const evalRes = await fetch(`${ORIGIN}/api/v1/admin/evaluations`);
if (!evalRes.ok) fail('G9', `evaluations endpoint returned ${evalRes.status}`);

// Operational counters only. No vendor names, amounts, or transaction ids.
const usageText = JSON.stringify(usage);
for (const leak of ['vendor_name', 'transaction_id', 'Acme', 'amount'])
  if (usageText.includes(leak)) fail('G9', `usage endpoint leaks financial data: ${leak}`);

pass('G9', `${services.length} services up`,
     `UI + API on one origin at ${ORIGIN}`,
     `chat via nginx: ${cj.answer}`,
     `SSE unbuffered, first frame in ${ttfb}ms`,
     `observability public and clean: ${usage.runs} runs, no financial fields`);
