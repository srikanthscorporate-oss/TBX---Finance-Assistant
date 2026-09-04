#!/usr/bin/env python3
"""End-to-end pipeline run against real ClickHouse with a stubbed LLM."""
from __future__ import annotations

import csv
import os
import sys
import uuid
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.agents.pipeline import ConversationState, DatasetContext, Pipeline  # noqa: E402
from app.db.clickhouse import ClickHouseClient  # noqa: E402
from app.llm.router import ModelRouter  # noqa: E402
from app.services.dates import DatasetCalendar  # noqa: E402
from app.services.resolver import VendorRecord  # noqa: E402
from stub_llm import stub_completion  # noqa: E402

RAW = Path(__file__).resolve().parents[3] / "data" / "raw"


def build() -> Pipeline:
    ch = ClickHouseClient(
        host=os.getenv("CH_HOST", "localhost"), port=int(os.getenv("CH_PORT", "18123")),
        user=os.getenv("CH_ADMIN_USER", "tbx_admin"),
        password=os.getenv("CH_ADMIN_PASSWORD", "change-me-admin"))
    vrows = list(csv.DictReader((RAW / "vendors.csv").open()))
    trows = list(csv.DictReader((RAW / "transactions.csv").open()))
    ctx = DatasetContext(
        calendar=DatasetCalendar(
            min_date=min(date.fromisoformat(r["txn_date"]) for r in trows),
            max_date=max(date.fromisoformat(r["txn_date"]) for r in trows)),
        vendors=[VendorRecord(r["vendor_id"], r["vendor_name"], r["legal_name"],
                              r["category"], r["status"]) for r in vrows],
        categories=sorted({r["category"] for r in trows}),
        currency="INR", dataset_version="synthetic-v1")
    return Pipeline(ch, ModelRouter(completion_fn=stub_completion), ctx)


def show(pipe, question, state, indent="") -> None:
    r = pipe.run(question, state)
    print(f"{indent}Q: {question}")
    print(f"{indent}   state={r.state.value}")
    if r.answer:
        print(f"{indent}   A: {r.answer}")
        ev = r.evidence
        print(f"{indent}      period={ev.resolved_period}  records={ev.total_record_count}  "
              f"verify={ev.verification.passed_count}/{ev.verification.total_count}  "
              f"confidence={ev.confidence.band.value} ({ev.confidence.score:.2f})  "
              f"query={ev.query_duration_ms}ms")
        if ev.breakdown:
            for row in ev.breakdown[:3]:
                print(f"{indent}      - {row.label:26} {row.value:>14,.2f}  ({row.share_pct}%)")
    if r.clarification:
        opts = ", ".join(o.label for o in r.clarification.options)
        print(f"{indent}   ?: {r.clarification.question}")
        if opts:
            print(f"{indent}      options: {opts}")
    if r.message:
        print(f"{indent}   !: {r.message}")
    tok = sum(c["prompt_tokens"] + c["completion_tokens"] for c in r.model_usage)
    print(f"{indent}   llm_calls={len(r.model_usage)} tokens~{tok}\n")


def main() -> int:
    pipe = build()
    print(f"dataset: {pipe.ctx.calendar.min_date} .. {pipe.ctx.calendar.max_date}\n")
    print("=" * 78)
    print("SINGLE-TURN")
    print("=" * 78)
    for q in [
        "How much did we spend last month?",
        "How much did we spend with Acme Technologies last month?",
        "How much did we spend with Acme last month?",
        "Which transactions are still unreconciled?",
        "What is our reconciliation rate for the last 6 months?",
        "Show me the top vendors last quarter",
        "How much did we spend on Marketing last quarter?",
        "How much GST did we pay last month?",
        "What is Apple's stock price?",
        "How much did we spend with Tesla last month?",
    ]:
        show(pipe, q, ConversationState(conversation_id=uuid.uuid4().hex))

    print("=" * 78)
    print("MULTI-TURN (context carried via the previous validated plan)")
    print("=" * 78)
    state = ConversationState(conversation_id=uuid.uuid4().hex)
    show(pipe, "How much did we spend with Acme Technologies last month?", state)
    show(pipe, "What about the month before?", state)
    show(pipe, "Break that down by category", state)
    return 0


if __name__ == "__main__":
    sys.exit(main())
