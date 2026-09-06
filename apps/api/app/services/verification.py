"""Deterministic checks on a query result before it may become an answer.

Blocking failures veto the answer; warnings lower confidence.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from ..contracts.enums import Intent, Metric, TransactionType
from ..contracts.evidence import VerificationResult
from ..contracts.plan import FinanceQueryPlan

REL_TOLERANCE = 1e-6

SPEND_INTENTS = {Intent.SPEND_SUMMARY, Intent.COUNTERPARTY_SPEND, Intent.TOP_COUNTERPARTIES}
_ = TransactionType
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
    _check_single_type(vr, plan, aggregate)
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
    if plan.counterparty_name and not plan.counterparty:
        vr.add("counterparty_resolved", False,
               f"counterparty {plan.counterparty_name!r} was never resolved")
    elif plan.counterparty:
        vr.add("counterparty_resolved", True, f"{plan.counterparty_name or '?'} -> {plan.counterparty}")
    if plan.account_last4 and not plan.account_id:
        vr.add("account_resolved", False, f"account ending {plan.account_last4} was never resolved")
    elif plan.account_id:
        vr.add("account_resolved", True, plan.account_id)


def _check_rows_present(vr, plan, rows, aggregate) -> None:
    """Zero rows is a warning; whether it is an answer or DATA_UNAVAILABLE is the caller's call."""
    count = _record_count(rows, aggregate)
    if count == 0:
        vr.add("records_returned", False, "query matched zero records",
               severity="warning")
    else:
        vr.add("records_returned", True, f"{count} records")


def _check_single_type(vr, plan, aggregate) -> None:
    """A spend figure must never silently add credits to debits."""
    if aggregate is None or "type_variants" not in aggregate:
        return
    variants = int(aggregate["type_variants"] or 0)
    spend = plan.intent in SPEND_INTENTS and plan.metric is not Metric.COUNT
    if spend and variants > 1:
        vr.add("single_transaction_type", False,
               "debits and credits mixed in a spend total")
    elif variants > 1:
        vr.add("single_transaction_type", True,
               "credits and debits combined; the question did not restrict the type",
               severity="warning")
    else:
        vr.add("single_transaction_type", True,
               plan.transaction_type.value if plan.transaction_type else "one type present")


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
    if plan.intent not in SPEND_INTENTS:
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
    total = int(rows[0].get("total_matches") or 0) if rows else 0
    if rows and total > len(rows):
        vr.add("result_complete", True,
               f"showing {len(rows)} of {total} matching rows (limit {plan.limit})",
               severity="warning")
    elif rows and len(rows) >= plan.limit:
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
