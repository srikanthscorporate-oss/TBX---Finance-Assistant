// G22: refusals are fixed-wording steers with guided next questions.
import { post, get, dataPath, pass, fail } from './_lib.mjs';
const r = await post('/api/v1/chat', { message: 'what is my name?' });
if (r.state !== 'out_of_scope') fail('G22', `state=${r.state}, expected out_of_scope`);
if (!/isn't relevant to the services we provide/.test(r.message || '')) fail('G22', `wrong wording: ${r.message}`);
if (/does not relate|cannot be answered within|current context/i.test(r.message || '')) fail('G22', 'model wording leaked into the user message');
if (r.answer || r.evidence) fail('G22', 'refusal carried an answer or evidence');
const opts = r.clarification?.options ?? [];
if (opts.length < 3) fail('G22', `guided questions missing (${opts.length})`);
if (r.clarification?.field !== 'guided') fail('G22', 'guided options not flagged as guided');

const known = new Set((await get(await dataPath('counterparties?limit=500'))).map(c => c.name));
const v = await post('/api/v1/chat', { message: 'How much did I spend with Tesla last month?' });
if (v.state !== 'data_unavailable') fail('G22', `unknown counterparty state=${v.state}`);
const sugg = v.clarification?.options ?? [];
if (!sugg.length) fail('G22', 'unknown counterparty offered no counterparty names');
if (v.clarification.field !== 'counterparty') fail('G22', `suggestions field=${v.clarification.field}`);
for (const o of sugg) if (!known.has(o.value)) fail('G22', `suggested a counterparty that does not exist: ${o.value}`);

const g = await post('/api/v1/chat', { message: opts[0].value, conversation_id: r.conversation_id });
if (g.state !== 'answer' || !g.evidence) fail('G22', `guided question did not produce an answer (${g.state}: ${g.message || ''})`);
pass('G22', `out_of_scope: "${r.message.slice(0, 60)}..."`, `${opts.length} guided questions offered`,
     `unknown counterparty offered ${sugg.length} real counterparties (${sugg.slice(0, 3).map(o => o.label).join(', ')}...)`,
     `guided pick -> answer: ${g.answer}`);
