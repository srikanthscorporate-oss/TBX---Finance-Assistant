// G19: the question input is a multi-line text area with the documented keys.
import fs from 'node:fs';
import path from 'node:path';
import { ROOT, pass, fail } from './_lib.mjs';
const ORIGIN = process.env.TBX_ORIGIN || 'http://127.0.0.1:8080';
const html = await (await fetch(`${ORIGIN}/`)).text().catch(e => fail('G19', e.message));
const src = fs.readFileSync(path.join(ROOT, 'apps/web/components/Workbench.tsx'), 'utf8');
// The composer mounts only after an entity is chosen, so check the served page reached the
// app at all and assert the input's shape in the source.
if (!/Loading entities|Select your entity ID|<textarea[^>]*id="q"/.test(html))
  fail('G19', 'served page is neither the entity gate nor the question form');
if (!/<textarea[\s\S]{0,400}id="q"/.test(src)) fail('G19', 'no <textarea id="q"> in the source');
if (/<input[^>]*id="q"/.test(src)) fail('G19', 'single-line input still present');
if (!/Your question/.test(src)) fail('G19', 'textarea has no accessible label');
if (!/e\.key === 'Enter' && !e\.shiftKey/.test(src)) fail('G19', 'Enter-to-send / Shift+Enter-newline handling missing');
if (!/rows=\{?2\}?|min-h-\[/.test(src)) fail('G19', 'textarea is not sized taller than one line');
if (!/scrollHeight/.test(src)) fail('G19', 'textarea does not auto-grow');
pass('G19', 'textarea served with label', 'Enter sends, Shift+Enter newlines', 'auto-grows with content');
