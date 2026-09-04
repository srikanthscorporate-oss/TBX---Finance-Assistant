// G14: the 20M-record test limit from Section 7. The scale database holds at
// least 20M transactions, referential integrity is clean, and every compiler-
// shaped query answers within budget. Measured with ClickHouse's own timing,
// not a copied number.
import fs from 'node:fs';
import path from 'node:path';
import { ROOT, pass, fail } from './_lib.mjs';

const CH = process.env.CH_URL || 'http://localhost:18123';
const AUTH = `user=${process.env.CH_ADMIN_USER || 'tbx_admin'}&password=${process.env.CH_ADMIN_PASSWORD || 'change-me-admin'}`;
const DB = 'tbx_finance_scale';
const REQUIRED_ROWS = 20_000_000;
const BUDGET_MS = 500;   // per query; the API's own timeout is 10s, so this is strict

async function q(sql) {
  const r = await fetch(`${CH}/?${AUTH}&default_format=JSON`, { method: 'POST', body: sql });
  if (!r.ok) fail('G14', `query failed: ${await r.text()}`);
  const d = await r.json();
  return { rows: d.data, ms: (d.statistics?.elapsed ?? 0) * 1000, read: d.statistics?.rows_read ?? 0 };
}

const count = Number((await q(`SELECT count() AS n FROM ${DB}.transactions`)).rows[0].n);
if (count < REQUIRED_ROWS) fail('G14', `scale table has ${count.toLocaleString()} rows, need ${REQUIRED_ROWS.toLocaleString()}`);

// The load must have finished cleanly, with the report the loader writes.
const reportPath = path.join(ROOT, 'data/processed/data_quality_20m.json');
if (!fs.existsSync(reportPath)) fail('G14', 'no data-quality report for the scale load');
const rep = JSON.parse(fs.readFileSync(reportPath, 'utf8'));
if (rep.referential_problems?.length) fail('G14', `referential problems: ${rep.referential_problems.join('; ')}`);
const txn = rep.tables.find(t => t.file === 'transactions.csv');
if (!txn || txn.duplicate_ids !== 0) fail('G14', `duplicate ids in scale load: ${txn?.duplicate_ids}`);

// Every shape the compiler emits, at full scale.
const shapes = [
  ['vendor spend, one month', `SELECT sum(amount) v, count() c FROM ${DB}.transactions WHERE txn_date BETWEEN '2026-07-01' AND '2026-07-31' AND vendor_id='V1001'`],
  ['top vendors, one month',  `SELECT vendor_id, sum(amount) v, count() c FROM ${DB}.transactions WHERE txn_date BETWEEN '2026-07-01' AND '2026-07-31' GROUP BY vendor_id ORDER BY v DESC LIMIT 10`],
  ['unreconciled, all time',  `SELECT count() c FROM ${DB}.transactions WHERE reconciliation_status IN ('unmatched','pending','disputed')`],
  ['full-table total',        `SELECT sum(amount) v, count() c FROM ${DB}.transactions`],
  ['monthly trend, all time', `SELECT toStartOfMonth(txn_date) m, sum(amount) v FROM ${DB}.transactions GROUP BY m ORDER BY m`],
  ['reconciliation rate',     `SELECT countIf(reconciliation_status='matched')/count()*100 r FROM ${DB}.transactions WHERE txn_date >= '2026-03-01'`],
];
const timings = [];
for (const [label, sql] of shapes) {
  const { ms, read, rows } = await q(sql);
  if (!rows.length) fail('G14', `${label}: returned no rows at scale`);
  if (ms > BUDGET_MS) fail('G14', `${label}: ${ms.toFixed(0)}ms exceeds ${BUDGET_MS}ms budget`);
  timings.push(`${label}: ${ms.toFixed(1)}ms (read ${read.toLocaleString()})`);
}

// Partition pruning must actually work: a one-month query must not scan the table.
const pruned = await q(`SELECT count() c FROM ${DB}.transactions WHERE txn_date BETWEEN '2026-07-01' AND '2026-07-31'`);
if (pruned.read > count / 4) fail('G14', `one-month query read ${pruned.read.toLocaleString()} of ${count.toLocaleString()} rows: partition pruning not effective`);

// And the live golden dataset must be untouched by the scale load.
const live = Number((await q(`SELECT count() AS n FROM tbx_finance.transactions`)).rows[0].n);
if (live !== 3373) fail('G14', `live dataset was disturbed by the scale load: ${live} rows`);

pass('G14', `${count.toLocaleString()} rows loaded in ${rep.load_seconds}s, referential integrity clean, 0 duplicate ids`,
     ...timings, `one-month query read ${pruned.read.toLocaleString()} rows (pruned)`, `live dataset untouched (${live} rows)`);
