// G6: coreference over HTTP; the follow-up shifts the period and keeps the counterparty.
import { post, loadTransactions, defaultEntity, maxDate, monthsBefore, sumWhere, pass, fail } from './_lib.mjs';

const txns = loadTransactions();
const entity = defaultEntity(txns);
const mx = maxDate(txns);
const lastMonth = monthsBefore(mx, 1), monthBefore = monthsBefore(mx, 2);
const CP = 'ZOMATO';
const mine = txns.filter(r => r.entity_id === entity && r.counterparty === CP && r.transaction_type === 'debit');

const expA = sumWhere(mine, r => r.txn_date.startsWith(lastMonth));
const expB = sumWhere(mine, r => r.txn_date.startsWith(monthBefore));
if (!expA.count || !expB.count) fail('G6', 'fixture months are empty');
if (expA.total === expB.total) fail('G6', 'months are identical; test could not distinguish them');

const turn1 = await post('/api/v1/chat', { message: `How much did I spend with ${CP} last month?` });
if (turn1.state !== 'answer') fail('G6', `turn1 state=${turn1.state} (${turn1.message || ''})`);
const cid = turn1.conversation_id;
const t1 = turn1.evidence.facts.find(f => f.key === 'total');
if (Math.abs(Number(t1.value) - expA.total) > 0.02) fail('G6', `turn1 figure ${t1.value} != ${expA.total}`);

const turn2 = await post('/api/v1/chat', { message: 'What about the month before?', conversation_id: cid });
if (turn2.state !== 'answer') fail('G6', `turn2 state=${turn2.state} (${turn2.message || ''})`);
const t2 = turn2.evidence.facts.find(f => f.key === 'total');
if (Math.abs(Number(t2.value) - expB.total) > 0.02)
  fail('G6', `turn2 figure ${t2.value} != independent ${expB.total} for ${monthBefore}`);
if (turn2.plan.counterparty !== CP) fail('G6', `counterparty not carried into turn2: ${turn2.plan.counterparty}`);
if (turn2.evidence.entities_resolved.counterparty !== CP) fail('G6', 'counterparty name lost in turn2');
if (turn2.evidence.resolved_period === turn1.evidence.resolved_period) fail('G6', 'period did not shift');
if (turn2.evidence.resolved_start !== `${monthBefore}-01`)
  fail('G6', `turn2 period ${turn2.evidence.resolved_period} is not ${monthBefore}`);

const turn3 = await post('/api/v1/chat', { message: 'show me those transactions', conversation_id: cid });
if (turn3.state !== 'answer') fail('G6', `turn3 state=${turn3.state} (${turn3.message || ''})`);
const recs = turn3.evidence.records ?? [];
if (!recs.length) fail('G6', 'turn3 produced no records');
if (turn3.evidence.resolved_period !== turn2.evidence.resolved_period) fail('G6', 'turn3 lost the period');
if (turn3.plan.counterparty !== CP) fail('G6', 'turn3 lost the counterparty');
for (const r of recs) {
  if (r.counterparty !== CP) fail('G6', `turn3 record for ${r.counterparty}`);
  if (!r.transaction_date.startsWith(monthBefore)) fail('G6', `turn3 record outside ${monthBefore}: ${r.transaction_date}`);
  if (!/^X+\d{4}$/.test(r.account)) fail('G6', `turn3 record exposes an account: ${r.account}`);
}
if (turn3.evidence.total_record_count !== expB.count)
  fail('G6', `turn3 matched ${turn3.evidence.total_record_count} rows, independent ${expB.count}`);
const shownSum = Math.round(recs.reduce((a, r) => a + Number(r.amount), 0) * 100) / 100;
if (recs.length === expB.count && Math.abs(shownSum - expB.total) > 0.05)
  fail('G6', `turn3 records sum to ${shownSum}, expected ${expB.total}`);

pass('G6',
  `turn1 ${turn1.evidence.resolved_period}: ${t1.value} (independent ${expA.total})`,
  `turn2 ${turn2.evidence.resolved_period}: ${t2.value} (independent ${expB.total})`,
  `turn3 ${recs.length} records listed of ${turn3.evidence.total_record_count} (independent ${expB.count}), accounts masked`,
  `counterparty carried across all three turns`);
