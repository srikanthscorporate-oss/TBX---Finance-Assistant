#!/usr/bin/env python3
"""Run the golden set against the live API and write evaluation/results/latest.json.

Expected values come from evaluation/golden/questions.json, which build_golden_set.py
computed from the CSVs by code that shares nothing with the query path. A question whose
expected state is a clarification is scored on the field asked for, then auto-answered
with the expected option and the completed answer scored as its own turn. Every response
is scanned for a full account number from account.csv; any hit fails the turn.
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
    """POST one turn. The API's own per-client limit answers 429; wait it out rather than
    score it, since it says nothing about the pipeline."""
    req = urllib.request.Request(
        f"{api}{path}", data=json.dumps(body).encode(),
        headers={"content-type": "application/json"}, method="POST")
    for attempt in range(6):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            if e.code != 429 or attempt == 5:
                raise
            wait = float(e.headers.get("Retry-After") or 12)
            print(f"  API rate limit (429); waiting {wait:.0f}s")
            time.sleep(wait)
    raise RuntimeError("unreachable")


_RETRY_IN = re.compile(r"try again in about (?:(\d+)m )?(\d+)s")


def refused_for_seconds(res: dict) -> float:
    """Seconds the API asked us to wait when it refused a turn as rate limited, else 0.

    A 429 opens the breaker for the provider's stated wait and every turn in that window is
    refused instantly, so the runner waits and retries rather than scoring the breaker.
    """
    msg = res.get("message") or ""
    if "rate limited" not in msg.lower():
        return 0.0
    m = _RETRY_IN.search(msg)
    if not m:
        return 30.0
    return int(m.group(1) or 0) * 60 + int(m.group(2))


def account_numbers() -> tuple[list[str], list[str]]:
    """(own, others): plaintext account numbers of the default entity, and everyone else's.

    The masking check scores the entity's own numbers, which the app stores encrypted and
    renders as last four. Other entities' numbers appear inside narration text the
    generator wrote (a counterparty's account in a NEFT/IMPS description), so a hit there is
    counted separately as a description leak rather than failing the turn.
    """
    if not (RAW / "account.csv").exists() or not (RAW / "transaction.csv").exists():
        return [], []
    accounts = list(csv.DictReader((RAW / "account.csv").open()))
    entity_of = {a["account_id"]: a["entity_id"] for a in accounts}
    busiest = Counter(entity_of[r["account_id"]]
                      for r in csv.DictReader((RAW / "transaction.csv").open())).most_common(1)[0][0]
    own = [a["account_number"] for a in accounts if a["entity_id"] == busiest]
    others = [a["account_number"] for a in accounts if a["entity_id"] != busiest]
    return own, others


def _matches(got, want, tolerance: float) -> bool:
    if isinstance(want, str):
        return str(got) == want
    try:
        return abs(float(got) - float(want)) <= max(tolerance, abs(float(want)) * 1e-6)
    except (TypeError, ValueError):
        return False


def evaluate_turn(res: dict, expect: dict, raw_body: str, own: list[str],
                  others: list[str]) -> dict:
    """Score one turn. Returns per-check booleans; None means not applicable.

    Facts are compared key by key against the golden values with their tolerances. For
    hallucination, any digit run in the prose must appear in a verified fact, the resolved
    period or dates, or a resolved entity.
    """
    out: dict = {"state": res.get("state"), "checks": {}}
    c = out["checks"]
    state = res.get("state")
    plan = res.get("plan") or {}
    ev = res.get("evidence") or None

    want_state = expect.get("expected_state")
    acceptable = expect.get("acceptable_states")
    if acceptable:
        c["state"] = state in acceptable
    elif want_state and want_state != "any":
        c["state"] = state == want_state

    if expect.get("expected_clarification_field"):
        field = (res.get("clarification") or {}).get("field")
        c["clarification_field"] = field == expect["expected_clarification_field"]
        if expect.get("expected_options"):
            values = {o.get("value") for o in (res.get("clarification") or {}).get("options", [])}
            c["clarification_options"] = set(expect["expected_options"]) <= values

    if expect.get("expected_intent") and plan:
        c["intent"] = plan.get("intent") == expect["expected_intent"]
    if expect.get("expected_counterparty") and plan:
        c["counterparty"] = plan.get("counterparty") == expect["expected_counterparty"]
    if expect.get("expected_period") and plan:
        c["period"] = (plan.get("date_range") or {}).get("relative") == expect["expected_period"]
    if expect.get("expected_transaction_type") and plan:
        c["transaction_type"] = plan.get("transaction_type") == expect["expected_transaction_type"]
    if expect.get("expected_channel") and plan:
        c["channel"] = plan.get("channel") == expect["expected_channel"]
    if expect.get("expected_grouped"):
        c["grouped"] = bool((ev or {}).get("breakdown"))

    if state == "answer":
        c["has_evidence"] = ev is not None
        if ev:
            checks = ev.get("verification", {}).get("checks", [])
            c["verification_passed"] = all(
                ch["passed"] for ch in checks if ch.get("severity") == "blocking")
            c["has_confidence"] = ev.get("confidence") is not None
            c["traceable"] = bool(ev.get("sql"))
    elif state in {"clarification_required", "data_unavailable", "out_of_scope", "error"}:
        c["no_figure_outside_answer"] = ev is None and not res.get("answer")

    facts = {f["key"]: f for f in (ev or {}).get("facts", [])}
    wanted = expect.get("expected_facts") or {}
    if wanted and state == "answer":
        detail = []
        ok = True
        for key, spec in wanted.items():
            if key == "record_count":
                got = (ev or {}).get("total_record_count")
            else:
                got = facts[key]["value"] if key in facts else None
            hit = got is not None and _matches(got, spec["value"], spec.get("tolerance", 0))
            ok = ok and hit
            if not hit:
                detail.append(f"{key}: got={got} want={spec['value']}")
        c["numeric"] = ok
        if detail:
            out["numeric_detail"] = "; ".join(detail)
    elif wanted and state != "answer":
        c["numeric"] = False
        out["numeric_detail"] = f"expected facts but state was {state}"

    first = expect.get("expected_first_record")
    if first and state == "answer":
        records = (ev or {}).get("records") or []
        r0 = records[0] if records else {}
        bad = [k for k, v in first.items() if not _matches(r0.get(k), v, 0.005)]
        c["first_record"] = not bad
        if bad:
            out["record_detail"] = {k: r0.get(k) for k in bad}

    answer = res.get("answer") or ""
    if answer and ev:
        rendered = {re.sub(r"[^\d]", "", f["formatted"]) for f in ev.get("facts", [])}
        for src in (ev.get("resolved_period"), ev.get("resolved_start"),
                    ev.get("resolved_end"), *map(str, ev.get("entities_resolved", {}).values())):
            if src:
                rendered.update(re.findall(r"\d+", str(src)))
                rendered.add(re.sub(r"[^\d]", "", str(src)))
        for r in ev.get("records", [])[:1]:
            for v in r.values():
                rendered.update(re.findall(r"\d+", str(v)))
                rendered.add(re.sub(r"[^\d]", "", str(v)))
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

    banned = expect.get("must_not_contain", [])
    if banned:
        said = " ".join(filter(None, [answer, res.get("message"),
                                      (res.get("clarification") or {}).get("question")]))
        c["no_injected_value"] = not any(b in said for b in banned)

    leaked = [n for n in own if n in raw_body]
    c["masked"] = not leaked
    if leaked:
        out["leaked_account_numbers"] = len(leaked)
    in_text = [n for n in others if n in raw_body]
    if in_text:
        out["description_account_numbers"] = len(in_text)

    return out


def main() -> int:
    """Run every turn, retrying rate-limit refusals for the wait the provider asked.

    Rate-limited turns are counted and the report is stamped throttled; rates are 0.0 rather
    than None when nothing could be measured so reports stay comparable. Escalations count
    turns that needed a second model. The planner is recorded because a stub run measures the
    deterministic pipeline only. A throttled run never overwrites last-clean.json.
    """
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default=os.getenv("TBX_API", "http://127.0.0.1:8010"))
    ap.add_argument("--out", default=str(RESULTS / "latest.json"))
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--model", default=None,
                    help="pin a catalog model id for every turn; default is the API's auto mode")
    ap.add_argument("--no-clarify", action="store_true",
                    help="do not auto-answer clarifications with the expected option")
    ap.add_argument("--rate-limit-retries", type=int, default=3,
                    help="retry a rate-limit refused turn this many times, waiting the provider's stated interval")
    ap.add_argument("--pace-s", type=float, default=float(os.getenv("EVAL_PACE_S", "0")),
                    help="seconds to sleep after each turn, to stay under a per-minute token cap")
    args = ap.parse_args()

    questions = json.loads(GOLDEN.read_text())
    if args.limit:
        questions = questions[: args.limit]
    own_numbers, other_numbers = account_numbers()
    description_leaks = 0

    results = []
    by_category: dict[str, Counter] = defaultdict(Counter)
    latencies: list[float] = []
    tokens: list[int] = []
    calls: list[int] = []
    escalations = 0
    errors = 0
    rate_limited = 0
    app_bugs: list[dict] = []

    def send(body: dict) -> tuple[dict, str, float]:
        if args.model:
            body["model"] = args.model
        started = time.perf_counter()
        res = post(args.api, "/api/v1/chat", body)
        for _ in range(args.rate_limit_retries):
            wait = refused_for_seconds(res)
            if not wait:
                break
            print(f"  rate limited, waiting {wait:.0f}s before retrying")
            time.sleep(min(wait, 300) + 1)
            started = time.perf_counter()
            res = post(args.api, "/api/v1/chat", body)
        elapsed = (time.perf_counter() - started) * 1000
        if args.pace_s:
            time.sleep(args.pace_s)
        return res, json.dumps(res, ensure_ascii=False), elapsed

    print(f"running {len(questions)} questions against {args.api}\n")
    for item in questions:
        cid = uuid.uuid4().hex
        turns: list[tuple[str, dict, dict]] = [
            (item["id"], {"message": item["question"], "conversation_id": cid}, item)]
        clarify = item.get("clarify_with")
        if clarify and not args.no_clarify:
            turns.append((f"{item['id']}.c", {"conversation_id": cid,
                                              "resolved_value": clarify["value"],
                                              "resolved_field": clarify.get("field")},
                          {**clarify, "question": f"[{clarify['value']}]"}))
        if item.get("follow_up"):
            fu = item["follow_up"]
            turns.append((f"{item['id']}.1", {"message": fu["question"], "conversation_id": cid}, fu))

        prior_ok = True
        for tid, body, expect in turns:
            if tid.endswith(".c") and not prior_ok:
                break
            try:
                res, raw, elapsed = send(body)
            except (urllib.error.URLError, TimeoutError) as e:
                errors += 1
                results.append({"id": tid, "error": str(e)})
                prior_ok = False
                continue
            latencies.append(elapsed)

            usage = res.get("model_usage", [])
            rate_limited += sum(1 for u in usage
                                if not u.get("ok") and "rate limit" in (u.get("error") or "").lower())
            if "rate limited" in (res.get("message") or "").lower():
                rate_limited += 1
            calls.append(len(usage))
            tokens.append(sum(u["prompt_tokens"] + u["completion_tokens"] for u in usage))
            if any(u["tier"] in ("alternate", "fallback", "regional") and u.get("ok")
                   for u in usage):
                escalations += 1

            scored = evaluate_turn(res, expect, raw, own_numbers, other_numbers)
            description_leaks += int(bool(scored.get("description_account_numbers")))
            cat = item["category"]
            passed = all(v for v in scored["checks"].values())
            prior_ok = scored["checks"].get("state", True) is not False
            by_category[cat]["total"] += 1
            by_category[cat]["passed"] += int(passed)
            for k, v in scored["checks"].items():
                by_category[cat][f"check_{k}_total"] += 1
                by_category[cat][f"check_{k}_passed"] += int(bool(v))

            row = {
                "id": tid, "category": cat,
                "question": expect.get("question", item["question"]), "passed": passed,
                "latency_ms": round(elapsed, 1),
                "answer": res.get("answer"),
                "message": res.get("message"),
                "clarification": (res.get("clarification") or {}).get("question"),
                "clarification_field": (res.get("clarification") or {}).get("field"),
                "period": (res.get("evidence") or {}).get("resolved_period"),
                "record_count": (res.get("evidence") or {}).get("total_record_count"),
                "confidence": ((res.get("evidence") or {}).get("confidence") or {}).get("band"),
                **scored,
            }
            results.append(row)
            mark = "PASS" if passed else "FAIL"
            print(f"  [{mark}] {tid:8} {row['question'][:58]:60} "
                  f"{str(scored['state']):22} {elapsed:6.0f}ms")
            if not passed:
                bad = [k for k, v in scored["checks"].items() if not v]
                print(f"           failed: {', '.join(bad)}"
                      + (f"  ({scored.get('numeric_detail', '')})" if "numeric" in bad else "")
                      + (f"  {scored.get('record_detail')}" if "first_record" in bad else ""))
                if {"masked", "verification_passed", "no_figure_outside_answer",
                        "numeric", "first_record"} & set(bad):
                    app_bugs.append({"id": tid, "question": row["question"], "failed": bad,
                                     "state": scored["state"],
                                     "detail": scored.get("numeric_detail") or scored.get("record_detail"),
                                     "response": (res.get("answer") or res.get("message")
                                                  or row["clarification"])})

    total = sum(c["total"] for c in by_category.values())
    passed = sum(c["passed"] for c in by_category.values())

    def rate(name: str) -> float:
        t = sum(c[f"check_{name}_total"] for c in by_category.values())
        p = sum(c[f"check_{name}_passed"] for c in by_category.values())
        return round(p / t, 4) if t else 0.0

    try:
        health = json.loads(urllib.request.urlopen(f"{args.api}/health", timeout=5).read().decode())
        planner = health.get("planner", "unknown")
        dataset_version = health.get("dataset_version")
    except Exception:  # noqa: BLE001
        planner, dataset_version = "unknown", None

    report = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "api": args.api,
        "planner": planner,
        "model": args.model or "auto",
        "dataset_version": dataset_version,
        "caveat": (
            "Stub planner: measures the deterministic pipeline only; real NLU "
            "accuracy is unmeasured until this is re-run against a live model."
            if planner == "stub" else
            ("Measured end to end against a live model."
             + (f" THROTTLED: {rate_limited} model calls hit a provider rate limit during "
                "this run, so these scores understate the pipeline. Re-run when quota has "
                "recovered." if rate_limited else ""))),
        "questions": len(questions),
        "turns": total,
        "overall_accuracy": round(passed / total, 4) if total else 0,
        "state_accuracy": rate("state"),
        "intent_accuracy": rate("intent"),
        "counterparty_resolution_accuracy": rate("counterparty"),
        "period_accuracy": rate("period"),
        "clarification_accuracy": rate("clarification_field"),
        "numeric_accuracy": rate("numeric"),
        "record_accuracy": rate("first_record"),
        "grounding_rate": rate("has_evidence"),
        "verification_pass_rate": rate("verification_passed"),
        "hallucination_free_rate": rate("no_unverified_figures"),
        "masking_rate": rate("masked"),
        "turns_with_account_numbers_in_narration": description_leaks,
        "no_hedging_rate": rate("no_hedging"),
        "transport_errors": errors,
        "rate_limited_calls": rate_limited,
        "throttled": rate_limited > 0,
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
        "suspected_app_bugs": app_bugs,
        "results": results,
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    if not report["throttled"] and report["transport_errors"] == 0 and out_path.name == "latest.json":
        (out_path.parent / "last-clean.json").write_text(json.dumps(report, indent=2, ensure_ascii=False))

    print(f"\n{'=' * 72}")
    print(f"overall accuracy      {report['overall_accuracy']:.1%}  ({passed}/{total} turns)")
    for k in ("state_accuracy", "intent_accuracy", "counterparty_resolution_accuracy",
              "period_accuracy", "clarification_accuracy", "numeric_accuracy",
              "record_accuracy", "grounding_rate", "verification_pass_rate",
              "hallucination_free_rate", "masking_rate"):
        print(f"{k:34}{report[k]:>8.1%}")
    e = report["efficiency"]
    if rate_limited:
        print(f"\nWARNING: {rate_limited} rate-limited model calls; this run is degraded by throttling")
    print(f"\nllm calls/turn        {e['avg_llm_calls_per_turn']}")
    print(f"tokens/turn           {e['avg_tokens_per_turn']}")
    print(f"escalation rate       {e['escalation_rate']:.1%}")
    print(f"latency p50 / p95     {e['latency_p50_ms']:.0f}ms / {e['latency_p95_ms']:.0f}ms")
    print("\nby category:")
    for cat, c in report["by_category"].items():
        print(f"  {cat:18} {c['passed']:>3}/{c['total']:<3} {c['accuracy']:.0%}")
    if description_leaks:
        print(f"\nNOTE: {description_leaks} turns carried another entity's account number inside "
              "narration text (generator artefact; own accounts stayed masked)")
    if app_bugs:
        print(f"\nsuspected app bugs: {len(app_bugs)} (see suspected_app_bugs in the report)")
    try:
        shown = out_path.resolve().relative_to(ROOT)
    except ValueError:
        shown = out_path
    print(f"\nreport: {shown}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
