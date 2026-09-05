import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

export const API = process.env.TBX_API || 'http://127.0.0.1:8010';
export const ROOT = path.resolve(fileURLToPath(new URL('../..', import.meta.url)));

// The API rate-limits chat per minute; a verifier waits the window out rather than failing on it.
export async function fetchRetry(url, init) {
  for (let attempt = 0; ; attempt++) {
    const res = await fetch(url, init);
    if (res.status !== 429 || attempt >= 12) return res;
    await new Promise(r => setTimeout(r, 6000));
  }
}

export async function post(pathname, body) {
  const res = await fetchRetry(`${API}${pathname}`, {
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

let dataPrefix = null;
// The browse endpoints are mounted at /api/v1/data/* in the cut-over layout and at /api/v1/* in
// the previous one; probe once so the verifiers work against either build.
export async function dataPath(name) {
  if (dataPrefix === null) {
    const r = await fetch(`${API}/api/v1/data/dataset`);
    dataPrefix = r.ok ? '/api/v1/data' : '/api/v1';
  }
  return `${dataPrefix}/${name}`;
}

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

export function loadAccounts() {
  return parseCsv(fs.readFileSync(path.join(ROOT, 'data/raw/account.csv'), 'utf8'));
}

export function loadBanks() {
  return parseCsv(fs.readFileSync(path.join(ROOT, 'data/raw/bank.csv'), 'utf8'));
}

// Each row gains entity_id, bank_code, txn_date (YYYY-MM-DD), amount (Number), counterparty and
// channel, mirroring what the loader stores so expectations can be filtered the same way.
export function loadTransactions() {
  const accounts = new Map(loadAccounts().map(a => [a.account_id, a]));
  const rows = parseCsv(fs.readFileSync(path.join(ROOT, 'data/raw/transaction.csv'), 'utf8'));
  for (const r of rows) {
    const a = accounts.get(r.account_id);
    r.entity_id = a ? a.entity_id : '';
    r.bank_code = a ? a.bank_code : '';
    r.txn_date = r.transaction_date.slice(0, 10);
    r.amount = Number(r.transaction_amount);
    const [cp, ch] = parseNarration(r.description);
    r.counterparty = cp;
    r.channel = ch;
  }
  return rows;
}

export function defaultEntity(txns) {
  const per = new Map();
  for (const r of txns) per.set(r.entity_id, (per.get(r.entity_id) || 0) + 1);
  let best = '', n = -1;
  for (const [e, c] of per) if (c > n || (c === n && e < best)) { best = e; n = c; }
  return best;
}

export function sumWhere(rows, pred) {
  let total = 0, count = 0;
  for (const r of rows) if (pred(r)) { total += r.amount; count++; }
  return { total: Math.round(total * 100) / 100, count };
}

export function maxDate(txns) {
  let m = '';
  for (const r of txns) if (r.txn_date > m) m = r.txn_date;
  return m;
}

// Calendar month n months before the month of `dateStr`, as YYYY-MM.
export function monthsBefore(dateStr, n) {
  const [y, m] = dateStr.split('-').map(Number);
  const t = m - n;
  const yy = y + Math.floor((t - 1) / 12);
  const mm = ((t - 1) % 12 + 12) % 12 + 1;
  return `${yy}-${String(mm).padStart(2, '0')}`;
}

export function inMonth(dateStr, ym) { return dateStr.startsWith(ym); }

export function lastMonthOf(txns) { return monthsBefore(maxDate(txns), 1); }

export function pass(gate, ...notes) {
  for (const n of notes) console.log('  ' + n);
  console.log(`GATE_${gate}_PASS`);
  process.exit(0);
}

export function fail(gate, msg) {
  console.error(`GATE_${gate}_FAIL: ${msg}`);
  process.exit(1);
}

// Port of apps/api/app/services/narration.py; kept rule-for-rule so the expectation side of a
// gate classifies rows exactly as the loader did.
const IFSC = /^[A-Z]{4}0[A-Z0-9]{6}$/;
const NUMERIC = /^[\d\s/-]+$/;
const MASKED = /^X{2,}\d+$/i;
const MULTI_SPACE = /\s{2,}/;
const SUFFIX = /\s*(?:INWD\d*|OUTWD\d*|DPF\d+|BPES\s*DPF\d+)\s*$/i;

function isAlpha(c) { return /\p{L}/u.test(c); }

function stripChars(s, chars) {
  let a = 0, b = s.length;
  while (a < b && chars.includes(s[a])) a++;
  while (b > a && chars.includes(s[b - 1])) b--;
  return s.slice(a, b);
}

function clean(s) {
  s = s.trim().replace(SUFFIX, '');
  s = s.replace(/\s+/g, ' ');
  return stripChars(s, ' -/').toUpperCase();
}

function isName(seg) {
  seg = seg.trim();
  if (seg.length < 3 || NUMERIC.test(seg) || IFSC.test(seg) || MASKED.test(seg)) return false;
  let letters = 0;
  for (const c of seg) if (isAlpha(c)) letters++;
  return letters >= 3 && letters >= seg.length * 0.6;
}

function longestName(segments) {
  const names = segments.filter(isName);
  if (!names.length) return '';
  let best = names[0];
  for (const n of names) if (n.length > best.length) best = n;
  return clean(best);
}

export function parseNarration(desc) {
  const d = desc.trim();
  if (!d) return ['', 'OTHER'];
  const u = d.toUpperCase();

  if (u.includes('CHARGE') || u.includes(' FEE') || u.startsWith('GST')) return [clean(d), 'CHARGES'];

  if (u.startsWith('UPI')) {
    const parts = d.split(/[-/]/).filter(p => p.trim());
    const name = parts.length > 1 && isName(parts[1]) ? parts[1] : longestName(parts.slice(1));
    return [clean(name), 'UPI'];
  }

  if (u.startsWith('IMPS')) {
    const parts = d.split('/').map(p => p.trim()).filter(Boolean);
    const upper = parts.map(p => p.toUpperCase());
    const after = upper.includes('INET') ? parts.slice(upper.indexOf('INET') + 1) : parts.slice(1);
    const name = after.find(isName) || longestName(parts.slice(1));
    return [clean(name), 'IMPS'];
  }

  if (u.startsWith('NEFT') || u.startsWith('RTGS')) {
    const rail = u.startsWith('NEFT') ? 'NEFT' : 'RTGS';
    const sep = d.includes('/') && !d.includes(' - ') ? '/' : ' - ';
    const parts = d.split(sep).filter(p => p.trim());
    const last = parts[parts.length - 1];
    const name = parts.length > 1 && isName(last) ? last : longestName(parts.slice(1));
    return [clean(name.split(MULTI_SPACE)[0]), rail];
  }

  if (u.startsWith('FT')) {
    const parts = d.split(' - ').filter(p => p.trim());
    let tail = parts.length > 1 ? parts[parts.length - 1] : '';
    if (!isName(tail) && d.includes('-')) tail = d.split('-').at(-1);
    const name = tail.trim().split(MULTI_SPACE)[0];
    return [clean(name), 'FT'];
  }

  if (u.startsWith('R/') || d.includes('//')) {
    const after = d.includes('//') ? d.split('//').slice(1).join('//') : d;
    const parts = after.split('/').filter(p => p.trim());
    return [clean(longestName(parts)), 'OTHER'];
  }

  if (u.includes('CHEQUE') || u.includes('CHQ')) return ['CHEQUE DEPOSIT', 'CHEQUE'];
  if (u.includes('INTEREST')) return ['INTEREST', 'INTEREST'];

  const parts = d.split(/[/|-]/).filter(p => p.trim());
  return [clean(longestName(parts) || d.slice(0, 60)), 'OTHER'];
}
