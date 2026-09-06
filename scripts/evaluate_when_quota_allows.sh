#!/usr/bin/env bash
# Runs the golden evaluation once a real probe request succeeds twice a few minutes apart,
# backing off when the run still comes back throttled. Gate approval runs in the same shell.
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
export TBX_API="${TBX_API:-http://127.0.0.1:8010}"
MAX_ATTEMPTS="${MAX_ATTEMPTS:-8}"
# Groq free tier: 8,000 tokens/min on gpt-oss-20b; a turn bursts about 3,300 tokens,
# so about 25 s between turns keeps the primary's breaker from tripping.
export EVAL_PACE_S="${EVAL_PACE_S:-24}"

# Returns 0 when a real model call succeeded; the nonce defeats the answer cache.
probe() {
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
