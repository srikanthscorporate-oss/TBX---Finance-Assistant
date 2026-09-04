#!/usr/bin/env python3
"""The ERROR state: when the database cannot be queried we must refuse, not guess."""
from __future__ import annotations

import sys
import uuid
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.agents.pipeline import ConversationState, DatasetContext, Pipeline  # noqa: E402
from app.contracts.enums import ResponseState  # noqa: E402
from app.db.clickhouse import ClickHouseClient  # noqa: E402
from app.llm.router import ModelRouter  # noqa: E402
from app.services.dates import DatasetCalendar  # noqa: E402
from app.services.resolver import VendorRecord  # noqa: E402
from stub_llm import stub_completion  # noqa: E402

failures = []

# Point at a port with nothing on it, so every query fails at transport level.
ch = ClickHouseClient(host="127.0.0.1", port=9, user="x", password="y", timeout=2)
ctx = DatasetContext(
    calendar=DatasetCalendar(min_date=date(2025, 1, 1), max_date=date(2026, 8, 28)),
    vendors=[VendorRecord("V1001", "Acme Technologies")],
    categories=["Cloud Infrastructure"], currency="INR", dataset_version="test")
pipe = Pipeline(ch, ModelRouter(completion_fn=stub_completion), ctx)

r = pipe.run("How much did we spend with Acme Technologies last month?",
             ConversationState(conversation_id=uuid.uuid4().hex))

if r.state is not ResponseState.ERROR:
    failures.append(f"expected ERROR when the database is down, got {r.state.value}")
if r.answer is not None:
    failures.append(f"ERROR response carried an answer: {r.answer!r}")
if r.evidence is not None:
    failures.append("ERROR response carried an evidence package")
if not r.message:
    failures.append("ERROR response had no explanatory message")
# Crucially: no figure may appear in the failure message.
import re  # noqa: E402
if r.message and re.search(r"\d{3,}|[₹$€£]\s*\d", r.message):
    failures.append(f"ERROR message contains a figure: {r.message!r}")

# A verification failure must also refuse rather than answer.
print(f"error-path state: {r.state.value}")
print(f"error-path message: {r.message}")

if failures:
    for f in failures:
        print(f"  FAIL: {f}")
    sys.exit(1)
print("ERROR_PATH_PASS")
