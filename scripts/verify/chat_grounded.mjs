// G2: the answer's figure equals an independently computed value from the CSVs.
// The expected number is computed HERE from source data -- never copied from
// the API response -- so this gate can actually fail.
import { post, loadTransactions, sumWhere, pass, fail } from './_lib.mjs';

const txns = loadTransactions();

// Anchor: the dataset's own max month minus one = what "last month" must mean.
const maxDate = txns.map(r => r.txn_date).sort().at(-1);
const [y, m] = maxDate.split('-').map(Number);
const prev = m === 1 ? `${y - 1}-12` : `${y}-${String(m - 1).padStart(2, '0')}`;

const expected = sumWhere(txns, r => r.txn_date.startsWith(prev) && r.vendor_id === 'V1001');
if (expected.count === 0) fail('G2', 'fixture produced no rows; cannot prove anything');

const res = await post('/api/v1/chat',
  { message: 'How much did we spend with Acme Technologies last month?' });

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

// The rendered sentence must contain the verified figure, not some other number.
const rendered = total.formatted.replace(/[^\d]/g, '');
if (!res.answer.replace(/[^\d]/g, '').includes(rendered))
  fail('G2', `answer text does not carry the verified figure: ${res.answer}`);

// Grounding apparatus must actually be present and passing.
if (!ev.verification || ev.verification.checks.length < 3)
  fail('G2', 'verification checks missing');
const blockingFailed = ev.verification.checks.filter(c => !c.passed && c.severity === 'blocking');
if (blockingFailed.length) fail('G2', `blocking checks failed: ${blockingFailed.map(c => c.name)}`);
if (!ev.confidence || typeof ev.confidence.score !== 'number')
  fail('G2', 'no deterministic confidence');
if (!ev.sql || !ev.sql.includes('{')) fail('G2', 'evidence does not expose parameterized SQL');
if (/V1001/.test(ev.sql)) fail('G2', 'entity id was interpolated into SQL text, not bound');

pass('G2',
  `independent: ${expected.total} over ${expected.count} rows (${prev})`,
  `api:         ${got} over ${ev.total_record_count} rows (${ev.resolved_period})`,
  `verification ${ev.verification.checks.filter(c => c.passed).length}/${ev.verification.checks.length}, confidence ${ev.confidence.band} ${ev.confidence.score}`,
  `answer: ${res.answer}`);
