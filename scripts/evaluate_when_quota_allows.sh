#!/usr/bin/env bash
# Run the golden evaluation only when the model provider is actually answering.
#
# A rolling trip counter is not a quota signal (it expires on its own clock).
# This probes with ONE real request, requires it to succeed twice a few minutes
# apart, then runs the evaluation; if the run still comes back throttled it
# backs off and tries again, up to a limit. Then it refreshes the docs and
# records the gate ledger in the same shell so approvals bind.
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
export TBX_API="${TBX_API:-http://127.0.0.1:8010}"
MAX_ATTEMPTS="${MAX_ATTEMPTS:-8}"
# Groq's free tier allows 8,000 tokens per minute on gpt-oss-20b, refilled
# continuously at about 133 tokens a second. A turn bursts roughly 3,300
# tokens across its calls in a few seconds, so the bucket needs about 25
# seconds to recover before the next turn or the primary trips its breaker
# and the weaker alternate answers instead. The pace keeps the run clean.
export EVAL_PACE_S="${EVAL_PACE_S:-24}"

probe() {   # 0 when a real model call succeeded (a nonce defeats the answer cache)
  curl -sS -m 60 -X POST "$TBX_API/api/v1/chat" -H 'content-type: application/json' \
    -d "{\"message\":\"How many transactions were there last month? (probe $RANDOM$RANDOM)\",\"model\":\"auto\"}" \
  | python3 -c 'import json,sys; r=json.load(sys.stdin); ok=any(u.get("ok") for u in r.get("model_usage",[])); sys.exit(0 if ok and "rate limited" not in (r.get("message") or "").lower() else 1)'
}

attempt=0
while [ "$attempt" -lt "$MAX_ATTEMPTS" ]; do
  attempt=$((attempt + 1))
  until probe; do echo "$(date +%H:%M:%S) provider throttled; probing again in 15m"; sleep 900; done
  echo "$(date +%H:%M:%S) probe ok; confirming the window holds"; sleep 180
  if ! probe; then continue; fi
  echo "$(date +%H:%M:%S) running the evaluation (attempt $attempt)"
  node scripts/verify/eval.mjs 2>&1 | tail -6
  if python3 -c 'import json,sys; r=json.load(open("evaluation/results/latest.json")); sys.exit(1 if r.get("throttled") else 0)'; then
    echo "$(date +%H:%M:%S) clean run recorded"
    for g in states sse multiturn judge; do sleep 30; echo "  $(node scripts/verify/$g.mjs 2>&1 | tail -1)  <- $g"; done
    python3 scripts/refresh_readme_metrics.py; python3 scripts/build_sample_questions.py
    node "$HOME/.claude/skills/unlazy/scripts/gate-check.mjs" --approve GATES.md 2>&1 | grep -E "HANDOFF|met:|UNMET"
    exit 0
  fi
  echo "$(date +%H:%M:%S) run was throttled; backing off 30m"; sleep 1800
done
echo "gave up after $MAX_ATTEMPTS attempts"; exit 1
