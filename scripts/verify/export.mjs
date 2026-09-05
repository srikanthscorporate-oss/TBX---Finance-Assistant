// G7: CSV exports download, reconcile with an independent total, and never expose UTRs or account numbers.
import { API, parseCsv, dataPath, loadTransactions, defaultEntity, lastMonthOf, sumWhere, pass, fail } from './_lib.mjs';

const txns = loadTransactions();
const entity = defaultEntity(txns);
const prev = lastMonthOf(txns);
const mine = txns.filter(r => r.entity_id === entity && r.txn_date.startsWith(prev));
const expected = sumWhere(mine, r => r.transaction_type === 'debit');
// The export no longer forces debits, so a grouped export is only debit-only when asked to be.
function groupCp(pred) {
  const per = new Map();
  for (const r of mine) if (pred(r)) {
    const e = per.get(r.counterparty) || { total: 0, count: 0 };
    e.total += r.amount; e.count++; per.set(r.counterparty, e);
  }
  return per;
}
const perCp = groupCp(r => r.transaction_type === 'debit');
const perCpBoth = groupCp(() => true);
const expectedBoth = sumWhere(mine, () => true);
const exportPath = await dataPath('export.csv');

const url = `${API}${exportPath}?intent=spend_summary&group_by=counterparty&metric=sum&relative=last_month&transaction_type=debit`;
const res = await fetch(url);
if (!res.ok) fail('G7', `export returned ${res.status}: ${await res.text()}`);
const ct = res.headers.get('content-type') || '';
if (!ct.includes('text/csv')) fail('G7', `wrong content-type: ${ct}`);
const cd = res.headers.get('content-disposition') || '';
if (!/attachment; filename=".+\.csv"/.test(cd)) fail('G7', `bad disposition: ${cd}`);

const rows = parseCsv(await res.text());
if (!rows.length) fail('G7', 'export was empty');
if (!('counterparty' in rows[0])) fail('G7', 'grouped export lacks a counterparty column');
if (!('value' in rows[0])) fail('G7', 'export lacks a value column');
if (rows.length !== perCp.size) fail('G7', `export has ${rows.length} counterparties, independent ${perCp.size}`);
for (const r of rows) {
  const e = perCp.get(r.counterparty);
  if (!e) fail('G7', `export names an unexpected counterparty: ${r.counterparty}`);
  if (Math.abs(Number(r.value) - e.total) > 0.02) fail('G7', `${r.counterparty}: export ${r.value}, independent ${e.total.toFixed(2)}`);
  if (Number(r.record_count) !== e.count) fail('G7', `${r.counterparty}: export ${r.record_count} records, independent ${e.count}`);
}
const total = Math.round(rows.reduce((a, r) => a + Number(r.value), 0) * 100) / 100;
if (Math.abs(total - expected.total) > 0.05) fail('G7', `export sums to ${total}, independent debit total is ${expected.total}`);
const recordSum = rows.reduce((a, r) => a + Number(r.record_count), 0);
if (recordSum !== expected.count) fail('G7', `export record counts sum to ${recordSum}, expected ${expected.count}`);

// The same export with no transaction_type mixes both sides, and must equal the both-types sum.
const bothRes = await fetch(`${API}${exportPath}?intent=spend_summary&group_by=counterparty&metric=sum&relative=last_month`);
if (!bothRes.ok) fail('G7', `unfiltered export returned ${bothRes.status}: ${await bothRes.text()}`);
const bothRows = parseCsv(await bothRes.text());
if (bothRows.length !== perCpBoth.size)
  fail('G7', `unfiltered export has ${bothRows.length} counterparties, independent ${perCpBoth.size}`);
for (const r of bothRows) {
  const e = perCpBoth.get(r.counterparty);
  if (!e) fail('G7', `unfiltered export names an unexpected counterparty: ${r.counterparty}`);
  if (Math.abs(Number(r.value) - e.total) > 0.02)
    fail('G7', `${r.counterparty}: unfiltered export ${r.value}, independent both-types ${e.total.toFixed(2)}`);
  if (Number(r.record_count) !== e.count)
    fail('G7', `${r.counterparty}: unfiltered export ${r.record_count} records, independent ${e.count}`);
}
const bothTotal = Math.round(bothRows.reduce((a, r) => a + Number(r.value), 0) * 100) / 100;
if (Math.abs(bothTotal - expectedBoth.total) > 0.05)
  fail('G7', `unfiltered export sums to ${bothTotal}, independent both-types total is ${expectedBoth.total}`);
const bothRecords = bothRows.reduce((a, r) => a + Number(r.record_count), 0);
if (bothRecords !== expectedBoth.count)
  fail('G7', `unfiltered export record counts sum to ${bothRecords}, expected ${expectedBoth.count}`);
if (bothRecords === expected.count)
  fail('G7', 'the unfiltered export and the debit-only export cover the same rows; the filter proves nothing');

const det = await fetch(`${API}${exportPath}?intent=transaction_lookup&relative=last_month&limit=200`);
if (!det.ok) fail('G7', `detail export returned ${det.status}`);
const detRows = parseCsv(await det.text());
if (!detRows.length) fail('G7', 'detail export was empty');
if ('utr' in detRows[0] || /\butr\b/i.test(Object.keys(detRows[0]).join(','))) fail('G7', 'detail export carries a utr column');
if (!('account' in detRows[0])) fail('G7', 'detail export lacks the masked account column');
for (const r of detRows) if (!/^X+\d{4}$/.test(r.account)) fail('G7', `detail export exposes an account: ${r.account}`);
const utrs = new Set(txns.map(r => r.utr_number).filter(Boolean));
for (const r of detRows) for (const v of Object.values(r)) if (utrs.has(v)) fail('G7', `detail export contains a UTR: ${v}`);
for (const r of detRows) if (!r.transaction_date.startsWith(prev)) fail('G7', `detail row outside ${prev}: ${r.transaction_date}`);

const bad = await fetch(`${API}${exportPath}?intent=counterparty_spend&group_by=none&relative=last_month`);
if (bad.ok) fail('G7', 'ungrouped counterparty_spend export with no counterparty was accepted');
const badPeriod = await fetch(`${API}${exportPath}?intent=spend_summary&relative=next_decade`);
if (badPeriod.ok) fail('G7', 'unknown relative period was accepted');

pass('G7', `debit-only grouped by counterparty: ${rows.length} rows, sums to ${total} (independent ${expected.total}), every row matches`,
     `record counts reconcile: ${recordSum}`,
     `no transaction_type: ${bothRows.length} rows, sums to ${bothTotal} over ${bothRecords} records (independent both-types ${expectedBoth.total} / ${expectedBoth.count})`,
     `detail export: ${detRows.length} rows, no utr column, account column masked (whole-body leak check lives in masking.mjs)`,
     `ungrouped counterparty_spend refused (${bad.status}), unknown period refused (${badPeriod.status})`,
     `filename: ${cd.match(/filename="([^"]+)"/)[1]}`);
