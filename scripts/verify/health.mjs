// G1: the API boots against ClickHouse and reports the dataset window it loaded.
import { get, pass, fail } from './_lib.mjs';

const h = await get('/health').catch(e => fail('G1', `health unreachable: ${e.message}`));
if (h.status !== 'ok') fail('G1', `status=${h.status}`);
if (!h.ready) fail('G1', 'not ready');
if (!h.dataset_window || !/^\d{4}-\d{2}-\d{2}\.\.\d{4}-\d{2}-\d{2}$/.test(h.dataset_window))
  fail('G1', `bad dataset_window: ${h.dataset_window}`);
if (!h.vendors || h.vendors < 1) fail('G1', 'no vendors loaded');

const ds = await get('/api/v1/dataset');
if (!ds.min_date || !ds.max_date) fail('G1', 'dataset endpoint incomplete');
if (ds.max_date !== h.dataset_window.split('..')[1])
  fail('G1', 'health and dataset endpoints disagree on the window');

pass('G1', `window=${h.dataset_window}`, `vendors=${h.vendors}`,
     `version=${h.dataset_version}`, `currency=${ds.currency}`);
