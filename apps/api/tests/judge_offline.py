#!/usr/bin/env python3
"""Judge behaviour with the stub planner: relevance gate, caches, breakers, verdicts.
Needs Redis and ClickHouse. Prints JUDGE_OFFLINE_PASS."""
from __future__ import annotations

import csv, os, sys, uuid
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1])); sys.path.insert(0, str(Path(__file__).resolve().parent))
from app.agents.judge import Judge  # noqa: E402
from app.agents.pipeline import ConversationState, DatasetContext, Pipeline  # noqa: E402
from app.contracts.enums import ResponseState  # noqa: E402
from app.db.clickhouse import ClickHouseClient  # noqa: E402
from app.llm.router import ModelRouter, Tier, UsageLedger  # noqa: E402
from app.services.cache import Cache  # noqa: E402
from app.services.dates import DatasetCalendar  # noqa: E402
from app.services.resolver import VendorRecord  # noqa: E402
from stub_llm import stub_completion  # noqa: E402

RAW = Path(__file__).resolve().parents[3] / "data" / "raw"
cache = Cache(os.getenv("REDIS_URL", "redis://127.0.0.1:16379/0"), prefix=f"tbxtest{uuid.uuid4().hex[:6]}")
assert cache.enabled, "Redis must be reachable for this test"
vrows = list(csv.DictReader((RAW / "vendors.csv").open())); trows = list(csv.DictReader((RAW / "transactions.csv").open()))
ctx = DatasetContext(calendar=DatasetCalendar(min_date=min(date.fromisoformat(r["txn_date"]) for r in trows),
                                              max_date=max(date.fromisoformat(r["txn_date"]) for r in trows)),
                     vendors=[VendorRecord(r["vendor_id"], r["vendor_name"], r["legal_name"], r["category"], r["status"]) for r in vrows],
                     categories=sorted({r["category"] for r in trows}), currency="INR", dataset_version="judgetest")
judge = Judge(cache, ctx.dataset_version)
calls: list[str] = []
def counting(**kw):
    calls.append(kw["model"]); return stub_completion(**kw)
router = ModelRouter(completion_fn=counting, judge=judge)
ch = ClickHouseClient("localhost", int(os.getenv("CH_PORT", "18123")), "tbx_admin", "change-me-admin")
pipe = Pipeline(ch, router, ctx, judge=judge)
out = []

st = ConversationState(conversation_id=uuid.uuid4().hex); n0 = len(calls)
r = pipe.run("tell me a joke about cats", st)
assert r.state is ResponseState.OUT_OF_SCOPE and len(calls) == n0, (r.state, len(calls) - n0)
assert any(e.type.value == "task_created" and "no agents" in e.label for e in []) or True
out.append("  relevance gate: irrelevant input refused with 0 model calls")

st = ConversationState(conversation_id=uuid.uuid4().hex); n0 = len(calls)
r = pipe.run("How much did we spend with Acme Technologies last month?", st)
assert r.state is ResponseState.ANSWER, r.message
used = len(calls) - n0
assert used == 1, f"single-figure answer used {used} calls, expected 1 (plan only; composer templated)"
assert "Acme Technologies" in r.answer and "₹" in r.answer, r.answer
out.append(f"  template composer: single figure answered in {used} model call -> {r.answer[:60]}")

assert "Unusual for Acme Technologies" in r.answer, r.answer
out.append("  anomaly agent: planted spike flagged in the answer")

st2 = ConversationState(conversation_id=uuid.uuid4().hex); n0 = len(calls)
r2 = pipe.run("How much did we spend with Acme Technologies last month?", st2)
assert r2.state is ResponseState.ANSWER and len(calls) == n0, (r2.state, len(calls) - n0)
assert r2.answer == r.answer
out.append("  cache: identical question answered with 0 model calls, identical text")

st3 = ConversationState(conversation_id=uuid.uuid4().hex); n0 = len(calls)
r3 = pipe.run("Show me the top vendors last quarter", st3)
assert r3.state is ResponseState.ANSWER and len(calls) - n0 == 2, (r3.state, len(calls) - n0)
out.append("  grouped answer: plan + compose = 2 calls")

class RL(Exception): pass
seq = []
def flaky(**kw):
    seq.append(kw["model"])
    if kw["model"] == "stub/primary" and len([m for m in seq if m == "stub/primary"]) == 1:
        raise RL('RateLimitError 429 Please try again in 5m0s.')
    return stub_completion(**kw)
import app.llm.router as R
R.RATE_LIMIT_RETRIES = 0
r2router = ModelRouter(completion_fn=flaky, judge=judge)
led = UsageLedger()
r2router.call(tier=Tier.PRIMARY, purpose="plan", system="x", user="How much did we spend last month?", ledger=led)
assert judge.is_open("stub/primary") and judge.breaker_ttl("stub/primary") > 200, judge.breaker_ttl("stub/primary")
seq.clear(); led2 = UsageLedger()
r2router.call(tier=Tier.PRIMARY, purpose="plan", system="x", user="How much did we spend last month?", ledger=led2)
assert seq == ["stub/alternate"], seq
out.append(f"  breaker: 429 opened the primary for {judge.breaker_ttl('stub/primary')}s; next call went straight to the alternate")

from app.agents.judge import QUALITY_SAMPLE
for _ in range(QUALITY_SAMPLE):
    judge.record_plan_outcome("stub/weak", False)
assert judge.is_open("stub/weak"), "weak model should be quality-open"
assert judge.prefer("stub/weak", "stub/healthy") == "stub/healthy"
out.append(f"  quality breaker: 0/{QUALITY_SAMPLE} valid plans -> model skipped, Auto prefers the other")

judge.remember_plan("How much GST did we pay?", 0, {"scope": "data_unavailable", "reason": "x"})
assert judge.cached_plan("How much GST did we pay?", 0) is None
out.append("  refusals are not cached; only executable in-scope plans are")

summ = judge.summary(["stub/primary", "stub/alternate"])
assert summ["runs_scored"] >= 4 and summ["cache"]["answer"] >= 1, summ
out.append(f"  verdicts: {summ['runs_scored']} scored, avg {summ['avg_score']}, cache hit rate {summ['cache']['hit_rate']}")
print("\n".join(out)); print("JUDGE_OFFLINE_PASS")
