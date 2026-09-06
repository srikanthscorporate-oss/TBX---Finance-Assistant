#!/usr/bin/env python3
"""Cross-checks compile_plan() -> ClickHouse against a naive loop over data/raw/*.csv.

The two paths share no query code: the CSV side joins transaction to account by hand,
parses the narration with parse_narration and filters with plain comparisons. Prints
CROSSCHECK_PASS and exits non-zero on any mismatch.
"""
from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from bank_fixture import (  # noqa: E402
    Txn,
    calendar,
    ch_client,
    data_key,
    default_entity,
    load_accounts,
    load_transactions,
)

from app.contracts.enums import (  # noqa: E402
    Channel,
    GroupBy,
    Intent,
    Metric,
    ReferenceKind,
    TransactionType,  # noqa: E402
)
from app.contracts.plan import DateRange, FinanceQueryPlan  # noqa: E402
from app.services.compiler import compile_plan  # noqa: E402
from app.services.crypto import FieldCipher, load_key  # noqa: E402
from app.services.dates import resolve  # noqa: E402

ACCOUNTS = load_accounts()
TXNS = load_transactions(ACCOUNTS)
CAL = calendar(TXNS)
ENTITY = default_entity(TXNS)
MINE = [t for t in TXNS if t.entity_id == ENTITY]

failures: list[str] = []
checks = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global checks
    checks += 1
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"\n        {detail}" if detail and not ok else ""))
    if not ok:
        failures.append(f"{name}: {detail}")


def approx(a: float, b: float, tol: float = 0.02) -> bool:
    return abs(float(a) - float(b)) <= tol


def period(rel: str) -> DateRange:
    return resolve(DateRange(relative=rel), CAL)


def py_filter(rows: list[Txn], *, dr: DateRange | None = None, counterparty: str | None = None,
              txn_type: str | None = None, channel: str | None = None,
              min_amount: float | None = None, max_amount: float | None = None) -> list[Txn]:
    out = []
    for t in rows:
        if dr and not (dr.resolved_start <= t.txn_date <= dr.resolved_end):
            continue
        if counterparty and t.counterparty != counterparty:
            continue
        if txn_type and t.transaction_type != txn_type:
            continue
        if channel and t.channel != channel:
            continue
        if min_amount is not None and t.amount < min_amount:
            continue
        if max_amount is not None and t.amount > max_amount:
            continue
        out.append(t)
    return out


def run(ch, plan: FinanceQueryPlan, **kw):
    cq = compile_plan(plan, **kw)
    check(f"{plan.intent.value}: entity_id is bound, never inlined",
          cq.params.get("entity_id") == plan.entity_id and plan.entity_id not in cq.sql)
    return cq, ch.query(cq.sql, cq.params)


def aggregate_case(ch, name: str, plan: FinanceQueryPlan, rows: list[Txn], value) -> None:
    cq, res = run(ch, plan)
    got = res.rows[0] if res.rows else {}
    got_value = float(got.get("value") or 0)
    got_count = int(got.get("record_count") or 0)
    ok = got_count == len(rows) and (value is None or approx(got_value, value))
    check(name, ok, f"python value={value} rows={len(rows)}; clickhouse value={got_value} "
                    f"rows={got_count}\n        SQL: {cq.sql}\n        PARAMS: {cq.params}")


def main() -> int:
    ch = ch_client()
    assert ch.ping(), "ClickHouse is not reachable"
    print(f"dataset window: {CAL.min_date} .. {CAL.max_date}  ({len(TXNS):,} transactions, "
          f"{len(MINE):,} for entity {ENTITY[:8]}…)\n")

    dr = period("last_month")
    plan = FinanceQueryPlan(intent=Intent.SPEND_SUMMARY, entity_id=ENTITY, date_range=dr,
                            transaction_type=TransactionType.DEBIT)
    check("a sum plan carries no implicit side until one is stated",
          FinanceQueryPlan(intent=Intent.SPEND_SUMMARY, entity_id=ENTITY,
                           date_range=dr).transaction_type is None)
    rows = py_filter(MINE, dr=dr, txn_type="debit")
    debit_last_month = sum(t.amount for t in rows)
    aggregate_case(ch, "spend_summary sum, last month (debits)", plan, rows, debit_last_month)

    # Both sides: no transaction_type, include_both_types set by the "both" clarification.
    plan = FinanceQueryPlan(intent=Intent.SPEND_SUMMARY, entity_id=ENTITY, date_range=dr,
                            include_both_types=True)
    both_rows = py_filter(MINE, dr=dr)
    both_last_month = sum(t.amount for t in both_rows)
    aggregate_case(ch, "spend_summary sum, last month (both types)", plan, both_rows,
                   both_last_month)
    check("both-types total differs from the debit-only total",
          not approx(both_last_month, debit_last_month),
          f"both {both_last_month} vs debits {debit_last_month}")

    plan = FinanceQueryPlan(intent=Intent.SPEND_SUMMARY, entity_id=ENTITY, date_range=dr,
                            metric=Metric.COUNT)
    rows = py_filter(MINE, dr=dr)
    check("count metric leaves transaction_type unset", plan.transaction_type is None)
    aggregate_case(ch, "spend_summary count, last month (both types)", plan, rows, len(rows))

    dr = period("this_year")
    plan = FinanceQueryPlan(intent=Intent.SPEND_SUMMARY, entity_id=ENTITY, date_range=dr,
                            transaction_type=TransactionType.DEBIT)
    rows = py_filter(MINE, dr=dr, txn_type="debit")
    aggregate_case(ch, "spend_summary sum, this year", plan, rows, sum(t.amount for t in rows))

    plan = FinanceQueryPlan(intent=Intent.COUNTERPARTY_SPEND, entity_id=ENTITY,
                            counterparty_name="Swiggy", counterparty="SWIGGY",
                            transaction_type=TransactionType.DEBIT)
    rows = py_filter(MINE, counterparty="SWIGGY", txn_type="debit")
    swiggy_debits = sum(t.amount for t in rows)
    aggregate_case(ch, "counterparty_spend SWIGGY sum, all time", plan, rows, swiggy_debits)

    plan = FinanceQueryPlan(intent=Intent.COUNTERPARTY_SPEND, entity_id=ENTITY,
                            counterparty_name="Swiggy", counterparty="SWIGGY",
                            include_both_types=True)
    rows = py_filter(MINE, counterparty="SWIGGY")
    swiggy_both = sum(t.amount for t in rows)
    aggregate_case(ch, "counterparty_spend SWIGGY sum, all time (both types)", plan, rows,
                   swiggy_both)
    check("SWIGGY both-types total differs from the debit-only total",
          not approx(swiggy_both, swiggy_debits),
          f"both {swiggy_both} vs debits {swiggy_debits}")

    plan = FinanceQueryPlan(intent=Intent.COUNTERPARTY_SPEND, entity_id=ENTITY,
                            counterparty_name="Swiggy", counterparty="SWIGGY", metric=Metric.COUNT)
    rows = py_filter(MINE, counterparty="SWIGGY")
    aggregate_case(ch, "counterparty_spend SWIGGY count, all time", plan, rows, len(rows))

    dr = period("last_month")
    plan = FinanceQueryPlan(intent=Intent.TRANSACTION_LOOKUP, entity_id=ENTITY, date_range=dr,
                            max_amount=500, limit=1000)
    rows = py_filter(MINE, dr=dr, max_amount=500)
    cq, res = run(ch, plan)
    got_ids = {r["transaction_id"] for r in res.rows}
    total = int(res.rows[0]["total_matches"]) if res.rows else 0
    check("transaction_lookup <=500 last month: total_matches", total == len(rows),
          f"python {len(rows)} vs clickhouse {total}")
    exp_ids = {t.transaction_id for t in rows}
    check("transaction_lookup <=500 last month: row ids",
          got_ids == exp_ids if len(rows) <= 1000 else got_ids <= exp_ids and len(got_ids) == 1000,
          f"{len(got_ids ^ exp_ids)} ids differ")
    check("transaction_lookup rows carry no plaintext utr or account number",
          all("utr_number" not in r and "account_number" not in r
              and "account_number_enc" not in r for r in res.rows))

    dr = period("last_90_days")
    plan = FinanceQueryPlan(intent=Intent.TRANSACTION_LOOKUP, entity_id=ENTITY, date_range=dr,
                            min_amount=1000, max_amount=2000, transaction_type=TransactionType.DEBIT,
                            limit=1000)
    rows = py_filter(MINE, dr=dr, min_amount=1000, max_amount=2000, txn_type="debit")
    cq, res = run(ch, plan)
    total = int(res.rows[0]["total_matches"]) if res.rows else 0
    check("transaction_lookup between 1000 and 2000, last 90 days, debits",
          total == len(rows) and all(1000 <= float(r["transaction_amount"]) <= 2000 for r in res.rows),
          f"python {len(rows)} vs clickhouse {total}")

    dr = period("this_year")
    plan = FinanceQueryPlan(intent=Intent.SPEND_SUMMARY, entity_id=ENTITY, date_range=dr,
                            channel=Channel.UPI, transaction_type=TransactionType.DEBIT)
    rows = py_filter(MINE, dr=dr, channel="UPI", txn_type="debit")
    upi_debits = sum(t.amount for t in rows)
    aggregate_case(ch, "spend_summary UPI debits, this year", plan, rows, upi_debits)

    plan = FinanceQueryPlan(intent=Intent.SPEND_SUMMARY, entity_id=ENTITY, date_range=dr,
                            channel=Channel.UPI, include_both_types=True)
    rows = py_filter(MINE, dr=dr, channel="UPI")
    upi_both = sum(t.amount for t in rows)
    aggregate_case(ch, "spend_summary UPI both types, this year", plan, rows, upi_both)
    check("UPI both-types total differs from the debit-only total",
          not approx(upi_both, upi_debits), f"both {upi_both} vs debits {upi_debits}")

    dr = period("last_quarter")
    plan = FinanceQueryPlan(intent=Intent.LARGEST_TRANSACTIONS, entity_id=ENTITY, date_range=dr,
                            transaction_type=TransactionType.DEBIT, limit=10)
    rows = sorted(py_filter(MINE, dr=dr, txn_type="debit"),
                  key=lambda t: (-t.amount, t.transaction_id))[:10]
    cq, res = run(ch, plan)
    got = [r["transaction_id"] for r in res.rows]
    check("largest_transactions top 10 ordering, last quarter",
          got == [t.transaction_id for t in rows],
          f"python {[t.amount for t in rows]}\n        clickhouse "
          f"{[r['transaction_amount'] for r in res.rows]}")

    plan = FinanceQueryPlan(intent=Intent.TOP_COUNTERPARTIES, entity_id=ENTITY, date_range=dr,
                            transaction_type=TransactionType.DEBIT, limit=10)
    sums: dict[str, float] = defaultdict(float)
    counts: dict[str, int] = defaultdict(int)
    for t in py_filter(MINE, dr=dr, txn_type="debit"):
        sums[t.counterparty] += t.amount
        counts[t.counterparty] += 1
    top = sorted(sums.items(), key=lambda kv: -kv[1])[:10]
    cq, res = run(ch, plan)
    got_top = [(r["counterparty"], float(r["value"]), int(r["record_count"])) for r in res.rows]
    ok = len(got_top) == len(top) and all(
        g[0] == e[0] and approx(g[1], e[1]) and g[2] == counts[e[0]] for g, e in zip(got_top, top, strict=True))
    check("top_counterparties sum, last quarter", ok, f"python {top[:3]}\n        clickhouse {got_top[:3]}")

    dr = period("this_year")
    plan = FinanceQueryPlan(intent=Intent.CHANNEL_BREAKDOWN, entity_id=ENTITY, date_range=dr,
                            transaction_type=TransactionType.DEBIT)
    by_channel: dict[str, float] = defaultdict(float)
    for t in py_filter(MINE, dr=dr, txn_type="debit"):
        by_channel[t.channel] += t.amount
    cq, res = run(ch, plan)
    got_ch = {r["channel"]: float(r["value"]) for r in res.rows}
    ok = set(got_ch) == set(by_channel) and all(approx(got_ch[k], v) for k, v in by_channel.items())
    check("channel_breakdown debits, this year", ok, f"python {dict(by_channel)}\n        clickhouse {got_ch}")

    plan = FinanceQueryPlan(intent=Intent.TREND, entity_id=ENTITY, date_range=dr,
                            group_by=GroupBy.MONTH, transaction_type=TransactionType.DEBIT)
    by_month: dict[str, float] = defaultdict(float)
    for t in py_filter(MINE, dr=dr, txn_type="debit"):
        by_month[t.txn_date.replace(day=1).isoformat()] += t.amount
    cq, res = run(ch, plan)
    got_m = {str(r["month"])[:10]: float(r["value"]) for r in res.rows}
    ok = (list(got_m) == sorted(by_month) and all(approx(got_m[k], v) for k, v in by_month.items()))
    check("trend by month debits, this year (chronological)", ok,
          f"python {dict(sorted(by_month.items()))}\n        clickhouse {got_m}")

    plan = FinanceQueryPlan(intent=Intent.BALANCE, entity_id=ENTITY, limit=1000)
    accts = [a for a in ACCOUNTS.values() if a["entity_id"] == ENTITY]
    cq, res = run(ch, plan)
    got_bal = {r["account_id"]: float(r["available_balance"]) for r in res.rows}
    exp_bal = {a["account_id"]: float(a["available_balance"]) for a in accts}
    ok = set(got_bal) == set(exp_bal) and all(approx(got_bal[k], v) for k, v in exp_bal.items())
    check("balance from account table matches account.csv", ok,
          f"python {len(exp_bal)} accounts {sum(exp_bal.values()):,.2f}; "
          f"clickhouse {len(got_bal)} accounts {sum(got_bal.values()):,.2f}")
    check("balance rows carry last4 only, never account_number_enc",
          all("account_number_enc" not in r and "account_number" not in r for r in res.rows))

    target = next(t for t in MINE if t.reference)
    plan = FinanceQueryPlan(intent=Intent.REFERENCE_LOOKUP, entity_id=ENTITY,
                            reference=target.reference, reference_kind=ReferenceKind.REFERENCE)
    exp = [t for t in MINE if t.reference == target.reference]
    cq, res = run(ch, plan)
    check("reference_lookup by transaction_reference_id",
          {r["transaction_id"] for r in res.rows} == {t.transaction_id for t in exp},
          f"expected {[t.transaction_id for t in exp]}, got {[r['transaction_id'] for r in res.rows]}")

    cipher = FieldCipher(load_key(data_key()))
    target = next(t for t in MINE if t.utr)
    plan = FinanceQueryPlan(intent=Intent.REFERENCE_LOOKUP, entity_id=ENTITY,
                            reference=target.utr.lower(), reference_kind=ReferenceKind.UTR)
    exp = [t for t in MINE if t.utr == target.utr]
    cq, res = run(ch, plan, utr_hash=cipher.blind_index(target.utr.lower()))
    check("utr lookup via blind_index finds the row",
          {r["transaction_id"] for r in res.rows} == {t.transaction_id for t in exp},
          f"expected {[t.transaction_id for t in exp]}, got {[r['transaction_id'] for r in res.rows]}")
    check("utr lookup: plaintext never bound as a parameter",
          target.utr not in cq.params.values() and target.utr not in cq.sql)
    check("utr lookup: stored utr_enc decrypts to the CSV plaintext",
          bool(res.rows) and all(cipher.decrypt(r["utr_enc"]) == target.utr for r in res.rows))

    print(f"\n{checks - len(failures)}/{checks} checks passed")
    if failures:
        for f in failures:
            print(f"  FAIL: {f.splitlines()[0]}")
        return 1
    print("CROSSCHECK_PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
