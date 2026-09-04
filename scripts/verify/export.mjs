// G7: CSV export downloads and its rows reconcile with an independent total.
import { API, parseCsv, loadTransactions, sumWhere, pass, fail } from './_lib.mjs';

const txns = loadTransactions();
const maxDate = txns.map(r => r.txn_date).sort().at(-1);
const [y, m] = maxDate.split('-').map(Number);
const prev = m === 1 ? `${y-1}-12` : `${y}-${String(m-1).padStart(2,'0')}`;
const expected = sumWhere(txns, r => r.txn_date.startsWith(prev));

const url = `${API}/api/v1/export.csv?intent=total_spend&group_by=vendor&metric=sum&relative=last_month`;
const res = await fetch(url);
if (!res.ok) fail('G7', `export returned ${res.status}: ${await res.text()}`);

const ct = res.headers.get('content-type') || '';
if (!ct.includes('text/csv')) fail('G7', `wrong content-type: ${ct}`);
const cd = res.headers.get('content-disposition') || '';
if (!/attachment; filename=".+\.csv"/.test(cd)) fail('G7', `bad disposition: ${cd}`);

const rows = parseCsv(await res.text());
if (!rows.length) fail('G7', 'export was empty');
if (!('vendor_name' in rows[0])) fail('G7', 'export lacks a human-readable vendor_name');
if (!('value' in rows[0])) fail('G7', 'export lacks a value column');

const total = Math.round(rows.reduce((a, r) => a + Number(r.value), 0) * 100) / 100;
if (Math.abs(total - expected.total) > 0.05)
  fail('G7', `export sums to ${total}, independent total is ${expected.total}`);

const recordSum = rows.reduce((a, r) => a + Number(r.record_count), 0);
if (recordSum !== expected.count)
  fail('G7', `export record counts sum to ${recordSum}, expected ${expected.count}`);

// An invalid export request must be refused, not silently coerced.
// Note: vendor_spend grouped BY vendor with no named vendor is legitimate
// (spend across all vendors), so that is not the case to test. Ungrouped
// vendor_spend with no vendor names no entity at all and must be refused.
const bad = await fetch(`${API}/api/v1/export.csv?intent=vendor_spend&group_by=none&relative=last_month`);
if (bad.ok) fail('G7', 'ungrouped vendor_spend export with no vendor was accepted');

// And the legitimate grouped form must still work, or the refusal above would
// just be over-restriction rather than validation.
const grouped = await fetch(`${API}/api/v1/export.csv?intent=vendor_spend&group_by=vendor&relative=last_month`);
if (!grouped.ok) fail('G7', `grouped vendor_spend export was wrongly refused (${grouped.status})`);

pass('G7', `${rows.length} rows, sums to ${total} (independent ${expected.total})`,
     `record counts reconcile: ${recordSum}`,
     `ungrouped vendor_spend refused (${bad.status}), grouped form accepted (${grouped.status})`,
     `filename: ${cd.match(/filename="([^"]+)"/)[1]}`);
