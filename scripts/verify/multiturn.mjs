// G6: coreference over HTTP; the follow-up shifts the period and keeps the vendor.
import { post, get, loadTransactions, sumWhere, pass, fail } from './_lib.mjs';

const txns = loadTransactions();
const maxDate = txns.map(r => r.txn_date).sort().at(-1);
const [y, m] = maxDate.split('-').map(Number);
const mm = n => { const t = m - n; return t > 0 ? `${y}-${String(t).padStart(2,'0')}` : `${y-1}-${String(12+t).padStart(2,'0')}`; };
const lastMonth = mm(1), monthBefore = mm(2);

const expA = sumWhere(txns, r => r.txn_date.startsWith(lastMonth) && r.vendor_id === 'V1001');
const expB = sumWhere(txns, r => r.txn_date.startsWith(monthBefore) && r.vendor_id === 'V1001');
if (!expA.count || !expB.count) fail('G6', 'fixture months are empty');
if (expA.total === expB.total) fail('G6', 'months are identical; test could not distinguish them');

const turn1 = await post('/api/v1/chat',
  { message: 'How much did we spend with Acme Technologies last month?' });
if (turn1.state !== 'answer') fail('G6', `turn1 state=${turn1.state}`);
const cid = turn1.conversation_id;

const t1 = turn1.evidence.facts.find(f => f.key === 'total');
if (Math.abs(Number(t1.value) - expA.total) > 0.02)
  fail('G6', `turn1 figure ${t1.value} != ${expA.total}`);

const turn2 = await post('/api/v1/chat',
  { message: 'What about the month before?', conversation_id: cid });
if (turn2.state !== 'answer') fail('G6', `turn2 state=${turn2.state} (${turn2.message||''})`);

const t2 = turn2.evidence.facts.find(f => f.key === 'total');
if (Math.abs(Number(t2.value) - expB.total) > 0.02)
  fail('G6', `turn2 figure ${t2.value} != independent ${expB.total} for ${monthBefore}`);

if (turn2.plan.vendor_id !== 'V1001')
  fail('G6', `vendor not carried into turn2: ${turn2.plan.vendor_id}`);
if (turn2.evidence.entities_resolved.vendor_name !== 'Acme Technologies')
  fail('G6', 'vendor name lost in turn2');
if (turn2.evidence.resolved_period === turn1.evidence.resolved_period)
  fail('G6', 'period did not shift');

const turn3 = await post('/api/v1/chat',
  { message: 'Break that down by category', conversation_id: cid });
if (turn3.state !== 'answer') fail('G6', `turn3 state=${turn3.state}`);
if (!turn3.evidence.breakdown.length) fail('G6', 'turn3 produced no breakdown');
if (turn3.evidence.resolved_period !== turn2.evidence.resolved_period)
  fail('G6', 'turn3 lost the period');
const bsum = turn3.evidence.breakdown.reduce((a, r) => a + r.value, 0);
if (Math.abs(bsum - expB.total) > 0.05)
  fail('G6', `turn3 breakdown sums to ${bsum}, expected ${expB.total}`);

const conv = await get(`/api/v1/conversations/${cid}`);
if (conv.turns < 3) fail('G6', `conversation recorded ${conv.turns} turns`);

pass('G6',
  `turn1 ${turn1.evidence.resolved_period}: ${t1.value} (independent ${expA.total})`,
  `turn2 ${turn2.evidence.resolved_period}: ${t2.value} (independent ${expB.total})`,
  `turn3 breakdown over ${turn3.evidence.breakdown.length} categories sums to ${bsum.toFixed(2)}`,
  `vendor carried across all three turns`);
