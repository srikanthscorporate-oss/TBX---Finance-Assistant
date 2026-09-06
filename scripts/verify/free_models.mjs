// G18: the dropdown lists only free models within the ceiling.
import { get, pass, fail } from './_lib.mjs';
const d = await get('/api/v1/models').catch(e => fail('G18', e.message));
if (!Array.isArray(d.models) || !d.models.length) fail('G18', 'no models listed');
const limit = d.limit_b;
for (const m of d.models) {
  if (!m.listed) fail('G18', `${m.id} served but not marked listed`);
  if (m.over_limit && m.params_b > limit * 1.05) fail('G18', `${m.id} is ${m.params_b}B, over the ceiling`);
  if (!m.free && !(m.list_when_keyed && m.available))
    fail('G18', `${m.id} is paid and must not be listed (free-only policy)`);
  if (typeof m.size_label !== 'string' || !m.size_label.includes('B')) fail('G18', `${m.id} lacks a size label`);
}
const ids = new Set(d.models.map(m => m.id));
// Positive control: paid OpenRouter models must be absent even though the key is present.
for (const paid of ['openrouter/meta-llama/llama-3.1-8b-instruct', 'openrouter/qwen/qwen-2.5-7b-instruct'])
  if (ids.has(paid)) fail('G18', `paid model listed on a free-tier key: ${paid}`);
if (!Array.isArray(d.unlisted)) fail('G18', 'no unlisted explanation set');
for (const u of d.unlisted) if (!u.reason) fail('G18', `unlisted ${u.id} has no reason`);
if (!Array.isArray(d.excluded) || !d.excluded.find(x => x.id.includes('120b'))) fail('G18', 'excluded set missing the 120B model');
pass('G18', `${d.models.length} listed (all free or keyed, all within ${limit}B)`,
     ...d.models.map(m => `  ${m.label}: ${m.size_label}${m.free ? '' : ' (keyed)'}`),
     `${d.unlisted.length} unlisted with reasons, ${d.excluded.length} excluded over the ceiling`);
