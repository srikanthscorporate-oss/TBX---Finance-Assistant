// G2: the answer's figure matches an independent CSV computation for the default entity.
import { post, loadTransactions, defaultEntity, lastMonthOf, sumWhere, pass, fail } from './_lib.mjs';

const txns = loadTransactions();
const entity = defaultEntity(txns);
const prev = lastMonthOf(txns);
const CP = 'SWIGGY INSTAMART';

const expected = sumWhere(txns, r => r.entity_id === entity && r.txn_date.startsWith(prev)
                                   && r.counterparty === CP && r.transaction_type === 'debit');
if (expected.count === 0) fail('G2', 'fixture produced no rows; cannot prove anything');

const res = await post('/api/v1/chat', { message: `How much did I spend with ${CP} last month?` });
if (res.state !== 'answer') fail('G2', `state=${res.state} (${res.message || ''})`);
if (!res.evidence) fail('G2', 'no evidence package attached');

const ev = res.evidence;
const total = ev.facts.find(f => f.key === 'total');
if (!total) fail('G2', 'no computed total fact');
const got = Math.round(Number(total.value) * 100) / 100;
if (Math.abs(got - expected.total) > 0.02)
  fail('G2', `figure mismatch: api=${got} independent=${expected.total}`);
if (ev.total_record_count !== expected.count)
  fail('G2', `record count mismatch: api=${ev.total_record_count} independent=${expected.count}`);
// entities_resolved.entity_id is the MASKED label now: every character starred but the last four.
const maskedEntity = '*'.repeat(entity.length - 4) + entity.slice(-4);
const gotEntity = ev.entities_resolved.entity_id;
if (gotEntity !== maskedEntity)
  fail('G2', `scoped to ${gotEntity}, masked form of the independent default entity is ${maskedEntity}`);
if (gotEntity.slice(-4) !== entity.slice(-4))
  fail('G2', `masked label ends ${gotEntity.slice(-4)}, CSV default entity ends ${entity.slice(-4)}`);
if (gotEntity.includes(entity)) fail('G2', 'the raw entity id leaked into entities_resolved');

const rendered = total.formatted.replace(/[^\d]/g, '');
if (!res.answer.replace(/[^\d]/g, '').includes(rendered))
  fail('G2', `answer text does not carry the verified figure: ${res.answer}`);

if (!ev.verification || ev.verification.checks.length < 3) fail('G2', 'verification checks missing');
const blockingFailed = ev.verification.checks.filter(c => !c.passed && c.severity === 'blocking');
if (blockingFailed.length) fail('G2', `blocking checks failed: ${blockingFailed.map(c => c.name)}`);
if (!ev.confidence || typeof ev.confidence.score !== 'number') fail('G2', 'no deterministic confidence');
if (!ev.sql || !ev.sql.includes('{')) fail('G2', 'evidence does not expose parameterized SQL');
if (ev.sql.includes(CP) || ev.sql.includes(entity)) fail('G2', 'a value was interpolated into SQL text, not bound');

const expectedCount = sumWhere(txns, r => r.entity_id === entity && r.txn_date.startsWith(prev) && r.counterparty === CP);
// A count says nothing about the side, so the API asks; answering "both" leaves the type open.
const ask = await post('/api/v1/chat', { message: `how many transactions have I made with ${CP} last month` });
if (ask.state !== 'clarification_required' || ask.clarification?.field !== 'transaction_type')
  fail('G2', `count question state=${ask.state} field=${ask.clarification?.field}, expected a transaction_type ask`);
if (ask.answer || ask.evidence) fail('G2', 'the transaction_type clarification carried an answer or evidence');
const cnt = await post('/api/v1/chat', {
  message: '', conversation_id: ask.conversation_id, resolved_value: 'both',
});
if (cnt.state !== 'answer') fail('G2', `count question state=${cnt.state} (${cnt.message || ''})`);
const count = cnt.evidence.facts.find(f => f.key === 'count');
if (!count) fail('G2', 'count question produced no count fact');
if (Number(count.value) !== expectedCount.count)
  fail('G2', `count mismatch: api=${count.value} independent=${expectedCount.count} (both types)`);
if (cnt.plan.transaction_type) fail('G2', `count question narrowed to ${cnt.plan.transaction_type}; a count covers both types`);

pass('G2',
  `independent: ${expected.total} over ${expected.count} debits (${prev}, entity ${entity.slice(0, 8)})`,
  `api:         ${got} over ${ev.total_record_count} rows (${ev.resolved_period}), scoped to ${gotEntity}`,
  `count question: ${count.value} = independent ${expectedCount.count} (debits + credits)`,
  `verification ${ev.verification.checks.filter(c => c.passed).length}/${ev.verification.checks.length}, confidence ${ev.confidence.band} ${ev.confidence.score}`,
  `answer: ${res.answer}`);
