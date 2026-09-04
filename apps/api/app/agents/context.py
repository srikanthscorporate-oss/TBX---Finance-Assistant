"""Shared run-scoped types.

Extracted so planner, composer, evidence builder and the orchestrator can all
depend on these without importing each other.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from ..contracts.events import AgentEvent, EventType
from ..contracts.plan import FinanceQueryPlan
from ..llm.router import UsageLedger
from ..services.dates import DatasetCalendar
from ..services.resolver import VendorRecord

CAPABILITIES = [
    "Spend by vendor, category, account or period",
    "Vendor payouts and their status",
    "Reconciliation status, unreconciled transactions and reconciliation rate",
    "Transaction lookup and filtering",
    "Period-over-period comparisons and trends",
]

# What a refusal offers instead. Each is a real, answerable question, so the
# conversation always has a next step that leads to the right-hand pane doing
# something.
GUIDED_QUESTIONS = [
    "How much did we spend last month?",
    "Which transactions are still unreconciled?",
    "Show me the top vendors last month",
    "What is our reconciliation rate for the last 6 months?",
]

OUT_OF_SCOPE_MESSAGE = (
    "Your input isn't relevant to the services we provide. I answer questions "
    "about your spend, vendor payouts and reconciliation, from your financial "
    "records only. Try one of these instead."
)


@dataclass
class DatasetContext:
    """Everything the pipeline needs to know about the loaded data.

    Read from the database at startup, never hardcoded, which is what keeps
    relative periods anchored to the data rather than to today.
    """

    calendar: DatasetCalendar
    vendors: list[VendorRecord]
    categories: list[str]
    currency: str
    dataset_version: str = "unknown"


@dataclass
class ConversationState:
    """Multi-turn memory.

    Deliberately small: the last validated plan is all that is needed for
    coreference, and it is far more reliable than replaying raw chat history.
    """

    conversation_id: str
    last_plan: FinanceQueryPlan | None = None
    last_period_label: str | None = None
    turns: int = 0
    # A plan parked on a clarification. Answering the clarification completes
    # THIS plan rather than re-planning the original sentence, so the user's
    # wording is never re-interpreted a second time.
    pending_plan: FinanceQueryPlan | None = None
    pending_question: str | None = None


@dataclass
class RunContext:
    """One question's execution: its id, its event log and its model spend."""

    run_id: str
    conversation_id: str
    ledger: UsageLedger = field(default_factory=UsageLedger)
    events: list[AgentEvent] = field(default_factory=list)
    on_event: Callable[[AgentEvent], None] | None = None
    _seq: int = 0

    def emit(self, type_: EventType, label: str, **detail: Any) -> AgentEvent:
        self._seq += 1
        ev = AgentEvent(type=type_, run_id=self.run_id, seq=self._seq,
                        label=label, detail=detail)
        self.events.append(ev)
        if self.on_event:
            self.on_event(ev)
        return ev
