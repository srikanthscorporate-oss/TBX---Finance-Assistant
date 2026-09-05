// G24: no sideways scroll in the run pane; live stage indicator on the left.
import fs from 'node:fs';
import path from 'node:path';
import { ROOT, pass, fail } from './_lib.mjs';
const read = f => fs.readFileSync(path.join(ROOT, 'apps/web/components', f), 'utf8');
const run = read('RunPane.tsx'), ev = read('EvidencePanel.tsx'), rail = read('StageRail.tsx'), wb = read('Workbench.tsx');
if (!/overflow-x-hidden/.test(run)) fail('G24', 'run pane does not clip horizontal overflow');
if (!/overflow-wrap:anywhere/.test(run)) fail('G24', 'run pane does not force long tokens to wrap');
if (!/whitespace-pre-wrap break-all/.test(ev)) fail('G24', 'SQL block still extends sideways');
if (/overflow-x-auto[^\n]*\n[^\n]*\{evidence\.sql\}/.test(ev)) fail('G24', 'SQL block uses a sideways scroller');
if (/truncate/.test(rail)) fail('G24', 'stage summary truncates instead of wrapping');
if (!/break-words/.test(rail)) fail('G24', 'stage summary does not wrap');
if (!/className="dot/.test(wb)) fail('G24', 'no processing animation under the running query');
if (!/stageOf\(/.test(wb)) fail('G24', 'live indicator does not name the current stage');
// The panes mount only after an entity is chosen, so the first server render is the entity
// gate; assert the served page is that gate and check the clip in the component source.
const ORIGIN = process.env.TBX_ORIGIN || 'http://127.0.0.1:8080';
const html = await (await fetch(`${ORIGIN}/`)).text();
if (!/overflow-x-hidden|Loading entities|Select your entity ID/.test(html))
  fail('G24', 'served page is neither the entity gate nor the run pane');
pass('G24', 'pane clips sideways overflow, tokens wrap anywhere', 'SQL wraps, stage text wraps',
     'live stage indicator with animation under running query');
