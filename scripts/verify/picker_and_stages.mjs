// G21: picker structure and stage sequencing, checked in source and in the API.
import fs from 'node:fs';
import path from 'node:path';
import { ROOT, get, pass, fail } from './_lib.mjs';
const pk = fs.readFileSync(path.join(ROOT, 'apps/web/components/ModelPicker.tsx'), 'utf8');
if (/<select\b/.test(pk)) fail('G21', 'still a native select');
if (!/role="listbox"/.test(pk) || !/role="option"/.test(pk)) fail('G21', 'not an ARIA listbox');
if (!/max-h-\[\d+px\] overflow-y-auto/.test(pk)) fail('G21', 'list is not height-capped and scrollable');
for (const p of ["'groq'", "'openrouter'", "'sarvam'"]) if (!pk.includes(p)) fail('G21', `provider group missing: ${p}`);
if (!/ArrowDown/.test(pk) || !/Escape/.test(pk)) fail('G21', 'keyboard navigation missing');
if (!/filter\(m => m\.listed\)/.test(pk)) fail('G21', 'picker does not restrict to listed (free) models');
const d = await get('/api/v1/models');
for (const m of d.models) if (!m.free && !m.list_when_keyed) fail('G21', `paid model served: ${m.id}`);

const st = fs.readFileSync(path.join(ROOT, 'apps/web/lib/stages.ts'), 'utf8');
if (!/if \(!evs\.length\) return \[\];/.test(st)) fail('G21', 'stages still render before they start');
if (!/running && i === lastIndex \? 'active' : 'done'/.test(st)) fail('G21', 'more than one stage could be active');
const wb = fs.readFileSync(path.join(ROOT, 'apps/web/components/Workbench.tsx'), 'utf8');
if (!/DWELL_MS\s*=\s*(\d+)/.test(wb)) fail('G21', 'no minimum dwell between stage reveals');
const dwell = Number(wb.match(/DWELL_MS\s*=\s*(\d+)/)[1]);
if (dwell < 200) fail('G21', `dwell ${dwell}ms too short to read`);
if (!/queue\.shift\(\)/.test(wb)) fail('G21', 'events are not released sequentially');
pass('G21', 'ARIA listbox, provider groups, capped + scrollable, keyboard',
     `${d.models.length} free models served`, `stages reveal on start, one active, ${dwell}ms dwell`);
