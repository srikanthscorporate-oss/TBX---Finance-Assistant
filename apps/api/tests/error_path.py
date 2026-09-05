#!/usr/bin/env python3
"""Runs the pipeline against a dead port and checks the turn ends in the error state with
no answer, no evidence and no figure in the message. Prints ERROR_PATH_PASS."""
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

questions = [
    "How much did I spend with Zomato last month?",
    "What is my account balance?",
    "List transactions under 500 rupees this month",
]
for q in questions:
    r = pipe.run(q, ConversationState(conversation_id=uuid.uuid4().hex))
    print(f"Q: {q}\n   state={r.state.value}\n   message={r.message}")
    if r.state is not ResponseState.ERROR:
        failures.append(f"{q!r}: expected ERROR when the database is down, got {r.state.value}")
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

if failures:
    for f in failures:
        print(f"  FAIL: {f}")
    sys.exit(1)
print("ERROR_PATH_PASS")
