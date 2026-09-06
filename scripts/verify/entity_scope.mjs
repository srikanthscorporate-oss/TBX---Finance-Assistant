// G27: a conversation is locked to one entity, entity ids never leave the API in the clear, and
// nothing is answered before an entity is chosen. Every figure is recomputed from data/raw/*.csv.
import fs from 'node:fs';
import path from 'node:path';
import { API, ROOT, fetchRetry, loadAccounts, loadTransactions, defaultEntity, lastMonthOf,
         sumWhere, entityTokenFor, pass, fail } from './_lib.mjs';

const GATE = 'ENTITY_SCOPE';
const txns = loadTransactions();
const entity = defaultEntity(txns);
const prev = lastMonthOf(txns);
const mine = txns.filter(r => r.entity_id === entity);

const accountsCsv = fs.readFileSync(path.join(ROOT, 'data/raw/account.csv'), 'utf8');
const rawEntities = [...new Set(loadAccounts().map(a => a.entity_id).filter(Boolean))];
if (rawEntities.length < 2) fail(GATE, 'account.csv has fewer than two entities; scoping proves nothing');

// Every body the flow produces is swept for a raw entity id at the end.
const bodies = [];
async function chat(body, label) {
  const res = await fetchRetry(`${API}/api/v1/chat`, {
    method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body),
  });
  const text = await res.text();
  bodies.push({ label, text });
  let parsed = null;
  try { parsed = JSON.parse(text); } catch { fail(GATE, `${label}: non-JSON body ${text.slice(0, 200)}`); }
  return parsed;
}

function findRawEntity(text) {
  return rawEntities.filter(e => text.includes(e));
}

// --- (a) no entity chosen: ask, with masked labels and opaque values -------------------------
const ask = await chat({ message: 'what is my balance?', conversation_id: `gate-entity-a-${Date.now()}` }, 'no entity');
if (ask.state !== 'clarification_required') fail(GATE, `no-entity state=${ask.state} (${ask.message || ''})`);
if (ask.clarification?.field !== 'entity') fail(GATE, `no-entity field=${ask.clarification?.field}`);
if (ask.answer || ask.evidence) fail(GATE, 'the entity clarification carried an answer or evidence');
const options = ask.clarification.options || [];
if (options.length < 2) fail(GATE, `entity clarification offered ${options.length} options`);
for (const o of options) {
  if (!/^\*+[0-9a-f]{4}$/.test(o.label)) fail(GATE, `entity option label is not masked: "${o.label}"`);
  if (!o.value || typeof o.value !== 'string') fail(GATE, `entity option has no value: ${JSON.stringify(o)}`);
  if (accountsCsv.includes(o.value)) fail(GATE, `entity option value "${o.value}" appears verbatim in account.csv`);
  if (rawEntities.includes(o.value)) fail(GATE, `entity option value is a raw uuid: ${o.value}`);
}
const labels = options.map(o => o.label);
const mask = e => '*'.repeat(e.length - 4) + e.slice(-4);
const known = new Set(rawEntities.map(mask));
for (const l of labels) if (!known.has(l)) fail(GATE, `offered label ${l} matches no entity in account.csv`);
if (!labels.includes(mask(entity)))
  fail(GATE, `the default entity is not offered as its masked form ${mask(entity)}`);

// --- (b) answering with a token answers the question ------------------------------------------
const token = await entityTokenFor();
const other = await entityTokenFor('other');
if (!other) fail(GATE, 'could not obtain a second entity token');
if (other === token) fail(GATE, 'the "other" token is the same string as the default token');

const conv = `gate-entity-${Date.now()}`;
const CP = 'SWIGGY INSTAMART';
const expected = sumWhere(mine, r => r.txn_date.startsWith(prev) && r.counterparty === CP
                                  && r.transaction_type === 'debit');
if (!expected.count) fail(GATE, `fixture has no ${CP} debits in ${prev}`);

const answered = await chat({ message: `How much did I spend with ${CP} last month?`,
                              entity_id: token, conversation_id: conv }, 'first token');
if (answered.state !== 'answer') fail(GATE, `token turn state=${answered.state} (${answered.message || ''})`);
const total = answered.evidence?.facts.find(f => f.key === 'total');
if (!total) fail(GATE, 'token turn produced no total fact');
if (Math.abs(Number(total.value) - expected.total) > 0.02)
  fail(GATE, `token turn figure ${total.value} != independent ${expected.total}`);

// --- (c) a different token on the same conversation is refused --------------------------------
const SWITCH = "I don't have any Idea what you're talking about.";
const switched = await chat({ message: `How much did I spend with ${CP} last month?`,
                              entity_id: other, conversation_id: conv }, 'switched token');
if (switched.state !== 'out_of_scope') fail(GATE, `entity switch state=${switched.state}, expected out_of_scope`);
if (!(switched.message || '').startsWith(SWITCH))
  fail(GATE, `entity switch message does not start with the fixed refusal: ${JSON.stringify((switched.message || '').slice(0, 120))}`);
if (switched.answer) fail(GATE, 'the refused switch carried an answer');
if (switched.evidence) fail(GATE, 'the refused switch carried evidence');
if (switched.plan) fail(GATE, 'the refused switch carried a plan');

// --- (d) the original token still answers -----------------------------------------------------
const CP2 = 'ZOMATO';
const expected2 = sumWhere(mine, r => r.txn_date.startsWith(prev) && r.counterparty === CP2
                                   && r.transaction_type === 'debit');
if (!expected2.count) fail(GATE, `fixture has no ${CP2} debits in ${prev}`);
const back = await chat({ message: `How much did I spend with ${CP2} last month?`,
                          entity_id: token, conversation_id: conv }, 'original token again');
if (back.state !== 'answer') fail(GATE, `same-token turn state=${back.state} (${back.message || ''})`);
const total2 = back.evidence?.facts.find(f => f.key === 'total');
if (!total2) fail(GATE, 'same-token turn produced no total fact');
if (Math.abs(Number(total2.value) - expected2.total) > 0.02)
  fail(GATE, `same-token figure ${total2.value} != independent ${expected2.total}`);

// --- (e) a tampered or garbage token never answers --------------------------------------------
const tampered = token.slice(0, -6) + (token.slice(-6, -5) === 'A' ? 'B' : 'A') + token.slice(-5);
const badTokens = [
  ['garbage token', 'not-a-real-entity-token'],
  ['tampered token', tampered],
  ['raw uuid as token', rawEntities[0]],
];
const badStates = [];
for (const [label, value] of badTokens) {
  const r = await chat({ message: 'what is my balance?', entity_id: value,
                         conversation_id: `gate-entity-bad-${label.replace(/\W/g, '')}-${Date.now()}` }, label);
  if (r.state === 'answer') fail(GATE, `${label} produced an answer: ${r.answer}`);
  if (r.evidence) fail(GATE, `${label} carried evidence`);
  badStates.push(`${label} -> ${r.state}`);
}

// --- (f) no raw entity uuid appears in any body, and the checker can see one -------------------
const leaked = [];
for (const b of bodies) for (const e of findRawEntity(b.text)) leaked.push(`${b.label}: ${e}`);
if (leaked.length) fail(GATE, `raw entity id in a response body -> ${[...new Set(leaked)].slice(0, 3).join('; ')}`);
const control = findRawEntity(JSON.stringify({ state: 'answer', evidence: { entities_resolved: { entity_id: rawEntities[0] } } }));
if (!control.length) fail(GATE, 'positive control passed: the checker cannot see a raw entity id');

pass(GATE,
  `no entity -> clarification field=entity, ${options.length} options, all labels masked (${labels[0]}) and no value in account.csv`,
  `token -> ${answered.answer} (independent ${expected.total} over ${expected.count} debits)`,
  `different token on the same conversation -> out_of_scope, fixed refusal, no answer/evidence/plan`,
  `original token again -> ${back.answer} (independent ${expected2.total} over ${expected2.count} debits)`,
  `rejected tokens: ${badStates.join(' | ')}`,
  `${bodies.length} bodies swept, none carried any of the ${rawEntities.length} raw entity ids; control caught ${control.length}`);
