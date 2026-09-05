#!/usr/bin/env python3
"""Structurally invalid plans are rejected, and attacker-controlled values that are legitimate
(category, vendor_id) travel as bound parameters and never appear in the SQL text.

Control characters are refused by the plan contract before the resolver can normalise them.
Prints SECURITY_SUITE_PASS.
"""
from __future__ import annotations

import re
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pydantic import ValidationError  # noqa: E402

from app.contracts.enums import GroupBy, Intent, Metric  # noqa: E402
from app.contracts.plan import DateRange, FinanceQueryPlan  # noqa: E402
from app.services.compiler import CompilationError, compile_plan  # noqa: E402
from app.services.dates import DatasetCalendar, resolve  # noqa: E402
from app.services.resolver import MatchKind, VendorRecord, resolve_vendor  # noqa: E402

CAL = DatasetCalendar(min_date=date(2025, 1, 1), max_date=date(2026, 8, 28))
INJECTIONS = [
    "'; DROP TABLE tbx_finance.transactions; --",
    "' OR 1=1 --",
    "Acme' UNION SELECT password FROM system.users --",
    "\\'; SELECT * FROM system.tables; --",
    "Acme\x00Technologies",
]

failures: list[str] = []
checks = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global checks
    checks += 1
    if not ok:
        failures.append(f"{name}: {detail}")


bad_plans = [
    ("unknown intent", {"intent": "DROP_EVERYTHING"}),
    ("unknown metric", {"intent": "total_spend", "metric": "exec"}),
    ("unknown group_by", {"intent": "total_spend", "group_by": "password"}),
    ("extra field", {"intent": "total_spend", "sql": "SELECT 1"}),
    ("limit above cap", {"intent": "total_spend", "limit": 10**9}),
    ("limit below floor", {"intent": "total_spend", "limit": 0}),
    ("vendor_spend with no vendor", {"intent": "vendor_spend"}),
    ("comparison with no compare_to", {"intent": "period_comparison"}),
    ("inverted amount range", {"intent": "total_spend", "min_amount": 100, "max_amount": 1}),
]
for name, payload in bad_plans:
    try:
        FinanceQueryPlan.model_validate(payload)
        check(f"reject {name}", False, "plan was accepted")
    except ValidationError:
        check(f"reject {name}", True)

vendors = [VendorRecord("V1001", "Acme Technologies", "Acme Technologies Pvt Ltd")]
for payload in INJECTIONS:
    has_control = any(ord(c) < 32 or ord(c) == 127 for c in payload)

    if has_control:
        try:
            FinanceQueryPlan(intent=Intent.VENDOR_SPEND, vendor_name=payload)
            check(f"contract rejects control chars {payload[:20]!r}", False,
                  "plan was accepted")
        except ValidationError:
            check(f"contract rejects control chars {payload[:20]!r}", True)
        continue

    res = resolve_vendor(payload, vendors)
    check(f"resolver rejects {payload[:24]!r}",
          res.kind is MatchKind.NOT_FOUND,
          f"resolved to {res.best.vendor_name if res.best else None}")

    plan = FinanceQueryPlan(intent=Intent.VENDOR_SPEND, vendor_name=payload)
    try:
        cq = compile_plan(plan)
        check(f"compile refuses unresolved {payload[:20]!r}", False,
              f"compiled to: {cq.sql[:120]}")
    except CompilationError:
        check(f"compile refuses unresolved {payload[:20]!r}", True)

for payload in [p for p in INJECTIONS if not any(ord(c) < 32 or ord(c) == 127 for c in p)]:
    plan = FinanceQueryPlan(intent=Intent.CATEGORY_SPEND, category=payload,
                            date_range=resolve(DateRange(relative="last_month"), CAL))
    cq = compile_plan(plan)
    check(f"category value bound, not inlined: {payload[:20]!r}",
          payload not in cq.sql and payload in cq.params.values(),
          f"sql={cq.sql[:160]}")
    check(f"no statement terminator in sql: {payload[:16]!r}",
          ";" not in cq.sql, cq.sql[:160])

    plan2 = FinanceQueryPlan(intent=Intent.VENDOR_SPEND, vendor_name="x",
                             vendor_id=payload)
    cq2 = compile_plan(plan2)
    check(f"vendor_id bound, not inlined: {payload[:20]!r}",
          payload not in cq2.sql and payload in cq2.params.values())

FORBIDDEN = ("DROP", "DELETE", "INSERT", "ALTER", "TRUNCATE", "CREATE", "GRANT",
             "ATTACH", "SYSTEM", "URL(", "FILE(", "REMOTE(", "INTO OUTFILE")
samples = [
    FinanceQueryPlan(intent=Intent.TOTAL_SPEND,
                     date_range=resolve(DateRange(relative="last_month"), CAL)),
    FinanceQueryPlan(intent=Intent.TOP_VENDORS, group_by=GroupBy.VENDOR, limit=10),
    FinanceQueryPlan(intent=Intent.UNRECONCILED, metric=Metric.COUNT),
    FinanceQueryPlan(intent=Intent.RECONCILIATION_RATE),
    FinanceQueryPlan(intent=Intent.TREND, group_by=GroupBy.MONTH),
    FinanceQueryPlan(intent=Intent.VENDOR_PAYOUTS, vendor_name="a", vendor_id="V1001"),
]
for plan in samples:
    cq = compile_plan(plan)
    upper = cq.sql.upper()
    check(f"{plan.intent.value} is a SELECT", upper.strip().startswith("SELECT"), cq.sql[:80])
    for word in FORBIDDEN:
        check(f"{plan.intent.value} has no {word}", word not in upper, cq.sql[:120])
    check(f"{plan.intent.value} is one statement", ";" not in cq.sql, cq.sql[:120])
    dbs = set(re.findall(r"FROM\s+(\w+)\.", cq.sql))
    check(f"{plan.intent.value} reads only tbx_finance",
          dbs == {"tbx_finance"}, f"referenced databases: {dbs}")

from app.services.compiler import _INTENT_TABLE  # noqa: E402
for intent in Intent:
    check(f"intent {intent.value} is mapped", intent in _INTENT_TABLE)

print(f"security checks run: {checks}")
if failures:
    print(f"FAILURES ({len(failures)}):")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("SECURITY_SUITE_PASS")
