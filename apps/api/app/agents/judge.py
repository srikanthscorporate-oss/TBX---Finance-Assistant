"""The judge: deterministic scoring that feeds back into routing.

It is NOT another model call. Every run already produces the signals that
matter (verification, confidence, state, tokens, latency, which model ended up
answering); the judge turns them into a score, remembers them in Redis, and
uses them to make the next run cheaper and more likely to succeed:

  * plan cache      an identical question never re-runs the planner (0 tokens)
  * answer cache    an identical validated plan never re-runs query + compose
  * circuit breaker a rate-limited model is skipped for as long as the provider
                    asked, instead of every request paying the wait
  * model preference in Auto mode, start with whichever compliant model has the
                    better recent plan-validity rate, so a struggling primary
                    does not burn a call on every question

Keys carry the dataset version, so a reload invalidates cached answers.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any

from ..services.cache import Cache

PLAN_TTL = 24 * 3600
ANSWER_TTL = 3600
# Bumped when cache semantics change, so stale entries are orphaned rather
# than served. v2: refusals are no longer cached (see remember_plan).
CACHE_NS = "v3"
WINDOW_TTL = 3600           # rolling hour for per-model validity counters
MIN_SAMPLE = 6              # do not steer on fewer observations than this
STEER_MARGIN = 0.25         # switch preference only on a clear gap
# A model that is answering but almost never producing a valid plan is dead
# weight: each attempt costs calls and ends in the same failure. Below this
# validity, over at least this many recent plans, it is treated as open.
QUALITY_FLOOR = 0.2
QUALITY_SAMPLE = 12


def normalise_question(q: str) -> str:
    """Case, whitespace and punctuation-insensitive key for the plan cache."""
    q = q.strip().lower()
    q = re.sub(r"[^\w\s]", " ", q)
    return re.sub(r"\s+", " ", q).strip()


def question_key(q: str, conversation_turn: int) -> str:
    # A follow-up depends on the previous plan, so it is cached under its turn
    # position; a first question is context-free and shared across users.
    base = normalise_question(q)
    return hashlib.sha256(f"{conversation_turn if conversation_turn else 0}|{base}".encode()).hexdigest()[:20]


@dataclass
class Dispatch:
    """Which agents this run needs. Anything not needed is not spawned."""

    planner: str          # cache | full | delta | skip
    composer: str         # template | llm
    anomaly: bool
    model: str | None     # preferred first model for Auto, or None
    reasons: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {"planner": self.planner, "composer": self.composer, "anomaly": self.anomaly,
                "model": (self.model or "").split("/")[-1] or None, "reasons": self.reasons}


# Intents whose single-figure answers a template renders as well as a model.
TEMPLATE_INTENTS = {"total_spend", "vendor_spend", "category_spend", "account_spend",
                    "vendor_payouts", "unreconciled", "reconciliation_rate",
                    "transaction_lookup", "vendor_lookup", "payout_status"}
# Intents where a deterministic anomaly check adds real information.
ANOMALY_INTENTS = {"vendor_spend", "vendor_payouts"}


@dataclass
class Verdict:
    score: float
    grounded: bool
    verified: bool
    state: str
    tokens: int
    duration_ms: float
    model: str | None
    switched: bool
    notes: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {"score": self.score, "grounded": self.grounded, "verified": self.verified,
                "state": self.state, "tokens": self.tokens, "duration_ms": self.duration_ms,
                "model": self.model, "switched": self.switched, "notes": self.notes}


def _has_key(model_id: str) -> bool:
    from ..llm import catalog as _cat
    entry = _cat.by_id(model_id)
    return bool(entry and entry.available)


class Judge:
    def __init__(self, cache: Cache, dataset_version: str):
        self.c = cache
        self.v = dataset_version

    # -- caches ------------------------------------------------------------
    def cached_plan(self, question: str, turn: int) -> dict | None:
        return self.c.get_json("plan", CACHE_NS, self.v, question_key(question, turn))

    def remember_plan(self, question: str, turn: int, parsed: dict) -> None:
        """Cache only a plan that will actually be executed.

        A model's refusal ("out of scope", "data unavailable") is a judgement
        that can be wrong, especially from a weak or throttled model, and
        freezing it for a day turns one bad call into a day of bad answers.
        Refusals are cheap to recompute; only in-scope, validated plans are
        worth remembering.
        """
        if parsed.get("scope", "in_scope") != "in_scope":
            return
        if not (parsed.get("plan") or parsed.get("delta")):
            return
        self.c.set_json("plan", CACHE_NS, self.v, question_key(question, turn), value=parsed, ttl=PLAN_TTL)

    def cached_answer(self, fingerprint: str) -> dict | None:
        return self.c.get_json("answer", CACHE_NS, self.v, fingerprint)

    def remember_answer(self, fingerprint: str, payload: dict) -> None:
        self.c.set_json("answer", CACHE_NS, self.v, fingerprint, value=payload, ttl=ANSWER_TTL)

    # -- circuit breaker ---------------------------------------------------
    def trip(self, model: str, seconds: int) -> None:
        self.c.set_flag("breaker", model, ttl=seconds)
        self.c.incr("breaker_trips", model, ttl=WINDOW_TTL)

    def is_open(self, model: str) -> bool:
        if self.c.flag("breaker", model):
            return True
        rate, n = self.validity(model)
        return n >= QUALITY_SAMPLE and rate is not None and rate < QUALITY_FLOOR

    def breaker_ttl(self, model: str) -> int:
        return max(0, self.c.ttl("breaker", model))

    # -- plan validity, per model, rolling window -------------------------
    def record_plan_outcome(self, model: str, valid: bool) -> None:
        self.c.incr("validity", model, "ok" if valid else "fail", ttl=WINDOW_TTL)

    def validity(self, model: str) -> tuple[float | None, int]:
        ok = self.c.get_int("validity", model, "ok")
        fail = self.c.get_int("validity", model, "fail")
        n = ok + fail
        return (ok / n if n else None), n

    def prefer(self, primary: str, alternate: str | None) -> str:
        """Which model Auto should try first right now."""
        if self.is_open(primary) and alternate and not self.is_open(alternate):
            return alternate
        if not alternate:
            return primary
        p, pn = self.validity(primary)
        a, an = self.validity(alternate)
        if pn >= MIN_SAMPLE and an >= MIN_SAMPLE and p is not None and a is not None:
            if a - p >= STEER_MARGIN:
                return alternate
        return primary

    # -- dispatch ----------------------------------------------------------
    def dispatch_planning(self, question: str, turn: int, has_previous: bool,
                          primary: str, alternate: str | None) -> Dispatch:
        """Before planning: cache, delta or full, and which model first."""
        reasons: list[str] = []
        if self.cached_plan(question, turn) is not None:
            planner = "cache"; reasons.append("identical question seen before; planner skipped")
        elif has_previous:
            planner = "delta"; reasons.append("follow-up; only the changed fields are planned")
        else:
            planner = "full"
        model = self.prefer(primary, alternate)
        if model != primary:
            reasons.append(f"{model.split('/')[-1]} first: primary is rate limited or producing "
                           "fewer valid plans right now")
        return Dispatch(planner=planner, composer="llm", anomaly=False, model=model, reasons=reasons)

    def dispatch_answering(self, plan, evidence, d: Dispatch) -> Dispatch:
        """After the figure is verified: template or model, and any extra agent."""
        reasons = list(d.reasons)
        grouped = bool(evidence.breakdown)
        intent = plan.intent.value
        if not grouped and intent in TEMPLATE_INTENTS and plan.compare_to is None:
            composer = "template"
            reasons.append("single verified figure; templated sentence, no model call")
        else:
            composer = "llm"
        anomaly = intent in ANOMALY_INTENTS and plan.vendor_id is not None and plan.date_range is not None
        if anomaly:
            reasons.append("vendor with a period; anomaly check spawned")
        return Dispatch(planner=d.planner, composer=composer, anomaly=anomaly, model=d.model, reasons=reasons)

    # -- scoring -----------------------------------------------------------
    def score(self, response) -> Verdict:
        ev = response.evidence
        calls = response.model_usage or []
        tokens = sum(c.get("prompt_tokens", 0) + c.get("completion_tokens", 0) for c in calls)
        ok_models = [c["model"] for c in calls if c.get("ok")]
        switched = len(set(ok_models)) > 1
        notes: list[str] = []
        s = 0.0
        state = response.state.value

        if state == "answer" and ev is not None:
            s += 0.4
            verified = all(c.passed for c in ev.verification.checks if c.severity == "blocking")
            s += 0.2 if verified else 0.0
            if ev.confidence:
                s += 0.2 * ev.confidence.score
            if not verified:
                notes.append("blocking verification failed")
        else:
            verified = False
            # A correct refusal is a good outcome; an error is not.
            s += 0.5 if state in {"clarification_required", "data_unavailable", "out_of_scope"} else 0.0
            if state == "error":
                notes.append("run errored")

        # Efficiency: two calls and under ~1.5k tokens is the target shape.
        if tokens and tokens <= 1500:
            s += 0.1
        elif tokens > 3000:
            notes.append(f"{tokens} tokens, above budget")
        if len(calls) <= 2:
            s += 0.1
        elif switched:
            notes.append("needed a second model")
        # One plain sentence a person can read in a list.
        if state == "answer":
            reason = "verified answer" if verified else "answer with a failed check"
        elif state == "error":
            msg = (response.message or "").lower()
            reason = ("providers rate limited, nothing guessed" if "rate limited" in msg
                      else "could not build a valid query" if "query" in msg
                      else "error")
        elif state == "out_of_scope":
            reason = "refused: not about the financial records"
        elif state == "data_unavailable":
            reason = "refused: the data cannot answer it"
        elif state == "clarification_required":
            reason = "asked the user to clarify"
        else:
            reason = state
        notes.insert(0, reason)
        return Verdict(score=round(min(1.0, s), 3), grounded=ev is not None, verified=verified,
                       state=state, tokens=tokens, duration_ms=response.duration_ms or 0.0,
                       model=ok_models[-1].split("/")[-1] if ok_models else None,
                       switched=switched, notes=notes)

    def record(self, response, cache_hit: str | None) -> Verdict:
        v = self.score(response)
        self.c.push("judge", "runs", value={**v.to_dict(), "cache_hit": cache_hit,
                                             "run_id": response.run_id}, keep=500)
        self.c.incr("judge", "cache", cache_hit or "miss", ttl=24 * 3600)
        return v

    def summary(self, models: list[str]) -> dict[str, Any]:
        runs = self.c.recent("judge", "runs", n=200)
        scores = [r["score"] for r in runs if isinstance(r.get("score"), (int, float))]
        hits = {k: self.c.get_int("judge", "cache", k) for k in ("plan", "answer", "miss")}
        total = sum(hits.values()) or 1
        return {
            "enabled": self.c.enabled,
            "runs_scored": len(runs),
            "avg_score": round(sum(scores) / len(scores), 3) if scores else None,
            "cache": {**hits, "hit_rate": round((hits["plan"] + hits["answer"]) / total, 3)},
            "models": {
                m.split("/")[-1]: {
                    "available": _has_key(m),
                    "plan_validity": (lambda r: (round(r[0], 3) if r[0] is not None else None))(self.validity(m)),
                    "samples": self.validity(m)[1],
                    "breaker_open_s": self.breaker_ttl(m),
                    "quality_open": (lambda r: r[1] >= QUALITY_SAMPLE and r[0] is not None and r[0] < QUALITY_FLOOR)(self.validity(m)),
                    "trips_last_hour": self.c.get_int("breaker_trips", m),
                } for m in models
            },
            "recent": runs[:20],
        }
