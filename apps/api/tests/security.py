#!/usr/bin/env python3
"""Structurally invalid plans are rejected, and attacker-controlled values that are
legitimate (counterparty, reference, account digits) travel as bound parameters and never
appear in the SQL text. Control characters are refused by the plan contract before the
resolver can normalise them.

Includes a positive control: a fake compiler that inlines a parameter must be caught by
the same detector, so the suite is known to be able to fail. Prints SECURITY_SUITE_PASS.
"""
from __future__ import annotations

import re
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pydantic import ValidationError  # noqa: E402

from app.contracts.enums import Channel, GroupBy, Intent, Metric, ReferenceKind  # noqa: E402
from app.contracts.plan import DateRange, FinanceQueryPlan  # noqa: E402
from app.services.compiler import (  # noqa: E402
    _GROUP_BY_SQL,
    _INTENT_TABLE,
    CompilationError,
    CompiledQuery,
    compile_plan,
)
from app.services.dates import DatasetCalendar, resolve  # noqa: E402
from app.services.resolver import CounterpartyRecord, MatchKind, resolve_counterparty  # noqa: E402

CAL = DatasetCalendar(min_date=date(2025, 1, 1), max_date=date(2026, 8, 30))
LAST_MONTH = resolve(DateRange(relative="last_month"), CAL)
INJECTIONS = [
    "'; DROP TABLE tbx_finance.transaction; --",
    "' OR 1=1 --",
    "SWIGGY' UNION SELECT password FROM system.users --",
    "\\'; SELECT * FROM system.tables; --",
    "{entity_id:String} OR 1=1",
    "SWIGGY\x00INSTAMART",
    "SWIGGY\nINSTAMART",
]
CLEAN = [p for p in INJECTIONS if not any(ord(c) < 32 or ord(c) == 127 for c in p)]
DIRTY = [p for p in INJECTIONS if p not in CLEAN]

failures: list[str] = []
checks = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global checks
    checks += 1
    if not ok:
        failures.append(f"{name}: {detail}")


def inlined(payload: str, cq: CompiledQuery) -> bool:
    """The detector: a value is inlined if it appears in the SQL text or is not bound."""
    return payload in cq.sql or payload not in cq.params.values()


bad_plans = [
    ("unknown intent", {"intent": "DROP_EVERYTHING"}),
    ("old vocabulary intent", {"intent": "vendor_spend"}),
    ("unknown metric", {"intent": "spend_summary", "metric": "exec"}),
    ("unknown group_by", {"intent": "spend_summary", "group_by": "password"}),
    ("old vocabulary group_by", {"intent": "spend_summary", "group_by": "vendor"}),
    ("unknown channel", {"intent": "spend_summary", "channel": "SWIFT"}),
    ("unknown transaction_type", {"intent": "spend_summary", "transaction_type": "refund"}),
    ("unknown reference_kind", {"intent": "reference_lookup", "reference": "x", "reference_kind": "sql"}),
    ("unknown relative range", {"intent": "spend_summary", "date_range": {"relative": "forever"}}),
    ("extra field", {"intent": "spend_summary", "sql": "SELECT 1"}),
    ("extra field in date_range", {"intent": "spend_summary",
                                   "date_range": {"relative": "last_month", "where": "1=1"}}),
    ("limit above cap", {"intent": "spend_summary", "limit": 1001}),
    ("limit far above cap", {"intent": "spend_summary", "limit": 10**9}),
    ("limit below floor", {"intent": "spend_summary", "limit": 0}),
    ("negative min_amount", {"intent": "spend_summary", "min_amount": -1}),
    ("negative max_amount", {"intent": "spend_summary", "max_amount": -500}),
    ("inverted amount range", {"intent": "spend_summary", "min_amount": 100, "max_amount": 1}),
    ("account_last4 not four digits", {"intent": "balance", "account_last4": "12345"}),
    ("account_last4 with letters", {"intent": "balance", "account_last4": "12ab"}),
    ("account_last4 injection", {"intent": "balance", "account_last4": "1' OR '1'='1"}),
    ("bank_code over length", {"intent": "balance", "bank_code": "HDFC' OR 1=1 --"}),
    ("counterparty_spend with no counterparty", {"intent": "counterparty_spend"}),
    ("reference_lookup with no reference", {"intent": "reference_lookup"}),
    ("comparison with no compare_to", {"intent": "period_comparison"}),
    ("over-long counterparty", {"intent": "counterparty_spend", "counterparty_name": "A" * 201}),
]
for name, payload in bad_plans:
    try:
        FinanceQueryPlan.model_validate(payload)
        check(f"reject {name}", False, "plan was accepted")
    except ValidationError:
        check(f"reject {name}", True)

for payload in DIRTY:
    for field_ in ("counterparty_name", "reference", "account_id", "bank_code"):
        try:
            FinanceQueryPlan.model_validate({"intent": "transaction_lookup", field_: payload[:10]})
            check(f"contract rejects control chars in {field_}", False, "plan was accepted")
        except ValidationError:
            check(f"contract rejects control chars in {field_}", True)

counterparties = [CounterpartyRecord("SWIGGY", 100, "UPI"),
                  CounterpartyRecord("SWIGGY INSTAMART", 90, "UPI")]
for payload in CLEAN:
    res = resolve_counterparty(payload, counterparties)
    check(f"resolver does not match {payload[:24]!r}",
          res.kind in {MatchKind.NOT_FOUND, MatchKind.AMBIGUOUS},
          f"resolved to {res.best.name if res.best else None} ({res.kind.value})")

    plan = FinanceQueryPlan(intent=Intent.COUNTERPARTY_SPEND, counterparty_name=payload)
    try:
        cq = compile_plan(plan)
        check(f"compile refuses unresolved counterparty {payload[:20]!r}", False,
              f"compiled to: {cq.sql[:120]}")
    except CompilationError:
        check(f"compile refuses unresolved counterparty {payload[:20]!r}", True)

    plan = FinanceQueryPlan(intent=Intent.COUNTERPARTY_SPEND, counterparty_name="x",
                            counterparty=payload, date_range=LAST_MONTH, entity_id="ent-1")
    cq = compile_plan(plan)
    check(f"counterparty bound, not inlined: {payload[:20]!r}", not inlined(payload, cq),
          f"sql={cq.sql[:160]}")
    check(f"no statement terminator: {payload[:16]!r}", ";" not in cq.sql, cq.sql[:160])

    plan = FinanceQueryPlan(intent=Intent.REFERENCE_LOOKUP, reference=payload,
                            reference_kind=ReferenceKind.REFERENCE)
    cq = compile_plan(plan)
    check(f"reference bound, not inlined: {payload[:20]!r}",
          payload not in cq.sql and payload.strip() in cq.params.values())

    bank = "x' or 1=1"
    plan = FinanceQueryPlan(intent=Intent.SPEND_SUMMARY, account_id=payload, entity_id=payload,
                            bank_code=bank)
    cq = compile_plan(plan)
    check(f"account_id / entity_id bound, not inlined: {payload[:20]!r}",
          payload not in cq.sql and cq.params.get("account_id") == payload
          and cq.params.get("entity_id") == payload)
    check("bank_code bound, not inlined",
          bank not in cq.sql.lower() and cq.params.get("bank_code") == bank.upper())

plan = FinanceQueryPlan(intent=Intent.SPEND_SUMMARY, account_last4="1234")
try:
    compile_plan(plan)
    check("compile refuses unresolved account_last4", False, "compiled")
except CompilationError:
    check("compile refuses unresolved account_last4", True)

plan = FinanceQueryPlan(intent=Intent.BALANCE, account_last4="1234")
try:
    compile_plan(plan)
    check("balance refuses unresolved account_last4", False, "compiled")
except CompilationError:
    check("balance refuses unresolved account_last4", True)

plan = FinanceQueryPlan(intent=Intent.REFERENCE_LOOKUP, reference="UTR123456789",
                        reference_kind=ReferenceKind.UTR)
try:
    compile_plan(plan)
    check("UTR lookup without blind index refused", False, "compiled")
except CompilationError:
    check("UTR lookup without blind index refused", True)
cq = compile_plan(plan, utr_hash="ab" * 32)
check("UTR lookup binds the hash, never the plaintext",
      "UTR123456789" not in cq.sql and "UTR123456789" not in cq.params.values()
      and cq.params.get("utr_hash") == "ab" * 32 and "utr_hash" in cq.sql)
check("UTR hash is truncated in the evidence display",
      cq.display()["params"]["utr_hash"] != "ab" * 32
      and cq.display()["params"]["utr_hash"].endswith("…"))

plan = FinanceQueryPlan(intent=Intent.SPEND_SUMMARY, date_range=DateRange(relative="last_month"))
try:
    compile_plan(plan)
    check("compile refuses an unresolved date_range", False, "compiled")
except CompilationError:
    check("compile refuses an unresolved date_range", True)

FORBIDDEN = ("DROP", "DELETE", "INSERT", "ALTER", "TRUNCATE", "CREATE", "GRANT",
             "ATTACH", "SYSTEM", "URL(", "FILE(", "REMOTE(", "INTO OUTFILE", "SETTINGS")
for intent in Intent:
    check(f"intent {intent.value} is mapped", intent in _INTENT_TABLE)
    kw: dict = {"intent": intent, "entity_id": "ent-1", "date_range": LAST_MONTH}
    if intent is Intent.COUNTERPARTY_SPEND:
        kw.update(counterparty_name="swiggy", counterparty="SWIGGY")
    if intent is Intent.REFERENCE_LOOKUP:
        kw.update(reference="HDFCH123", reference_kind=ReferenceKind.REFERENCE)
    if intent is Intent.PERIOD_COMPARISON:
        kw.update(compare_to=resolve(DateRange(relative="month_before_last"), CAL))
    if intent is Intent.BALANCE:
        kw.pop("date_range")
    cq = compile_plan(FinanceQueryPlan(**kw))
    upper = cq.sql.upper()
    check(f"{intent.value} is a SELECT", upper.strip().startswith("SELECT"), cq.sql[:80])
    for word in FORBIDDEN:
        check(f"{intent.value} has no {word}", word not in upper, cq.sql[:120])
    check(f"{intent.value} is one statement", ";" not in cq.sql, cq.sql[:120])
    dbs = set(re.findall(r"FROM\s+(\w+)\.", cq.sql))
    check(f"{intent.value} reads only tbx_finance", dbs == {"tbx_finance"}, f"dbs: {dbs}")
    check(f"{intent.value} never selects account_number_enc",
          "account_number_enc" not in cq.sql and "account_number" not in cq.sql, cq.sql[:160])
    check(f"{intent.value} has no plaintext utr parameter",
          "utr" not in {k.lower() for k in cq.params} and "utr_number" not in cq.sql)
    check(f"{intent.value} row limit is bound and capped",
          "row_limit" not in cq.params or int(cq.params["row_limit"]) <= 1000)
    check(f"{intent.value} has no unbound braces",
          all(re.fullmatch(r"\w+:[\w()]+", m) for m in re.findall(r"\{([^{}]*)\}", cq.sql)),
          cq.sql[:160])
    check(f"{intent.value} params all bound in sql",
          all(f"{{{k}:" in cq.sql for k in cq.params), f"{list(cq.params)} vs {cq.sql[:160]}")

for group in GroupBy:
    if group is GroupBy.NONE:
        check("group_by none has no sql entry", group not in _GROUP_BY_SQL)
        continue
    check(f"group_by {group.value} is mapped", group in _GROUP_BY_SQL)
    cq = compile_plan(FinanceQueryPlan(intent=Intent.SPEND_SUMMARY, group_by=group,
                                       date_range=LAST_MONTH, entity_id="ent-1",
                                       channel=Channel.UPI, metric=Metric.SUM))
    check(f"group_by {group.value} compiles to a single grouped SELECT",
          cq.kind == "grouped" and "GROUP BY" in cq.sql and ";" not in cq.sql
          and "account_number" not in cq.sql)

plan = FinanceQueryPlan(intent=Intent.SPEND_SUMMARY, limit=1000)
check("limit at cap stays at cap", compile_plan(
    FinanceQueryPlan(intent=Intent.TRANSACTION_LOOKUP, limit=1000)).params["row_limit"] == 1000)


def fake_compile(plan: FinanceQueryPlan) -> CompiledQuery:
    """A deliberately broken compiler that concatenates the counterparty into the SQL."""
    return CompiledQuery(
        sql=f"SELECT sum(transaction_amount) FROM tbx_finance.transaction "
            f"WHERE counterparty = '{plan.counterparty}'",
        params={}, kind="aggregate")


probe = CLEAN[0]
fake = fake_compile(FinanceQueryPlan(intent=Intent.COUNTERPARTY_SPEND, counterparty_name="x",
                                     counterparty=probe))
check("positive control: inlined parameter is detected", inlined(probe, fake),
      "the detector accepted an inlined value; the suite cannot fail")

print(f"security checks run: {checks}")
if failures:
    print(f"FAILURES ({len(failures)}):")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("SECURITY_SUITE_PASS")
