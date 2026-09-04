#!/usr/bin/env python3
"""Independent cross-validation of the query compiler.

For each plan we compute the expected answer TWICE, by paths that share no code:
  A. compile_plan() -> ClickHouse
  B. a naive loop over the source CSVs in pure Python

If these disagree, the compiler is wrong. This is the check that would have
caught a bad WHERE clause, an off-by-one month boundary, or a wrong GROUP BY --
the failure modes that produce a confident, wrong financial answer.
"""
from __future__ import annotations

import csv
import os
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.contracts.enums import GroupBy, Intent, Metric, ReconStatus  # noqa: E402
from app.contracts.plan import DateRange, FinanceQueryPlan  # noqa: E402
from app.db.clickhouse import ClickHouseClient  # noqa: E402
from app.services.compiler import compile_plan  # noqa: E402
from app.services.dates import DatasetCalendar, resolve  # noqa: E402

RAW = Path(__file__).resolve().parents[3] / "data" / "raw"


def load_csv(name):
    with (RAW / name).open() as fh:
        return list(csv.DictReader(fh))


TXNS = load_csv("transactions.csv")
PAYOUTS = load_csv("vendor_payouts.csv")
CAL = DatasetCalendar(
    min_date=min(date.fromisoformat(r["txn_date"]) for r in TXNS),
    max_date=max(date.fromisoformat(r["txn_date"]) for r in TXNS),
)


def py_filter(rows, *, date_col, start=None, end=None, vendor=None, category=None,
              recon_in=None, status=None):
    out = []
    for r in rows:
        d = date.fromisoformat(r[date_col])
        if start and d < start:
            continue
        if end and d > end:
            continue
        if vendor and r["vendor_id"] != vendor:
            continue
        if category and r["category"] != category:
            continue
        if recon_in and r["reconciliation_status"] not in recon_in:
            continue
        if status and r["status"] != status:
            continue
        out.append(r)
    return out


def approx(a, b, tol=0.02):
    return abs(float(a) - float(b)) <= tol


def main() -> int:
    ch = ClickHouseClient(
        host=os.getenv("CH_HOST", "localhost"), port=int(os.getenv("CH_PORT", "18123")),
        user=os.getenv("CH_ADMIN_USER", "tbx_admin"),
        password=os.getenv("CH_ADMIN_PASSWORD", "change-me-admin"),
    )
    assert ch.ping(), "ClickHouse is not reachable"
    print(f"dataset window: {CAL.min_date} .. {CAL.max_date}  ({len(TXNS):,} transactions)\n")

    failures = 0
    cases = []

    # 1. Total spend, last month (relative -> dataset-anchored)
    dr = resolve(DateRange(relative="last_month"), CAL)
    plan = FinanceQueryPlan(intent=Intent.TOTAL_SPEND, date_range=dr, metric=Metric.SUM)
    rows = py_filter(TXNS, date_col="txn_date", start=dr.resolved_start, end=dr.resolved_end)
    cases.append(("total spend, last month", plan,
                  sum(float(r["amount"]) for r in rows), len(rows)))

    # 2. Vendor spend, last month
    dr2 = resolve(DateRange(relative="last_month"), CAL)
    plan = FinanceQueryPlan(intent=Intent.VENDOR_SPEND, vendor_name="Acme Technologies",
                            vendor_id="V1001", date_range=dr2, metric=Metric.SUM)
    rows = py_filter(TXNS, date_col="txn_date", start=dr2.resolved_start,
                     end=dr2.resolved_end, vendor="V1001")
    cases.append(("Acme Technologies spend, last month", plan,
                  sum(float(r["amount"]) for r in rows), len(rows)))

    # 3. Unreconciled count, all time
    plan = FinanceQueryPlan(intent=Intent.UNRECONCILED, metric=Metric.COUNT, limit=1000)
    rows = py_filter(TXNS, date_col="txn_date",
                     recon_in={"unmatched", "pending", "disputed"})
    cases.append(("unreconciled transactions (detail)", plan, None, len(rows)))

    # 4. Category spend
    dr3 = resolve(DateRange(relative="last_quarter"), CAL)
    plan = FinanceQueryPlan(intent=Intent.CATEGORY_SPEND, category="Marketing",
                            date_range=dr3, metric=Metric.SUM)
    rows = py_filter(TXNS, date_col="txn_date", start=dr3.resolved_start,
                     end=dr3.resolved_end, category="Marketing")
    cases.append(("Marketing spend, last quarter", plan,
                  sum(float(r["amount"]) for r in rows), len(rows)))

    # 5. Reconciliation rate
    dr4 = resolve(DateRange(relative="last_6_months"), CAL)
    plan = FinanceQueryPlan(intent=Intent.RECONCILIATION_RATE, date_range=dr4)
    rows = py_filter(TXNS, date_col="txn_date", start=dr4.resolved_start, end=dr4.resolved_end)
    matched = sum(1 for r in rows if r["reconciliation_status"] == "matched")
    rate = round(100.0 * matched / len(rows), 2) if rows else 0
    cases.append(("reconciliation rate, last 6 months", plan, rate, len(rows)))

    # 6. Vendor payouts
    dr5 = resolve(DateRange(relative="last_month"), CAL)
    plan = FinanceQueryPlan(intent=Intent.VENDOR_PAYOUTS, vendor_name="Globex Software",
                            vendor_id="V1005", date_range=dr5, metric=Metric.SUM)
    prows = py_filter(PAYOUTS, date_col="payout_date", start=dr5.resolved_start,
                      end=dr5.resolved_end, vendor="V1005")
    cases.append(("Globex payouts, last month", plan,
                  sum(float(r["amount"]) for r in prows), len(prows)))

    for label, plan, expected_value, expected_count in cases:
        cq = compile_plan(plan)
        res = ch.query(cq.sql, cq.params)
        if cq.kind == "detail":
            got_value, got_count = None, len(res.rows)
        else:
            got_value = res.rows[0].get("value") if res.rows else 0
            got_count = int(res.rows[0].get("record_count", 0)) if res.rows else 0

        ok_count = got_count == expected_count
        ok_value = expected_value is None or approx(got_value, expected_value)
        status = "PASS" if (ok_count and ok_value) else "FAIL"
        if status == "FAIL":
            failures += 1
        val_str = "-" if expected_value is None else f"{float(expected_value):,.2f}"
        got_str = "-" if got_value is None else f"{float(got_value):,.2f}"
        print(f"[{status}] {label}")
        print(f"        python: value={val_str:>18}  rows={expected_count:>5}")
        print(f"        clickh: value={got_str:>18}  rows={got_count:>5}  ({res.duration_ms}ms)")
        if status == "FAIL":
            print(f"        SQL: {cq.sql}\n        PARAMS: {cq.params}")

    # 7. Grouped: top vendors must sum to the ungrouped total (the aggregate /
    #    breakdown consistency the verifier asserts at runtime).
    dr6 = resolve(DateRange(relative="last_month"), CAL)
    gplan = FinanceQueryPlan(intent=Intent.TOP_VENDORS, date_range=dr6,
                             metric=Metric.SUM, group_by=GroupBy.VENDOR, limit=100)
    gq = compile_plan(gplan)
    grouped = ch.query(gq.sql, gq.params)
    tplan = FinanceQueryPlan(intent=Intent.TOTAL_SPEND, date_range=dr6, metric=Metric.SUM)
    tq = compile_plan(tplan)
    total = float(ch.query(tq.sql, tq.params).rows[0]["value"])
    bsum = sum(float(r["value"]) for r in grouped.rows)
    ok = approx(bsum, total, tol=0.05)
    failures += 0 if ok else 1
    print(f"[{'PASS' if ok else 'FAIL'}] breakdown sums to aggregate")
    print(f"        breakdown({len(grouped.rows)} vendors): {bsum:,.2f}   aggregate: {total:,.2f}")

    print(f"\n{len(cases) + 1 - failures}/{len(cases) + 1} checks passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
