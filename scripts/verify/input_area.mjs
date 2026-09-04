// G16: the question input is a multi-line text area with the documented keys.
import fs from 'node:fs';
import path from 'node:path';
import { ROOT, pass, fail } from './_lib.mjs';
const ORIGIN = process.env.TBX_ORIGIN || 'http://127.0.0.1:8080';
const html = await (await fetch(`${ORIGIN}/`)).text().catch(e => fail('G16', e.message));
if (!/<textarea[^>]*id="q"/.test(html)) fail('G16', 'served page has no <textarea id="q">');
if (/<input[^>]*id="q"/.test(html)) fail('G16', 'single-line input still present');
if (!/for="q"[^>]*>Your question/.test(html) && !/Your question/.test(html)) fail('G16', 'textarea has no accessible label');
const src = fs.readFileSync(path.join(ROOT, 'apps/web/components/Workbench.tsx'), 'utf8');
if (!/e\.key === 'Enter' && !e\.shiftKey/.test(src)) fail('G16', 'Enter-to-send / Shift+Enter-newline handling missing');
if (!/rows=\{?2\}?|min-h-\[/.test(src)) fail('G16', 'textarea is not sized taller than one line');
if (!/scrollHeight/.test(src)) fail('G16', 'textarea does not auto-grow');
pass('G16', 'textarea served with label', 'Enter sends, Shift+Enter newlines', 'auto-grows with content');
