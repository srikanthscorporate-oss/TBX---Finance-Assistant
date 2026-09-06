"""Run-scoped types shared by the planner, composer, evidence builder and pipeline."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from ..contracts.events import AgentEvent, EventType
from ..contracts.plan import FinanceQueryPlan
from ..llm.router import UsageLedger
from ..services.dates import DatasetCalendar
from ..services.resolver import AccountRecord, CounterpartyRecord

CAPABILITIES = [
    "Spend and receipts by period, counterparty, account, bank or channel",
    "Transaction lists filtered by amount, date, type or counterparty",
    "Lookup by reference number or UTR",
    "Account balances",
    "Period-over-period comparisons, trends and largest transactions",
]

GUIDED_QUESTIONS = [
    "How much did I spend last month?",
    "List transactions under 500 rupees this month",
    "Who did I pay the most in the last 90 days?",
    "What is my account balance?",
]
"""Offered with every refusal; each must be answerable by the pipeline."""

OUT_OF_SCOPE_MESSAGE = (
    "Your input isn't relevant to the services we provide. I answer questions "
    "about your bank transactions, counterparties, balances and references, from "
    "your records only. Try one of these instead."
)


@dataclass
class DatasetContext:
    """Loaded-data facts read from the database at startup.

    Relative periods anchor to the dataset's calendar, not today's date.
    """

    calendar: DatasetCalendar
    counterparties: list[CounterpartyRecord]
    accounts: list[AccountRecord]
    banks: dict[str, str]
    entities: list[str]
    currency: str = "INR"
    dataset_version: str = "unknown"
    default_entity: str | None = None

    def counterparties_for(self, entity_id: str | None) -> list[CounterpartyRecord]:
        if not entity_id:
            return self.counterparties
        scoped = [c for c in self.counterparties if entity_id in c.entities]
        return scoped or self.counterparties

    def accounts_for(self, entity_id: str | None) -> list[AccountRecord]:
        if not entity_id:
            return self.accounts
        return [a for a in self.accounts if a.entity_id == entity_id]


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
    pending_field: str | None = None
    entity_id: str | None = None


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
