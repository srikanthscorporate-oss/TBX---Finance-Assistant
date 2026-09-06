// G14: the scale database holds >=20M encrypted transactions and every compiler-shaped query is in budget.
import fs from 'node:fs';
import path from 'node:path';
import { ROOT, pass, fail } from './_lib.mjs';

const CH = process.env.CH_URL || 'http://localhost:18123';
const AUTH = `user=${process.env.CH_AGENT_USER || 'tbx_agent'}&password=${process.env.CH_AGENT_PASSWORD || 'change-me-agent'}`;
const DB = 'tbx_finance_scale';
const REQUIRED_ROWS = 20_000_000;
const BUDGET_MS = 1000;

async function q(sql, params = {}) {
  const qs = Object.entries(params).map(([k, v]) => `param_${k}=${encodeURIComponent(v)}`).join('&');
  const r = await fetch(`${CH}/?${AUTH}&default_format=JSON&${qs}`, { method: 'POST', body: sql });
  if (!r.ok) fail('G14', `query failed: ${await r.text()}`);
  const d = await r.json();
  return { rows: d.data, ms: (d.statistics?.elapsed ?? 0) * 1000, read: d.statistics?.rows_read ?? 0 };
}

const liveBefore = Number((await q('SELECT count() AS n FROM tbx_finance.transaction')).rows[0].n);
if (!liveBefore) fail('G14', 'live tbx_finance.transaction is empty');

const count = Number((await q(`SELECT count() AS n FROM ${DB}.transaction`)).rows[0].n);
if (count < REQUIRED_ROWS) fail('G14', `scale table has ${count.toLocaleString()} rows, need ${REQUIRED_ROWS.toLocaleString()}`);

const reportPath = path.join(ROOT, 'data/processed/data_quality_bank_20m.json');
if (!fs.existsSync(reportPath)) fail('G14', 'no data-quality report for the scale load');
const rep = JSON.parse(fs.readFileSync(reportPath, 'utf8'));
if (rep.referential_problems?.length) fail('G14', `referential problems: ${rep.referential_problems.join('; ')}`);
const txn = rep.tables.find(t => t.file === 'transaction.csv');
if (!txn || txn.duplicate_ids !== 0) fail('G14', `duplicate ids in scale load: ${txn?.duplicate_ids}`);
if (txn.rows < REQUIRED_ROWS) fail('G14', `report covers ${txn.rows} rows`);

// Rows without a UTR in the source (UPI, charges, interest) store empty strings; every row that has one must carry ciphertext and a blind index.
const enc = (await q(`SELECT countIf(utr_enc != '' AND utr_hash = '') AS unindexed, countIf(utr_enc = '' AND utr_hash != '') AS hashonly, countIf(match(utr_enc, '^[0-9a-f]{32}==$')) AS plain, countIf(utr_enc != '') AS withUtr FROM ${DB}.transaction`)).rows[0];
if (Number(enc.unindexed) || Number(enc.hashonly)) fail('G14', `${enc.unindexed} rows lack a blind index, ${enc.hashonly} rows carry a hash with no ciphertext`);
if (Number(enc.plain)) fail('G14', `${enc.plain} scale rows store the UTR in plaintext`);
if (Number(enc.withUtr) < count / 2) fail('G14', `only ${enc.withUtr} of ${count} scale rows carry a UTR`);
const entities = Number((await q(`SELECT uniqExact(entity_id) AS n FROM ${DB}.transaction`)).rows[0].n);
if (entities < 100) fail('G14', `only ${entities} entities at scale`);

const busiest = (await q(`SELECT entity_id, count() AS c FROM ${DB}.transaction GROUP BY entity_id ORDER BY c DESC LIMIT 1`)).rows[0];
const entity = busiest.entity_id;
const account = (await q(`SELECT account_id FROM ${DB}.transaction WHERE entity_id = {entity_id:String} GROUP BY account_id ORDER BY count() DESC LIMIT 1`, { entity_id: entity })).rows[0].account_id;
const counterparty = (await q(`SELECT counterparty FROM ${DB}.transaction WHERE entity_id = {entity_id:String} GROUP BY counterparty ORDER BY count() DESC LIMIT 1`, { entity_id: entity })).rows[0].counterparty;
const maxDate = (await q(`SELECT max(txn_date) AS d FROM ${DB}.transaction`)).rows[0].d;
const [y, m] = maxDate.split('-').map(Number);
const py = m === 1 ? y - 1 : y, pm = m === 1 ? 12 : m - 1;
const mStart = `${py}-${String(pm).padStart(2, '0')}-01`;
const mEndNext = `${y}-${String(m).padStart(2, '0')}-01`;
const maxNext = new Date(Date.UTC(y, m - 1, Number(maxDate.slice(8, 10)) + 1)).toISOString().slice(0, 10);
const qStart = `${y}-${String(Math.floor((m - 1) / 3) * 3 + 1).padStart(2, '0')}-01`;
const hash = (await q(`SELECT utr_hash FROM ${DB}.transaction WHERE entity_id = {entity_id:String} AND utr_hash != '' LIMIT 1`, { entity_id: entity })).rows[0].utr_hash;

const shapes = [
  ['entity month debit sum', `SELECT sum(t.transaction_amount) AS value, count() AS record_count, uniqExact(t.transaction_type) AS type_variants FROM ${DB}.transaction AS t WHERE t.entity_id = {entity_id:String} AND t.transaction_date >= toDateTime64({d_start:Date}, 6) AND t.transaction_date < toDateTime64({d_end_next:Date}, 6) AND t.transaction_type = {transaction_type:String}`,
    { entity_id: entity, d_start: mStart, d_end_next: mEndNext, transaction_type: 'debit' }],
  ['entity counterparty count', `SELECT count() AS value, count() AS record_count, uniqExact(t.transaction_type) AS type_variants FROM ${DB}.transaction AS t WHERE t.entity_id = {entity_id:String} AND t.counterparty = {counterparty:String}`,
    { entity_id: entity, counterparty }],
  ['entity+account month trend', `SELECT toStartOfMonth(t.txn_date) AS month, sum(t.transaction_amount) AS value, count() AS record_count FROM ${DB}.transaction AS t WHERE t.entity_id = {entity_id:String} AND t.account_id = {account_id:String} AND t.transaction_type = {transaction_type:String} GROUP BY month ORDER BY month ASC LIMIT {row_limit:UInt32}`,
    { entity_id: entity, account_id: account, transaction_type: 'debit', row_limit: 100 }],
  ['utr_hash lookup', `SELECT t.transaction_id AS transaction_id, t.utr_enc AS utr_enc, count() OVER () AS total_matches FROM ${DB}.transaction AS t WHERE t.entity_id = {entity_id:String} AND t.utr_hash = {utr_hash:String} ORDER BY t.transaction_date DESC, t.transaction_id LIMIT {row_limit:UInt32}`,
    { entity_id: entity, utr_hash: hash, row_limit: 100 }],
  ['largest 10 debits in a quarter', `SELECT t.transaction_id AS transaction_id, t.transaction_amount AS transaction_amount, count() OVER () AS total_matches FROM ${DB}.transaction AS t WHERE t.entity_id = {entity_id:String} AND t.transaction_date >= toDateTime64({d_start:Date}, 6) AND t.transaction_date < toDateTime64({d_end_next:Date}, 6) AND t.transaction_type = {transaction_type:String} ORDER BY t.transaction_amount DESC, t.transaction_id LIMIT {row_limit:UInt32}`,
    { entity_id: entity, d_start: qStart, d_end_next: maxNext, transaction_type: 'debit', row_limit: 10 }],
  ['full-table total', `SELECT sum(t.transaction_amount) AS value, count() AS record_count FROM ${DB}.transaction AS t WHERE 1`, {}],
  ['monthly trend, all entities', `SELECT toStartOfMonth(t.txn_date) AS month, sum(t.transaction_amount) AS value, count() AS record_count FROM ${DB}.transaction AS t WHERE 1 GROUP BY month ORDER BY month ASC LIMIT {row_limit:UInt32}`, { row_limit: 1000 }],
];
const timings = [];
let entityMonthRead = null;
for (const [label, sql, params] of shapes) {
  const { ms, read, rows } = await q(sql, params);
  if (!rows.length) fail('G14', `${label}: returned no rows at scale`);
  if (ms > BUDGET_MS) fail('G14', `${label}: ${ms.toFixed(0)}ms exceeds ${BUDGET_MS}ms budget`);
  if (label === 'entity month debit sum') entityMonthRead = read;
  timings.push(`${label}: ${ms.toFixed(1)}ms (read ${read.toLocaleString()} rows)`);
}
if (entityMonthRead >= 2_000_000) {
  for (const t of timings) console.log('  ' + t);
  fail('G14', `entity-month query read ${entityMonthRead.toLocaleString()} rows (limit 2,000,000); the compiler filters on the materialized txn_date, which ClickHouse does not use for partition pruning, while a filter on transaction_date would prune to one partition`);
}

const liveAfter = Number((await q('SELECT count() AS n FROM tbx_finance.transaction')).rows[0].n);
if (liveAfter !== liveBefore) fail('G14', `live dataset changed during the gate: ${liveBefore} -> ${liveAfter}`);

pass('G14', `${count.toLocaleString()} rows loaded in ${rep.load_seconds}s across ${entities} entities, referential integrity clean, 0 duplicate ids, ${Number(enc.withUtr).toLocaleString()} UTRs encrypted with blind index`,
     `busiest entity ${entity.slice(0, 8)}, period ${mStart}..${mEndNext}`,
     ...timings, `live tbx_finance.transaction unchanged (${liveBefore.toLocaleString()} rows)`);
