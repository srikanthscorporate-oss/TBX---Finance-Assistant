// G18: the chart set exists, uses only palette tokens, and its pages and endpoints are in place.
import fs from 'node:fs';
import path from 'node:path';
import { ROOT, get, pass, fail } from './_lib.mjs';
const ORIGIN = process.env.TBX_ORIGIN || 'http://127.0.0.1:8080';
const charts = fs.readFileSync(path.join(ROOT, 'apps/web/components/charts.tsx'), 'utf8');
for (const c of ['export function BarSeries', 'export function LineSeries', 'export function RingChart',
                 'export function TimingBar', 'export function Sparkline', 'export function SignalDots'])
  if (!charts.includes(c)) fail('G18', `charts.tsx lacks ${c}`);
const hexes = charts.match(/#[0-9a-fA-F]{6}\b/g) || [];
if (hexes.length) fail('G18', `raw hex colours in charts.tsx: ${[...new Set(hexes)].join(', ')}`);
if (!/var\(--seq-|var\(--cat-|var\(--good\)|var\(--critical\)/.test(charts)) fail('G18', 'charts do not reference palette tokens');
const run = fs.readFileSync(path.join(ROOT, 'apps/web/components/RunPane.tsx'), 'utf8');
for (const c of ['TimingBar', 'SignalDots', 'RingChart']) if (!run.includes(c)) fail('G18', `RunPane does not use ${c}`);
const obs = fs.readFileSync(path.join(ROOT, 'apps/web/components/Observability.tsx'), 'utf8');
for (const c of ['Sparkline', 'TimingBar', 'BarSeries']) if (!obs.includes(c)) fail('G18', `Observability does not use ${c}`);

// The session sections render only once a run exists, so make one first; any outcome counts.
await fetch(`${ORIGIN}/api/v1/chat`, { method: 'POST', headers: { 'content-type': 'application/json' },
  body: JSON.stringify({ message: 'what is my name?' }) }).catch(() => {});
const home = await (await fetch(`${ORIGIN}/`)).text();
for (const t of ['Run details', 'Nothing running']) if (!home.includes(t)) fail('G18', `run pane structure missing: ${t}`);
const page = await (await fetch(`${ORIGIN}/observability`)).text();
for (const t of ['Where the time goes', 'Model mix', 'Accuracy by question category', 'Recent runs'])
  if (!page.includes(t)) fail('G18', `observability structure missing: ${t}`);

const u = await get('/api/v1/admin/usage');
if (u.runs > 0) {
  if (!u.time_split_ms || typeof u.time_split_ms.llm !== 'number') fail('G18', 'usage lacks time_split_ms');
  if (!Array.isArray(u.recent) || !u.recent.length) fail('G18', 'usage lacks recent history');
  const r = u.recent.at(-1);
  for (const k of ['state', 'duration_ms', 'tokens', 'at']) if (!(k in r)) fail('G18', `recent run lacks ${k}`);
  if (JSON.stringify(u.recent).match(/vendor_name|transaction_id|₹/)) fail('G18', 'recent history leaks financial data');
}
pass('G18', 'six chart primitives, token-only colour', 'run pane + observability wired',
     `usage: time split + ${u.recent?.length ?? 0} recent runs, no financial fields`);
