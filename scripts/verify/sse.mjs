// G4: the SSE endpoint streams ordered agent events and terminates cleanly.
import { API, pass, fail } from './_lib.mjs';

const res = await fetch(`${API}/api/v1/chat/stream`, {
  method: 'POST',
  headers: { 'content-type': 'application/json' },
  body: JSON.stringify({ message: 'How much did we spend with Acme Technologies last month?' }),
});
if (!res.ok) fail('G4', `stream returned ${res.status}`);
if (!(res.headers.get('content-type') || '').includes('text/event-stream'))
  fail('G4', `wrong content-type: ${res.headers.get('content-type')}`);

const text = await res.text();
const events = [...text.matchAll(/^event: (\S+)\ndata: (.*)$/gm)]
  .map(m => ({ type: m[1], data: JSON.parse(m[2]) }));

if (events.length < 5) fail('G4', `only ${events.length} events streamed`);

const types = events.map(e => e.type);
for (const required of ['run_started', 'intent_detected', 'query_executed',
                        'verification_completed', 'run_completed'])
  if (!types.includes(required)) fail('G4', `missing event: ${required}`);

if (types[0] !== 'run_started') fail('G4', `first event was ${types[0]}`);
if (types.at(-1) !== 'final') fail('G4', `last event was ${types.at(-1)}, expected final`);

// Sequence numbers must be strictly increasing across agent events.
const seqs = events.filter(e => e.type !== 'final').map(e => e.data.seq);
for (let i = 1; i < seqs.length; i++)
  if (seqs[i] <= seqs[i - 1]) fail('G4', `seq not increasing: ${seqs}`);

// verification must be reported before the answer is generated.
if (types.indexOf('verification_completed') > types.indexOf('answer_generated'))
  fail('G4', 'answer generated before verification completed');

const final = events.at(-1).data;
if (final.state !== 'answer' || !final.evidence) fail('G4', 'final payload incomplete');

// The timeline must not leak model reasoning.
if (/chain of thought|reasoning:|let me think/i.test(text))
  fail('G4', 'stream appears to expose model reasoning');

pass('G4', `${events.length} events`, `order: ${types.join(' -> ')}`);
