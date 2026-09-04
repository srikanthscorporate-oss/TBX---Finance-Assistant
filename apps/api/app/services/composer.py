"""Response composition by placeholder interpolation.

THE CENTRAL GROUNDING MECHANISM.

The composing model is never asked to state a figure. It writes prose containing
typed placeholders -- {{total}}, {{record_count}}, {{vendor_name}} -- drawn from
a whitelist we hand it, and the server substitutes the verified values from the
EvidencePackage *after* generation.

Consequences:
  * A number the model invented cannot reach the user, because the model has no
    channel through which to emit one.
  * A placeholder we never computed fails closed (ComposeError), rather than
    rendering as literal braces or an empty string.
  * Any bare digit the model writes anyway is caught by the digit scan and the
    draft is rejected.

This converts "we check the model's arithmetic" into "the model cannot do
arithmetic in the first place".
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from ..contracts.evidence import ComputedFact, EvidencePackage

PLACEHOLDER_RE = re.compile(r"\{\{\s*([a-z][a-z0-9_.]{0,63})\s*\}\}")

# Digits the model is allowed to write literally: ordinals and small counts in
# prose ("the top 5 vendors") are harmless, but anything that could read as a
# monetary amount is not. We allow standalone integers 0-99 only when they are
# not adjacent to a currency symbol or decimal point.
BARE_NUMBER_RE = re.compile(r"(?<![\w.]) (?:\d{1,3}(?:,\d{3})+ | \d+\.\d+ | \d{3,}) (?![\w])", re.X)
CURRENCY_ADJACENT_RE = re.compile(r"[₹$€£¥]\s*\d|\d\s*(?:crore|lakh|million|billion|k\b|m\b|bn\b)", re.I)


class ComposeError(ValueError):
    """The draft cannot be safely rendered. The caller retries once with a
    corrective instruction, then falls back to a deterministic template."""


@dataclass
class ComposedAnswer:
    text: str
    placeholders_used: list[str]
    retries: int = 0
    fallback_used: bool = False


def allowed_keys(evidence: EvidencePackage) -> list[str]:
    """The exact vocabulary the composer prompt advertises to the model."""
    keys = evidence.fact_keys()
    if evidence.resolved_period:
        keys.append("period")
    if evidence.currency:
        keys.append("currency")
    for name in evidence.entities_resolved:
        keys.append(f"entity.{name}")
    return sorted(set(keys))


def render(draft: str, evidence: EvidencePackage, *, strict: bool = True) -> ComposedAnswer:
    """Substitute verified values into a draft. Raises ComposeError if the draft
    cites something we did not compute, or writes a figure of its own."""
    facts = evidence.fact_map()
    values = _value_table(evidence, facts)

    unknown = [k for k in PLACEHOLDER_RE.findall(draft) if k not in values]
    if unknown:
        raise ComposeError(
            f"draft cites placeholder(s) with no verified value: {', '.join(sorted(set(unknown)))}. "
            f"Allowed: {', '.join(sorted(values))}"
        )

    if strict:
        _reject_literal_figures(draft)

    used: list[str] = []

    def _sub(m: re.Match[str]) -> str:
        key = m.group(1)
        used.append(key)
        return values[key]

    text = PLACEHOLDER_RE.sub(_sub, draft).strip()
    text = re.sub(r"[ \t]{2,}", " ", text)

    if not text:
        raise ComposeError("draft rendered to an empty answer")

    # A truncated generation leaves a dangling "{{" that the placeholder regex
    # never matched, so it survived substitution and would have been shown to
    # the user as literal braces. Anything brace-shaped left here means the
    # draft was malformed: fail closed.
    if "{{" in text or "}}" in text:
        raise ComposeError(
            "draft contains an unterminated placeholder (likely a truncated "
            "generation); rendered text must contain no braces")

    # A sentence that never finished is not an answer.
    if not text.rstrip().endswith((".", "!", "?", "%")):
        raise ComposeError(f"draft ends mid-sentence: {text[-40:]!r}")

    return ComposedAnswer(text=text, placeholders_used=used)


def _value_table(evidence: EvidencePackage, facts: dict[str, ComputedFact]) -> dict[str, str]:
    values = {k: f.formatted for k, f in facts.items()}
    if evidence.resolved_period:
        values["period"] = evidence.resolved_period
    if evidence.currency:
        values["currency"] = evidence.currency
    for name, val in evidence.entities_resolved.items():
        values[f"entity.{name}"] = str(val)
    return values


def _reject_literal_figures(draft: str) -> None:
    """Catch a model that ignored the instruction and typed a number anyway.

    Placeholders are stripped first so that legitimate ones are not mistaken for
    literals.
    """
    stripped = PLACEHOLDER_RE.sub(" ", draft)
    if CURRENCY_ADJACENT_RE.search(stripped):
        raise ComposeError("draft contains a literal currency figure; use a {{placeholder}}")
    match = BARE_NUMBER_RE.search(stripped)
    if match:
        raise ComposeError(
            f"draft contains the literal number {match.group(0).strip()!r}; "
            "every figure must be a {{placeholder}}"
        )


def deterministic_fallback(evidence: EvidencePackage, question: str | None = None) -> ComposedAnswer:
    """Template answer used when the composing model fails twice.

    Deliberately plain. A slightly stilted sentence built from verified values
    beats a fluent one we cannot vouch for.
    """
    facts = evidence.facts
    if not facts:
        raise ComposeError("no facts to render")

    primary = facts[0]
    parts = [f"{primary.formatted}"]
    if evidence.resolved_period:
        parts.append(f"for {evidence.resolved_period}")
    if "vendor_name" in evidence.entities_resolved:
        parts.append(f"({evidence.entities_resolved['vendor_name']})")
    sentence = " ".join(parts) + "."
    if evidence.total_record_count:
        sentence += f" Based on {evidence.total_record_count:,} records."
    return ComposedAnswer(text=sentence, placeholders_used=[], fallback_used=True)


def format_money(value: float, currency: str | None) -> str:
    symbol = {"INR": "₹", "USD": "$", "EUR": "€", "GBP": "£", "JPY": "¥"}.get(
        (currency or "").upper(), ""
    )
    formatted = f"{value:,.2f}"
    if formatted.endswith(".00"):
        formatted = formatted[:-3]
    return f"{symbol}{formatted}" if symbol else f"{formatted} {currency or ''}".strip()


def format_count(value: float | int) -> str:
    return f"{int(value):,}"


def format_percent(value: float) -> str:
    return f"{value:.2f}%".replace(".00%", "%")


# Intent-aware sentences for single-figure answers. Every value is a verified
# fact; the only thing chosen here is the wording. Rendered at zero tokens.
def template_answer(evidence: EvidencePackage, intent: str) -> ComposedAnswer | None:
    f = evidence.fact_map()
    ent = evidence.entities_resolved
    period = evidence.resolved_period
    vendor = ent.get("vendor_name")
    category = ent.get("category")
    n = evidence.total_record_count
    when = f" in {period}" if period else ""
    recs = f"across {n:,} transactions" if n else "with no matching transactions"

    text: str | None = None
    if intent == "vendor_spend" and "total" in f and vendor:
        text = f"You spent {f['total'].formatted} with {vendor}{when}, {recs}."
    elif intent == "category_spend" and "total" in f and category:
        text = f"{category} spend{when} came to {f['total'].formatted}, {recs}."
    elif intent in {"total_spend", "account_spend"} and "total" in f:
        text = f"Total spend{when} was {f['total'].formatted}, {recs}."
    elif intent == "vendor_payouts" and "total" in f:
        who = f" to {vendor}" if vendor else ""
        text = f"Payouts{who}{when} totalled {f['total'].formatted}, {recs.replace('transactions', 'payouts')}."
    elif intent == "reconciliation_rate" and "rate" in f:
        extra = ""
        if "matched" in f and "unmatched" in f:
            extra = f" ({f['matched'].formatted} matched, {f['unmatched'].formatted} not)"
        text = f"{f['rate'].formatted} of transactions{when} are reconciled{extra}."
    elif intent == "unreconciled" and "count" in f:
        text = f"There are {f['count'].formatted} unreconciled transactions{when}."
    elif "count" in f:
        text = f"{f['count'].formatted} records match{when}."
    elif "total" in f:
        text = f"The total{when} is {f['total'].formatted}, {recs}."
    if text is None:
        return None
    return ComposedAnswer(text=text, placeholders_used=list(f.keys()), fallback_used=False)
