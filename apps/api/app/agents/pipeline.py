"""Orchestration.

The happy path is TWO model calls: one structured plan, one composed sentence.
Everything between them is deterministic Python with no model involvement, and
that is what makes the numbers defensible while keeping latency and token cost
down.

This module decides WHAT happens and in what order. It delegates the how:
  planner.py           the plan call, validation and escalation
  composer_agent.py    the compose call, retry and template fallback
  evidence_builder.py  assembling the evidence package
  services/*           resolution, dates, compilation, verification, confidence
"""
from __future__ import annotations

import uuid
from typing import Callable, Iterable

from pydantic import ValidationError

from ..contracts.enums import Metric, ResponseState
from ..contracts.evidence import EvidencePackage
from ..llm.router import AllModelsRateLimited, Tier
from ..contracts.events import AgentEvent, EventType
from ..contracts.response import AssistantResponse, Clarification, ClarificationOption
from ..db.clickhouse import ClickHouseClient, QueryError
from ..llm.router import ModelRouter, ModelSpec
from ..services import confidence as conf
from ..services import verification as verif
from ..services.compiler import CompilationError, compile_plan
from ..services.dates import DateResolutionError, resolve
from ..services.resolver import MatchKind, resolve_vendor
from . import anomaly as anomaly_agent
from . import relevance, suggestions
from .composer_agent import Composer
from .context import (CAPABILITIES, GUIDED_QUESTIONS, OUT_OF_SCOPE_MESSAGE,
                      ConversationState, DatasetContext, RunContext)
from .evidence_builder import EvidenceBuilder, record_count, split_result
from .judge import Dispatch, Judge
from .planner import Planner, PlanningFailed
from ..services import composer as comp_svc
from ..services.cache import cache as get_cache

# Re-exported so existing callers keep importing these from here.
__all__ = ["Pipeline", "ConversationState", "DatasetContext", "RunContext", "CAPABILITIES"]


class Pipeline:
    def __init__(self, ch: ClickHouseClient, router: ModelRouter, ctx: DatasetContext,
                 on_event: Callable[[AgentEvent], None] | None = None,
                 judge: Judge | None = None):
        self.ch = ch
        self.ctx = ctx
        self.on_event = on_event
        self.planner = Planner(router, ctx)
        self.composer = Composer(router)
        self.evidence = EvidenceBuilder(ctx)
        self.judge = judge or Judge(get_cache(), ctx.dataset_version)
        router.judge = self.judge

    # -- public ------------------------------------------------------------

    def run(self, question: str, state: ConversationState,
            model_choice: str | None = None) -> AssistantResponse:
        rc = RunContext(run_id=f"run_{uuid.uuid4().hex[:12]}",
                        conversation_id=state.conversation_id,
                        on_event=self.on_event)
        try:
            pinned = self.planner.router.spec_for_choice(model_choice)
        except ValueError as e:
            rc.emit(EventType.RUN_FAILED, "Model not permitted", error=str(e))
            return self._respond(rc, ResponseState.ERROR, message=str(e))
        rc.emit(EventType.RUN_STARTED, "Understanding your question",
                question=question, turn=state.turns + 1,
                model=pinned.model if pinned else "auto")
        # A new question supersedes any clarification still waiting.
        state.pending_plan = state.pending_question = None
        if not question.strip():
            return self._respond(rc, ResponseState.ERROR, message="Please type a question.")
        try:
            return self._run(question, state, rc, pinned)
        except AllModelsRateLimited as e:
            rc.emit(EventType.RUN_FAILED, "Providers rate limited; nothing was guessed",
                    retry_after_s=e.retry_after_s, models=e.models)
            mins = f"{e.retry_after_s // 60}m {e.retry_after_s % 60}s" if e.retry_after_s >= 60 else f"{e.retry_after_s}s"
            return self._respond(
                rc, ResponseState.ERROR,
                message=f"The model providers are rate limited right now, so I have not "
                        f"answered rather than guess. Please try again in about {mins}.")
        except PlanningFailed as e:
            # Say which model failed and why, rather than a generic error. With
            # a pinned model this is the honest outcome of honouring the pin.
            rc.emit(EventType.RUN_FAILED, "No valid plan", model=e.model,
                    attempts=e.attempts, error=str(e.last)[:200])
            hint = (" Try Auto, or a different model from the dropdown."
                    if pinned else " Please rephrase, or try again.")
            return self._respond(
                rc, ResponseState.ERROR,
                message=f"{e.model.split('/')[-1]} could not turn that into a query I "
                        f"can run safely, after {e.attempts} attempts.{hint}")
        except Exception as e:  # noqa: BLE001 -- last-resort guard
            rc.emit(EventType.RUN_FAILED, "Run failed", error=str(e)[:300])
            return self._respond(rc, ResponseState.ERROR,
                                 message="Something went wrong while answering that. "
                                         "Please try again.")

    # -- the sequence ------------------------------------------------------

    def _run(self, question: str, state: ConversationState,
             rc: RunContext, pinned: ModelSpec | None) -> AssistantResponse:
        # 0. Judge: is this even about the records? No agent runs otherwise.
        rel = relevance.assess(question, self.ctx, state.last_plan is not None)
        if not rel.relevant:
            rc.emit(EventType.TASK_CREATED, "Judge: not relevant, no agents spawned",
                    dispatch={"planner": "skip", "composer": "skip", "anomaly": False,
                              "reasons": [rel.reason]})
            self._judge_record(rc, None)
            return self._refuse(rc, "out_of_scope", rel.reason)

        # 0b. Judge: which agents, which model, or a cache hit.
        reg = self.planner.router.registry
        primary = reg[Tier.PRIMARY].model if Tier.PRIMARY in reg else ""
        alternate = reg[Tier.ALTERNATE].model if Tier.ALTERNATE in reg else None
        d = self.judge.dispatch_planning(question, state.turns, state.last_plan is not None,
                                         primary, alternate)
        rc.emit(EventType.TASK_CREATED, f"Judge: planner={d.planner}, relevance: {rel.reason}",
                dispatch=d.to_dict(), signals=rel.signals)

        # 1. Plan (model call one), unless the judge found it cached.
        cache_hit: str | None = None
        if d.planner == "cache" and pinned is None:
            parsed = self.judge.cached_plan(question, state.turns) or {}
            cache_hit = "plan"
            rc.emit(EventType.PLAN_VALIDATED, "Plan reused from cache (0 tokens)")
        else:
            parsed, _switched = self.planner.plan(question, state, rc, pinned=pinned,
                                                  prefer=None if pinned else d.model)
            if pinned is None:
                self.judge.remember_plan(question, state.turns, parsed)
        scope = parsed.get("scope", "in_scope")

        if scope in {"out_of_scope", "data_unavailable"}:
            return self._refuse(rc, scope, parsed.get("reason"))
        rc.emit(EventType.SCOPE_CHECKED, "In scope")

        # 2. Validate against the closed schema.
        try:
            plan = self.planner.materialise(parsed, state)
        except ValidationError as e:
            rc.emit(EventType.RUN_FAILED, "Plan failed validation", errors=e.errors()[:3])
            return self._respond(
                rc, ResponseState.ERROR,
                message="I couldn't turn that into a query I can run safely. "
                        "Rather than guess at what you meant, I'd rather stop here.")

        # A follow-up that yields an identical plan means coreference failed.
        # Answering would re-report the SAME figure under the new question's
        # framing, which is the most misleading thing this system could do.
        if (state.last_plan is not None
                and plan.fingerprint() == state.last_plan.fingerprint()):
            rc.emit(EventType.CLARIFICATION_REQUIRED, "Follow-up did not change the query")
            return self._respond(
                rc, ResponseState.CLARIFICATION_REQUIRED,
                clarification=Clarification(
                    question="I couldn't tell what that changes about the previous "
                             "question. Could you state the period or vendor you mean?"))

        plan.user_question = question
        rc.emit(EventType.INTENT_DETECTED, f"Intent: {plan.intent.value}",
                intent=plan.intent.value, metric=plan.metric.value,
                group_by=plan.group_by.value)

        # 3. Resolve the vendor deterministically. Ambiguity asks, never guesses.
        entity_match = entity_score = None
        if plan.vendor_name and not plan.vendor_id:
            outcome = self._resolve_vendor(plan, rc)
            if isinstance(outcome, AssistantResponse):
                if outcome.state is ResponseState.CLARIFICATION_REQUIRED:
                    state.pending_plan = plan
                    state.pending_question = question
                return outcome
            entity_match, entity_score = outcome

        return self._execute(question, state, rc, plan, entity_match, entity_score, pinned,
                             dispatch=d, cache_hit=cache_hit)

    def run_resolved(self, vendor_id: str, state: ConversationState,
                     model_choice: str | None = None) -> AssistantResponse:
        """Complete a plan parked on a vendor clarification.

        The user picked an option, so the entity is now certain: pin it on the
        parked plan and run the rest of the pipeline. No second planning call.
        """
        rc = RunContext(run_id=f"run_{uuid.uuid4().hex[:12]}",
                        conversation_id=state.conversation_id, on_event=self.on_event)
        plan, question = state.pending_plan, state.pending_question
        if plan is None:
            rc.emit(EventType.RUN_FAILED, "Nothing to clarify")
            return self._respond(rc, ResponseState.ERROR,
                                 message="There is no pending question to complete.")
        vendor = next((v for v in self.ctx.vendors if v.vendor_id == vendor_id), None)
        if vendor is None:
            rc.emit(EventType.RUN_FAILED, "Unknown vendor id", vendor_id=vendor_id)
            return self._respond(rc, ResponseState.ERROR,
                                 message="That option does not match a vendor in the dataset.")
        try:
            pinned = self.planner.router.spec_for_choice(model_choice)
        except ValueError as e:
            return self._respond(rc, ResponseState.ERROR, message=str(e))

        state.pending_plan = state.pending_question = None
        plan = plan.model_copy(update={"vendor_id": vendor.vendor_id,
                                       "vendor_name": vendor.vendor_name})
        rc.emit(EventType.RUN_STARTED, "Completing your question", question=question,
                turn=state.turns + 1, model=pinned.model if pinned else "auto")
        rc.emit(EventType.SCOPE_CHECKED, "In scope")
        rc.emit(EventType.INTENT_DETECTED, f"Intent: {plan.intent.value}",
                intent=plan.intent.value, metric=plan.metric.value, group_by=plan.group_by.value)
        rc.emit(EventType.ENTITY_RESOLVED, f"Vendor: {vendor.vendor_name}",
                query=vendor.vendor_name, vendor_id=vendor.vendor_id, match="chosen", score=1.0)
        try:
            return self._execute(question or "", state, rc, plan, MatchKind.EXACT, 1.0, pinned,
                                 dispatch=Dispatch("skip", "llm", False, None,
                                                   ["clarification answered; planner not needed"]),
                                 cache_hit=None)
        except Exception as e:  # noqa: BLE001
            rc.emit(EventType.RUN_FAILED, "Run failed", error=str(e)[:300])
            return self._respond(rc, ResponseState.ERROR,
                                 message="Something went wrong while answering that.")

    def _execute(self, question: str, state: ConversationState, rc: RunContext,
                 plan, entity_match, entity_score, pinned,
                 dispatch: Dispatch, cache_hit: str | None) -> AssistantResponse:
        """Everything after the entity is certain: dates, compile, query,
        verify, evidence, compose."""

        # 4. Resolve dates against the DATASET, not today.
        was_relative = bool(plan.date_range and plan.date_range.relative)
        try:
            if plan.date_range:
                plan.date_range = resolve(plan.date_range, self.ctx.calendar)
            if plan.compare_to:
                plan.compare_to = resolve(plan.compare_to, self.ctx.calendar)
        except DateResolutionError as e:
            return self._respond(rc, ResponseState.ERROR, message=str(e))

        if plan.date_range:
            rc.emit(EventType.DATES_RESOLVED, f"Period: {plan.date_range.resolved_label}",
                    start=str(plan.date_range.resolved_start),
                    end=str(plan.date_range.resolved_end), was_relative=was_relative)
        rc.emit(EventType.PLAN_VALIDATED, "Query plan validated",
                fingerprint=plan.fingerprint())

        # 4b. Judge: an identical validated plan was answered recently.
        hit = self.judge.cached_answer(plan.fingerprint()) if pinned is None else None
        if hit:
            rc.emit(EventType.TASK_CREATED, "Judge: answer reused from cache (0 tokens, no query)",
                    dispatch={"planner": dispatch.planner, "composer": "cache", "anomaly": False})
            rc.emit(EventType.ANSWER_GENERATED, "Answer ready (cached)")
            state.last_plan = plan
            state.last_period_label = plan.date_range.resolved_label if plan.date_range else None
            state.turns += 1
            rc.emit(EventType.RUN_COMPLETED, "Done")
            resp = AssistantResponse(
                run_id=rc.run_id, conversation_id=rc.conversation_id,
                state=ResponseState.ANSWER, answer=hit["answer"],
                evidence=EvidencePackage.model_validate(hit["evidence"]), plan=plan,
                chart_hint=hit.get("chart_hint"),
                follow_up_suggestions=suggestions.follow_ups(plan),
                model_usage=rc.ledger.summary())
            self._judge_record(rc, resp, cache_hit="answer")
            return resp

        # 5. Compile and execute. No model anywhere near this.
        try:
            cq = compile_plan(plan)
        except CompilationError as e:
            rc.emit(EventType.RUN_FAILED, "Could not compile query", error=str(e))
            return self._respond(rc, ResponseState.ERROR,
                                 message="I couldn't turn that into a safe query.")

        rc.emit(EventType.TOOL_STARTED, "Querying financial records", kind=cq.kind)
        try:
            result = self.ch.query(cq.sql, cq.params)
        except QueryError as e:
            rc.emit(EventType.RUN_FAILED, "Query failed", error=str(e)[:200])
            return self._respond(rc, ResponseState.ERROR,
                                 message="The financial database could not be queried. "
                                         "I won't guess at the figure.")

        aggregate, rows = split_result(cq.kind, result.rows)
        rc.emit(EventType.QUERY_EXECUTED, f"{len(result.rows)} rows returned",
                duration_ms=result.duration_ms, rows_read=result.rows_read)

        # 6. Verify. Blocking failures veto the answer entirely.
        rc.emit(EventType.VERIFICATION_STARTED, "Verifying result")
        vr = verif.verify(plan, rows, aggregate=aggregate,
                          dataset_min=self.ctx.calendar.min_date,
                          dataset_max=self.ctx.calendar.max_date)
        rc.emit(EventType.VERIFICATION_COMPLETED,
                f"Verification: {vr.passed_count}/{vr.total_count} passed",
                passed=vr.passed,
                checks=[{"name": c.name, "passed": c.passed, "detail": c.detail}
                        for c in vr.checks])

        count = record_count(aggregate, rows)
        if not vr.passed:
            failed = [c.name for c in vr.checks if not c.passed and c.severity == "blocking"]
            return self._respond(
                rc, ResponseState.DATA_UNAVAILABLE,
                message="I can't give you a figure I can stand behind for that "
                        f"({', '.join(failed)}). Rather than guess, I'd rather tell you.",
                capabilities=CAPABILITIES)

        if count == 0 and plan.metric is Metric.SUM:
            period = plan.date_range.resolved_label if plan.date_range else "the dataset"
            return self._respond(
                rc, ResponseState.DATA_UNAVAILABLE,
                message=f"There are no matching records for {period}, so there is no "
                        "figure to report.",
                capabilities=CAPABILITIES)

        # 7. Evidence and confidence.
        evidence = self.evidence.build(rc, plan, cq, result, aggregate, rows, vr)
        evidence.confidence = conf.compute(
            plan, vr, entity_match=entity_match, entity_score=entity_score or 1.0,
            record_count=count, was_relative_date=was_relative,
            truncated=len(rows) >= plan.limit if rows else False)
        rc.emit(EventType.CONFIDENCE_COMPUTED,
                f"Confidence: {evidence.confidence.band.value} "
                f"({evidence.confidence.score:.0%})",
                score=evidence.confidence.score, signals=evidence.confidence.signals)

        # 8. Judge: template or model; and whether an anomaly agent is worth it.
        d2 = self.judge.dispatch_answering(plan, evidence, dispatch)
        rc.emit(EventType.TASK_CREATED,
                f"Judge: composer={d2.composer}{', anomaly agent' if d2.anomaly else ''}",
                dispatch=d2.to_dict())

        answer = None
        if d2.composer == "template":
            t = comp_svc.template_answer(evidence, plan.intent.value)
            answer = t.text if t else None
        if answer is None:
            answer = self.composer.compose(question, evidence, rc, pinned=pinned)

        if d2.anomaly:
            fact = evidence.fact_map().get("total")
            if fact and plan.date_range and plan.date_range.resolved_start:
                a = anomaly_agent.check(
                    self.ch, "vendor_payouts" if plan.intent.value == "vendor_payouts" else "transactions",
                    plan.vendor_id, plan.vendor_name or plan.vendor_id,
                    plan.date_range.resolved_start, plan.date_range.resolved_end,
                    float(fact.value), evidence.currency)
                rc.emit(EventType.TOOL_COMPLETED,
                        "Anomaly check: " + ("unusual" if a.flagged else "within normal range"),
                        flagged=a.flagged, ratio=a.ratio, z=a.z, history_months=a.history_months)
                if a.sentence:
                    # Every figure in the sentence becomes a fact, so the callout is as
                    # traceable as the answer it accompanies and the hallucination
                    # detector can verify it rather than flag it.
                    from ..contracts.evidence import ComputedFact as _CF
                    evidence.facts.append(_CF(key="anomaly_ratio", value=a.ratio or 0.0, kind="ratio",
                                              formatted=f"{a.ratio:.1f}x" if a.ratio else "n/a"))
                    evidence.facts.append(_CF(key="anomaly_baseline", value=a.baseline or 0.0, kind="money",
                                              currency=evidence.currency,
                                              formatted=comp_svc.format_money(a.baseline or 0.0, evidence.currency)))
                    evidence.facts.append(_CF(key="anomaly_history_months", value=a.history_months, kind="count",
                                              formatted=str(a.history_months)))
                    answer = f"{answer} {a.sentence}"
                    evidence.verification.add("anomaly_callout", True, a.sentence, severity="warning")
        rc.emit(EventType.ANSWER_GENERATED, "Answer ready")

        state.last_plan = plan
        state.last_period_label = (plan.date_range.resolved_label
                                   if plan.date_range else None)
        state.turns += 1

        rc.emit(EventType.RUN_COMPLETED, "Done")
        resp = AssistantResponse(
            run_id=rc.run_id, conversation_id=rc.conversation_id,
            state=ResponseState.ANSWER, answer=answer, evidence=evidence, plan=plan,
            chart_hint=suggestions.chart_hint(plan, rows),
            follow_up_suggestions=suggestions.follow_ups(plan),
            model_usage=rc.ledger.summary())
        if pinned is None:
            self.judge.remember_answer(plan.fingerprint(), {
                "answer": answer, "evidence": evidence.model_dump(mode="json"),
                "chart_hint": resp.chart_hint})
        self._judge_record(rc, resp, cache_hit=cache_hit)
        return resp

    def _judge_record(self, rc: RunContext, resp: AssistantResponse | None,
                      cache_hit: str | None = None) -> None:
        if resp is None:
            return
        try:
            v = self.judge.record(resp, cache_hit)
            rc.emit(EventType.TASK_COMPLETED, f"Judge: score {v.score:.2f}",
                    verdict=v.to_dict())
        except Exception:  # noqa: BLE001 -- scoring must never fail a run
            pass

    # -- helpers -----------------------------------------------------------

    def _resolve_vendor(self, plan, rc: RunContext):
        """Returns (match_kind, score), or a finished response when it cannot."""
        res = resolve_vendor(plan.vendor_name, self.ctx.vendors)

        if res.kind is MatchKind.AMBIGUOUS:
            rc.emit(EventType.CLARIFICATION_REQUIRED,
                    f"'{plan.vendor_name}' matches {len(res.candidates)} vendors")
            return self._respond(
                rc, ResponseState.CLARIFICATION_REQUIRED,
                clarification=Clarification(
                    question=f"There are {len(res.candidates)} vendors matching "
                             f"“{plan.vendor_name}”. Which one do you mean?",
                    field="vendor_name",
                    options=[ClarificationOption(label=c.record.vendor_name,
                                                 value=c.record.vendor_id,
                                                 hint=c.record.category)
                             for c in res.candidates]))

        if res.kind is MatchKind.NOT_FOUND:
            rc.emit(EventType.RUN_FAILED, f"No vendor named '{plan.vendor_name}'")
            near = [v.vendor_name for v in self.ctx.vendors][:6]
            return self._respond(
                rc, ResponseState.DATA_UNAVAILABLE,
                message=f"There is no vendor matching “{plan.vendor_name}” in this "
                        "dataset. Did you mean one of these?",
                clarification=Clarification(
                    question="Pick a vendor to ask the same question about:",
                    field="vendor_name",
                    options=[ClarificationOption(label=n, value=n) for n in near]),
                capabilities=CAPABILITIES)

        plan.vendor_id = res.best.vendor_id
        plan.vendor_name = res.best.vendor_name
        rc.emit(EventType.ENTITY_RESOLVED, f"Vendor: {res.best.vendor_name}",
                query=res.query, vendor_id=res.best.vendor_id,
                match=res.kind.value, score=res.score)
        return res.kind, res.score

    def _refuse(self, rc: RunContext, scope: str, reason: str | None) -> AssistantResponse:
        """A refusal is a steer, not a dead end.

        The user-facing sentence is ours, fixed, and never the model's own
        wording (the model's reason is kept in the event log for the pane).
        Every refusal carries guided questions, so the chat keeps offering a
        relevant next step until something actually runs.
        """
        guide = Clarification(
            question="Ask about spend, payouts or reconciliation. For example:",
            field="guided",
            options=[ClarificationOption(label=q, value=q) for q in GUIDED_QUESTIONS])
        if scope == "out_of_scope":
            rc.emit(EventType.SCOPE_CHECKED, "Not relevant to this service",
                    reason=(reason or "")[:200])
            return self._respond(rc, ResponseState.OUT_OF_SCOPE,
                                 message=OUT_OF_SCOPE_MESSAGE, clarification=guide,
                                 capabilities=CAPABILITIES)
        rc.emit(EventType.SCOPE_CHECKED, "Data not available", reason=(reason or "")[:200])
        return self._respond(
            rc, ResponseState.DATA_UNAVAILABLE,
            message=(reason or "The dataset does not contain what that needs.")
                    + " Here is what I can answer:",
            clarification=guide, capabilities=CAPABILITIES)

    def _respond(self, rc: RunContext, state: ResponseState, *,
                 message: str | None = None,
                 clarification: Clarification | None = None,
                 capabilities: Iterable[str] = ()) -> AssistantResponse:
        rc.emit(EventType.RUN_COMPLETED, f"Finished: {state.value}")
        resp = AssistantResponse(
            run_id=rc.run_id, conversation_id=rc.conversation_id, state=state,
            message=message, clarification=clarification,
            supported_capabilities=list(capabilities),
            model_usage=rc.ledger.summary())
        self._judge_record(rc, resp)
        return resp
