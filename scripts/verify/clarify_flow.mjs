// G17: clarification is a two-step flow completed by resolved_value, for counterparties and periods.
import { post, loadTransactions, defaultEntity, lastMonthOf, sumWhere, pass, fail } from './_lib.mjs';

const txns = loadTransactions();
const entity = defaultEntity(txns);
const prev = lastMonthOf(txns);
const mine = txns.filter(r => r.entity_id === entity);

const swiggyAll = sumWhere(mine, r => r.counterparty === 'SWIGGY');
if (!swiggyAll.count) fail('CLARIFY', 'fixture has no SWIGGY rows for the default entity');

const step1 = await post('/api/v1/chat', { message: 'how many transactions have I made with Swiggy' });
if (step1.state !== 'clarification_required') fail('CLARIFY', `step1 state=${step1.state} (${step1.message || ''})`);
if (step1.answer || step1.evidence || step1.plan) fail('CLARIFY', 'clarification carried an answer, evidence or plan');
if (step1.clarification?.field !== 'counterparty') fail('CLARIFY', `field=${step1.clarification?.field}`);
const opts = step1.clarification.options;
const values = opts.map(o => o.value);
for (const want of ['SWIGGY', 'SWIGGY INSTAMART'])
  if (!values.includes(want)) fail('CLARIFY', `options lack ${want}: ${values}`);
if (/\d{4,}|[₹$]\s*\d/.test(step1.clarification.question)) fail('CLARIFY', 'clarification question contains a figure');

const step2 = await post('/api/v1/chat', {
  message: '', conversation_id: step1.conversation_id, resolved_value: 'SWIGGY',
});
if (step2.state !== 'answer') fail('CLARIFY', `step2 state=${step2.state} (${step2.message || ''})`);
if (step2.plan?.counterparty !== 'SWIGGY') fail('CLARIFY', `step2 resolved to ${step2.plan?.counterparty}`);
const count = step2.evidence?.facts.find(f => f.key === 'count');
if (!count) fail('CLARIFY', 'step2 has no count fact');
const expectedCount = step2.evidence.resolved_start
  ? sumWhere(mine, r => r.counterparty === 'SWIGGY' && r.txn_date >= step2.evidence.resolved_start && r.txn_date <= step2.evidence.resolved_end)
  : swiggyAll;
if (Number(count.value) !== expectedCount.count)
  fail('CLARIFY', `step2 count ${count.value} != independent ${expectedCount.count} (${step2.evidence.resolved_period || 'all time'})`);

const step3 = await post('/api/v1/chat', { message: 'I want a list of transactions that are less than 500 Rupees' });
if (step3.state !== 'clarification_required') fail('CLARIFY', `step3 state=${step3.state} (${step3.message || ''})`);
if (step3.clarification?.field !== 'date_range') fail('CLARIFY', `step3 field=${step3.clarification?.field}`);
const periods = step3.clarification.options.map(o => o.value);
if (periods.length !== 6) fail('CLARIFY', `expected 6 period options, got ${periods.length}: ${periods}`);
if (!periods.includes('last_month')) fail('CLARIFY', `period options lack last_month: ${periods}`);

const step4 = await post('/api/v1/chat', {
  message: '', conversation_id: step3.conversation_id, resolved_value: 'last_month',
});
if (step4.state !== 'answer') fail('CLARIFY', `step4 state=${step4.state} (${step4.message || ''})`);
const recs = step4.evidence?.records ?? [];
if (!recs.length) fail('CLARIFY', 'step4 returned no records');
for (const r of recs) if (!(Number(r.amount) <= 500)) fail('CLARIFY', `record over 500: ${r.amount}`);
const expectedSmall = sumWhere(mine, r => r.txn_date.startsWith(prev) && r.amount <= 500);
const small = step4.evidence.facts.find(f => f.key === 'count');
if (!small) fail('CLARIFY', 'step4 has no count fact');
if (Number(small.value) !== expectedSmall.count)
  fail('CLARIFY', `step4 count ${small.value} != independent ${expectedSmall.count} for ${prev}`);
if (step4.evidence.resolved_start !== `${prev}-01`) fail('CLARIFY', `step4 period ${step4.evidence.resolved_period} is not ${prev}`);

const stale = await post('/api/v1/chat', {
  message: '', conversation_id: step1.conversation_id, resolved_value: 'SWIGGY',
});
if (stale.state === 'answer') fail('CLARIFY', 'a stale resolution produced an answer');

pass('CLARIFY', `counterparty options: ${opts.map(o => `${o.label} (${o.hint || ''})`).join(' | ')}`,
     `SWIGGY -> ${step2.answer} (independent ${expectedCount.count})`,
     `period options: ${periods.join(' | ')}`,
     `last_month -> ${recs.length} records shown, ${small.value} matching (independent ${expectedSmall.count}), all <= 500`,
     `stale resolution refused (${stale.state})`);
