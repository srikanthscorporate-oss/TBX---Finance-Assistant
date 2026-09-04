#!/usr/bin/env python3
"""Generate docs/sample-questions.md from an actual evaluation run.

A submission requirement asks for "sample questions and the corresponding
answers produced by the assistant". Generating this from the real run means the
document cannot drift from what the system actually does.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "evaluation" / "results" / "latest.json"
OUT = ROOT / "docs" / "sample-questions.md"

SHOWCASE = ["V01", "T01", "T01.1", "R01", "R03", "G02", "E01",
            "A01", "M01", "O01", "M06", "X01"]

NOTES = {
    "A01": "Two vendors match “Acme”. The assistant refuses to pick one.",
    "M01": "The dataset has no GST column, so no figure is invented.",
    "O01": "Outside the dataset entirely.",
    "M06": "No such vendor. Reported as absent rather than answered with zero.",
    "T01.1": "Follow-up: the period moves, the vendor is carried over.",
    "X01": "Prompt-injection attempt. The stated number is ignored.",
}


def main() -> int:
    if not REPORT.exists():
        raise SystemExit("run scripts/run_evaluation.py first")
    rep = json.loads(REPORT.read_text())
    by_id = {r["id"]: r for r in rep["results"]}

    lines = [
        "# Sample Questions and Answers",
        "",
        f"Produced by an actual run of the golden evaluation set on "
        f"{rep['generated_at']}.",
        "",
        f"- **Planner:** `{rep.get('planner', 'unknown')}` - {rep.get('caveat', '')}",
        f"- **Overall accuracy:** {rep['overall_accuracy']:.1%} "
        f"across {rep['turns']} turns",
        f"- **Grounding rate:** {rep['grounding_rate']:.0%} · "
        f"**Hallucination-free:** {rep['hallucination_free_rate']:.0%}",
        "",
        "Every figure below was computed by a database query and verified before "
        "it was rendered. See [architecture](../README.md#how-a-figure-is-produced).",
        "",
        "---",
        "",
    ]

    for qid in SHOWCASE:
        r = by_id.get(qid)
        if not r:
            continue
        lines.append(f"### {r['question']}")
        lines.append("")
        said = r.get("answer") or r.get("clarification") or r.get("message") or ""
        lines.append(f"> {said}")
        lines.append("")
        meta = [f"**State:** `{r['state']}`"]
        if r.get("period"):
            meta.append(f"**Period:** {r['period']}")
        if r.get("record_count"):
            meta.append(f"**Records:** {r['record_count']:,}")
        if r.get("confidence"):
            meta.append(f"**Confidence:** {r['confidence']}")
        meta.append(f"**Latency:** {r['latency_ms']:.0f} ms")
        lines.append(" \u00b7 ".join(meta[:2]) + ("  " + "  ".join(meta[2:]) if len(meta) > 2 else ""))
        if qid in NOTES:
            lines.append("")
            lines.append(f"> {NOTES[qid]}")
        lines.append("")
        lines.append("---")
        lines.append("")

    lines += [
        "## Accuracy by category",
        "",
        "| Category | Passed | Total | Accuracy |",
        "|---|---:|---:|---:|",
    ]
    for cat, c in rep["by_category"].items():
        lines.append(f"| {cat} | {c['passed']} | {c['total']} | {c['accuracy']:.0%} |")

    e = rep["efficiency"]
    lines += [
        "",
        "## Efficiency",
        "",
        "| Metric | Value |",
        "|---|---:|",
        f"| LLM calls per turn | {e['avg_llm_calls_per_turn']} |",
        f"| Tokens per turn | {e['avg_tokens_per_turn']:,.0f} |",
        f"| Escalation rate | {e['escalation_rate']:.1%} |",
        f"| Latency p50 | {e['latency_p50_ms']:.0f} ms |",
        f"| Latency p95 | {e['latency_p95_ms']:.0f} ms |",
        "",
    ]

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines))
    print(f"wrote {OUT.relative_to(ROOT)} ({len(SHOWCASE)} showcased questions)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
