#!/usr/bin/env python3
"""End-to-end pipeline run against real ClickHouse with the stubbed LLM.

Every scenario asserts the exact terminal state the demo relies on, and no response may
carry a full account number. Prints E2E_OFFLINE_PASS.
"""
from __future__ import annotations

import os
import re
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from bank_fixture import (  # noqa: E402
    build_context,
    ch_client,
    data_key,
    default_entity,
    load_accounts,
    load_banks,
    load_transactions,
)

os.environ.setdefault("TBX_DATA_KEY", data_key())

from stub_llm import stub_completion  # noqa: E402

from app.agents.pipeline import ConversationState, Pipeline  # noqa: E402
from app.contracts.enums import ResponseState  # noqa: E402
from app.contracts.response import AssistantResponse  # noqa: E402
from app.llm.router import ModelRouter  # noqa: E402

ACCOUNTS = load_accounts()
BANKS = load_banks()
TXNS = load_transactions(ACCOUNTS)
ENTITY = default_entity(TXNS)
ACCOUNT_NUMBERS = {a["account_number"] for a in ACCOUNTS.values()}

failures: list[str] = []
responses: list[AssistantResponse] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" -- {detail}" if detail and not ok else ""))
    if not ok:
        failures.append(f"{name}: {detail}")


def build() -> Pipeline:
    ctx = build_context(ACCOUNTS, BANKS, TXNS, dataset_version=f"e2e-{uuid.uuid4().hex[:8]}")
    return Pipeline(ch_client(), ModelRouter(completion_fn=stub_completion), ctx)


def ask(pipe: Pipeline, question: str, state: ConversationState) -> AssistantResponse:
    r = pipe.run(question, state)
    responses.append(r)
    print(f"Q: {question}\n   state={r.state.value}"
          + (f"\n   A: {r.answer}" if r.answer else "")
          + (f"\n   ?: {r.clarification.question} [{r.clarification.field}]"
             if r.clarification else "")
          + (f"\n   !: {r.message}" if r.message else ""))
    return r


def resolve(pipe: Pipeline, value: str, state: ConversationState) -> AssistantResponse:
    r = pipe.run_resolved(value, state)
    responses.append(r)
    print(f"-> chose {value!r}\n   state={r.state.value}"
          + (f"\n   A: {r.answer}" if r.answer else "")
          + (f"\n   !: {r.message}" if r.message else ""))
    return r


def fresh() -> ConversationState:
    return ConversationState(conversation_id=uuid.uuid4().hex)


def main() -> int:
    pipe = build()
    print(f"dataset: {pipe.ctx.calendar.min_date} .. {pipe.ctx.calendar.max_date}, "
          f"entity {ENTITY[:8]}…\n")

    st = fresh()
    r = ask(pipe, "list transactions less than 500 rupees", st)
    check("amount list without period asks for one", r.state is ResponseState.CLARIFICATION_REQUIRED)
    check("clarification field is date_range",
          r.clarification is not None and r.clarification.field == "date_range")
    check("six period options", r.clarification is not None and len(r.clarification.options) == 6,
          str(r.clarification and [o.value for o in r.clarification.options]))
    check("clarification carries no evidence", r.evidence is None and r.answer is None)
    r = resolve(pipe, "last_month", st)
    check("chosen period answers", r.state is ResponseState.ANSWER, r.message or "")
    if r.state is ResponseState.ANSWER:
        ev = r.evidence
        check("detail answer has records", bool(ev.records) and bool(ev.record_columns))
        check("every record is under 500", all(rec["amount"] <= 500 for rec in ev.records))
        keys = {f.key for f in ev.facts}
        check("facts include count and record_count", {"count", "record_count"} <= keys, str(keys))
        check("records are masked accounts", all(re.fullmatch(r"X{6}\d{4}", rec["account"])
                                                 for rec in ev.records))
        check("period resolved to last month", ev.resolved_period is not None
              and ev.resolved_start is not None)

    st = fresh()
    r = ask(pipe, "how many transactions have I made with Swiggy", st)
    check("Swiggy is ambiguous", r.state is ResponseState.CLARIFICATION_REQUIRED)
    check("clarification field is counterparty",
          r.clarification is not None and r.clarification.field == "counterparty")
    opts = [o.value for o in r.clarification.options] if r.clarification else []
    check("two options SWIGGY / SWIGGY INSTAMART", sorted(opts) == ["SWIGGY", "SWIGGY INSTAMART"], str(opts))
    check("options carry hints", bool(r.clarification) and all(o.hint for o in r.clarification.options))
    r = resolve(pipe, "SWIGGY", st)
    check("chosen counterparty answers", r.state is ResponseState.ANSWER, r.message or "")
    if r.state is ResponseState.ANSWER:
        expected = sum(1 for t in TXNS if t.entity_id == ENTITY and t.counterparty == "SWIGGY")
        fact = r.evidence.fact_map().get("count")
        check("SWIGGY count matches the CSV", fact is not None and int(fact.value) == expected,
              f"csv {expected} vs {fact and fact.value}")
        check("entities_resolved names the exact counterparty",
              r.evidence.entities_resolved.get("counterparty") == "SWIGGY")

    target = next(t for t in TXNS if t.entity_id == ENTITY and t.utr)
    st = fresh()
    r = ask(pipe, f"UTR {target.utr}", st)
    check("UTR lookup answers", r.state is ResponseState.ANSWER, r.message or "")
    if r.state is ResponseState.ANSWER:
        recs = r.evidence.records
        check("exactly one record", len(recs) == 1 and r.evidence.total_record_count == 1)
        if recs:
            check("record utr equals the plaintext", recs[0]["utr"] == target.utr,
                  f"{recs[0]['utr']!r} vs {target.utr!r}")
            check("record account is masked to the last four",
                  recs[0]["account"] == "XXXXXX" + ACCOUNTS[target.account_id]["account_number"][-4:],
                  recs[0]["account"])
            check("record is the right transaction", recs[0]["transaction_id"] == target.transaction_id)
        check("utr_hash is shown truncated in sql_params",
              str(r.evidence.sql_params.get("utr_hash", "")).endswith("…"))

    st = fresh()
    r = ask(pipe, "UTR ZZZZ0000NOTAREALUTR9999", st)
    check("unknown UTR is data_unavailable", r.state is ResponseState.DATA_UNAVAILABLE, r.message or "")
    check("unknown UTR carries no evidence", r.evidence is None and r.answer is None)

    st = fresh()
    r = ask(pipe, "How much did I spend with Zomato last month?", st)
    check("counterparty spend answers", r.state is ResponseState.ANSWER, r.message or "")
    first_period = r.evidence.resolved_period if r.evidence else None
    r = ask(pipe, "what about the month before?", st)
    check("follow-up answers", r.state is ResponseState.ANSWER, r.message or "")
    if r.state is ResponseState.ANSWER:
        check("follow-up changed the period", r.evidence.resolved_period != first_period,
              f"{first_period} -> {r.evidence.resolved_period}")
        check("follow-up kept the counterparty", r.plan.counterparty == "ZOMATO")
        check("follow-up resolved month_before_last",
              r.plan.date_range is not None and r.plan.date_range.relative == "month_before_last")
    r = ask(pipe, "show me those transactions", st)
    check("'show me those' answers with detail", r.state is ResponseState.ANSWER, r.message or "")
    if r.state is ResponseState.ANSWER:
        check("detail records for ZOMATO", bool(r.evidence.records)
              and all(rec["counterparty"] == "ZOMATO" for rec in r.evidence.records))
        check("detail intent", r.plan.intent.value == "transaction_lookup")

    st = fresh()
    r = ask(pipe, "What is my account balance?", st)
    check("balance answers", r.state is ResponseState.ANSWER, r.message or "")
    if r.state is ResponseState.ANSWER:
        accts = [a for a in ACCOUNTS.values() if a["entity_id"] == ENTITY]
        expected = sum(float(a["available_balance"]) for a in accts)
        fact = r.evidence.fact_map().get("balance_total")
        check("balance_total matches account.csv",
              fact is not None and abs(float(fact.value) - expected) < 0.05,
              f"csv {expected:,.2f} vs {fact and fact.value}")
        check("balance records are masked", all(re.fullmatch(r"X{6}\d{4}", rec["account"])
                                                for rec in r.evidence.records))
        check("record columns are the balance set", "available_balance_formatted" in r.evidence.record_columns)

    st = fresh()
    r = ask(pipe, "What's the weather like today?", st)
    check("weather is out_of_scope", r.state is ResponseState.OUT_OF_SCOPE, r.state.value)
    check("out_of_scope carries no figure", r.evidence is None and r.answer is None)

    st = fresh()
    r = ask(pipe, "Which transactions are still unreconciled?", st)
    check("unreconciled is data_unavailable", r.state is ResponseState.DATA_UNAVAILABLE, r.state.value)
    check("data_unavailable carries no figure", r.evidence is None and r.answer is None)

    st = fresh()
    r = ask(pipe, "How much did I spend with Tesla last month?", st)
    check("unknown counterparty is data_unavailable", r.state is ResponseState.DATA_UNAVAILABLE, r.state.value)
    check("unknown counterparty offers options",
          r.clarification is not None and r.clarification.field == "counterparty"
          and len(r.clarification.options) > 0)
    check("unknown counterparty carries no evidence", r.evidence is None and r.answer is None)

    leaked = 0
    for resp in responses:
        blob = resp.model_dump_json()
        for run_ in re.findall(r"\d{10,}", blob):
            if any(n in run_ for n in ACCOUNT_NUMBERS):
                leaked += 1
    check(f"no full account number in any of {len(responses)} responses", leaked == 0, f"{leaked} leaks")
    check("every turn ended in a defined state", all(r.state in ResponseState for r in responses))

    print()
    if failures:
        print(f"FAILURES ({len(failures)}):")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("E2E_OFFLINE_PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
