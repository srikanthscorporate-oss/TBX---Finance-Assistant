// G12: the application is reachable over HTTPS at the production domain.
import { pass, fail } from './_lib.mjs';

const DOMAIN = process.env.TBX_DOMAIN || 'strawhatpirates-hackathon.tech';
const ORIGIN = `https://${DOMAIN}`;

let health;
try {
  const res = await fetch(`${ORIGIN}/health`, { signal: AbortSignal.timeout(15000) });
  if (!res.ok) fail('G12', `${ORIGIN}/health returned ${res.status}`);
  health = await res.json();
} catch (e) {
  fail('G12', `${ORIGIN} unreachable: ${e.message}`);
}

if (!health.ready) fail('G12', 'deployed API reports not ready');
if (!health.dataset_window) fail('G12', 'deployed API has no dataset loaded');

const ui = await fetch(ORIGIN, { signal: AbortSignal.timeout(15000) });
if (!ui.ok) fail('G12', `UI returned ${ui.status}`);
const body = await ui.text();
if (!/StrawHat Finance Assistant/.test(body)) fail('G12', 'UI shell not served');

const chat = await fetch(`${ORIGIN}/api/v1/chat`, {
  method: 'POST', headers: { 'content-type': 'application/json' },
  body: JSON.stringify({ message: 'Which transactions are still unreconciled?' }),
  signal: AbortSignal.timeout(45000),
});
if (!chat.ok) fail('G12', `production chat returned ${chat.status}`);
const cj = await chat.json();
if (cj.state !== 'answer' || !cj.evidence) fail('G12', `production chat state=${cj.state}`);

const admin = await fetch(`${ORIGIN}/api/v1/admin/usage`, { signal: AbortSignal.timeout(10000) });
if (admin.ok) fail('G12', 'admin endpoint is publicly reachable in production');

pass('G12', `${ORIGIN} serving dataset ${health.dataset_version} (${health.dataset_window})`,
     `production answer: ${cj.answer}`,
     `admin blocked (${admin.status})`);
