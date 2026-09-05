#!/usr/bin/env python3
"""Judge behaviour with the stub planner: relevance gate, caches, breakers, verdicts.
Needs Redis and ClickHouse. Prints JUDGE_OFFLINE_PASS."""
from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from bank_fixture import (  # noqa: E402
    build_context,
    ch_client,
    data_key,
    load_accounts,
    load_banks,
    load_transactions,
)

os.environ.setdefault("TBX_DATA_KEY", data_key())

from stub_llm import stub_completion  # noqa: E402

import app.llm.router as R  # noqa: E402
from app.agents.judge import QUALITY_SAMPLE, Judge  # noqa: E402
from app.agents.pipeline import ConversationState, Pipeline  # noqa: E402
from app.contracts.enums import ResponseState  # noqa: E402
from app.llm.router import ModelRouter, Tier, UsageLedger  # noqa: E402
from app.services.cache import Cache  # noqa: E402

cache = Cache(os.getenv("REDIS_URL", "redis://127.0.0.1:16379/0"),
              prefix=f"tbxtest{uuid.uuid4().hex[:6]}")
assert cache.enabled, "Redis must be reachable for this test"
accounts = load_accounts()
ctx = build_context(accounts, load_banks(), load_transactions(accounts),
                    dataset_version=f"judgetest-{uuid.uuid4().hex[:6]}")
judge = Judge(cache, ctx.dataset_version)
calls: list[str] = []
events: list = []


def counting(**kw):
    calls.append(kw["model"])
    return stub_completion(**kw)


router = ModelRouter(completion_fn=counting, judge=judge)
pipe = Pipeline(ch_client(), router, ctx, judge=judge, on_event=events.append)
out: list[str] = []


def fresh() -> ConversationState:
    return ConversationState(conversation_id=uuid.uuid4().hex)


n0 = len(calls)
r = pipe.run("tell me a joke about cats", fresh())
assert r.state is ResponseState.OUT_OF_SCOPE and len(calls) == n0, (r.state, len(calls) - n0)
assert any(e.type.value == "task_created" and "no agents" in e.label for e in events), \
    [e.label for e in events]
out.append("  relevance gate: irrelevant input refused with 0 model calls")

events.clear()
n0 = len(calls)
r = pipe.run("How much did I spend with Zomato last month?", fresh())
assert r.state is ResponseState.ANSWER, r.message
used = len(calls) - n0
assert used == 1, f"single-figure answer used {used} calls, expected 1 (plan only; composer templated)"
assert "ZOMATO" in r.answer and "₹" in r.answer, r.answer
assert r.plan.intent.value == "counterparty_spend" and r.plan.transaction_type.value == "debit"
out.append(f"  template composer: single figure answered in {used} model call -> {r.answer[:60]}")

anomaly_events = [e for e in events if e.label.startswith("Anomaly check")]
assert anomaly_events, [e.label for e in events]
assert any(e.type.value == "task_created" and "anomaly agent" in e.label for e in events)
flagged = anomaly_events[0].detail.get("flagged")
if flagged:
    assert "Unusual for ZOMATO" in r.answer, r.answer
    assert "anomaly_ratio" in r.evidence.fact_keys(), r.evidence.fact_keys()
    assert any(c.name == "anomaly_callout" for c in r.evidence.verification.checks)
else:
    assert "Unusual" not in r.answer, r.answer
out.append(f"  anomaly agent: spawned for a counterparty with a period "
           f"({'flagged, figures grounded as facts' if flagged else 'within normal range'})")

n0 = len(calls)
r2 = pipe.run("How much did I spend with Zomato last month?", fresh())
assert r2.state is ResponseState.ANSWER and len(calls) == n0, (r2.state, len(calls) - n0)
assert r2.answer == r.answer
assert r2.evidence.fact_map()["total"].value == r.evidence.fact_map()["total"].value
out.append("  cache: identical question answered with 0 model calls, identical text")

n0 = len(calls)
r3 = pipe.run("Show me the top counterparties last quarter", fresh())
assert r3.state is ResponseState.ANSWER and len(calls) - n0 == 2, (r3.state, r3.message, len(calls) - n0)
assert r3.plan.intent.value == "top_counterparties" and r3.evidence.breakdown
out.append("  grouped answer: plan + compose = 2 calls")

n0 = len(calls)
r4 = pipe.run("What is my account balance?", fresh())
assert r4.state is ResponseState.ANSWER and len(calls) - n0 == 1, (r4.state, r4.message, len(calls) - n0)
assert "balance_total" in r4.evidence.fact_keys()
out.append("  balance: templated from the account table in 1 call")


class RL(Exception):
    pass


seq: list[str] = []


def flaky(**kw):
    seq.append(kw["model"])
    if kw["model"] == "stub/primary" and len([m for m in seq if m == "stub/primary"]) == 1:
        raise RL("RateLimitError 429 Please try again in 5m0s.")
    return stub_completion(**kw)


R.RATE_LIMIT_RETRIES = 0
r2router = ModelRouter(completion_fn=flaky, judge=judge)
led = UsageLedger()
r2router.call(tier=Tier.PRIMARY, purpose="plan", system="x",
              user="How much did I spend last month?", ledger=led)
assert judge.is_open("stub/primary") and judge.breaker_ttl("stub/primary") > 200, \
    judge.breaker_ttl("stub/primary")
seq.clear()
led2 = UsageLedger()
r2router.call(tier=Tier.PRIMARY, purpose="plan", system="x",
              user="How much did I spend last month?", ledger=led2)
assert seq == ["stub/alternate"], seq
out.append(f"  breaker: 429 opened the primary for {judge.breaker_ttl('stub/primary')}s; "
           "next call went straight to the alternate")

for _ in range(QUALITY_SAMPLE):
    judge.record_plan_outcome("stub/weak", False)
assert judge.is_open("stub/weak"), "weak model should be quality-open"
assert judge.prefer("stub/weak", "stub/healthy") == "stub/healthy"
out.append(f"  quality breaker: 0/{QUALITY_SAMPLE} valid plans -> model skipped, Auto prefers the other")

judge.remember_plan("Which transactions are unreconciled?", 0,
                    {"scope": "data_unavailable", "reason": "x"})
assert judge.cached_plan("Which transactions are unreconciled?", 0) is None
judge.remember_plan("What is the weather?", 0, {"scope": "out_of_scope", "reason": "x"})
assert judge.cached_plan("What is the weather?", 0) is None
out.append("  refusals are not cached; only executable in-scope plans are")

summ = judge.summary(["stub/primary", "stub/alternate"])
assert summ["runs_scored"] >= 5 and summ["cache"]["answer"] >= 1, summ
out.append(f"  verdicts: {summ['runs_scored']} scored, avg {summ['avg_score']}, "
           f"cache hit rate {summ['cache']['hit_rate']}")
print("\n".join(out))
print("JUDGE_OFFLINE_PASS")
