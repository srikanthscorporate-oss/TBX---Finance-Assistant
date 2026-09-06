"""First model call: a question to a schema-valid FinanceQueryPlan.

Attempt order: the primary (or pinned) model, the same model again with the validation
error, then the alternate model in auto mode only. No larger model is ever tried.
"""
from __future__ import annotations

from typing import Any

from ..contracts.enums import Channel, Intent
from ..contracts.events import EventType
from ..contracts.plan import FinanceQueryPlan, PlanDelta
from ..llm.router import AllModelsRateLimited, ModelRouter, ModelSpec, Tier, extract_json
from . import prompts
from .context import ConversationState, DatasetContext, RunContext

RELATIVE_VOCABULARY = (
    "last_month, this_month, month_before_last, last_quarter, this_quarter, "
    "last_year, this_year, last_7_days, last_30_days, last_90_days, "
    "last_6_months, last_12_months, today, yesterday, all_time"
)


class PlanningFailed(RuntimeError):
    """Every permitted attempt produced an unusable plan."""

    def __init__(self, model: str, attempts: int, last: Exception | None):
        self.model, self.attempts, self.last = model, attempts, last
        super().__init__(f"{model} did not produce a valid plan in {attempts} attempts: {last}")


class Planner:
    def __init__(self, router: ModelRouter, ctx: DatasetContext):
        self.router = router
        self.ctx = ctx

    def plan(self, question: str, state: ConversationState, rc: RunContext,
             pinned: ModelSpec | None = None, prefer: str | None = None) -> tuple[dict[str, Any], bool]:
        """Return (parsed_response, switched_model)."""
        system, user = self._prompt(question, state)

        attempts: list[tuple[Tier, bool, str]] = [
            (Tier.PRIMARY, False, ""),
            (Tier.PRIMARY, False, "retry"),
        ]
        if pinned is None and self.router.available(Tier.ALTERNATE):
            attempts.append((Tier.ALTERNATE, True, "alternate"))

        last_error: Exception | None = None
        feedback = ""
        for tier, switched, kind in attempts:
            try:
                raw = self.router.call(
                    tier=tier, purpose="plan" if not kind else f"plan_{kind}",
                    system=system + feedback, user=user, ledger=rc.ledger,
                    json_mode=True, max_tokens=1200, pinned=pinned, prefer=prefer)
                parsed = extract_json(raw)
                used = next((c.model for c in reversed(rc.ledger.calls) if c.ok), None)
                try:
                    if parsed.get("scope", "in_scope") == "in_scope":
                        self.materialise(parsed, state)
                except Exception:
                    if used and self.router.judge is not None:
                        self.router.judge.record_plan_outcome(used, False)
                    raise
                if used and self.router.judge is not None:
                    self.router.judge.record_plan_outcome(used, True)
                if switched:
                    rc.emit(EventType.FALLBACK_COMPLETED,
                            "Switched to an alternate model after a planning failure")
                return parsed, switched
            except AllModelsRateLimited:
                raise
            except Exception as e:  # noqa: BLE001
                last_error = e
                reason = str(e)[:300]
                rc.emit(EventType.FALLBACK_STARTED,
                        "Plan was unusable; retrying with feedback" if kind != "alternate"
                        else "Retry failed; trying an alternate model",
                        error=reason[:160])
                feedback = (f"\n\nYour previous response was rejected: {reason}. "
                            f"Return only a JSON object matching the schema exactly.")
                continue

        tried = pinned.model if pinned else "the configured models"
        raise PlanningFailed(tried, len(attempts), last_error)

    def materialise(self, parsed: dict[str, Any],
                    state: ConversationState) -> FinanceQueryPlan:
        if "delta" in parsed and state.last_plan is not None:
            delta = PlanDelta.model_validate(parsed.get("delta") or {})
            delta.clear = parsed.get("clear", []) or []
            return delta.apply_to(state.last_plan)
        return FinanceQueryPlan.model_validate(parsed.get("plan") or parsed)

    def _prompt(self, question: str, state: ConversationState) -> tuple[str, str]:
        if state.last_plan is not None:
            system, user_t = prompts.load("plan_delta_v1")
            system = prompts.fill(
                system,
                previous_plan=state.last_plan.model_dump_json(
                    exclude_none=True, exclude={"user_question"}),
                previous_period=state.last_period_label or "not specified")
        else:
            system, user_t = prompts.load("scope_and_plan_v1")
            system = prompts.fill(
                system,
                dataset_min=self.ctx.calendar.min_date,
                dataset_max=self.ctx.calendar.max_date,
                channels=", ".join(c.value for c in Channel),
                top_counterparties=", ".join(c.name for c in self.ctx.counterparties[:25]),
                intents=", ".join(i.value for i in Intent),
                relatives=RELATIVE_VOCABULARY)
        return system, prompts.fill(user_t, question=question)
