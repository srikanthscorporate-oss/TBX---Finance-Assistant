"""Response composition by placeholder interpolation.

The composing model writes prose with typed placeholders from a whitelist and
the server substitutes verified values afterwards. An unknown placeholder or a
literal figure rejects the draft.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from ..contracts.evidence import ComputedFact, EvidencePackage

PLACEHOLDER_RE = re.compile(r"\{\{\s*([a-z][a-z0-9_.]{0,63})\s*\}\}")

BARE_NUMBER_RE = re.compile(r"(?<![\w.]) (?:\d{1,3}(?:,\d{3})+ | \d+\.\d+ | \d{3,}) (?![\w])", re.X)
"""Standalone 0-99 in prose is tolerated; grouped, decimal and 3+ digit numbers are not."""
CURRENCY_ADJACENT_RE = re.compile(r"[₹$€£¥]\s*\d|\d\s*(?:crore|lakh|million|billion|k\b|m\b|bn\b)", re.I)


class ComposeError(ValueError):
    """The draft cannot be rendered; the caller retries once, then uses the template."""


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
    """Substitute verified values into a draft.

    Raises ComposeError for an unknown placeholder, a literal figure, leftover
    braces (a truncated generation) or a draft that ends mid-sentence.
    """
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

    if "{{" in text or "}}" in text:
        raise ComposeError(
            "draft contains an unterminated placeholder (likely a truncated "
            "generation); rendered text must contain no braces")

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
    """Plain template answer used when the composing model fails twice."""
    facts = evidence.facts
    if not facts:
        raise ComposeError("no facts to render")

    primary = facts[0]
    parts = [f"{primary.formatted}"]
    if evidence.resolved_period:
        parts.append(f"for {evidence.resolved_period}")
    if "counterparty" in evidence.entities_resolved:
        parts.append(f"({evidence.entities_resolved['counterparty']})")
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


def template_answer(evidence: EvidencePackage, intent: str) -> ComposedAnswer | None:
    """Intent-aware sentence for a single-figure answer at zero tokens; only the wording is
    chosen here."""
    f = evidence.fact_map()
    ent = evidence.entities_resolved
    period = evidence.resolved_period
    cp = ent.get("counterparty")
    acct = ent.get("account")
    n = evidence.total_record_count
    when = f" in {period}" if period else ""
    where = f" from account {acct}" if acct else ""
    recs = f"across {n:,} transactions" if n else "with no matching transactions"
    kind = "received" if ent.get("transaction_type") == "credit" else "spent"

    text: str | None = None
    if intent == "counterparty_spend" and "total" in f and cp:
        text = f"You {kind} {f['total'].formatted} with {cp}{when}{where}, {recs}."
    elif intent == "counterparty_spend" and "count" in f and cp:
        text = f"You made {f['count'].formatted} transactions with {cp}{when}{where}."
    elif intent in {"spend_summary", "account_summary"} and "total" in f:
        text = f"Total {kind}{when}{where} was {f['total'].formatted}, {recs}."
    elif intent == "reference_lookup" and "count" in f:
        ref = ent.get("reference", "that reference")
        label = "UTR" if ent.get("reference_kind") == "utr" else "Reference"
        if int(f["count"].value) == 1:
            r = evidence.records[0] if evidence.records else {}
            text = (f"{label} {ref} is a {r.get('transaction_type', '')} of "
                    f"{r.get('amount_formatted', '')} on {r.get('transaction_date', '')} "
                    f"to {r.get('counterparty') or 'an unnamed counterparty'} via {r.get('channel', '')}, "
                    f"from account {r.get('account', '')}.")
        else:
            text = f"{f['count'].formatted} transactions match {label.lower()} {ref}."
    elif intent == "balance" and "balance_total" in f:
        text = f"Your available balance is {f['balance_total'].formatted} across {f['count'].formatted} accounts."
    elif intent == "largest_transactions" and evidence.records:
        r0 = evidence.records[0]
        n = len(evidence.records)
        what = "credits" if ent.get("transaction_type") == "credit" else "debits"
        biggest = (f"the biggest was {r0.get('amount_formatted')} to {r0.get('counterparty') or 'an unnamed counterparty'} "
                   f"on {str(r0.get('transaction_date', ''))[:10]}")
        text = f"Your {n} largest {what}{when}{where} total {f['shown_total' if 'shown_total' in f else 'total'].formatted}; {biggest}."
    elif intent == "transaction_lookup" and "count" in f:
        shown = f.get("shown_count")
        if shown:
            text = (f"{f['count'].formatted} transactions match{when}{where}; the first "
                    f"{shown.formatted} are listed, totalling {f['shown_total'].formatted}.")
        else:
            text = f"{f['count'].formatted} transactions match{when}{where}, totalling {f['total'].formatted}."
    elif "count" in f:
        text = f"{f['count'].formatted} records match{when}."
    elif "total" in f:
        text = f"The total{when} is {f['total'].formatted}, {recs}."
    if text is None:
        return None
    return ComposedAnswer(text=text, placeholders_used=list(f.keys()), fallback_used=False)
