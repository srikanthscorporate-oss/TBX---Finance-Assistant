// G11: adversarial plans are refused; attacker-controlled counterparties, references and account digits are bound.
import { run } from './_run.mjs';
import { pass, fail } from './_lib.mjs';
import { dataKey } from './_run.mjs';

const PY = 'apps/api/.venv/bin/python';
const env = { TBX_DATA_KEY: dataKey() };
const r = run(PY, ['apps/api/tests/security.py'], { token: 'SECURITY_SUITE_PASS', env });
if (!r.ok) fail('G11', `security suite failed (exit ${r.status}):\n${r.out.slice(-1500)}`);

// Positive control: a compiler that inlines a parameter must make the suite fail.
const control = run(PY, ['-c', `
import sys, re
sys.path.insert(0, "apps/api")
import app.services.compiler as c
_orig = c.compile_plan
def broken(plan):
    q = _orig(plan)
    # Inline the parameter instead of binding it -- the exact defect G11 exists to catch.
    if "counterparty" in q.params:
        q.sql = q.sql.replace("{counterparty:String}", "'" + str(q.params["counterparty"]) + "'")
    return q
c.compile_plan = broken
exec(open("apps/api/tests/security.py").read())
`], { token: 'SECURITY_SUITE_PASS', env });
if (control.ok) fail('G11', 'positive control passed -- the suite cannot detect an inlined parameter');

const count = r.out.match(/security checks run: (\d+)/);
pass('G11', `${count ? count[1] : '?'} checks passed`,
     `positive control correctly failed (exit ${control.status})`);
