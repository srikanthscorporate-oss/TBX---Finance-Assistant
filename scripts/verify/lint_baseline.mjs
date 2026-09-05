// Lint baseline: ruff and mypy findings must not grow past the recorded counts.
import { run } from './_run.mjs';
import { ROOT, pass, fail } from './_lib.mjs';

const RUFF_MAX = 83, MYPY_MAX = 23;
const ruff = run('apps/api/.venv/bin/ruff', ['check', 'apps/api', 'scripts', '--output-format', 'concise']);
if (ruff.status === null) fail('LINT_BASELINE', `ruff did not run:\n${ruff.out.slice(-400)}`);
const ruffCount = ruff.out.split('\n').filter(l => /^\S+\.py:\d+:\d+: [A-Z]+\d+/.test(l)).length;

const mypy = run(`${ROOT}/apps/api/.venv/bin/mypy`, ['app'], { cwd: `${ROOT}/apps/api` });
if (mypy.status === null) fail('LINT_BASELINE', `mypy did not run:\n${mypy.out.slice(-400)}`);
const mypyCount = mypy.out.split('\n').filter(l => /: error: /.test(l)).length;

const notes = [`ruff findings: ${ruffCount} (baseline ${RUFF_MAX})`, `mypy errors: ${mypyCount} (baseline ${MYPY_MAX})`];
if (ruffCount > RUFF_MAX) fail('LINT_BASELINE', `${notes[0]}\n${ruff.out.split('\n').slice(0, 20).join('\n')}`);
if (mypyCount > MYPY_MAX) fail('LINT_BASELINE', `${notes[1]}\n${mypy.out.split('\n').filter(l => /error/.test(l)).slice(0, 20).join('\n')}`);
for (const n of notes) console.log('  ' + n);
console.log('LINT_BASELINE_PASS');
