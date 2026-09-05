// G28: the assistant assumes nothing. An unstated period and an unstated side are asked for, in
// that order, before any figure exists; the answer changes with the side the user picks; an
// ambiguous counterparty is asked about rather than guessed; and a balance is never asked either.
import { post, loadTransactions, defaultEntity, lastMonthOf, sumWhere, pass, fail } from './_lib.mjs';

const GATE = 'NO_ASSUMPTIONS';
const txns = loadTransactions();
const entity = defaultEntity(txns);
const prev = lastMonthOf(txns);
const mine = txns.filter(r => r.entity_id === entity);
const CP = 'SWIGGY INSTAMART';

const expectedBoth = sumWhere(mine, r => r.counterparty === CP && r.txn_date.startsWith(prev));
const expectedDebit = sumWhere(mine, r => r.counterparty === CP && r.txn_date.startsWith(prev)
                                       && r.transaction_type === 'debit');
if (!expectedBoth.count) fail(GATE, `fixture has no ${CP} rows in ${prev}`);
if (expectedBoth.count === expectedDebit.count)
  fail(GATE, `${CP} in ${prev} has no credits, so the side cannot change the answer; fixture proves nothing`);

const QUESTION = `how many transactions have I made with ${CP}`;

function requireAsk(res, field, where) {
  if (res.state === 'answer') fail(GATE, `${where}: answered before asking for ${field} -> ${res.answer}`);
  if (res.state !== 'clarification_required') fail(GATE, `${where} state=${res.state} (${res.message || ''})`);
  if (res.clarification?.field !== field) fail(GATE, `${where} asked ${res.clarification?.field}, expected ${field}`);
  if (res.answer || res.evidence) fail(GATE, `${where} carried an answer or evidence`);
  const values = (res.clarification.options || []).map(o => o.value);
  if (values.length < 2) fail(GATE, `${where} carried no options`);
  return values;
}

// Walk the chain once per side, from a fresh conversation each time.
async function ask(side) {
  const q1 = await post('/api/v1/chat', { message: QUESTION });
  const periods = requireAsk(q1, 'date_range', `${side}/step1`);
  if (!periods.includes('last_month')) fail(GATE, `period options lack last_month: ${periods}`);
  const conv = q1.conversation_id;

  const q2 = await post('/api/v1/chat', { message: '', conversation_id: conv, resolved_value: 'last_month' });
  const sides = requireAsk(q2, 'transaction_type', `${side}/step2`);
  for (const want of ['debit', 'credit', 'both'])
    if (!sides.includes(want)) fail(GATE, `transaction_type options lack ${want}: ${sides}`);

  const q3 = await post('/api/v1/chat', { message: '', conversation_id: conv, resolved_value: side });
  if (q3.state !== 'answer') fail(GATE, `${side}/step3 state=${q3.state} (${q3.message || ''})`);
  const count = q3.evidence?.facts.find(f => f.key === 'count');
  if (!count) fail(GATE, `${side}/step3 produced no count fact`);
  if (q3.evidence.resolved_start !== `${prev}-01`)
    fail(GATE, `${side}/step3 period ${q3.evidence.resolved_period} is not ${prev}`);
  return { res: q3, count: Number(count.value), periods, sides };
}

const both = await ask('both');
if (both.res.plan?.transaction_type)
  fail(GATE, `"both" narrowed the plan to ${both.res.plan.transaction_type}`);
if (both.count !== expectedBoth.count)
  fail(GATE, `"both" count ${both.count} != independent both-types ${expectedBoth.count}`);

const debit = await ask('debit');
if (debit.res.plan?.transaction_type !== 'debit')
  fail(GATE, `"debit" produced plan transaction_type=${debit.res.plan?.transaction_type}`);
if (debit.count !== expectedDebit.count)
  fail(GATE, `"debit" count ${debit.count} != independent debit-only ${expectedDebit.count}`);
if (both.count === debit.count)
  fail(GATE, `both-types and debit-only gave the same figure (${both.count}); the choice did nothing`);

// --- an ambiguous counterparty is asked about, never picked -----------------------------------
const amb = await post('/api/v1/chat', { message: 'how many transactions have I made with Swiggy' });
const cpValues = requireAsk(amb, 'counterparty', 'ambiguous name');
for (const want of ['SWIGGY', 'SWIGGY INSTAMART'])
  if (!cpValues.includes(want)) fail(GATE, `counterparty options lack ${want}: ${cpValues}`);

// --- a balance is neither period- nor side-dependent, so neither is asked ----------------------
const bal = await post('/api/v1/chat', { message: 'what is my balance?' });
if (bal.state !== 'answer') fail(GATE, `balance state=${bal.state} (${bal.clarification?.field || bal.message || ''})`);
const balTotal = bal.evidence?.facts.find(f => f.key === 'balance_total');
if (!balTotal) fail(GATE, 'balance answer carried no balance_total fact');
if (bal.plan?.date_range) fail(GATE, 'the balance plan carries a date range it was never given');
if (bal.plan?.transaction_type) fail(GATE, 'the balance plan carries a transaction type it was never given');

pass(GATE,
  `"${QUESTION}" -> date_range (${both.periods.join(' | ')}) -> transaction_type (${both.sides.join(' | ')}), never answered first`,
  `both  -> ${both.count} = independent both-types ${expectedBoth.count}`,
  `debit -> ${debit.count} = independent debit-only ${expectedDebit.count} (the two differ)`,
  `ambiguous "Swiggy" -> counterparty ask (${cpValues.join(' | ')}), no guess`,
  `balance -> ${bal.answer} with no period or type asked`);
