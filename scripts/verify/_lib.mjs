// Shared helpers for gate verification scripts.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

export const API = process.env.TBX_API || 'http://127.0.0.1:8010';
export const ROOT = path.resolve(fileURLToPath(new URL('../..', import.meta.url)));

export async function post(pathname, body) {
  const res = await fetch(`${API}${pathname}`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`POST ${pathname} -> ${res.status} ${await res.text()}`);
  return res.json();
}

export async function get(pathname) {
  const res = await fetch(`${API}${pathname}`);
  if (!res.ok) throw new Error(`GET ${pathname} -> ${res.status}`);
  return res.json();
}

// Parse a CSV into rows of objects. Handles quoted fields.
export function parseCsv(text) {
  const rows = [];
  let field = '', row = [], inQuotes = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (inQuotes) {
      if (c === '"' && text[i + 1] === '"') { field += '"'; i++; }
      else if (c === '"') inQuotes = false;
      else field += c;
    } else if (c === '"') inQuotes = true;
    else if (c === ',') { row.push(field); field = ''; }
    else if (c === '\n') { row.push(field); rows.push(row); row = []; field = ''; }
    else if (c !== '\r') field += c;
  }
  if (field || row.length) { row.push(field); rows.push(row); }
  const header = rows.shift();
  return rows.filter(r => r.length === header.length)
             .map(r => Object.fromEntries(header.map((h, i) => [h, r[i]])));
}

// Independent computation from the source CSVs -- shares no code with the app.
export function loadTransactions() {
  return parseCsv(fs.readFileSync(path.join(ROOT, 'data/raw/transactions.csv'), 'utf8'));
}

export function sumWhere(rows, pred) {
  let total = 0, count = 0;
  for (const r of rows) if (pred(r)) { total += Number(r.amount); count++; }
  return { total: Math.round(total * 100) / 100, count };
}

export function inMonth(dateStr, ym) { return dateStr.startsWith(ym); }

export function pass(gate, ...notes) {
  for (const n of notes) console.log('  ' + n);
  console.log(`GATE_${gate}_PASS`);
  process.exit(0);
}

export function fail(gate, msg) {
  console.error(`GATE_${gate}_FAIL: ${msg}`);
  process.exit(1);
}
