// G15: no full account number reaches any response body, and every account-shaped field is masked.
import { API, fetchRetry, parseCsv, dataPath, loadTransactions, loadAccounts, defaultEntity, entityTokenFor, pass, fail } from './_lib.mjs';

const txns = loadTransactions();
const entity = defaultEntity(txns);
const accounts = loadAccounts();
const numbers = accounts.map(a => a.account_number).filter(n => n && n.length >= 8);
if (!numbers.length) fail('MASKING', 'account.csv has no account numbers to check against');
const utr = txns.find(r => r.entity_id === entity && r.utr_number)?.utr_number;
if (!utr) fail('MASKING', 'no plaintext UTR for the default entity in transaction.csv');

const ACCOUNT_KEYS = /^(account|account_number|masked|account_masked)$/;
function leaks(body) {
  const problems = [];
  for (const n of numbers) if (body.includes(n)) problems.push(`full account number ${n}`);
  let parsed;
  try { parsed = JSON.parse(body); } catch { parsed = null; }
  const walk = (v, path) => {
    if (Array.isArray(v)) v.forEach((x, i) => walk(x, `${path}[${i}]`));
    else if (v && typeof v === 'object') for (const [k, x] of Object.entries(v)) {
      if (ACCOUNT_KEYS.test(k) && typeof x === 'string' && !/^X+\d{4}$/.test(x)) problems.push(`${path}.${k}="${x}" is not masked`);
      walk(x, `${path}.${k}`);
    }
  };
  if (parsed) walk(parsed, '$');
  else if (body.startsWith('transaction_date,') || body.includes(',account,'))
    for (const r of parseCsv(body)) for (const [k, x] of Object.entries(r))
      if (ACCOUNT_KEYS.test(k) && !/^X+\d{4}$/.test(x)) problems.push(`csv ${k}="${x}" is not masked`);
  return problems;
}

const token = await entityTokenFor();
const scope = `entity_id=${encodeURIComponent(token)}`;

// Every question states its period and its side, so the run answers instead of asking, and the
// checker actually sees detail records rather than a clarification body.
async function chat(message) {
  const r = await fetchRetry(`${API}/api/v1/chat`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ message, entity_id: token }) });
  const body = await r.text();
  let state = '?';
  try { state = JSON.parse(body).state; } catch {}
  return { label: `chat "${message.slice(0, 48)}"`, body, state };
}
async function raw(path) {
  const r = await fetch(`${API}${path}`);
  return { label: `GET ${path.split('?')[0]}`, body: await r.text(), state: String(r.status) };
}

const samples = [
  await chat('show me my debit transactions last month'),
  await chat(`UTR ${utr}`),
  await chat('what is my balance?'),
  await chat('What are my largest debits last month?'),
  await chat('Who are my top counterparties by debits last month?'),
  await chat('How much did I spend with SWIGGY INSTAMART last month?'),
  await chat('list my debits under 500 rupees last month'),
  await chat('what credits did I receive last month?'),
  await raw(`${await dataPath('export.csv')}?intent=transaction_lookup&relative=last_90_days&limit=1000&${scope}`),
  await raw(`${await dataPath('accounts')}?${scope}`),
  await raw(`${await dataPath('transactions')}?${scope}&relative=all_time&limit=1000`),
];
const notes = [];
const failures = [];
for (const s of samples) {
  if (s.label.startsWith('chat ') && s.state !== 'answer')
    failures.push(`${s.label} did not answer (state=${s.state}); the checker saw no real body`);
  const p = leaks(s.body);
  notes.push(`${s.label} -> ${s.state}, ${s.body.length} bytes, ${p.length ? p.length + ' leaks' : 'clean'}`);
  if (p.length) failures.push(`${s.label}: ${[...new Set(p)].slice(0, 3).join('; ')}`);
}
if (!samples.some(s => s.label.startsWith('chat ') && s.body.includes('"records":[{')))
  failures.push('no chat sample carried records; the checker saw no detail rows');
const balance = samples.find(s => s.label.includes('balance'));
if (!balance || !/balance_total/.test(balance.body)) failures.push('the balance question produced no balance rows');
const exported = samples.find(s => s.label.includes('export.csv'));
if (!exported || parseCsv(exported.body).length === 0) failures.push('the CSV export was empty; nothing to check for leaks');

const control = leaks(JSON.stringify({ state: 'answer', evidence: { records: [{ account: numbers[0] }] }, answer: `paid from ${numbers[0]}` }));
if (!control.length) fail('MASKING', 'positive control passed: the checker cannot see a real account number');

if (failures.length) fail('MASKING', `\n  ${failures.join('\n  ')}`);
pass('MASKING', ...notes, `positive control caught ${control.length} leaks in a fake body`);
