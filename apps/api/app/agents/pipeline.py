"""Per-turn orchestration: two model calls (plan, compose) with deterministic steps between."""
from __future__ import annotations

import uuid
from typing import Callable, Iterable

from pydantic import ValidationError

from ..contracts.enums import Intent, Metric, ReferenceKind, ResponseState
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
from ..services.crypto import FieldCipher, KeyError_
from ..services.resolver import MatchKind, resolve_account, resolve_counterparty
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
import logging

log = logging.getLogger("tbx.pipeline")

PERIOD_OPTIONS = [
    ("last_7_days", "Last 7 days"), ("last_30_days", "Last 30 days"),
    ("this_month", "This month"), ("last_month", "Last month"),
    ("last_90_days", "Last 90 days"), ("all_time", "All time"),
]
"""Offered when a list question names no period; value is the RelativeRange key."""

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
        try:
            self.cipher: FieldCipher | None = FieldCipher.from_env()
        except KeyError_ as e:
            log.warning("%s; UTR lookups will not decrypt", e)
            self.cipher = None
        self.evidence = EvidenceBuilder(ctx, self.cipher)
        self.judge = judge or Judge(get_cache(), ctx.dataset_version)
        router.judge = self.judge

    def run(self, question: str, state: ConversationState,
            model_choice: str | None = None, entity_id: str | None = None) -> AssistantResponse:
        rc = RunContext(run_id=f"run_{uuid.uuid4().hex[:12]}",
                        conversation_id=state.conversation_id,
                        on_event=self.on_event)
        if entity_id is not None:
            state.entity_id = entity_id or None
        elif state.entity_id is None:
            state.entity_id = self.ctx.default_entity
        try:
            pinned = self.planner.router.spec_for_choice(model_choice)
        except ValueError as e:
            rc.emit(EventType.RUN_FAILED, "Model not permitted", error=str(e))
            return self._respond(rc, ResponseState.ERROR, message=str(e))
        rc.emit(EventType.RUN_STARTED, "Understanding your question",
                question=question, turn=state.turns + 1,
                model=pinned.model if pinned else "auto")
        state.pending_plan = state.pending_question = state.pending_field = None
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

    def _run(self, question: str, state: ConversationState,
             rc: RunContext, pinned: ModelSpec | None) -> AssistantResponse:
        """Relevance gate, plan, validate, resolve the vendor, then `_execute`.

        A new question clears any pending clarification. A follow-up whose plan
        fingerprint equals the previous plan's asks for clarification instead of
        re-reporting the same figure.
        """
        rel = relevance.assess(question, self.ctx, state.last_plan is not None)
        if not rel.relevant:
            rc.emit(EventType.TASK_CREATED, "Judge: not relevant, no agents spawned",
                    dispatch={"planner": "skip", "composer": "skip", "anomaly": False,
                              "reasons": [rel.reason]})
            self._judge_record(rc, None)
            return self._refuse(rc, "out_of_scope", rel.reason)

        reg = self.planner.router.registry
        primary = reg[Tier.PRIMARY].model if Tier.PRIMARY in reg else ""
        alternate = reg[Tier.ALTERNATE].model if Tier.ALTERNATE in reg else None
        d = self.judge.dispatch_planning(question, state.turns, state.last_plan is not None,
                                         primary, alternate)
        rc.emit(EventType.TASK_CREATED, f"Judge: planner={d.planner}, relevance: {rel.reason}",
                dispatch=d.to_dict(), signals=rel.signals)

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

        try:
            plan = self.planner.materialise(parsed, state)
        except ValidationError as e:
            rc.emit(EventType.RUN_FAILED, "Plan failed validation", errors=e.errors()[:3])
            return self._respond(
                rc, ResponseState.ERROR,
                message="I couldn't turn that into a query I can run safely. "
                        "Rather than guess at what you meant, I'd rather stop here.")

        if (state.last_plan is not None
                and plan.fingerprint() == state.last_plan.fingerprint()):
            rc.emit(EventType.CLARIFICATION_REQUIRED, "Follow-up did not change the query")
            return self._respond(
                rc, ResponseState.CLARIFICATION_REQUIRED,
                clarification=Clarification(
                    question="I couldn't tell what that changes about the previous "
                             "question. Could you state the period, counterparty or "
                             "amount you mean?"))

        plan.user_question = question
        rc.emit(EventType.INTENT_DETECTED, f"Intent: {plan.intent.value}",
                intent=plan.intent.value, metric=plan.metric.value,
                group_by=plan.group_by.value)

        plan.entity_id = state.entity_id
        entity_match = entity_score = None
        outcome = self._resolve(plan, rc)
        if isinstance(outcome, AssistantResponse):
            if outcome.state is ResponseState.CLARIFICATION_REQUIRED:
                state.pending_plan = plan
                state.pending_question = question
                state.pending_field = outcome.clarification.field if outcome.clarification else None
            return outcome
        entity_match, entity_score = outcome

        return self._execute(question, state, rc, plan, entity_match, entity_score, pinned,
                             dispatch=d, cache_hit=cache_hit)

    def run_resolved(self, value: str, state: ConversationState,
                     model_choice: str | None = None, field: str | None = None) -> AssistantResponse:
        """Complete a plan parked on a clarification without a second planning call.

        `field` names what the option answers: counterparty, account, or date_range. It
        defaults to the field the clarification asked for.
        """
        rc = RunContext(run_id=f"run_{uuid.uuid4().hex[:12]}",
                        conversation_id=state.conversation_id, on_event=self.on_event)
        plan, question = state.pending_plan, state.pending_question
        field = field or state.pending_field
        if plan is None or not field:
            rc.emit(EventType.RUN_FAILED, "Nothing to clarify")
            return self._respond(rc, ResponseState.ERROR,
                                 message="There is no pending question to complete.")
        try:
            pinned = self.planner.router.spec_for_choice(model_choice)
        except ValueError as e:
            return self._respond(rc, ResponseState.ERROR, message=str(e))

        rc.emit(EventType.RUN_STARTED, "Completing your question", question=question,
                turn=state.turns + 1, model=pinned.model if pinned else "auto")
        rc.emit(EventType.SCOPE_CHECKED, "In scope")

        if field == "counterparty":
            rec = next((c for c in self.ctx.counterparties if c.name == value), None)
            if rec is None:
                rc.emit(EventType.RUN_FAILED, "Unknown counterparty", value=value)
                return self._respond(rc, ResponseState.ERROR,
                                     message="That option does not match a counterparty in the records.")
            plan = plan.model_copy(update={"counterparty": rec.name, "counterparty_name": rec.name})
            rc.emit(EventType.ENTITY_RESOLVED, f"Counterparty: {rec.name}",
                    query=rec.name, counterparty=rec.name, match="chosen", score=1.0)
        elif field == "account":
            acct = next((a for a in self.ctx.accounts if a.account_id == value), None)
            if acct is None:
                rc.emit(EventType.RUN_FAILED, "Unknown account", value=value)
                return self._respond(rc, ResponseState.ERROR,
                                     message="That option does not match an account in the records.")
            plan = plan.model_copy(update={"account_id": acct.account_id, "account_last4": acct.last4})
            rc.emit(EventType.ENTITY_RESOLVED, f"Account: {acct.masked}",
                    account=acct.masked, match="chosen", score=1.0)
        elif field == "date_range":
            from ..contracts.plan import DateRange
            try:
                plan = plan.model_copy(update={"date_range": DateRange(relative=value)})  # type: ignore[arg-type]
            except ValidationError:
                return self._respond(rc, ResponseState.ERROR,
                                     message="That option is not a period I understand.")
        else:
            return self._respond(rc, ResponseState.ERROR, message=f"Unknown clarification field {field}.")

        state.pending_plan = state.pending_question = state.pending_field = None
        rc.emit(EventType.INTENT_DETECTED, f"Intent: {plan.intent.value}",
                intent=plan.intent.value, metric=plan.metric.value, group_by=plan.group_by.value)
        outcome = self._resolve(plan, rc)
        if isinstance(outcome, AssistantResponse):
            if outcome.state is ResponseState.CLARIFICATION_REQUIRED:
                state.pending_plan, state.pending_question = plan, question
                state.pending_field = outcome.clarification.field if outcome.clarification else None
            return outcome
        try:
            return self._execute(question or "", state, rc, plan, outcome[0], outcome[1], pinned,
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
        """Dates, compile, query, verify, evidence, compose.

        Relative periods anchor to the dataset's calendar, not today's date. Anomaly
        figures are appended as facts so the callout is verifiable like the answer.
        """
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

        utr_hash = None
        if plan.reference and plan.reference_kind is ReferenceKind.UTR:
            if self.cipher is None:
                return self._respond(rc, ResponseState.ERROR,
                                     message="UTR lookup is not available: the data key is not configured.")
            utr_hash = self.cipher.blind_index(plan.reference)
        try:
            cq = compile_plan(plan, utr_hash=utr_hash)
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

        if count == 0 and (plan.metric is Metric.SUM or plan.is_detail):
            period = plan.date_range.resolved_label if plan.date_range else "the records"
            if plan.reference:
                what = (f"No transaction carries the {plan.reference_kind.value if plan.reference_kind else 'reference'} "
                        f"“{plan.reference}”. Check the number, or say “UTR” if it is one.")
            else:
                what = f"There are no matching transactions in {period}, so there is nothing to report."
            return self._respond(rc, ResponseState.DATA_UNAVAILABLE, message=what,
                                 capabilities=CAPABILITIES)

        evidence = self.evidence.build(rc, plan, cq, result, aggregate, rows, vr)
        evidence.confidence = conf.compute(
            plan, vr, entity_match=entity_match, entity_score=entity_score or 1.0,
            record_count=count, was_relative_date=was_relative,
            truncated=len(rows) >= plan.limit if rows else False)
        rc.emit(EventType.CONFIDENCE_COMPUTED,
                f"Confidence: {evidence.confidence.band.value} "
                f"({evidence.confidence.score:.0%})",
                score=evidence.confidence.score, signals=evidence.confidence.signals)

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
                    self.ch, plan.counterparty or "", plan.entity_id,
                    plan.date_range.resolved_start, plan.date_range.resolved_end,
                    float(fact.value), evidence.currency)
                rc.emit(EventType.TOOL_COMPLETED,
                        "Anomaly check: " + ("unusual" if a.flagged else "within normal range"),
                        flagged=a.flagged, ratio=a.ratio, z=a.z, history_months=a.history_months)
                if a.sentence:
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

    def _resolve(self, plan, rc: RunContext):
        """Counterparty, account and (for open-ended lists) period resolution.

        Returns (match_kind, score), or a finished response: a clarification with a
        dropdown when a name is ambiguous or a list has no period, DATA_UNAVAILABLE
        when a name matches nothing.
        """
        match, score = None, None
        if plan.counterparty_name and not plan.counterparty:
            res = resolve_counterparty(plan.counterparty_name,
                                       self.ctx.counterparties_for(plan.entity_id))
            if res.kind is MatchKind.AMBIGUOUS:
                rc.emit(EventType.CLARIFICATION_REQUIRED,
                        f"'{plan.counterparty_name}' matches {len(res.candidates)} counterparties")
                return self._respond(
                    rc, ResponseState.CLARIFICATION_REQUIRED,
                    clarification=Clarification(
                        question=f"“{plan.counterparty_name}” matches {len(res.candidates)} "
                                 "names in your transactions. Which one do you mean?",
                        field="counterparty",
                        options=[ClarificationOption(
                            label=c.record.name, value=c.record.name,
                            hint=f"{c.record.txn_count:,} transactions via {c.record.channel}")
                            for c in res.candidates]))
            if res.kind is MatchKind.NOT_FOUND:
                rc.emit(EventType.RUN_FAILED, f"No counterparty named '{plan.counterparty_name}'")
                near = self.ctx.counterparties_for(plan.entity_id)[:6]
                return self._respond(
                    rc, ResponseState.DATA_UNAVAILABLE,
                    message=f"None of your transactions name “{plan.counterparty_name}”. "
                            "These are the counterparties you deal with most:",
                    clarification=Clarification(
                        question="Pick one to ask the same question about:",
                        field="counterparty",
                        options=[ClarificationOption(label=c.name, value=c.name,
                                                     hint=f"{c.txn_count:,} transactions")
                                 for c in near]),
                    capabilities=CAPABILITIES)
            plan.counterparty = res.best.name
            plan.counterparty_name = res.best.name
            rc.emit(EventType.ENTITY_RESOLVED, f"Counterparty: {res.best.name}",
                    query=res.query, counterparty=res.best.name,
                    match=res.kind.value, score=res.score)
            match, score = res.kind, res.score

        if plan.account_last4 and not plan.account_id:
            ar = resolve_account(plan.account_last4, self.ctx.accounts_for(plan.entity_id))
            if ar.kind is MatchKind.AMBIGUOUS:
                rc.emit(EventType.CLARIFICATION_REQUIRED,
                        f"{len(ar.matches)} accounts end in {plan.account_last4}")
                return self._respond(
                    rc, ResponseState.CLARIFICATION_REQUIRED,
                    clarification=Clarification(
                        question=f"{len(ar.matches)} accounts end in {plan.account_last4}. Which one?",
                        field="account",
                        options=[ClarificationOption(label=a.masked, value=a.account_id,
                                                     hint=a.bank_name)
                                 for a in ar.matches]))
            if ar.kind is MatchKind.NOT_FOUND:
                rc.emit(EventType.RUN_FAILED, f"No account ending {plan.account_last4}")
                accts = self.ctx.accounts_for(plan.entity_id)[:8]
                return self._respond(
                    rc, ResponseState.DATA_UNAVAILABLE,
                    message=f"No account ends in {plan.account_last4}. Your accounts are:",
                    clarification=Clarification(
                        question="Pick an account:", field="account",
                        options=[ClarificationOption(label=a.masked, value=a.account_id,
                                                     hint=a.bank_name) for a in accts]),
                    capabilities=CAPABILITIES)
            plan.account_id = ar.matches[0].account_id
            rc.emit(EventType.ENTITY_RESOLVED, f"Account: {ar.matches[0].masked}",
                    account=ar.matches[0].masked, match="exact", score=1.0)
            if match is None:
                match, score = MatchKind.EXACT, 1.0

        if (plan.intent in {Intent.TRANSACTION_LOOKUP, Intent.LARGEST_TRANSACTIONS}
                and plan.date_range is None and not plan.reference):
            rc.emit(EventType.CLARIFICATION_REQUIRED, "List question without a period")
            return self._respond(
                rc, ResponseState.CLARIFICATION_REQUIRED,
                clarification=Clarification(
                    question="Which period should I look at?",
                    field="date_range",
                    options=[ClarificationOption(label=lbl, value=key)
                             for key, lbl in PERIOD_OPTIONS]))

        return match, score

    def _refuse(self, rc: RunContext, scope: str, reason: str | None) -> AssistantResponse:
        """Refuse with a fixed message and guided questions; the model's reason goes to the log."""
        guide = Clarification(
            question="Ask about your transactions, counterparties, balances or a reference. For example:",
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
