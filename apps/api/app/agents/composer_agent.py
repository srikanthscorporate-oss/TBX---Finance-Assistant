"""Second model call: prose around {{placeholder}} keys, filled server-side from the evidence.

A rejected draft is retried on the same model with the rejection reason, then on the
alternate model (auto mode only), then replaced by a deterministic template.
"""
from __future__ import annotations

from ..contracts.events import EventType
from ..contracts.evidence import EvidencePackage
from ..llm.router import ModelRouter, ModelSpec, Tier
from ..services import composer as comp
from . import prompts
from .context import RunContext

FACT_DESCRIPTIONS = {
    "shown_total": ("the combined value of ONLY the rows listed in the table "
                    "below, which was cut off by a row limit. Describe it as the "
                    "rows shown, never as a total"),
    "shown_count": "how many rows are listed below (fewer than the full match count)",
    "total": "the total value",
    "count": "the number of matching transactions",
    "record_count": "how many transactions the figure is based on",
    "top_value": "the largest single group's value",
    "top_label": "the name of the largest group",
    "group_count": "how many groups are shown",
    "balance_total": "sum of available balances",
    "amount": "the amount of the single matching transaction",
    "txn_date": "the date and time of the single matching transaction",
    "counterparty": "who the single matching transaction was with",
    "channel": "the payment rail of the single matching transaction",
    "account": "the masked account of the single matching transaction",
    "txn_type": "whether the single matching transaction was a debit or a credit",
}


class Composer:
    def __init__(self, router: ModelRouter):
        self.router = router

    def compose(self, question: str, evidence: EvidencePackage, rc: RunContext,
                pinned: ModelSpec | None = None) -> str:
        system = self._prompt(question, evidence)
        _, user_t = prompts.load("response_composer_v1")
        user = prompts.fill(user_t)

        attempts: list[tuple[Tier, str]] = [(Tier.PRIMARY, "compose"),
                                            (Tier.PRIMARY, "compose_retry")]
        if pinned is None and self.router.available(Tier.ALTERNATE):
            attempts.append((Tier.ALTERNATE, "compose_alternate"))

        last_error = ""
        for tier, purpose in attempts:
            corrective = (f"\n\nYour previous attempt was rejected: {last_error} Fix it."
                          if last_error else "")
            try:
                draft = self.router.call(
                    tier=tier, purpose=purpose, system=system + corrective, user=user,
                    ledger=rc.ledger, max_tokens=800, pinned=pinned)
                return comp.render(draft, evidence).text
            except comp.ComposeError as e:
                last_error = str(e)
                rc.emit(EventType.FALLBACK_STARTED,
                        "Draft rejected by the grounding check", reason=last_error[:160])
            except Exception as e:  # noqa: BLE001 -- provider failure
                last_error = str(e)
                break

        rc.emit(EventType.FALLBACK_COMPLETED, "Used the deterministic answer template")
        return comp.deterministic_fallback(evidence, question).text

    def _prompt(self, question: str, evidence: EvidencePackage) -> str:
        allowed = comp.allowed_keys(evidence)
        descriptions = "\n".join(
            f"- {{{{{f.key}}}}} = "
            + FACT_DESCRIPTIONS.get(f.key, f"the {f.kind} value")
            + (f" (over {f.record_count} records)" if f.record_count else "")
            for f in evidence.facts)
        system_t, _ = prompts.load("response_composer_v1")
        return prompts.fill(
            system_t,
            allowed_placeholders=", ".join("{{" + k + "}}" for k in allowed),
            fact_descriptions=descriptions,
            question=question,
            period_placeholder_note=evidence.resolved_period or "the whole dataset")
