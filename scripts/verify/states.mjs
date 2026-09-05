// G3: the four user-facing response states are reachable and non-answer states carry nothing else.
import { post, pass, fail } from './_lib.mjs';

const cases = [
  { q: 'How much did I spend with SWIGGY INSTAMART last month?', want: 'answer' },
  { q: 'how many transactions have I made with Swiggy',          want: 'clarification_required' },
  { q: 'UTR deadbeef00000000000000000000000==',                   want: 'data_unavailable' },
  { q: "What is Apple's stock price?",                            want: 'out_of_scope' },
  { q: 'How much did I spend with Tesla last month?',             want: 'data_unavailable' },
];

const seen = new Set();
const notes = [];
for (const { q, want } of cases) {
  const r = await post('/api/v1/chat', { message: q });
  if (r.state !== want) fail('G3', `"${q}" -> ${r.state}, expected ${want} (${r.message || ''})`);
  seen.add(r.state);
  notes.push(`${r.state.padEnd(22)} <- ${q}`);

  if (r.state !== 'answer') {
    if (r.answer) fail('G3', `${r.state} carried an answer: ${r.answer}`);
    if (r.evidence) fail('G3', `${r.state} carried an evidence package`);
    if (r.plan) fail('G3', `${r.state} carried a plan`);
    const text = r.message || r.clarification?.question || '';
    if (/[₹$€£]\s*\d/.test(text) || /\b\d{4,}\b(?!=)/.test(text.replace(/deadbeef\S+/, '')))
      fail('G3', `${r.state} message contains a figure: ${text}`);
  } else if (!r.evidence || !r.plan) fail('G3', 'answer state lacks evidence or plan');
}

const clar = await post('/api/v1/chat', { message: 'how many transactions have I made with Swiggy' });
if (!clar.clarification?.options?.length) fail('G3', 'clarification offered no options');
if (clar.clarification.options.length < 2) fail('G3', 'clarification needs >=2 options');
if (clar.clarification.field !== 'counterparty') fail('G3', `clarification field=${clar.clarification.field}`);

for (const s of ['answer', 'clarification_required', 'data_unavailable', 'out_of_scope'])
  if (!seen.has(s)) fail('G3', `state never observed: ${s}`);

pass('G3', ...notes, `clarification options: ${clar.clarification.options.map(o => o.label).join(' | ')}`);
