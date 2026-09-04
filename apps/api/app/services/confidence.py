"""Confidence from data-quality signals.

We never ask the model how confident it is -- a language model's stated
certainty is uncorrelated with whether the underlying figure is right. Every
signal here is something we measured about the query and its result.
"""
from __future__ import annotations

from ..contracts.enums import ConfidenceBand
from ..contracts.evidence import ConfidenceReport, VerificationResult
from ..contracts.plan import FinanceQueryPlan
from .resolver import MatchKind

# Each signal contributes its weight when satisfied. Weights sum to 1.0.
WEIGHTS = {
    "entity_exact": 0.22,
    "dates_explicit": 0.18,
    "verification_clean": 0.25,
    "data_complete": 0.15,
    "single_currency": 0.10,
    "deterministic_metric": 0.10,
}

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
    signals: dict[str, float] = {}
    reasons: list[str] = []

    # 1. Entity resolution quality.
    if entity_match is None:
        signals["entity_exact"] = 1.0            # no entity to resolve
    elif entity_match is MatchKind.EXACT:
        signals["entity_exact"] = 1.0
    elif entity_match is MatchKind.UNIQUE_FUZZY:
        signals["entity_exact"] = max(0.0, min(1.0, entity_score))
        reasons.append(f"vendor matched approximately (score {entity_score:.2f})")
    else:
        signals["entity_exact"] = 0.0
        reasons.append("vendor could not be resolved unambiguously")

    # 2. Date interpretation. An explicit window is stronger evidence that we
    #    understood the question than a relative phrase we interpreted for them.
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

    # 3. Verification outcome.
    total = verification.total_count or 1
    passed = verification.passed_count
    signals["verification_clean"] = passed / total
    if not verification.passed:
        signals["verification_clean"] = 0.0
        reasons.append("one or more blocking verification checks failed")
    for w in verification.warnings:
        reasons.append(w.detail or w.name)

    # 4. Completeness.
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

    # 5. Currency consistency.
    cur = next((c for c in verification.checks if c.name == "currency_consistent"), None)
    signals["single_currency"] = 1.0 if (cur is None or cur.passed) else 0.0

    # 6. The metric itself is a deterministic SQL aggregate, always true here --
    #    kept explicit so the panel shows why that matters.
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
