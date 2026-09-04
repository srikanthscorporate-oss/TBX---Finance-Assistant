#!/usr/bin/env python3
"""Rewrite the headline metrics in README.md and docs/model-choice.md from the
latest evaluation report, so the documents can never quote a number the report
does not hold. A throttled run is labelled as such rather than presented as the
pipeline's accuracy.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "evaluation" / "results" / "latest.json"


def main() -> int:
    r = json.loads(REPORT.read_text())
    e = r["efficiency"]
    throttled = bool(r.get("throttled"))
    tag = (" **This run was throttled by provider rate limits and understates the pipeline;"
           " a clean re-run is pending.**" if throttled else "")

    readme = ROOT / "README.md"
    s = readme.read_text()
    if throttled:
        # Do not quote a quota event as if it were a measurement.
        para = (f"Measured over {r['turns']} turns of a {r['questions']}-question golden set against\n"
                f"live models: **no clean measurement is on disk.** The last run on "
                f"{r['generated_at'][:10]} was throttled by provider rate limits "
                f"({r.get('rate_limited_calls', 0)} of {r['turns']} turns refused before any model "
                f"call), so its scores are a quota event, not the pipeline. The evaluation "
                f"re-runs automatically once quota recovers. "
                f"See [docs/model-choice.md](docs/model-choice.md).")
    else:
        para = (f"Measured over {r['turns']} turns of a {r['questions']}-question golden set against\n"
            f"live models on {r['generated_at'][:10]}: **grounding {r['grounding_rate']:.0%}**, "
            f"**hallucination-free\n{r['hallucination_free_rate']:.0%}**, **verification "
            f"{r['verification_pass_rate']:.0%}**,\nvendor resolution {r['vendor_resolution_accuracy']:.0%}, "
            f"overall\n{r['overall_accuracy']:.1%}, {e['avg_llm_calls_per_turn']} model calls and "
            f"{e['avg_tokens_per_turn']:.0f} tokens per turn.{tag} "
            f"See [docs/model-choice.md](docs/model-choice.md).")
    if throttled:
        row_note = " (throttled run)"
    new, n = re.subn(r"Measured over \d+ turns of a \d+-question golden set against\n.*?See \[docs/model-choice\.md\]\(docs/model-choice\.md\)\.",
                     para, s, count=1, flags=re.S)
    if not n:
        print("README headline paragraph not found; nothing changed", file=sys.stderr)
    else:
        readme.write_text(new)

    mc = ROOT / "docs" / "model-choice.md"
    t = mc.read_text()
    row = (f"| **gpt-oss-20b** (primary, ALLaM 7B alternate) | {r['overall_accuracy']:.1%} | "
           f"{r['numeric_accuracy']:.1%} | {r['grounding_rate']:.0%} | {r['hallucination_free_rate']:.0%} | "
           f"{e['avg_tokens_per_turn']:,.0f} | {e['latency_p50_ms']:.0f} ms | {e['latency_p95_ms']:.0f} ms | "
           f"{e['escalation_rate']:.1%}{' (throttled run)' if throttled else ''} |")
    new_t, m = re.subn(r"\| \*\*gpt-oss-20b\*\* \(primary, ALLaM 7B alternate\) \|.*", row, t, count=1)
    if m:
        mc.write_text(new_t)
    print(f"refreshed: overall {r['overall_accuracy']:.1%}, grounding {r['grounding_rate']:.0%}, "
          f"{e['avg_llm_calls_per_turn']} calls/turn, throttled={throttled}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
