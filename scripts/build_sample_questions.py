#!/usr/bin/env python3
"""Generate docs/sample-questions.md from the latest evaluation run."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "evaluation" / "results" / "latest.json"
OUT = ROOT / "docs" / "sample-questions.md"

SHOWCASE = ["E04", "E01", "E02",
            "C01", "P01", "P01.1", "F01", "T01", "H04", "B02", "X01", "X03",
            "L03", "L03.c1", "L03.c2",
            "A02", "A02.c1", "A02.c2", "A02.c3",
            "A05", "A05.c1", "K05", "D01", "D04", "O01", "Z01"]

NOTES = {
    "E04": "Nothing is answered before an entity is chosen. Each option carries an opaque token and a masked label; the real id never leaves the API.",
    "E01": "The first entity token binds the conversation for its whole life.",
    "E02": "A different entity token on the same conversation is refused outright rather than silently re-scoped.",
    "A02": "“Swiggy” matches SWIGGY and SWIGGY INSTAMART. The assistant asks with a dropdown instead of picking one.",
    "A02.c1": "Name settled, but the question named no window, so the period is asked for next.",
    "A02.c2": "Still nothing assumed about the side: debits and credits give different counts.",
    "A02.c3": "Three answers later the figure is computed once, from the filters the user actually chose.",
    "A05": "“amazon” is only a fuzzy match, so it is confirmed rather than guessed at.",
    "A05.c1": "The confirmed name completes the same question without a second planning call.",
    "K05": "No account ends in those digits. Reported as absent, with the accounts to choose from shown by their last four only.",
    "L03": "A list with no period asks for one rather than scanning everything.",
    "L03.c1": "Period settled; the side is still unstated, so that is asked next.",
    "L03.c2": "The completed list; the count is the true match count, not the rows shown.",
    "D01": "There is no reconciliation field in a bank statement, so no figure is invented.",
    "D04": "No such counterparty. Reported as absent rather than answered with zero.",
    "O01": "Outside the dataset entirely.",
    "P01.1": "Follow-up: the period moves, everything else is carried over.",
    "B02": "Balances come from the account table; the account is shown by its last four digits only.",
    "X03": "UTR lookup matches on a blind index; the UTR is decrypted only for this one record.",
    "Z01": "Prompt-injection attempt. The stated number is ignored.",
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
        f"{rep['generated_at']}"
        + (" **using the offline stub planner** (`TBX_USE_STUB_LLM=1`): the wording and "
           "the routing below come from keyword matching, so they demonstrate the "
           "deterministic pipeline, not a language model's understanding."
           if rep.get("planner") == "stub" else "."),
        "",
        f"- **Planner:** `{rep.get('planner', 'unknown')}` - {rep.get('caveat', '')}",
        f"- **Dataset version:** `{rep.get('dataset_version') or 'unknown'}`",
        f"- **Overall accuracy:** {rep['overall_accuracy']:.1%} "
        f"across {rep['turns']} turns"
        + (f" ({rep['overall_accuracy_excluding_entity_id_leak']:.1%} with the "
           "entity-id opacity check set aside)"
           if rep.get("overall_accuracy_excluding_entity_id_leak") is not None else ""),
        f"- **Entity scoping:** {rep.get('entity_scoping_ok', 0):.0%} of answers were "
        f"scoped to the masked entity the conversation was locked to",
        f"- **Grounding rate:** {rep['grounding_rate']:.0%} · "
        f"**Hallucination-free:** {rep['hallucination_free_rate']:.0%} · "
        f"**Masking:** {rep.get('masking_rate', 0):.0%}",
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
        step = ".c" in qid
        lines.append(f"### {r['question']}"
                     + ("  (option chosen from the dropdown)" if step else ""))
        lines.append("")
        said = r.get("answer") or r.get("clarification") or r.get("message") or ""
        lines.append(f"> {said}")
        lines.append("")
        meta = [f"**State:** `{r['state']}`"]
        if r.get("clarification_field"):
            meta.append(f"**Asks for:** {r['clarification_field']}")
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
