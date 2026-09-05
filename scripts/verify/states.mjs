// G3: all five response states are reachable through the HTTP API.
import { post, pass, fail } from './_lib.mjs';

const cases = [
  { q: 'How much did we spend with Acme Technologies last month?', want: 'answer' },
  { q: 'How much did we spend with Acme last month?',              want: 'clarification_required' },
  { q: 'How much GST did we pay last month?',                      want: 'data_unavailable' },
  { q: "What is Apple's stock price?",                             want: 'out_of_scope' },
  { q: 'How much did we spend with Tesla last month?',             want: 'data_unavailable' },
];

const seen = new Set();
const notes = [];
for (const { q, want } of cases) {
  const r = await post('/api/v1/chat', { message: q });
  if (r.state !== want) fail('G3', `"${q}" -> ${r.state}, expected ${want}`);
  seen.add(r.state);
  notes.push(`${r.state.padEnd(22)} <- ${q}`);

  if (r.state !== 'answer') {
    if (r.answer) fail('G3', `${r.state} carried an answer: ${r.answer}`);
    if (r.evidence) fail('G3', `${r.state} carried an evidence package`);
    const text = r.message || r.clarification?.question || '';
    if (/\d{4,}|[₹$€£]\s*\d/.test(text))
      fail('G3', `${r.state} message contains a figure: ${text}`);
  }
}

const clar = await post('/api/v1/chat', { message: 'How much did we spend with Acme last month?' });
if (!clar.clarification?.options?.length) fail('G3', 'clarification offered no options');
if (clar.clarification.options.length < 2) fail('G3', 'clarification needs >=2 options');

for (const s of ['answer', 'clarification_required', 'data_unavailable', 'out_of_scope'])
  if (!seen.has(s)) fail('G3', `state never observed: ${s}`);

pass('G3', ...notes, `clarification options: ${clar.clarification.options.map(o => o.label).join(' | ')}`);
