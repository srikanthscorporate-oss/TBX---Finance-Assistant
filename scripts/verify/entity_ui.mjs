// Entity selection and chat persistence in the web app: the picker gates first load, the
// choice is remembered by its stable masked label, and only Clear History resets either.
import fs from 'node:fs';
import path from 'node:path';
import { ROOT, pass, fail } from './_lib.mjs';

const G = 'ENTITY_UI';
const src = fs.readFileSync(path.join(ROOT, 'apps/web/components/Workbench.tsx'), 'utf8');
const shell = fs.readFileSync(path.join(ROOT, 'apps/web/components/Shell.tsx'), 'utf8');
const api = fs.readFileSync(path.join(ROOT, 'apps/web/lib/api.ts'), 'utf8');

// The chat opens normally; the entity is chosen from a dropdown and the composer waits.
if (!/Select your entity ID/.test(src)) fail(G, 'no prompt to select an entity');
if (!/Pick an entity to begin/.test(src)) fail(G, 'chat area does not tell the user to pick an entity');
if (!/disabled=\{busy \|\| !entityId\}/.test(src)) fail(G, 'composer accepts questions before an entity is chosen');
if (!/<textarea id="q"/.test(src)) fail(G, 'the Ask page has no question form');
if (!/<select id="entity"/.test(src)) fail(G, 'entity is not chosen from a dropdown');

// The token is re-encrypted per fetch, so a restore keyed on it would silently drop history.
if (!/e\.label === saved\.label/.test(src)) fail(G, 'saved entity is not matched by its stable label');
if (!/loadStored<Turn\[\]>\(TRANSCRIPT_KEY\)/.test(src)) fail(G, 'transcript is never restored on mount');
if (!/store\(TRANSCRIPT_KEY, turns/.test(src)) fail(G, 'transcript is never persisted');

// Navigating away and back must not reset; only the clear event may.
const resetBlocks = src.match(/setTurns\(\[\]\)/g) ?? [];
if (resetBlocks.length > 3) fail(G, `setTurns([]) appears ${resetBlocks.length} times; a stray reset would wipe history on remount`);
if (!/HISTORY_CLEARED_EVENT, reset/.test(src)) fail(G, 'clear-history event does not reset the pane');
if (!/removeItem\(TRANSCRIPT_KEY\)/.test(src)) fail(G, 'clear history does not drop the stored transcript');

// Switching entity is refused until the history is cleared.
if (!/if \(entityId\) \{ setSwitchBlocked\(true\); return; \}/.test(src))
  fail(G, 'entity can be switched without clearing the history');
if (!/entityId \? \(/.test(src)) fail(G, 'the dropdown is not replaced by a locked label once chosen');
if (!/Clear History first/.test(src)) fail(G, 'no message telling the user to clear history first');

if (!/Clear History/.test(shell)) fail(G, 'header has no Clear History button');
if (!/history\/clear/.test(api)) fail(G, 'no client call to the clear-history endpoint');

const ORIGIN = process.env.TBX_ORIGIN || process.env.TBX_WEB || 'http://127.0.0.1:3000';
const res = await fetch(`${ORIGIN}/`).catch(e => fail(G, `web app unreachable at ${ORIGIN}: ${e.message}`));
if (!res.ok) fail(G, `GET / -> ${res.status}`);
const html = await res.text();
if (!/Clear History/.test(html)) fail(G, 'served page does not render the Clear History button');
if (!/<textarea[^>]*id="q"/.test(html)) fail(G, 'the served Ask page has no question form');

pass(G, 'entity chosen from a dropdown, chat explains why', 'choice and transcript persist by label',
     'switching requires Clear History', 'Clear History wired end to end');
