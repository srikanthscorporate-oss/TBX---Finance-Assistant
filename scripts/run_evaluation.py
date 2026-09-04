#!/usr/bin/env python3
"""Run the golden set against the live API and measure accuracy.

Expected numeric values are recomputed from the source CSVs here, by code that
shares nothing with the application. A question only counts as numerically
correct when the API's figure matches that independent computation.

Metrics reported:
  state accuracy   -- did we land in the right response state?
  numeric accuracy -- when we answered, was the figure right?
  grounding rate   -- share of answers carrying evidence + passing verification
  hallucination    -- answers whose stated figure disagrees with the evidence,
                      or which state a figure with no verified fact behind it
  efficiency       -- tokens, LLM calls, latency, escalation rate
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import statistics
import sys
import time
import urllib.error
import urllib.request
import uuid
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
GOLDEN = ROOT / "evaluation" / "golden" / "questions.json"
RESULTS = ROOT / "evaluation" / "results"

HEDGE_RE = re.compile(
    r"\b(i estimate|probably|roughly|approximately|i assume|i'd guess|"
    r"based on typical|it seems like|around about)\b", re.I)


def post(api: str, path: str, body: dict, timeout: int = 60) -> dict:
    req = urllib.request.Request(
        f"{api}{path}", data=json.dumps(body).encode(),
        headers={"content-type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


class Independent:
    """Expected values computed straight from the CSVs."""

    def __init__(self) -> None:
        self.txns = list(csv.DictReader((RAW / "transactions.csv").open()))

    def compute(self, spec: dict) -> tuple[float, int] | None:
        if spec is None:
            return None
        rows = self.txns
        if "month" in spec:
            rows = [r for r in rows if r["txn_date"].startswith(spec["month"])]
        if "vendor_id" in spec:
            rows = [r for r in rows if r["vendor_id"] == spec["vendor_id"]]
        if "category" in spec:
            rows = [r for r in rows if r["category"] == spec["category"]]
        if "recon_in" in spec:
            rows = [r for r in rows if r["reconciliation_status"] in spec["recon_in"]]
        if spec.get("metric") == "count":
            return float(len(rows)), len(rows)
        return round(sum(float(r["amount"]) for r in rows), 2), len(rows)


def evaluate_turn(res: dict, expect: dict, ind: Independent) -> dict:
    """Score one turn. Returns per-check booleans; None means not applicable."""
    out: dict = {"state": res.get("state"), "checks": {}}
    c = out["checks"]

    want_state = expect.get("expected_state")
    acceptable = expect.get("acceptable_states")
    if acceptable:
        c["state"] = res.get("state") in acceptable
    elif want_state and want_state != "any":
        c["state"] = res.get("state") == want_state
    if expect.get("expect_intent") and res.get("plan"):
        c["intent"] = res["plan"].get("intent") == expect["expect_intent"]
    if expect.get("expect_vendor_id") and res.get("plan"):
        c["vendor"] = res["plan"].get("vendor_id") == expect["expect_vendor_id"]
    if expect.get("expect_grouped"):
        c["grouped"] = bool((res.get("evidence") or {}).get("breakdown"))

    ev = res.get("evidence") or None
    if res.get("state") == "answer":
        c["has_evidence"] = ev is not None
        if ev:
            checks = ev.get("verification", {}).get("checks", [])
            c["verification_passed"] = all(
                ch["passed"] for ch in checks if ch.get("severity") == "blocking")
            c["has_confidence"] = ev.get("confidence") is not None
            c["traceable"] = bool(ev.get("sql")) and ev.get("total_record_count", 0) >= 0

    # Numeric accuracy against an independent computation.
    exp = ind.compute(expect.get("value_spec")) if expect.get("value_spec") else None
    if exp is not None and ev:
        want_value, want_count = exp
        facts = {f["key"]: f for f in ev.get("facts", [])}
        got = None
        for key in ("total", "count", "rate"):
            if key in facts:
                got = float(facts[key]["value"])
                break
        if got is None:
            c["numeric"] = False
            out["numeric_detail"] = "no value fact"
        else:
            c["numeric"] = abs(got - want_value) <= max(0.02, abs(want_value) * 1e-6)
            out["numeric_detail"] = f"got={got} want={want_value}"
        if ev.get("total_record_count") is not None and want_count:
            c["record_count"] = ev["total_record_count"] == want_count

    # Hallucination: any figure in the prose must exist among verified facts.
    answer = res.get("answer") or ""
    if answer and ev:
        # Everything the server is allowed to have interpolated: verified facts,
        # plus the resolved period/date strings and entity names. A digit run
        # outside this set means the model wrote a figure of its own.
        rendered = {re.sub(r"[^\d]", "", f["formatted"]) for f in ev.get("facts", [])}
        for src in (ev.get("resolved_period"), ev.get("resolved_start"),
                    ev.get("resolved_end"), *map(str, ev.get("entities_resolved", {}).values())):
            if src:
                rendered.update(re.findall(r"\d+", str(src)))
                rendered.add(re.sub(r"[^\d]", "", str(src)))
        rendered.discard("")
        digits = re.findall(r"[\d,]+\.?\d*", answer)
        unverified = [d for d in digits
                      if re.sub(r"[^\d]", "", d) not in rendered
                      and len(re.sub(r"[^\d]", "", d)) > 2]
        c["no_unverified_figures"] = not unverified
        if unverified:
            out["unverified"] = unverified

    for text in (res.get("message"), answer):
        if text and HEDGE_RE.search(text):
            c["no_hedging"] = False
            out["hedge"] = text[:120]
            break
    else:
        if expect.get("must_not_hedge") or answer:
            c["no_hedging"] = True

    for banned in expect.get("must_not_contain", []):
        if banned in (answer + (res.get("message") or "")):
            c["no_injected_value"] = False
            break
    else:
        if expect.get("must_not_contain"):
            c["no_injected_value"] = True

    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default=os.getenv("TBX_API", "http://127.0.0.1:8010"))
    ap.add_argument("--out", default=str(RESULTS / "latest.json"))
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    questions = json.loads(GOLDEN.read_text())
    if args.limit:
        questions = questions[: args.limit]
    ind = Independent()

    results = []
    by_category: dict[str, Counter] = defaultdict(Counter)
    latencies: list[float] = []
    tokens: list[int] = []
    calls: list[int] = []
    escalations = 0
    errors = 0

    print(f"running {len(questions)} questions against {args.api}\n")
    for item in questions:
        cid = uuid.uuid4().hex
        turns = [item] + [
            {**f, "id": f"{item['id']}.{i + 1}"}
            for i, f in enumerate(item.get("follow_ups", []))
        ]
        for turn in turns:
            started = time.perf_counter()
            try:
                res = post(args.api, "/api/v1/chat",
                           {"message": turn["question"], "conversation_id": cid})
            except (urllib.error.URLError, TimeoutError) as e:
                errors += 1
                results.append({"id": turn.get("id", item["id"]), "error": str(e)})
                continue
            elapsed = (time.perf_counter() - started) * 1000
            latencies.append(elapsed)

            usage = res.get("model_usage", [])
            calls.append(len(usage))
            tokens.append(sum(u["prompt_tokens"] + u["completion_tokens"] for u in usage))
            if any(u["tier"] == "escalation" for u in usage):
                escalations += 1

            scored = evaluate_turn(res, turn, ind)
            cat = item["category"]
            passed = all(v for v in scored["checks"].values())
            by_category[cat]["total"] += 1
            by_category[cat]["passed"] += int(passed)
            for k, v in scored["checks"].items():
                by_category[cat][f"check_{k}_total"] += 1
                by_category[cat][f"check_{k}_passed"] += int(bool(v))

            results.append({
                "id": turn.get("id", item["id"]), "category": cat,
                "question": turn["question"], "passed": passed,
                "latency_ms": round(elapsed, 1),
                "answer": res.get("answer"),
                "message": res.get("message"),
                "clarification": (res.get("clarification") or {}).get("question"),
                "period": (res.get("evidence") or {}).get("resolved_period"),
                "record_count": (res.get("evidence") or {}).get("total_record_count"),
                "confidence": ((res.get("evidence") or {}).get("confidence") or {}).get("band"),
                **scored,
            })
            mark = "PASS" if passed else "FAIL"
            print(f"  [{mark}] {turn.get('id', item['id']):8} {turn['question'][:58]:60} "
                  f"{scored['state']:22} {elapsed:6.0f}ms")
            if not passed:
                bad = [k for k, v in scored["checks"].items() if not v]
                print(f"           failed: {', '.join(bad)}"
                      + (f"  ({scored.get('numeric_detail','')})" if "numeric" in bad else ""))

    total = sum(c["total"] for c in by_category.values())
    passed = sum(c["passed"] for c in by_category.values())

    def rate(name: str) -> float | None:
        t = sum(c[f"check_{name}_total"] for c in by_category.values())
        p = sum(c[f"check_{name}_passed"] for c in by_category.values())
        return round(p / t, 4) if t else None

    # Record which planner produced these numbers. A run against the offline
    # stub measures the DETERMINISTIC pipeline (resolution, dates, compilation,
    # verification, grounding) and says nothing about real NLU accuracy. Without
    # this stamp the headline figure is easy to misread.
    try:
        planner = json.loads(urllib.request.urlopen(
            f"{args.api}/health", timeout=5).read().decode()).get("planner", "unknown")
    except Exception:  # noqa: BLE001
        planner = "unknown"

    report = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "api": args.api,
        "planner": planner,
        "caveat": (
            "Stub planner: measures the deterministic pipeline only; real NLU "
            "accuracy is unmeasured until this is re-run against a live model."
            if planner == "stub" else
            "Measured end to end against a live model."),
        "questions": len(questions),
        "turns": total,
        "overall_accuracy": round(passed / total, 4) if total else 0,
        "state_accuracy": rate("state"),
        "intent_accuracy": rate("intent"),
        "vendor_resolution_accuracy": rate("vendor"),
        "numeric_accuracy": rate("numeric"),
        "record_count_accuracy": rate("record_count"),
        "grounding_rate": rate("has_evidence"),
        "verification_pass_rate": rate("verification_passed"),
        "hallucination_free_rate": rate("no_unverified_figures"),
        "no_hedging_rate": rate("no_hedging"),
        "transport_errors": errors,
        "efficiency": {
            "avg_llm_calls_per_turn": round(statistics.mean(calls), 2) if calls else 0,
            "avg_tokens_per_turn": round(statistics.mean(tokens), 1) if tokens else 0,
            "total_tokens": sum(tokens),
            "escalation_rate": round(escalations / total, 4) if total else 0,
            "latency_p50_ms": round(statistics.median(latencies), 1) if latencies else 0,
            "latency_p95_ms": round(sorted(latencies)[int(len(latencies) * 0.95)], 1)
            if len(latencies) > 3 else 0,
        },
        "by_category": {
            cat: {"total": c["total"], "passed": c["passed"],
                  "accuracy": round(c["passed"] / c["total"], 4)}
            for cat, c in sorted(by_category.items())
        },
        "results": results,
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2))

    print(f"\n{'=' * 72}")
    print(f"overall accuracy      {report['overall_accuracy']:.1%}  ({passed}/{total} turns)")
    for k in ("state_accuracy", "intent_accuracy", "vendor_resolution_accuracy",
              "numeric_accuracy", "grounding_rate", "verification_pass_rate",
              "hallucination_free_rate"):
        v = report[k]
        print(f"{k:22}{'  n/a' if v is None else f'{v:.1%}':>8}")
    e = report["efficiency"]
    print(f"\nllm calls/turn        {e['avg_llm_calls_per_turn']}")
    print(f"tokens/turn           {e['avg_tokens_per_turn']}")
    print(f"escalation rate       {e['escalation_rate']:.1%}")
    print(f"latency p50 / p95     {e['latency_p50_ms']:.0f}ms / {e['latency_p95_ms']:.0f}ms")
    print("\nby category:")
    for cat, c in report["by_category"].items():
        print(f"  {cat:16} {c['passed']:>3}/{c['total']:<3} {c['accuracy']:.0%}")
    try:
        shown = out_path.resolve().relative_to(ROOT)
    except ValueError:
        shown = out_path
    print(f"\nreport: {shown}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
