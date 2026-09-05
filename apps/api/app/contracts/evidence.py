"""The evidence package, the only source of figures in a response.

The composer cites facts by key; substitution happens server-side after generation.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .enums import ConfidenceBand


class SourceRecordRef(BaseModel):
    """A pointer back to a source row."""

    model_config = ConfigDict(extra="forbid")

    table: str
    record_id: str
    txn_date: date | None = None
    vendor_id: str | None = None
    amount: float | None = None


class BreakdownRow(BaseModel):
    """One row of the table shown beside the answer."""

    model_config = ConfigDict(extra="allow")

    label: str
    value: float
    record_count: int | None = None
    share_pct: float | None = None


class ComputedFact(BaseModel):
    """One computed value; `key` is cited as `{{key}}` and `formatted` is substituted."""

    model_config = ConfigDict(extra="forbid")

    key: str = Field(pattern=r"^[a-z][a-z0-9_.]{0,63}$")
    value: float | int | str
    kind: Literal["money", "count", "percent", "ratio", "text", "date"] = "money"
    currency: str | None = None
    formatted: str
    sql_expression: str | None = None
    record_count: int | None = None


class VerificationCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    passed: bool
    detail: str | None = None
    severity: Literal["blocking", "warning"] = "blocking"


class VerificationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    checks: list[VerificationCheck] = Field(default_factory=list)

    @property
    def passed(self) -> bool:
        """Blocking failures veto an answer; warnings only reduce confidence."""
        return all(c.passed for c in self.checks if c.severity == "blocking")

    @property
    def passed_count(self) -> int:
        return sum(1 for c in self.checks if c.passed)

    @property
    def total_count(self) -> int:
        return len(self.checks)

    @property
    def warnings(self) -> list[VerificationCheck]:
        return [c for c in self.checks if not c.passed and c.severity == "warning"]

    def add(self, name: str, passed: bool, detail: str | None = None,
            severity: Literal["blocking", "warning"] = "blocking") -> None:
        self.checks.append(
            VerificationCheck(name=name, passed=passed, detail=detail, severity=severity)
        )


class ConfidenceReport(BaseModel):
    """Confidence from data-quality signals, not model self-report."""

    model_config = ConfigDict(extra="forbid")

    score: float = Field(ge=0.0, le=1.0)
    band: ConfidenceBand
    signals: dict[str, float] = Field(default_factory=dict)
    reasons: list[str] = Field(default_factory=list)


class EvidencePackage(BaseModel):
    """Everything needed to check an answer."""

    model_config = ConfigDict(extra="forbid")

    evidence_id: str
    run_id: str
    plan_fingerprint: str

    facts: list[ComputedFact] = Field(default_factory=list)
    breakdown: list[BreakdownRow] = Field(default_factory=list)
    breakdown_columns: list[str] = Field(default_factory=list)
    sample_records: list[SourceRecordRef] = Field(default_factory=list)

    total_record_count: int = 0
    resolved_period: str | None = None
    resolved_start: date | None = None
    resolved_end: date | None = None
    currency: str | None = None
    entities_resolved: dict[str, Any] = Field(default_factory=dict)

    sql: str | None = None
    sql_params: dict[str, Any] = Field(default_factory=dict)
    query_duration_ms: float | None = None

    verification: VerificationResult = Field(default_factory=VerificationResult)
    confidence: ConfidenceReport | None = None
    dataset_version: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

    def fact_map(self) -> dict[str, ComputedFact]:
        return {f.key: f for f in self.facts}

    def fact_keys(self) -> list[str]:
        return [f.key for f in self.facts]
