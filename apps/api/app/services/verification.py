"""Deterministic checks on a query result before it may become an answer.

Blocking failures veto the answer; warnings lower confidence.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from ..contracts.enums import Intent, Metric
from ..contracts.evidence import VerificationResult
from ..contracts.plan import FinanceQueryPlan

REL_TOLERANCE = 1e-6
"""Absorbs float round-tripping through JSON; Decimal64 sums are exact."""


def verify(
    plan: FinanceQueryPlan,
    rows: list[dict[str, Any]],
    *,
    aggregate: dict[str, Any] | None = None,
    dataset_min: date | None = None,
    dataset_max: date | None = None,
) -> VerificationResult:
    vr = VerificationResult()

    _check_dates_resolved(vr, plan)
    _check_window_within_dataset(vr, plan, dataset_min, dataset_max)
    _check_entity_resolved(vr, plan)
    _check_rows_present(vr, plan, rows, aggregate)
    _check_currency(vr, rows, aggregate)
    _check_aggregate_matches_breakdown(vr, plan, rows, aggregate)
    _check_no_negative_where_impossible(vr, plan, rows, aggregate)
    _check_limit_not_truncating(vr, plan, rows)

    return vr


def _check_dates_resolved(vr: VerificationResult, plan: FinanceQueryPlan) -> None:
    if plan.date_range is None:
        vr.add("date_range_present", True, "no date filter requested (all-time)",
               severity="warning")
        return
    ok = plan.date_range.is_resolved
    vr.add("date_range_resolved", ok,
           plan.date_range.resolved_label if ok else "date range never resolved")


def _check_window_within_dataset(vr, plan, dmin, dmax) -> None:
    if plan.date_range is None or not plan.date_range.is_resolved or not (dmin and dmax):
        return
    s, e = plan.date_range.resolved_start, plan.date_range.resolved_end
    if e < dmin or s > dmax:
        vr.add("window_within_dataset", False,
               f"requested {s}..{e} lies entirely outside the dataset ({dmin}..{dmax})")
    elif s < dmin or e > dmax:
        vr.add("window_within_dataset", True,
               f"requested {s}..{e} extends past dataset bounds ({dmin}..{dmax}); "
               "result covers the overlap only", severity="warning")
    else:
        vr.add("window_within_dataset", True, f"{s}..{e} within {dmin}..{dmax}")


def _check_entity_resolved(vr: VerificationResult, plan: FinanceQueryPlan) -> None:
    if plan.vendor_name and not plan.vendor_id:
        vr.add("vendor_resolved", False,
               f"vendor {plan.vendor_name!r} was never resolved to an id")
    elif plan.vendor_id:
        vr.add("vendor_resolved", True, f"{plan.vendor_name or '?'} -> {plan.vendor_id}")


def _check_rows_present(vr, plan, rows, aggregate) -> None:
    """Zero rows is a warning; whether it is an answer or DATA_UNAVAILABLE is the caller's call."""
    count = _record_count(rows, aggregate)
    if count == 0:
        vr.add("records_returned", False, "query matched zero records",
               severity="warning")
    else:
        vr.add("records_returned", True, f"{count} records")


def _check_currency(vr, rows, aggregate) -> None:
    variants = None
    if aggregate and "currency_variants" in aggregate:
        variants = int(aggregate["currency_variants"] or 0)
    else:
        seen = {r.get("currency") for r in rows if r.get("currency")}
        variants = len(seen) if seen else None

    if variants is None:
        return
    if variants > 1:
        vr.add("currency_consistent", False,
               f"{variants} currencies in one aggregate; totals would be meaningless")
    else:
        vr.add("currency_consistent", True, "single currency")


def _check_aggregate_matches_breakdown(vr, plan, rows, aggregate) -> None:
    """Total and breakdown must agree; catches a wrong GROUP BY, a silent LIMIT or a filter
    mismatch."""
    if aggregate is None or not rows or plan.metric is not Metric.SUM:
        return
    if not all("value" in r for r in rows):
        return
    total = _as_float(aggregate.get("value"))
    if total is None:
        return
    if len(rows) >= min(plan.limit, 1000):
        vr.add("aggregate_matches_breakdown", True,
               "breakdown truncated by limit; not compared", severity="warning")
        return
    breakdown_sum = sum(_as_float(r.get("value")) or 0.0 for r in rows)
    denom = max(abs(total), 1.0)
    if abs(breakdown_sum - total) / denom <= REL_TOLERANCE:
        vr.add("aggregate_matches_breakdown", True, f"{breakdown_sum:.2f} == {total:.2f}")
    else:
        vr.add("aggregate_matches_breakdown", False,
               f"breakdown sums to {breakdown_sum:.2f} but aggregate is {total:.2f}")


def _check_no_negative_where_impossible(vr, plan, rows, aggregate) -> None:
    if plan.intent not in {Intent.TOTAL_SPEND, Intent.VENDOR_SPEND,
                           Intent.CATEGORY_SPEND, Intent.VENDOR_PAYOUTS}:
        return
    values = [_as_float(r.get("value")) for r in rows if "value" in r]
    if aggregate is not None:
        values.append(_as_float(aggregate.get("value")))
    negatives = [v for v in values if v is not None and v < 0]
    if negatives:
        vr.add("spend_non_negative", False,
               f"{len(negatives)} negative spend value(s); check credits/reversals handling",
               severity="warning")
    else:
        vr.add("spend_non_negative", True)


def _check_limit_not_truncating(vr, plan, rows) -> None:
    if rows and len(rows) >= plan.limit:
        vr.add("result_complete", True,
               f"result hit the {plan.limit}-row limit and may be partial",
               severity="warning")


def _record_count(rows, aggregate) -> int:
    if aggregate and aggregate.get("record_count") is not None:
        return int(aggregate["record_count"])
    return len(rows)


def _as_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
