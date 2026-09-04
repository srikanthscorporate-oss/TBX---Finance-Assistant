"""The FinanceQueryPlan: the only thing an LLM is allowed to produce that
influences a database query.

The planner emits this object and nothing else. It never emits SQL, never emits
a number, and never emits a field name that is not declared here. The compiler
turns a validated plan into a parameterized ClickHouse query.
"""
from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .enums import Direction, GroupBy, Intent, Metric, ReconStatus, TxnStatus

# Relative expressions the planner may use. They are resolved against the
# DATASET's max transaction date, never against today -- see services/dates.py.
RelativeRange = Literal[
    "last_month",
    "this_month",
    "last_quarter",
    "this_quarter",
    "last_year",
    "this_year",
    "last_7_days",
    "last_30_days",
    "last_90_days",
    "last_6_months",
    "last_12_months",
    "month_before_last",
    "all_time",
]


class DateRange(BaseModel):
    """Either a relative expression or an explicit absolute window.

    `resolved_start` / `resolved_end` are filled in by the date resolver, never
    by the model. They are what actually reaches the query, and what we echo
    back to the user so the window is auditable.
    """

    model_config = ConfigDict(extra="forbid")

    relative: RelativeRange | None = None
    start: date | None = None
    end: date | None = None

    resolved_start: date | None = Field(default=None, exclude=False)
    resolved_end: date | None = Field(default=None, exclude=False)
    resolved_label: str | None = None

    @model_validator(mode="after")
    def _exactly_one_form(self) -> "DateRange":
        has_relative = self.relative is not None
        has_absolute = self.start is not None or self.end is not None
        if has_relative and has_absolute:
            raise ValueError("date_range: give either `relative` or `start`/`end`, not both")
        if not has_relative and not has_absolute:
            raise ValueError("date_range: one of `relative` or `start`/`end` is required")
        if has_absolute and (self.start is None or self.end is None):
            raise ValueError("date_range: absolute ranges need both `start` and `end`")
        if self.start and self.end and self.start > self.end:
            raise ValueError("date_range: `start` must not be after `end`")
        return self

    @property
    def is_resolved(self) -> bool:
        return self.resolved_start is not None and self.resolved_end is not None


class FinanceQueryPlan(BaseModel):
    """A fully-typed, validated description of one deterministic query.

    Note what is absent: no free-text filter, no raw SQL fragment, no arbitrary
    column reference. The closed vocabulary is the point.
    """

    model_config = ConfigDict(extra="forbid")

    intent: Intent

    # Entities. IDs are resolved by deterministic lookup from the *_name fields;
    # the model proposes a name, the resolver decides the id.
    vendor_name: str | None = None
    vendor_id: str | None = None
    category: str | None = None
    account_code: str | None = None

    # Filters
    date_range: DateRange | None = None
    compare_to: DateRange | None = None
    txn_status: TxnStatus | None = None
    recon_status: ReconStatus | None = None
    direction: Direction | None = None
    min_amount: float | None = None
    max_amount: float | None = None
    currency: str | None = Field(default=None, max_length=3)

    # Shape of the result
    metric: Metric = Metric.SUM
    group_by: GroupBy = GroupBy.NONE
    limit: Annotated[int, Field(ge=1, le=1000)] = 100
    order_desc: bool = True

    # Free-text echo of what the user asked, for tracing only. Never queried on.
    user_question: str | None = None

    @field_validator("vendor_name", "vendor_id", "category", "account_code",
                     "currency", mode="after")
    @classmethod
    def _no_control_characters(cls, v: str | None) -> str | None:
        """Reject control characters in any value that reaches a query.

        These values are always bound as parameters, so this is not the
        injection defence -- that is the compiler's allowlist. This exists so a
        name containing a NUL or newline cannot be silently normalised into a
        match for a *different*, real entity, and so such values never reach
        logs or the evidence panel.
        """
        if v is None:
            return v
        if any(ord(ch) < 32 or ord(ch) == 127 for ch in v):
            raise ValueError("value contains control characters")
        if len(v) > 200:
            raise ValueError("value exceeds 200 characters")
        return v

    @model_validator(mode="after")
    def _intent_requirements(self) -> "FinanceQueryPlan":
        """Intent-level coherence.

        These requirements are deliberately narrow. An entity-scoped intent is
        satisfied EITHER by naming the entity or by grouping across it:
        "spend by category" and "total vendor payouts last month" are both
        legitimate questions, and rejecting them forced a pointless escalation
        and then an error, when the plan was correct all along.
        """
        if self.intent is Intent.PERIOD_COMPARISON and self.compare_to is None:
            raise ValueError("period_comparison requires `compare_to`")

        # vendor_payouts selects the payouts TABLE; it does not require a
        # vendor. "Total vendor payouts last month" is a legitimate aggregate.
        # vendor_spend does name an entity, so it needs one, or a grouping
        # across vendors.
        has_vendor = bool(self.vendor_name or self.vendor_id)
        grouped_by_vendor = self.group_by is GroupBy.VENDOR
        if self.intent is Intent.VENDOR_SPEND and not (has_vendor or grouped_by_vendor):
            raise ValueError("vendor_spend needs either a vendor or group_by=vendor")

        grouped_by_category = self.group_by is GroupBy.CATEGORY
        if self.intent is Intent.CATEGORY_SPEND and not (self.category or grouped_by_category):
            raise ValueError(
                "category_spend needs either a category or group_by=category")
        if self.min_amount is not None and self.max_amount is not None:
            if self.min_amount > self.max_amount:
                raise ValueError("min_amount must not exceed max_amount")
        return self

    def fingerprint(self) -> str:
        """Stable hash of the semantic content, for caching and dedup."""
        import hashlib

        payload = self.model_dump_json(
            exclude={"user_question"}, exclude_none=True
        )
        return hashlib.sha256(payload.encode()).hexdigest()[:16]


class PlanDelta(BaseModel):
    """A follow-up turn.

    Rather than re-planning from raw chat history, the model emits only the
    fields that change relative to the previous validated plan. This is both
    more accurate for coreference ("what about the month before?") and far
    cheaper in tokens.
    """

    model_config = ConfigDict(extra="forbid")

    intent: Intent | None = None
    vendor_name: str | None = None
    category: str | None = None
    account_code: str | None = None
    date_range: DateRange | None = None
    compare_to: DateRange | None = None
    txn_status: TxnStatus | None = None
    recon_status: ReconStatus | None = None
    metric: Metric | None = None
    group_by: GroupBy | None = None
    limit: int | None = None

    # Fields the follow-up explicitly clears (e.g. "across all vendors now").
    clear: list[str] = Field(default_factory=list)

    def apply_to(self, base: FinanceQueryPlan) -> FinanceQueryPlan:
        data = base.model_dump()
        for field in self.clear:
            if field in data and field not in {"intent", "metric", "group_by", "limit"}:
                data[field] = None
        for field, value in self.model_dump(exclude={"clear"}, exclude_none=True).items():
            data[field] = value
        # A changed vendor name invalidates the previously resolved id.
        if self.vendor_name is not None:
            data["vendor_id"] = None
        return FinanceQueryPlan.model_validate(data)
