"""Run-scoped types shared by the planner, composer, evidence builder and pipeline."""
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

GUIDED_QUESTIONS = [
    "How much did we spend last month?",
    "Which transactions are still unreconciled?",
    "Show me the top vendors last month",
    "What is our reconciliation rate for the last 6 months?",
]
"""Offered with every refusal; each must be answerable by the pipeline."""

OUT_OF_SCOPE_MESSAGE = (
    "Your input isn't relevant to the services we provide. I answer questions "
    "about your spend, vendor payouts and reconciliation, from your financial "
    "records only. Try one of these instead."
)


@dataclass
class DatasetContext:
    """Loaded-data facts read from the database at startup.

    Relative periods anchor to the dataset's calendar, not today's date.
    """

    calendar: DatasetCalendar
    vendors: list[VendorRecord]
    categories: list[str]
    currency: str
    dataset_version: str = "unknown"


@dataclass
class ConversationState:
    """Multi-turn memory: the last validated plan is enough for coreference.

    `pending_plan` is a plan parked on a clarification; answering the clarification
    completes it rather than re-planning the original question.
    """

    conversation_id: str
    last_plan: FinanceQueryPlan | None = None
    last_period_label: str | None = None
    turns: int = 0
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
