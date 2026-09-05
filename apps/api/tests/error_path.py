#!/usr/bin/env python3
"""Runs the pipeline against a dead port and checks the turn ends in the error state with
no answer, no evidence and no figure in the message.

The questions are fully specified -- entity chosen, period stated, side stated, a
counterparty that exists -- so the run reaches the query and fails there rather than
stopping at a clarification. A deliberately under-specified question is kept at the end
to prove a clarification is not mistaken for an error. Prints ERROR_PATH_PASS."""
from __future__ import annotations

import re
import sys
import uuid
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from stub_llm import stub_completion  # noqa: E402

from app.agents.pipeline import ConversationState, DatasetContext, Pipeline  # noqa: E402
from app.contracts.enums import ResponseState  # noqa: E402
from app.db.clickhouse import ClickHouseClient  # noqa: E402
from app.llm.router import ModelRouter  # noqa: E402
from app.services import entity_token  # noqa: E402
from app.services.dates import DatasetCalendar  # noqa: E402
from app.services.resolver import AccountRecord, CounterpartyRecord  # noqa: E402

failures: list[str] = []

ch = ClickHouseClient(host="127.0.0.1", port=9, user="x", password="y", timeout=2)
ctx = DatasetContext(
    calendar=DatasetCalendar(min_date=date(2025, 1, 1), max_date=date(2026, 8, 30)),
    counterparties=[CounterpartyRecord("ZOMATO", 10, "UPI", frozenset({"ent-1"}))],
    accounts=[AccountRecord("acct-1", "ent-1", "1234", "HDFC", "HDFC BANK LIMITED", 1, 100.0)],
    banks={"HDFC": "HDFC BANK LIMITED"}, entities=["ent-1"], currency="INR",
    dataset_version="errortest", default_entity="ent-1")
pipe = Pipeline(ch, ModelRouter(completion_fn=stub_completion), ctx)

ENTITY_TOKEN = entity_token.encode("ent-1")

questions = [
    "How much did I spend with ZOMATO last month?",   # counterparty + period + debit side
    "What is my account balance?",                     # balance needs neither period nor side
    "List debits under 500 rupees this month",         # list + period + explicit side
]
for q in questions:
    r = pipe.run(q, ConversationState(conversation_id=uuid.uuid4().hex), entity_id=ENTITY_TOKEN)
    print(f"Q: {q}\n   state={r.state.value}\n   message={r.message}")
    if r.state is not ResponseState.ERROR:
        failures.append(f"{q!r}: expected ERROR when the database is down, got {r.state.value}"
                        + (f" [{r.clarification.field}]" if r.clarification else ""))
    if r.answer is not None:
        failures.append(f"{q!r}: ERROR response carried an answer: {r.answer!r}")
    if r.evidence is not None:
        failures.append(f"{q!r}: ERROR response carried an evidence package")
    if r.plan is not None and r.evidence is not None:
        failures.append(f"{q!r}: ERROR response carried a plan with evidence")
    if not r.message:
        failures.append(f"{q!r}: ERROR response had no explanatory message")
    if r.message and re.search(r"\d{3,}|[₹$€£]\s*\d", r.message):
        failures.append(f"{q!r}: ERROR message contains a figure: {r.message!r}")

# A missing entity is a clarification, not an error: the DB being down must not turn an
# unanswered question into a failure state.
r = pipe.run("How much did I spend with ZOMATO last month?",
             ConversationState(conversation_id=uuid.uuid4().hex))
print(f"Q: (no entity chosen)\n   state={r.state.value}\n   field="
      f"{r.clarification.field if r.clarification else None}")
if r.state is not ResponseState.CLARIFICATION_REQUIRED:
    failures.append(f"no entity: expected clarification_required, got {r.state.value}")
if not (r.clarification and r.clarification.field == "entity"):
    failures.append("no entity: clarification did not ask for the entity")
if r.answer is not None or r.evidence is not None:
    failures.append("no entity: clarification carried an answer or evidence")

# Likewise an unstated period: still a clarification with the database unreachable.
r = pipe.run("How much did I spend with ZOMATO?",
             ConversationState(conversation_id=uuid.uuid4().hex), entity_id=ENTITY_TOKEN)
print(f"Q: (no period)\n   state={r.state.value}\n   field="
      f"{r.clarification.field if r.clarification else None}")
if r.state is not ResponseState.CLARIFICATION_REQUIRED:
    failures.append(f"no period: expected clarification_required, got {r.state.value}")
if not (r.clarification and r.clarification.field == "date_range"):
    failures.append("no period: clarification did not ask for the period")
if r.answer is not None or r.evidence is not None:
    failures.append("no period: clarification carried an answer or evidence")

if failures:
    for f in failures:
        print(f"  FAIL: {f}")
    sys.exit(1)
print("ERROR_PATH_PASS")
