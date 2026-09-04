"""The orchestration pipeline.

Happy path is TWO LLM calls: one structured plan, one composed sentence.
Everything between them -- entity resolution, date resolution, compilation,
execution, verification, confidence, evidence -- is deterministic Python with no
model involvement. That is what makes the numbers defensible and what keeps
latency and token cost low.

Escalation to a larger model happens only after a *measured* failure of the
small model (an unparseable or invalid plan, or two rejected drafts), never on a
guess about how hard the question looks.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Callable, Iterable

from pydantic import ValidationError

from ..contracts.enums import ConfidenceBand, Intent, Metric, ResponseState
from ..contracts.events import AgentEvent, EventType
from ..contracts.evidence import (
    BreakdownRow, ComputedFact, EvidencePackage, SourceRecordRef,
)
from ..contracts.plan import DateRange, FinanceQueryPlan, PlanDelta
from ..contracts.response import AssistantResponse, Clarification, ClarificationOption
from ..db.clickhouse import ClickHouseClient, QueryError
from ..llm.router import ModelRouter, Tier, UsageLedger, extract_json
from ..services import composer as comp
from ..services import confidence as conf
from ..services import verification as verif
from ..services.compiler import CompilationError, compile_plan
from ..services.dates import DatasetCalendar, DateResolutionError, resolve
from ..services.resolver import MatchKind, VendorRecord, resolve_vendor
from . import prompts

CAPABILITIES = [
    "Spend by vendor, category, account or period",
    "Vendor payouts and their status",
    "Reconciliation status, unreconciled transactions and reconciliation rate",
    "Transaction lookup and filtering",
    "Period-over-period comparisons and trends",
]


@dataclass
class DatasetContext:
    """Everything the pipeline needs to know about the loaded data."""

    calendar: DatasetCalendar
    vendors: list[VendorRecord]
    categories: list[str]
    currency: str
    dataset_version: str = "unknown"


@dataclass
class ConversationState:
    """Multi-turn memory. Deliberately small: the last validated plan is all we
    need for coreference, and it is far more reliable than replaying raw chat."""

    conversation_id: str
    last_plan: FinanceQueryPlan | None = None
    last_period_label: str | None = None
    turns: int = 0


@dataclass
class RunContext:
    run_id: str
    conversation_id: str
    ledger: UsageLedger = field(default_factory=UsageLedger)
    events: list[AgentEvent] = field(default_factory=list)
    _seq: int = 0

    def emit(self, type_: EventType, label: str, **detail: Any) -> AgentEvent:
        self._seq += 1
        ev = AgentEvent(type=type_, run_id=self.run_id, seq=self._seq,
                        label=label, detail=detail)
        self.events.append(ev)
        return ev


class Pipeline:
    def __init__(self, ch: ClickHouseClient, router: ModelRouter, ctx: DatasetContext,
                 on_event: Callable[[AgentEvent], None] | None = None):
        self.ch = ch
        self.router = router
        self.ctx = ctx
        self.on_event = on_event

    # -- public ------------------------------------------------------------

    def run(self, question: str, state: ConversationState) -> AssistantResponse:
        rc = RunContext(run_id=f"run_{uuid.uuid4().hex[:12]}",
                        conversation_id=state.conversation_id)
        self._ev(rc, EventType.RUN_STARTED, "Understanding your question",
                 question=question, turn=state.turns + 1)

        try:
            return self._run_inner(question, state, rc)
        except Exception as e:  # noqa: BLE001 -- last-resort guard
            self._ev(rc, EventType.RUN_FAILED, "Run failed", error=str(e)[:300])
            return self._respond(rc, ResponseState.ERROR,
                                 message="Something went wrong while answering that. "
                                         "Please try again.")

    # -- stages ------------------------------------------------------------

    def _run_inner(self, question: str, state: ConversationState,
                   rc: RunContext) -> AssistantResponse:
        # 1. Plan (LLM call #1)
        parsed, escalated = self._plan(question, state, rc)
        scope = parsed.get("scope", "in_scope")

        if scope == "out_of_scope":
            self._ev(rc, EventType.SCOPE_CHECKED, "Out of scope", reason=parsed.get("reason"))
            return self._respond(
                rc, ResponseState.OUT_OF_SCOPE,
                message=parsed.get("reason")
                or "That is outside what I can answer from this financial dataset.",
                capabilities=CAPABILITIES)

        if scope == "data_unavailable":
            self._ev(rc, EventType.SCOPE_CHECKED, "Data not available",
                     reason=parsed.get("reason"))
            return self._respond(
                rc, ResponseState.DATA_UNAVAILABLE,
                message=parsed.get("reason")
                or "The dataset does not contain the information needed to answer that.",
                capabilities=CAPABILITIES)

        self._ev(rc, EventType.SCOPE_CHECKED, "In scope")

        # 2. Validate the plan against the closed schema.
        try:
            plan = self._materialise_plan(parsed, state)
        except ValidationError as e:
            # Both the small and the escalated model failed to produce a valid
            # plan. That is our failure, not an ambiguous question, so it is an
            # ERROR rather than a clarification.
            self._ev(rc, EventType.RUN_FAILED, "Plan failed validation",
                     errors=e.errors()[:3])
            return self._respond(
                rc, ResponseState.ERROR,
                message="I couldn't turn that into a query I can run safely. "
                        "Rather than guess at what you meant, I'd rather stop here.")
        # A follow-up that yields a plan identical to the previous turn means
        # coreference failed. Answering it would re-report the SAME figure under
        # the new question's framing ("the month before" over last month's
        # number), which is the most misleading thing this system could do.
        if (state.last_plan is not None
                and plan.fingerprint() == state.last_plan.fingerprint()):
            self._ev(rc, EventType.CLARIFICATION_REQUIRED,
                     "Follow-up did not change the query")
            return self._respond(
                rc, ResponseState.CLARIFICATION_REQUIRED,
                clarification=Clarification(
                    question="I couldn't tell what that changes about the previous "
                             "question. Could you state the period or vendor you mean?"))

        plan.user_question = question
        self._ev(rc, EventType.INTENT_DETECTED, f"Intent: {plan.intent.value}",
                 intent=plan.intent.value, metric=plan.metric.value,
                 group_by=plan.group_by.value)

        # 3. Resolve the vendor deterministically. Ambiguity -> clarification.
        entity_match = entity_score = None
        if plan.vendor_name and not plan.vendor_id:
            res = resolve_vendor(plan.vendor_name, self.ctx.vendors)
            entity_match, entity_score = res.kind, res.score
            if res.kind is MatchKind.AMBIGUOUS:
                self._ev(rc, EventType.CLARIFICATION_REQUIRED,
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
                self._ev(rc, EventType.RUN_FAILED, f"No vendor named '{plan.vendor_name}'")
                return self._respond(
                    rc, ResponseState.DATA_UNAVAILABLE,
                    message=f"There is no vendor matching “{plan.vendor_name}” "
                            f"in this dataset.",
                    capabilities=CAPABILITIES)
            plan.vendor_id = res.best.vendor_id
            plan.vendor_name = res.best.vendor_name
            self._ev(rc, EventType.ENTITY_RESOLVED,
                     f"Vendor: {res.best.vendor_name}",
                     query=res.query, vendor_id=res.best.vendor_id,
                     match=res.kind.value, score=res.score)

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
            self._ev(rc, EventType.DATES_RESOLVED,
                     f"Period: {plan.date_range.resolved_label}",
                     start=str(plan.date_range.resolved_start),
                     end=str(plan.date_range.resolved_end),
                     was_relative=was_relative)

        self._ev(rc, EventType.PLAN_VALIDATED, "Query plan validated",
                 fingerprint=plan.fingerprint())

        # 5. Compile + execute. No LLM anywhere near this.
        try:
            cq = compile_plan(plan)
        except CompilationError as e:
            self._ev(rc, EventType.RUN_FAILED, "Could not compile query", error=str(e))
            return self._respond(rc, ResponseState.ERROR,
                                 message="I couldn't turn that into a safe query.")

        self._ev(rc, EventType.TOOL_STARTED, "Querying financial records",
                 kind=cq.kind)
        try:
            result = self.ch.query(cq.sql, cq.params)
        except QueryError as e:
            self._ev(rc, EventType.RUN_FAILED, "Query failed", error=str(e)[:200])
            return self._respond(rc, ResponseState.ERROR,
                                 message="The financial database could not be queried. "
                                         "I won't guess at the figure.")

        aggregate, rows = self._split_result(cq.kind, result.rows)
        self._ev(rc, EventType.QUERY_EXECUTED,
                 f"{result.rows and len(result.rows) or 0} rows returned",
                 duration_ms=result.duration_ms, rows_read=result.rows_read)

        # 6. Verify.
        self._ev(rc, EventType.VERIFICATION_STARTED, "Verifying result")
        vr = verif.verify(plan, rows, aggregate=aggregate,
                          dataset_min=self.ctx.calendar.min_date,
                          dataset_max=self.ctx.calendar.max_date)
        self._ev(rc, EventType.VERIFICATION_COMPLETED,
                 f"Verification: {vr.passed_count}/{vr.total_count} passed",
                 passed=vr.passed,
                 checks=[{"name": c.name, "passed": c.passed, "detail": c.detail}
                         for c in vr.checks])

        record_count = self._record_count(aggregate, rows)

        if not vr.passed:
            failed = [c.name for c in vr.checks if not c.passed and c.severity == "blocking"]
            return self._respond(
                rc, ResponseState.DATA_UNAVAILABLE,
                message="I can't give you a figure I can stand behind for that "
                        f"({', '.join(failed)}). Rather than guess, I'd rather tell you.",
                capabilities=CAPABILITIES)

        if record_count == 0 and plan.metric is Metric.SUM:
            period = plan.date_range.resolved_label if plan.date_range else "the dataset"
            return self._respond(
                rc, ResponseState.DATA_UNAVAILABLE,
                message=f"There are no matching records for {period}, so there is no "
                        f"figure to report.",
                capabilities=CAPABILITIES)

        # 7. Evidence + confidence.
        evidence = self._build_evidence(rc, plan, cq, result, aggregate, rows, vr)
        confidence = conf.compute(
            plan, vr, entity_match=entity_match, entity_score=entity_score or 1.0,
            record_count=record_count, was_relative_date=was_relative,
            truncated=len(rows) >= plan.limit if rows else False)
        evidence.confidence = confidence
        self._ev(rc, EventType.CONFIDENCE_COMPUTED,
                 f"Confidence: {confidence.band.value} ({confidence.score:.0%})",
                 score=confidence.score, signals=confidence.signals)

        # 8. Compose (LLM call #2). Placeholders only.
        answer = self._compose(question, evidence, rc, escalated=escalated)
        self._ev(rc, EventType.ANSWER_GENERATED, "Answer ready")

        state.last_plan = plan
        state.last_period_label = plan.date_range.resolved_label if plan.date_range else None
        state.turns += 1

        self._ev(rc, EventType.RUN_COMPLETED, "Done")
        return AssistantResponse(
            run_id=rc.run_id, conversation_id=rc.conversation_id,
            state=ResponseState.ANSWER, answer=answer, evidence=evidence, plan=plan,
            chart_hint=self._chart_hint(plan, rows),
            follow_up_suggestions=self._suggestions(plan),
            model_usage=rc.ledger.summary())

    # -- LLM stages --------------------------------------------------------

    def _plan(self, question: str, state: ConversationState,
              rc: RunContext) -> tuple[dict[str, Any], bool]:
        """Returns (parsed, escalated). Escalates once on a parse failure."""
        is_followup = state.last_plan is not None
        if is_followup:
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
                categories=", ".join(self.ctx.categories),
                intents=", ".join(i.value for i in Intent),
                relatives=("last_month, this_month, month_before_last, last_quarter, "
                           "this_quarter, last_year, this_year, last_7_days, "
                           "last_30_days, last_90_days, last_6_months, last_12_months, "
                           "all_time"))
        user = prompts.fill(user_t, question=question)

        last_error: Exception | None = None
        for tier, escalated in ((Tier.SMALL, False), (Tier.ESCALATION, True)):
            try:
                raw = self.router.call(tier=tier, purpose="plan", system=system,
                                       user=user, ledger=rc.ledger, json_mode=True,
                                       max_tokens=1200)
                parsed = extract_json(raw)

                # Validate HERE, inside the retry loop. A plan that does not
                # satisfy the schema is a planning failure, and planning
                # failures are exactly what escalation exists for. Validating
                # after the loop (as this once did) turned every malformed plan
                # into a "please rephrase" shown to the user, which hid real
                # model failures behind what looked like a clarification.
                if parsed.get("scope", "in_scope") == "in_scope":
                    self._materialise_plan(parsed, state)

                if escalated:
                    self._ev(rc, EventType.FALLBACK_COMPLETED,
                             "Escalated to a larger model after a planning failure")
                return parsed, escalated

            except Exception as e:  # noqa: BLE001
                last_error = e
                if tier is Tier.SMALL:
                    self._ev(rc, EventType.FALLBACK_STARTED,
                             "Small model produced an unusable plan; escalating",
                             error=str(e)[:160])
                    continue
                raise

        raise last_error or RuntimeError("planning failed with no recorded error")

    def _compose(self, question: str, evidence: EvidencePackage, rc: RunContext,
                 *, escalated: bool) -> str:
        allowed = comp.allowed_keys(evidence)
        system_t, user_t = prompts.load("response_composer_v1")
        descriptions = {
            "shown_total": "the combined value of ONLY the groups listed in the "
                           "table below, which was cut off by a row limit -- "
                           "describe it as the top groups shown, never as a total",
            "total": "the total value",
            "count": "the number of matching records",
            "rate": "the percentage",
            "record_count": "how many records the figure is based on",
            "top_value": "the largest single group's value",
            "group_count": "how many groups are shown",
        }
        facts_desc = "\n".join(
            f"- {{{{{f.key}}}}} = " +
            descriptions.get(f.key, f"the {f.kind} value") +
            (f" (over {f.record_count} records)" if f.record_count else "")
            for f in evidence.facts)
        system = prompts.fill(
            system_t,
            allowed_placeholders=", ".join("{{" + k + "}}" for k in allowed),
            fact_descriptions=facts_desc,
            question=question,
            period_placeholder_note=evidence.resolved_period or "the whole dataset")

        last_error = ""
        for attempt in range(2):
            tier = Tier.ESCALATION if attempt else Tier.SMALL
            try:
                draft = self.router.call(
                    tier=tier, purpose=f"compose{'_retry' if attempt else ''}",
                    system=system + (f"\n\nYour previous attempt was rejected: "
                                     f"{last_error} Fix it." if attempt else ""),
                    user=prompts.fill(user_t), ledger=rc.ledger, max_tokens=800)
                return comp.render(draft, evidence).text
            except comp.ComposeError as e:
                last_error = str(e)
                self._ev(rc, EventType.FALLBACK_STARTED,
                         "Draft rejected by the grounding check", reason=last_error[:160])
            except Exception as e:  # noqa: BLE001 -- provider failure
                last_error = str(e)
                break

        # Both drafts rejected: a plain templated sentence built from verified
        # values beats a fluent one we cannot vouch for.
        self._ev(rc, EventType.FALLBACK_COMPLETED, "Used the deterministic answer template")
        return comp.deterministic_fallback(evidence, question).text

    # -- helpers -----------------------------------------------------------

    def _materialise_plan(self, parsed: dict[str, Any],
                          state: ConversationState) -> FinanceQueryPlan:
        if "delta" in parsed and state.last_plan is not None:
            delta = PlanDelta.model_validate(parsed.get("delta") or {})
            delta.clear = parsed.get("clear", []) or []
            return delta.apply_to(state.last_plan)
        return FinanceQueryPlan.model_validate(parsed.get("plan") or parsed)

    @staticmethod
    def _split_result(kind: str, rows: list[dict]) -> tuple[dict | None, list[dict]]:
        if kind == "aggregate":
            return (rows[0] if rows else {}), []
        return None, rows

    @staticmethod
    def _record_count(aggregate: dict | None, rows: list[dict]) -> int:
        if aggregate and aggregate.get("record_count") is not None:
            return int(aggregate["record_count"])
        if rows and all("record_count" in r for r in rows):
            return sum(int(r["record_count"]) for r in rows)
        return len(rows)

    def _build_evidence(self, rc, plan, cq, result, aggregate, rows, vr) -> EvidencePackage:
        currency = self.ctx.currency
        if aggregate and aggregate.get("currency"):
            currency = aggregate["currency"]

        facts: list[ComputedFact] = []
        record_count = self._record_count(aggregate, rows)

        if aggregate:
            value = float(aggregate.get("value") or 0)
            if plan.intent is Intent.RECONCILIATION_RATE:
                facts.append(ComputedFact(key="rate", value=value, kind="percent",
                                          formatted=comp.format_percent(value),
                                          record_count=record_count))
                for k in ("matched", "unmatched"):
                    if k in aggregate:
                        facts.append(ComputedFact(
                            key=k, value=int(aggregate[k]), kind="count",
                            formatted=comp.format_count(aggregate[k])))
            elif plan.metric is Metric.COUNT:
                facts.append(ComputedFact(key="count", value=int(value), kind="count",
                                          formatted=comp.format_count(value),
                                          record_count=record_count))
            else:
                facts.append(ComputedFact(
                    key="total", value=value, kind="money", currency=currency,
                    formatted=comp.format_money(value, currency),
                    sql_expression=f"{plan.metric.value}(amount)",
                    record_count=record_count))
        elif rows and cq.kind == "grouped":
            total = sum(float(r.get("value") or 0) for r in rows)
            # A grouped result cut off by the row limit is a SUBTOTAL of the
            # groups shown, not the total. Naming it "total" would let the
            # composer write "total spend was X" about a truncated figure --
            # a correct-looking sentence stating a wrong number.
            truncated = len(rows) >= plan.limit
            facts.append(ComputedFact(
                key="shown_total" if truncated else "total",
                value=total, kind="money", currency=currency,
                formatted=comp.format_money(total, currency),
                record_count=record_count))
            top = rows[0]
            facts.append(ComputedFact(
                key="top_value", value=float(top.get("value") or 0), kind="money",
                currency=currency,
                formatted=comp.format_money(float(top.get("value") or 0), currency)))
            facts.append(ComputedFact(
                key="group_count", value=len(rows), kind="count",
                formatted=comp.format_count(len(rows))))
        elif rows:
            facts.append(ComputedFact(key="count", value=len(rows), kind="count",
                                      formatted=comp.format_count(len(rows))))

        facts.append(ComputedFact(key="record_count", value=record_count, kind="count",
                                  formatted=comp.format_count(record_count)))

        breakdown: list[BreakdownRow] = []
        if cq.kind == "grouped" and cq.label_column:
            total = sum(float(r.get("value") or 0) for r in rows) or 1.0
            name_by_id = {v.vendor_id: v.vendor_name for v in self.ctx.vendors}
            for r in rows:
                label = str(r.get(cq.label_column))
                breakdown.append(BreakdownRow(
                    label=name_by_id.get(label, label),
                    value=float(r.get("value") or 0),
                    record_count=int(r.get("record_count") or 0),
                    share_pct=round(100.0 * float(r.get("value") or 0) / total, 2)))

        samples = [
            SourceRecordRef(
                table="transactions", record_id=str(r.get("transaction_id", "")),
                txn_date=date.fromisoformat(r["txn_date"]) if r.get("txn_date") else None,
                vendor_id=r.get("vendor_id"),
                amount=float(r["amount"]) if r.get("amount") else None)
            for r in rows[:25] if "transaction_id" in r
        ]

        return EvidencePackage(
            evidence_id=f"ev_{uuid.uuid4().hex[:12]}", run_id=rc.run_id,
            plan_fingerprint=plan.fingerprint(), facts=facts, breakdown=breakdown,
            breakdown_columns=cq.columns, sample_records=samples,
            total_record_count=record_count,
            resolved_period=plan.date_range.resolved_label if plan.date_range else None,
            resolved_start=plan.date_range.resolved_start if plan.date_range else None,
            resolved_end=plan.date_range.resolved_end if plan.date_range else None,
            currency=currency,
            entities_resolved={k: v for k, v in {
                "vendor_name": plan.vendor_name, "vendor_id": plan.vendor_id,
                "category": plan.category}.items() if v},
            sql=cq.sql, sql_params={k: str(v) for k, v in cq.params.items()},
            query_duration_ms=result.duration_ms, verification=vr,
            dataset_version=self.ctx.dataset_version)

    @staticmethod
    def _chart_hint(plan: FinanceQueryPlan, rows: list[dict]) -> str | None:
        if not rows:
            return None
        if plan.group_by.value in {"day", "week", "month", "quarter", "year"}:
            return "line"
        if plan.group_by.value != "none":
            return "bar"
        return None

    @staticmethod
    def _suggestions(plan: FinanceQueryPlan) -> list[str]:
        out = []
        if plan.date_range:
            out.append("What about the month before?")
        if plan.group_by.value == "none":
            out.append("Break that down by category")
        if plan.vendor_id:
            out.append("Is that unusual for this vendor?")
        else:
            out.append("Which vendors account for most of it?")
        return out[:3]

    def _ev(self, rc: RunContext, type_: EventType, label: str, **detail) -> None:
        ev = rc.emit(type_, label, **detail)
        if self.on_event:
            self.on_event(ev)

    def _respond(self, rc: RunContext, state: ResponseState, *,
                 message: str | None = None,
                 clarification: Clarification | None = None,
                 capabilities: Iterable[str] = ()) -> AssistantResponse:
        self._ev(rc, EventType.RUN_COMPLETED, f"Finished: {state.value}")
        return AssistantResponse(
            run_id=rc.run_id, conversation_id=rc.conversation_id, state=state,
            message=message, clarification=clarification,
            supported_capabilities=list(capabilities),
            model_usage=rc.ledger.summary())
