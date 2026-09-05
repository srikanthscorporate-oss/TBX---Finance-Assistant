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
    if plan.group_by.value == "none" and not plan.is_detail:
        out.append("Break that down by channel")
    if plan.counterparty:
        out.append("Is that unusual for this counterparty?")
    elif not plan.is_detail:
        out.append("Who did I pay the most?")
    else:
        out.append("What is the total of those?")
    return out[:3]
