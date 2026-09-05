// G17: clarification is a real multi-step flow completed by resolved_value, for counterparties,
// periods and the transaction side. The API assumes nothing: it asks in order and only then answers.
import { post, loadTransactions, defaultEntity, lastMonthOf, sumWhere, pass, fail } from './_lib.mjs';

const txns = loadTransactions();
const entity = defaultEntity(txns);
const prev = lastMonthOf(txns);
const mine = txns.filter(r => r.entity_id === entity);

const swiggyAll = sumWhere(mine, r => r.counterparty === 'SWIGGY');
if (!swiggyAll.count) fail('CLARIFY', 'fixture has no SWIGGY rows for the default entity');

function checkAsk(res, field, where) {
  if (res.state !== 'clarification_required') fail('CLARIFY', `${where} state=${res.state} (${res.message || ''})`);
  if (res.clarification?.field !== field) fail('CLARIFY', `${where} field=${res.clarification?.field}, expected ${field}`);
  const options = res.clarification.options;
  if (!Array.isArray(options) || options.length < 2) fail('CLARIFY', `${where} carried no options`);
  for (const o of options)
    if (!o || typeof o.value !== 'string' || !o.value || typeof o.label !== 'string' || !o.label)
      fail('CLARIFY', `${where} option is not a {label, value}: ${JSON.stringify(o)}`);
  // A non-answer state must never carry a figure, evidence or plan.
  if (res.answer || res.evidence || res.plan) fail('CLARIFY', `${where} carried an answer, evidence or plan`);
  if (/\d{4,}|[₹$]\s*\d/.test(res.clarification.question)) fail('CLARIFY', `${where} question contains a figure`);
  return options.map(o => o.value);
}

// --- chain one: an ambiguous counterparty, then the period, then the side ---------------------
const step1 = await post('/api/v1/chat', { message: 'how many transactions have I made with Swiggy' });
const cpValues = checkAsk(step1, 'counterparty', 'step1');
for (const want of ['SWIGGY', 'SWIGGY INSTAMART'])
  if (!cpValues.includes(want)) fail('CLARIFY', `counterparty options lack ${want}: ${cpValues}`);
const conv = step1.conversation_id;

const step2 = await post('/api/v1/chat', { message: '', conversation_id: conv, resolved_value: 'SWIGGY' });
const periods = checkAsk(step2, 'date_range', 'step2');
if (periods.length !== 6) fail('CLARIFY', `expected 6 period options, got ${periods.length}: ${periods}`);
if (!periods.includes('last_month')) fail('CLARIFY', `period options lack last_month: ${periods}`);

const step3 = await post('/api/v1/chat', { message: '', conversation_id: conv, resolved_value: 'last_month' });
const sides = checkAsk(step3, 'transaction_type', 'step3');
for (const want of ['debit', 'credit', 'both'])
  if (!sides.includes(want)) fail('CLARIFY', `transaction_type options lack ${want}: ${sides}`);

const step4 = await post('/api/v1/chat', { message: '', conversation_id: conv, resolved_value: 'both' });
if (step4.state !== 'answer') fail('CLARIFY', `step4 state=${step4.state} (${step4.message || ''})`);
if (step4.plan?.counterparty !== 'SWIGGY') fail('CLARIFY', `step4 resolved to ${step4.plan?.counterparty}`);
if (step4.plan?.transaction_type) fail('CLARIFY', `"both" narrowed to ${step4.plan.transaction_type}`);
const count = step4.evidence?.facts.find(f => f.key === 'count');
if (!count) fail('CLARIFY', 'step4 has no count fact');
// "both" means no type filter, so the independent count covers debits and credits alike.
const expectedBoth = sumWhere(mine, r => r.counterparty === 'SWIGGY' && r.txn_date.startsWith(prev));
if (step4.evidence.resolved_start !== `${prev}-01`)
  fail('CLARIFY', `step4 period ${step4.evidence.resolved_period} is not ${prev}`);
if (Number(count.value) !== expectedBoth.count)
  fail('CLARIFY', `step4 count ${count.value} != independent both-types ${expectedBoth.count} for ${prev}`);

// --- chain two: an amount filter with no period and no side -----------------------------------
const s1 = await post('/api/v1/chat', { message: 'I want a list of transactions that are less than 500 Rupees' });
const p2 = checkAsk(s1, 'date_range', 'step5');
if (p2.length !== 6) fail('CLARIFY', `expected 6 period options, got ${p2.length}: ${p2}`);
const conv2 = s1.conversation_id;

const s2 = await post('/api/v1/chat', { message: '', conversation_id: conv2, resolved_value: 'last_month' });
checkAsk(s2, 'transaction_type', 'step6');

const s3 = await post('/api/v1/chat', { message: '', conversation_id: conv2, resolved_value: 'both' });
if (s3.state !== 'answer') fail('CLARIFY', `step7 state=${s3.state} (${s3.message || ''})`);
const recs = s3.evidence?.records ?? [];
if (!recs.length) fail('CLARIFY', 'step7 returned no records');
for (const r of recs) if (!(Number(r.amount) <= 500)) fail('CLARIFY', `record over 500: ${r.amount}`);
const expectedSmall = sumWhere(mine, r => r.txn_date.startsWith(prev) && r.amount <= 500);
const small = s3.evidence.facts.find(f => f.key === 'count');
if (!small) fail('CLARIFY', 'step7 has no count fact');
if (Number(small.value) !== expectedSmall.count)
  fail('CLARIFY', `step7 count ${small.value} != independent ${expectedSmall.count} for ${prev} (both types)`);
if (s3.evidence.resolved_start !== `${prev}-01`) fail('CLARIFY', `step7 period ${s3.evidence.resolved_period} is not ${prev}`);

// --- a resolution against a conversation with nothing parked never answers --------------------
const stale = await post('/api/v1/chat', { message: '', conversation_id: conv, resolved_value: 'SWIGGY' });
if (stale.state === 'answer') fail('CLARIFY', 'a stale resolution produced an answer');

pass('CLARIFY',
     `chain: counterparty (${cpValues.join(' | ')}) -> date_range (${periods.join(' | ')}) -> transaction_type (${sides.join(' | ')})`,
     `SWIGGY / ${prev} / both -> ${step4.answer} (independent both-types ${expectedBoth.count})`,
     `under 500: date_range -> transaction_type -> ${recs.length} records shown, ${small.value} matching (independent ${expectedSmall.count}), all <= 500`,
     `every clarification carried options and no evidence`,
     `stale resolution refused (${stale.state})`);
