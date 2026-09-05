// G17: clarification is a two-step flow completed by option id.
import { post, loadTransactions, sumWhere, pass, fail } from './_lib.mjs';
const txns = loadTransactions();
const maxDate = txns.map(r => r.txn_date).sort().at(-1);
const [y, m] = maxDate.split('-').map(Number);
const prev = m === 1 ? `${y - 1}-12` : `${y}-${String(m - 1).padStart(2, '0')}`;
const expected = sumWhere(txns, r => r.txn_date.startsWith(prev) && r.vendor_id === 'V1002');
if (!expected.count) fail('G17', 'fixture has no Acme Logistics rows last month');

const step1 = await post('/api/v1/chat', { message: 'How much did we spend with Acme last month?' });
if (step1.state !== 'clarification_required') fail('G17', `step1 state=${step1.state}`);
if (step1.answer || step1.evidence) fail('G17', 'clarification carried an answer or evidence');
const opts = step1.clarification?.options ?? [];
if (opts.length < 2) fail('G17', 'clarification offered fewer than two options');
const logistics = opts.find(o => o.label === 'Acme Logistics');
if (!logistics) fail('G17', `options lack Acme Logistics: ${opts.map(o => o.label)}`);
if (/\d{4,}|[₹$]\s*\d/.test(step1.clarification.question)) fail('G17', 'clarification question contains a figure');

// No message text: the original question must not be re-planned.
const step2 = await post('/api/v1/chat', {
  message: '', conversation_id: step1.conversation_id, resolved_vendor_id: logistics.value,
});
if (step2.state !== 'answer') fail('G17', `step2 state=${step2.state} (${step2.message || ''})`);
if (step2.plan?.vendor_id !== 'V1002') fail('G17', `step2 resolved to ${step2.plan?.vendor_id}, expected V1002`);
const total = step2.evidence?.facts.find(f => f.key === 'total');
if (!total) fail('G17', 'step2 has no total fact');
if (Math.abs(Number(total.value) - expected.total) > 0.02)
  fail('G17', `step2 figure ${total.value} != independent ${expected.total}`);
if (step2.evidence.total_record_count !== expected.count)
  fail('G17', `record count ${step2.evidence.total_record_count} != ${expected.count}`);
if (!step2.evidence.verification.checks.length) fail('G17', 'no verification on the completed answer');

const step3 = await post('/api/v1/chat', {
  message: '', conversation_id: step1.conversation_id, resolved_vendor_id: logistics.value,
});
if (step3.state === 'answer') fail('G17', 'a stale resolution produced an answer');

pass('G17', `clarified: ${opts.map(o => o.label).join(' | ')}`,
     `completed by option -> ${step2.answer}`,
     `figure ${total.value} matches independent ${expected.total} over ${expected.count} rows`,
     `stale resolution refused (${step3.state})`);
