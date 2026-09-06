"""Operational metrics: run-level counters for tokens, cost, latency and model switching."""
from __future__ import annotations

import json
import os
from collections import Counter
from pathlib import Path
from typing import Any

from fastapi import APIRouter

from ...state import app_state

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])

def _eval_report_path() -> Path:
    """Locate the evaluation report.

    TBX_EVAL_REPORT wins; otherwise walk upward for an evaluation/results
    directory, since the package sits at a different depth inside the container.
    """
    env = os.getenv("TBX_EVAL_REPORT")
    if env:
        return Path(env)
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "evaluation" / "results" / "latest.json"
        if candidate.parent.is_dir():
            return candidate
    return Path("/evaluation/results/latest.json")


EVAL_REPORT = _eval_report_path()


@router.get("/usage")
async def usage() -> dict[str, Any]:
    """Aggregate the usage ring buffer.

    escalation_rate keeps its name for report continuity but counts runs that
    needed a second model; there is no larger tier.
    """
    runs = app_state.usage_log
    if not runs:
        return {"runs": 0}

    tiers = Counter(c["tier"] for r in runs for c in r["calls"])
    tokens = sum(c["prompt_tokens"] + c["completion_tokens"] for r in runs for c in r["calls"])
    cost = sum(c["cost_usd"] for r in runs for c in r["calls"])
    latencies = sorted(r["duration_ms"] for r in runs if r.get("duration_ms"))
    escalated = sum(1 for r in runs
                    if any(c["tier"] in ("alternate", "fallback", "regional") and c["ok"]
                           for c in r["calls"]))

    def pct(p: float) -> float:
        if not latencies:
            return 0.0
        return round(latencies[min(len(latencies) - 1, int(len(latencies) * p))], 1)

    return {
        "runs": len(runs),
        "total_tokens": tokens,
        "avg_tokens_per_run": round(tokens / len(runs), 1),
        "total_cost_usd": round(cost, 6),
        "avg_cost_per_run_usd": round(cost / len(runs), 8),
        "llm_calls_per_run": round(sum(len(r["calls"]) for r in runs) / len(runs), 2),
        "escalation_rate": round(escalated / len(runs), 4),
        "small_model_share": round(tiers["primary"] / max(sum(tiers.values()), 1), 4),
        "latency_p50_ms": pct(0.5),
        "latency_p95_ms": pct(0.95),
        "states": dict(Counter(r["state"] for r in runs)),
        "tier_calls": dict(tiers),
        "time_split_ms": {
            "llm": round(sum(r.get("llm_ms", 0) for r in runs), 1),
            "query": round(sum(r.get("query_ms", 0) for r in runs), 1),
            "other": round(sum(r.get("other_ms", 0) for r in runs), 1),
        },
        "recent": [
            {k: r.get(k) for k in ("run_id", "state", "duration_ms", "llm_ms",
                                   "query_ms", "tokens", "model", "switched", "at")}
            for r in runs[-40:]
        ],
    }


@router.get("/evaluations")
async def evaluations() -> dict[str, Any]:
    """Re-resolve the report path each call; it is usually written after the API starts."""
    report = _eval_report_path()
    if not report.exists():
        return {"available": False,
                "hint": "Run scripts/run_evaluation.py to measure accuracy, grounding "
                        "and efficiency against the golden question set."}
    latest = json.loads(report.read_text())
    clean_path = report.parent / "last-clean.json"
    clean = json.loads(clean_path.read_text()) if clean_path.exists() else None
    if clean is None and not latest.get("throttled"):
        clean = latest
    return {"available": True, **latest, "last_clean": clean}


@router.get("/health")
async def health() -> dict[str, Any]:
    ch_ok = bool(app_state.ch and app_state.ch.ping())
    return {
        "mysql": "up" if ch_ok else "down",
        "dataset_loaded": app_state.ready,
        "dataset_version": app_state.ctx.dataset_version if app_state.ctx else None,
        "conversations_in_memory": len(app_state.conversations),
    }


@router.get("/judge")
async def judge() -> dict[str, Any]:
    """Cache hit rate, per-model plan validity, open breakers and recent verdicts."""
    if not app_state.judge:
        return {"enabled": False}
    models = app_state.router.configured_models() if app_state.router else []
    return app_state.judge.summary(models)
