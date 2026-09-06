"""FinanceQueryPlan: the only model output that influences a query. The compiler turns a
validated plan into a parameterized SQL query."""
from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .enums import Channel, GroupBy, Intent, Metric, ReferenceKind, TransactionType

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
    "today",
    "yesterday",
    "all_time",
]
"""Resolved in services/dates.py against the dataset's max transaction date, not today."""


class DateRange(BaseModel):
    """A relative expression or an absolute window.

    `resolved_start` / `resolved_end` are set by the date resolver, not the model, and
    are what reaches the query.
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
    """A typed description of one query.

    The model proposes `counterparty_name`; the resolver sets `counterparty` to the exact
    stored value. `entity_id` is set by the API from the request, never by the model.
    `user_question` is an echo for tracing and is never queried on.
    """

    model_config = ConfigDict(extra="forbid")

    intent: Intent

    entity_id: str | None = None
    counterparty_name: str | None = None
    counterparty: str | None = None
    account_last4: str | None = Field(default=None, min_length=4, max_length=4, pattern=r"^\d{4}$")
    account_id: str | None = None
    bank_code: str | None = Field(default=None, max_length=10)

    reference: str | None = None
    reference_kind: ReferenceKind | None = None

    date_range: DateRange | None = None
    compare_to: DateRange | None = None
    transaction_type: TransactionType | None = None
    include_both_types: bool = False
    channel: Channel | None = None
    min_amount: float | None = Field(default=None, ge=0)
    max_amount: float | None = Field(default=None, ge=0)

    metric: Metric = Metric.SUM
    group_by: GroupBy = GroupBy.NONE
    limit: Annotated[int, Field(ge=1, le=1000)] = 100
    order_desc: bool = True

    user_question: str | None = None

    @field_validator("counterparty_name", "counterparty", "account_id", "bank_code",
                     "reference", "entity_id", mode="after")
    @classmethod
    def _no_control_characters(cls, v: str | None) -> str | None:
        """Reject control characters and over-long values.

        Not the injection defence (values are bound parameters); this stops a name with a
        NUL or newline from being normalised into a match for a different entity.
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

    A counterparty intent needs a counterparty or a grouping across them. A reference
        lookup needs the reference and defaults to the plaintext reference id. The
        debit/credit split is never inferred here; the pipeline asks when it is unstated.
        """
        if self.intent is Intent.PERIOD_COMPARISON and self.compare_to is None:
            raise ValueError("period_comparison requires `compare_to`")

        has_cp = bool(self.counterparty_name or self.counterparty)
        if self.intent is Intent.COUNTERPARTY_SPEND and not (
                has_cp or self.group_by is GroupBy.COUNTERPARTY):
            raise ValueError("counterparty_spend needs a counterparty or group_by=counterparty")

        if self.intent is Intent.REFERENCE_LOOKUP:
            if not self.reference:
                raise ValueError("reference_lookup requires `reference`")
            if self.reference_kind is None:
                self.reference_kind = ReferenceKind.REFERENCE
        elif self.reference and self.reference_kind is None:
            self.reference_kind = ReferenceKind.REFERENCE


        if self.min_amount is not None and self.max_amount is not None:
            if self.min_amount > self.max_amount:
                raise ValueError("min_amount must not exceed max_amount")
        return self

    @property
    def is_detail(self) -> bool:
        return self.intent in {Intent.TRANSACTION_LOOKUP, Intent.REFERENCE_LOOKUP,
                               Intent.LARGEST_TRANSACTIONS}

    def fingerprint(self) -> str:
        """Stable hash of the plan minus `user_question`, for caching and dedup."""
        import hashlib

        payload = self.model_dump_json(
            exclude={"user_question"}, exclude_none=True
        )
        return hashlib.sha256(payload.encode()).hexdigest()[:16]


class PlanDelta(BaseModel):
    """A follow-up turn: only the fields that change relative to the previous plan.

    `clear` lists fields the follow-up resets. A changed counterparty name drops the
    resolved counterparty.
    """

    model_config = ConfigDict(extra="forbid")

    intent: Intent | None = None
    counterparty_name: str | None = None
    account_last4: str | None = None
    bank_code: str | None = None
    reference: str | None = None
    reference_kind: ReferenceKind | None = None
    date_range: DateRange | None = None
    compare_to: DateRange | None = None
    transaction_type: TransactionType | None = None
    include_both_types: bool | None = None
    channel: Channel | None = None
    min_amount: float | None = None
    max_amount: float | None = None
    metric: Metric | None = None
    group_by: GroupBy | None = None
    limit: int | None = None

    clear: list[str] = Field(default_factory=list)

    def apply_to(self, base: FinanceQueryPlan) -> FinanceQueryPlan:
        data = base.model_dump()
        for field in self.clear:
            if field in data and field not in {"intent", "metric", "group_by", "limit",
                                               "entity_id"}:
                data[field] = None
            if field == "counterparty_name":
                data["counterparty"] = None
            if field == "account_last4":
                data["account_id"] = None
        for field, value in self.model_dump(exclude={"clear"}, exclude_none=True).items():
            data[field] = value
        if self.counterparty_name is not None:
            data["counterparty"] = None
        if self.account_last4 is not None:
            data["account_id"] = None
        return FinanceQueryPlan.model_validate(data)
