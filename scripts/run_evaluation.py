#!/usr/bin/env python3
"""Run the golden set against the live API and write evaluation/results/latest.json.

Expected values come from evaluation/golden/questions.json, which build_golden_set.py
computed from the CSVs by code that shares nothing with the query path.

Every conversation is fresh, so the first message of each one carries the default entity's
opaque token, fetched once from /api/v1/entities. A question whose expected state is a
clarification is walked step by step: each clarification is scored on the field asked for
and on carrying options, then answered with the golden `resolutions` entry and the next
response scored as its own turn (`<id>.c1`, `<id>.c2`, ...). Chains are capped at four
steps and a field the item did not expect fails the turn.

Every response is scanned for a full account number from account.csv and for a raw entity
uuid; either hit fails the turn. A small entity-behaviour suite, computed here rather than
from the golden file because it needs live tokens, checks that a conversation is locked to
the entity it started with.
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

MAX_CHAIN_STEPS = 4
"""A clarification chain longer than this is a bug, not a conversation."""

ENTITY_SWITCH_PREFIX = "I don't have any Idea what you're talking about."
"""Exactly how the API must open when a second entity arrives on a conversation."""

ENTITY_PROBES = ["How much did I spend last month?",
                 "How much did I spend in the last 7 days?"]
"""Fully specified questions for the entity-behaviour suite. They differ from each other
because a repeat of the same sentence on one conversation is read as a follow-up delta."""

ENTITY_FOLLOW_UP = "What about the month before?"
"""Sent last on the entity-behaviour conversation: the refusal must not have unbound the
entity, so the original question can still be moved on."""

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


def entity_ids() -> tuple[str, list[str]]:
    """(default entity uuid, every entity uuid) straight from account.csv.

    The default is the busiest entity, the same rule the API and the golden builder use.
    Raw uuids must never appear in a response body now that the API hands out tokens and
    masked labels, so the runner keeps the plaintext list to scan for.
    """
    if not (RAW / "account.csv").exists() or not (RAW / "transaction.csv").exists():
        return "", []
    accounts = list(csv.DictReader((RAW / "account.csv").open()))
    entity_of = {a["account_id"]: a["entity_id"] for a in accounts}
    busiest = Counter(entity_of[r["account_id"]]
                      for r in csv.DictReader((RAW / "transaction.csv").open())).most_common(1)[0][0]
    return busiest, sorted({a["entity_id"] for a in accounts})


def mask_entity(entity_id: str) -> str:
    """The label the API renders: everything starred but the last four characters."""
    return "*" * (len(entity_id) - 4) + entity_id[-4:] if len(entity_id) > 4 else "*" * len(entity_id)


def fetch_entity_tokens(api: str) -> tuple[str, str]:
    """(default token, some other entity's token) from the live catalogue.

    Tokens are opaque ciphertext and change per server key, so they cannot be baked into
    the golden file; they are fetched once and reused for every conversation.
    """
    with urllib.request.urlopen(f"{api}/api/v1/entities", timeout=20) as r:
        entities = json.loads(r.read().decode())
    if not entities:
        raise SystemExit("the API listed no entities")
    default = next((e for e in entities if e.get("default")), entities[0])
    other = next((e for e in entities if e["entity_id"] != default["entity_id"]), None)
    return default["entity_id"], (other or {}).get("entity_id", "")


def _matches(got, want, tolerance: float) -> bool:
    if isinstance(want, str):
        return str(got) == want
    try:
        return abs(float(got) - float(want)) <= max(tolerance, abs(float(want)) * 1e-6)
    except (TypeError, ValueError):
        return False


def evaluate_turn(res: dict, expect: dict, raw_body: str, own: list[str],
                  others: list[str], entities: list[str] = (),
                  masked_default: str = "") -> dict:
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
        clar = res.get("clarification") or {}
        c["clarification_field"] = clar.get("field") == expect["expected_clarification_field"]
        c["clarification_has_options"] = bool(clar.get("options"))
        if expect.get("expected_options"):
            values = {o.get("value") for o in clar.get("options", [])}
            c["clarification_options"] = set(expect["expected_options"]) <= values

    if expect.get("expected_message_prefix"):
        c["message_prefix"] = (res.get("message") or "").startswith(
            expect["expected_message_prefix"])

    if expect.get("expected_no_period"):
        # A balance or a reference lookup does not depend on a window or a side, so the
        # API must answer it rather than asking about either.
        asked = (res.get("clarification") or {}).get("field")
        c["answered_without_asking"] = asked not in {"date_range", "transaction_type"}

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
        for r in ev.get("records", []):
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

    if state == "answer" and masked_default:
        resolved = (ev or {}).get("entities_resolved") or {}
        c["entity_scoped"] = resolved.get("entity_id") == masked_default

    exposed = [e for e in entities if e in raw_body]
    if entities:
        c["entity_id_opaque"] = not exposed
        if exposed:
            out["leaked_entity_ids"] = exposed

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
    default_entity, entity_uuids = entity_ids()
    masked_default = mask_entity(default_entity) if default_entity else ""
    default_token, other_token = fetch_entity_tokens(args.api)
    print(f"entity {masked_default or '(unknown)'} "
          f"({len(entity_uuids)} in the dataset); token sent on every first message")
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

    def record(tid: str, res: dict, expect: dict, raw: str, elapsed: float,
               category: str, question: str) -> bool:
        """Score one turn, fold it into the totals, print it, return whether it passed."""
        nonlocal description_leaks, rate_limited, escalations
        latencies.append(elapsed)
        usage = res.get("model_usage", [])
        rate_limited += sum(1 for u in usage
                            if not u.get("ok") and "rate limit" in (u.get("error") or "").lower())
        if "rate limited" in (res.get("message") or "").lower():
            rate_limited += 1
        calls.append(len(usage))
        tokens.append(sum(u["prompt_tokens"] + u["completion_tokens"] for u in usage))
        if any(u["tier"] in ("alternate", "fallback", "regional") and u.get("ok") for u in usage):
            escalations += 1

        scored = evaluate_turn(res, expect, raw, own_numbers, other_numbers,
                               entity_uuids, masked_default)
        description_leaks += int(bool(scored.get("description_account_numbers")))
        passed = all(v for v in scored["checks"].values())
        by_category[category]["total"] += 1
        by_category[category]["passed"] += int(passed)
        for k, v in scored["checks"].items():
            by_category[category][f"check_{k}_total"] += 1
            by_category[category][f"check_{k}_passed"] += int(bool(v))

        row = {
            "id": tid, "category": category, "question": question, "passed": passed,
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
        print(f"  [{'PASS' if passed else 'FAIL'}] {tid:10} {question[:56]:58} "
              f"{str(scored['state']):22} {elapsed:6.0f}ms")
        if not passed:
            bad = [k for k, v in scored["checks"].items() if not v]
            print(f"           failed: {', '.join(bad)}"
                  + (f"  ({scored.get('numeric_detail', '')})" if "numeric" in bad else "")
                  + (f"  {scored.get('record_detail')}" if "first_record" in bad else ""))
            if {"masked", "entity_id_opaque", "entity_scoped", "verification_passed",
                    "no_figure_outside_answer", "numeric", "first_record",
                    "answered_without_asking", "message_prefix"} & set(bad):
                app_bugs.append({"id": tid, "question": question, "failed": bad,
                                 "state": scored["state"],
                                 "detail": scored.get("numeric_detail")
                                 or scored.get("record_detail")
                                 or scored.get("leaked_entity_ids"),
                                 "response": (res.get("answer") or res.get("message")
                                              or row["clarification"])})
        return passed

    def fail_turn(tid: str, category: str, question: str, why: str) -> None:
        """Record a turn the runner refused to continue, so it counts against the score."""
        by_category[category]["total"] += 1
        results.append({"id": tid, "category": category, "question": question,
                        "passed": False, "state": None, "checks": {"chain": False},
                        "chain_error": why})
        print(f"  [FAIL] {tid:10} {question[:56]:58} {why}")
        app_bugs.append({"id": tid, "question": question, "failed": ["chain"],
                         "state": None, "detail": why, "response": None})

    print(f"running {len(questions)} questions against {args.api}\n")
    for item in questions:
        cid = uuid.uuid4().hex
        category, question = item["category"], item["question"]
        try:
            res, raw, elapsed = send({"message": question, "conversation_id": cid,
                                      "entity_id": default_token})
        except (urllib.error.URLError, TimeoutError) as e:
            errors += 1
            results.append({"id": item["id"], "error": str(e)})
            continue
        ok = record(item["id"], res, item, raw, elapsed, category, question)

        resolutions = list(item.get("resolutions") or [])
        step = 0
        while (ok and not args.no_clarify
               and res.get("state") == "clarification_required" and step < len(resolutions)):
            if step >= MAX_CHAIN_STEPS:
                fail_turn(f"{item['id']}.c{step + 1}", category, question,
                          f"clarification chain exceeded {MAX_CHAIN_STEPS} steps")
                ok = False
                break
            r = resolutions[step]
            asked = (res.get("clarification") or {}).get("field")
            if asked != r["field"]:
                fail_turn(f"{item['id']}.c{step + 1}", category, question,
                          f"asked for {asked!r}, which this question did not expect")
                ok = False
                break
            step += 1
            tid = f"{item['id']}.c{step}"
            try:
                res, raw, elapsed = send({"conversation_id": cid,
                                          "resolved_value": r["value"],
                                          "resolved_field": r["field"]})
            except (urllib.error.URLError, TimeoutError) as e:
                errors += 1
                results.append({"id": tid, "error": str(e)})
                ok = False
                break
            ok = record(tid, res, r["expect"], raw, elapsed,
                        category, f"[{r['field']} = {r['value']}]")

        if ok and item.get("follow_up"):
            fu = item["follow_up"]
            try:
                res, raw, elapsed = send({"message": fu["question"], "conversation_id": cid})
            except (urllib.error.URLError, TimeoutError) as e:
                errors += 1
                results.append({"id": f"{item['id']}.1", "error": str(e)})
            else:
                record(f"{item['id']}.1", res, fu, raw, elapsed, category, fu["question"])

    # --- entity behaviour, computed here because it needs live tokens
    if other_token:
        cid = uuid.uuid4().hex
        plan = [
            ("E01", {"message": ENTITY_PROBES[0], "conversation_id": cid,
                     "entity_id": default_token},
             {"expected_state": "answer"}, "first entity token binds the conversation"),
            ("E02", {"message": ENTITY_PROBES[1], "conversation_id": cid,
                     "entity_id": other_token},
             {"expected_state": "out_of_scope",
              "expected_message_prefix": ENTITY_SWITCH_PREFIX},
             "a second, different entity token is refused"),
            ("E03", {"message": ENTITY_FOLLOW_UP, "conversation_id": cid,
                     "entity_id": default_token},
             {"expected_state": "answer"}, "the bound entity still answers"),
            ("E04", {"message": ENTITY_PROBES[0], "conversation_id": uuid.uuid4().hex},
             {"expected_state": "clarification_required",
              "expected_clarification_field": "entity"},
             "no entity chosen: the API asks which one"),
        ]
        for tid, body, expect, label in plan:
            try:
                res, raw, elapsed = send(body)
            except (urllib.error.URLError, TimeoutError) as e:
                errors += 1
                results.append({"id": tid, "error": str(e)})
                continue
            record(tid, res, expect, raw, elapsed, "entity_scoping", label)

    total = sum(c["total"] for c in by_category.values())
    passed = sum(c["passed"] for c in by_category.values())
    # A single systemic defect can fail every turn and hide everything else, so the report
    # also carries the score with the entity-id check set aside. It is a second view of the
    # same results, never a reason to stop checking.
    passed_ex = sum(1 for r in results
                    if r.get("checks") is not None
                    and all(v for k, v in r["checks"].items() if k != "entity_id_opaque"))

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
        "overall_accuracy_excluding_entity_id_leak":
            round(passed_ex / total, 4) if total else 0,
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
        "entity_scoping_ok": rate("entity_scoped"),
        "entity_id_opacity_rate": rate("entity_id_opaque"),
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
    print(f"  ... ignoring the entity-id check "
          f"{report['overall_accuracy_excluding_entity_id_leak']:.1%}  ({passed_ex}/{total})")
    for k in ("state_accuracy", "intent_accuracy", "counterparty_resolution_accuracy",
              "period_accuracy", "clarification_accuracy", "numeric_accuracy",
              "record_accuracy", "grounding_rate", "verification_pass_rate",
              "hallucination_free_rate", "masking_rate", "entity_scoping_ok",
              "entity_id_opacity_rate"):
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
