// G4: the SSE endpoint streams ordered agent events and terminates cleanly.
import { API, fetchRetry, entityTokenFor, pass, fail } from './_lib.mjs';

// A fresh amount bound each run so the judge's answer cache cannot short-circuit the query stage.
// The question is fully specified -- period, side ("spend" = debits) and an exact counterparty --
// so the run reaches query_executed instead of stopping at a clarification.
const nonce = 100000 + (Date.now() % 900000);
const res = await fetchRetry(`${API}/api/v1/chat/stream`, {
  method: 'POST',
  headers: { 'content-type': 'application/json' },
  body: JSON.stringify({
    message: `How much did I spend with SWIGGY INSTAMART last month, under ${nonce} rupees?`,
    entity_id: await entityTokenFor(),
  }),
});
if (!res.ok) fail('G4', `stream returned ${res.status}`);
if (!(res.headers.get('content-type') || '').includes('text/event-stream'))
  fail('G4', `wrong content-type: ${res.headers.get('content-type')}`);

const text = await res.text();
const events = [...text.matchAll(/^event: (\S+)\ndata: (.*)$/gm)]
  .map(m => ({ type: m[1], data: JSON.parse(m[2]) }));

if (events.length < 5) fail('G4', `only ${events.length} events streamed`);

const types = events.map(e => e.type);
for (const required of ['run_started', 'intent_detected', 'entity_resolved', 'query_executed',
                        'verification_completed', 'run_completed'])
  if (!types.includes(required)) fail('G4', `missing event: ${required} in ${types.join(' -> ')}`);

if (types[0] !== 'run_started') fail('G4', `first event was ${types[0]}`);
if (types.at(-1) !== 'final') fail('G4', `last event was ${types.at(-1)}, expected final`);

const seqs = events.filter(e => e.type !== 'final').map(e => e.data.seq);
for (let i = 1; i < seqs.length; i++)
  if (seqs[i] <= seqs[i - 1]) fail('G4', `seq not increasing: ${seqs}`);

if (types.indexOf('verification_completed') > types.indexOf('answer_generated'))
  fail('G4', 'answer generated before verification completed');

const ent = events.find(e => e.type === 'entity_resolved');
if (!ent.data.detail || !('counterparty' in ent.data.detail || 'account' in ent.data.detail))
  fail('G4', `entity_resolved detail carries neither counterparty nor account: ${JSON.stringify(ent.data.detail)}`);

const final = events.at(-1).data;
if (final.state !== 'answer' || !final.evidence) fail('G4', `final payload incomplete (${final.state}: ${final.message || ''})`);
if (/\d{10,}/.test(JSON.stringify(final.evidence.entities_resolved))) fail('G4', 'entities_resolved carries a long number');

if (/chain of thought|reasoning:|let me think/i.test(text))
  fail('G4', 'stream appears to expose model reasoning');

pass('G4', `${events.length} events`, `order: ${types.join(' -> ')}`,
     `entity_resolved: ${JSON.stringify(ent.data.detail)}`);
