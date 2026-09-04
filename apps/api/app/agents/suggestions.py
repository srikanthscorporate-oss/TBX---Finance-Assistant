"""Chart selection and follow-up prompts. Deterministic, no model involved."""
from __future__ import annotations

from ..contracts.plan import FinanceQueryPlan

TIME_GRAINS = {"day", "week", "month", "quarter", "year"}


def chart_hint(plan: FinanceQueryPlan, rows: list[dict]) -> str | None:
    """A time grain reads as a line; any other grouping reads as bars."""
    if not rows:
        return None
    if plan.group_by.value in TIME_GRAINS:
        return "line"
    if plan.group_by.value != "none":
        return "bar"
    return None


def follow_ups(plan: FinanceQueryPlan) -> list[str]:
    out: list[str] = []
    if plan.date_range:
        out.append("What about the month before?")
    if plan.group_by.value == "none":
        out.append("Break that down by category")
    if plan.vendor_id:
        out.append("Is that unusual for this vendor?")
    else:
        out.append("Which vendors account for most of it?")
    return out[:3]
