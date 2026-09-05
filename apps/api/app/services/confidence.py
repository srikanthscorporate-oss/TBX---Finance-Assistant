"""Confidence from measured data-quality signals, not model self-report."""
from __future__ import annotations

from ..contracts.enums import ConfidenceBand
from ..contracts.evidence import ConfidenceReport, VerificationResult
from ..contracts.plan import FinanceQueryPlan
from .resolver import MatchKind

WEIGHTS = {
    "entity_exact": 0.22,
    "dates_explicit": 0.18,
    "verification_clean": 0.25,
    "data_complete": 0.15,
    "single_type": 0.10,
    "deterministic_metric": 0.10,
}
"""Weight each signal contributes when satisfied; weights sum to 1.0."""

HIGH_MIN = 0.90
MEDIUM_MIN = 0.75


def compute(
    plan: FinanceQueryPlan,
    verification: VerificationResult,
    *,
    entity_match: MatchKind | None = None,
    entity_score: float = 1.0,
    record_count: int = 0,
    was_relative_date: bool = False,
    truncated: bool = False,
) -> ConfidenceReport:
    """Score from entity, date, verification, completeness and currency signals.

    An explicit date window scores higher than a relative phrase we interpreted;
    the metric signal is always satisfied since every metric is a SQL aggregate.
    """
    signals: dict[str, float] = {}
    reasons: list[str] = []

    if entity_match is None:
        signals["entity_exact"] = 1.0  # no entity to resolve
    elif entity_match is MatchKind.EXACT:
        signals["entity_exact"] = 1.0
    elif entity_match is MatchKind.UNIQUE_FUZZY:
        signals["entity_exact"] = max(0.0, min(1.0, entity_score))
        reasons.append(f"counterparty matched approximately (score {entity_score:.2f})")
    else:
        signals["entity_exact"] = 0.0
        reasons.append("counterparty could not be resolved unambiguously")

    if plan.date_range is None:
        signals["dates_explicit"] = 0.7
        reasons.append("no period specified; answered across the whole dataset")
    elif was_relative_date:
        signals["dates_explicit"] = 0.85
        reasons.append(
            f"interpreted the period as {plan.date_range.resolved_label}"
        )
    else:
        signals["dates_explicit"] = 1.0

    total = verification.total_count or 1
    passed = verification.passed_count
    signals["verification_clean"] = passed / total
    if not verification.passed:
        signals["verification_clean"] = 0.0
        reasons.append("one or more blocking verification checks failed")
    for w in verification.warnings:
        reasons.append(w.detail or w.name)

    if record_count == 0:
        signals["data_complete"] = 0.0
        reasons.append("no records matched")
    elif truncated:
        signals["data_complete"] = 0.5
        reasons.append("result was truncated by the row limit")
    elif record_count < 5:
        signals["data_complete"] = 0.8
        reasons.append(f"based on only {record_count} record(s)")
    else:
        signals["data_complete"] = 1.0

    cur = next((c for c in verification.checks if c.name == "single_transaction_type"), None)
    signals["single_type"] = 1.0 if (cur is None or cur.passed) else 0.0

    signals["deterministic_metric"] = 1.0

    score = sum(WEIGHTS[k] * v for k, v in signals.items() if k in WEIGHTS)
    score = round(max(0.0, min(1.0, score)), 4)

    if not verification.passed:
        band = ConfidenceBand.LOW
    elif score >= HIGH_MIN:
        band = ConfidenceBand.HIGH
    elif score >= MEDIUM_MIN:
        band = ConfidenceBand.MEDIUM
    else:
        band = ConfidenceBand.LOW

    return ConfidenceReport(score=score, band=band, signals=signals, reasons=reasons)
