// G20: refusals are fixed-wording steers with guided next questions.
import { post, pass, fail } from './_lib.mjs';
const r = await post('/api/v1/chat', { message: 'what is my name?' });
if (r.state !== 'out_of_scope') fail('G20', `state=${r.state}, expected out_of_scope`);
if (!/isn't relevant to the services we provide/.test(r.message || '')) fail('G20', `wrong wording: ${r.message}`);
if (/does not relate|cannot be answered within|current context/i.test(r.message || '')) fail('G20', 'model wording leaked into the user message');
if (r.answer || r.evidence) fail('G20', 'refusal carried an answer or evidence');
const opts = r.clarification?.options ?? [];
if (opts.length < 3) fail('G20', `guided questions missing (${opts.length})`);
if (r.clarification?.field !== 'guided') fail('G20', 'guided options not flagged as guided');

const v = await post('/api/v1/chat', { message: 'How much did we spend with Tesla last month?' });
if (v.state !== 'data_unavailable') fail('G20', `unknown vendor state=${v.state}`);
if (!(v.clarification?.options?.length)) fail('G20', 'unknown vendor offered no vendor names');
if (!v.clarification.options.some(o => o.label === 'Acme Technologies')) fail('G20', 'vendor suggestions lack a real vendor');

// Picking a guided question must lead to a real, evidenced answer.
const g = await post('/api/v1/chat', { message: opts[0].value, conversation_id: r.conversation_id });
if (g.state !== 'answer' || !g.evidence) fail('G20', `guided question did not produce an answer (${g.state}: ${g.message || ''})`);
pass('G20', `out_of_scope: "${r.message.slice(0, 60)}..."`, `${opts.length} guided questions offered`,
     `unknown vendor offered ${v.clarification.options.length} vendors`, `guided pick -> answer: ${g.answer}`);
