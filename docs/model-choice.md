# Model Choice and Efficiency

Model efficiency is 20% of the hackathon score. This document records what we
chose, why, and what it measured - with the methodology fixed in advance so the
numbers cannot be chosen after the fact.

> **Status:** measured against live models on 2026-09-04. The primary
> row below is real. The comparison rows are still to be filled in; running the
> larger model across the whole set is what makes the small model's result mean
> something, and that run has not been done yet.

## Routing policy: small model first, escalate only on measured failure

The obvious design - "send hard questions to a bigger model" - optimises against
the thing being scored. We invert it:

- **Default:** the smallest model that passes the golden set, for both the
  planner and the composer.
- **Escalation happens only after an observed failure**, never a guess about
  difficulty:
 - the planner returned JSON that would not validate against `FinanceQueryPlan`, or
 - the composer's draft was rejected twice by the grounding check.
- **Fallback** (a different provider, same size class) covers transport failure,
  and never silently upgrades model size.

Because escalation is triggered by a concrete event, the **escalation rate is a
measured number**, reported per run at `/api/v1/admin/usage` and in every
evaluation report. That is the honest version of "we used a small model".

## Why the work is small-model shaped

Most of the burden that usually forces a large model has been moved out of the
model entirely:

| Task | Who does it |
|---|---|
| Arithmetic and aggregation | ClickHouse |
| Entity resolution | Deterministic resolver (`services/resolver.py`) |
| Date interpretation | Deterministic resolver, anchored to the dataset |
| Choosing tables, joins, filters | Query compiler, from a closed vocabulary |
| Checking the result | Verification engine |
| Deciding confidence | Computed from data-quality signals |
| Stating the figure | Server-side placeholder interpolation |

What remains for the model is: map a sentence onto a small enum-shaped object,
and write one or two sentences containing placeholders. Both are well within an
8B model's reach - which is the argument for the routing policy above, and the
reason the token budget stays near ~1k/turn.

## Candidates

| Tier | Model | Rationale |
|---|---|---|
| Small (default) | `openai/gpt-oss-20b` (Groq) | 20B mixture-of-experts, roughly 3.6B active per token. Open weights, JSON mode, low latency |
| Escalation | `openai/gpt-oss-120b` (Groq) | Used only after a measured small-model failure |
| Fallback | `inclusionai/ling-3.0-flash-fin:free` (OpenRouter) | Free tier by policy. Absorbs a provider outage at zero cost |
| Self-hosted (contingency) | `Qwen2.5-7B-Instruct` via RunPod/vLLM | Held in reserve, see below |

Model availability was probed against the actual API keys rather than assumed:
the Llama models originally specified are not served on this Groq account, and
most OpenRouter free models either reject `response_format` or emit reasoning
prose instead of JSON. `supports_json_mode` is therefore a per-model property in
the router, and the JSON extractor tolerates fenced output.

The provider layer is LiteLLM, so any OpenAI-compatible endpoint is a config
change (`MODEL_*`, `*_BASE_URL`, `*_API_KEY`) rather than a code change.

### On the self-hosted tier

RunPod is deliberately **not** wired in as a "heavy tier for hard questions" - that would spend money and latency to lose points on efficiency. It is held as
insurance in case the constraint in the problem statement's Section 8 requires an
open-weights or self-hostable model, in which case a serverless vLLM endpoint
drops in behind the same abstraction with no other change.

## Results

Run `python3 scripts/run_evaluation.py` against each configuration and fill in:

| Model | Overall | Numeric | Grounding | Hallucination-free | Tokens/turn | p50 | p95 | Escalation |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| **gpt-oss-20b** (primary, with 120b escalation) | 89.7% | 85.0% | 100% | 100% | 1,695 | 2559 ms | 4387 ms | 44.1% |
| gpt-oss-120b only | | | | | | | | |
| free fallback only | | | | | | | | |

Measured over 68 turns across 64 golden questions.

### What the numbers say

The three properties the challenge actually scores held perfectly: **grounding
100%**, **verification 100%**,
**hallucination-free 100%**. Not one answer stated
a figure that was not computed and verified first, and vendor resolution was
100%.

The open problem is efficiency, not accuracy. Escalation is running at
44.1% and 3.04 calls per turn
against a two-call target, so nearly half of all questions are paying for a
second, larger model. Each escalation is a *measured* failure rather than a
guess, so the rate is a real signal: it says the small model's first output is
being rejected more often than it should be. That is the next thing to fix, and
it is a prompt and schema problem before it is a model problem. Two such causes
were already found and fixed this way: an over-strict plan schema that rejected
valid grouped aggregates, and a truncated-generation path that silently emitted
literal braces.

**Reading the table:** the claim we want to support is that the *small* model is
sufficient. That is only demonstrated if the 8B row's accuracy is close to the
70B row's while its cost and latency are materially lower. Running the large
model is what makes the small model's result meaningful - a single row proves
nothing.

## Reproducing

```bash
export GROQ_API_KEY=...
# remove TBX_USE_STUB_LLM from .env first, then per configuration:
MODEL_PLANNER=groq/llama-3.1-8b-instant MODEL_COMPOSER=groq/llama-3.1-8b-instant \
  python3 scripts/run_evaluation.py --out evaluation/results/8b.json
MODEL_PLANNER=groq/llama-3.3-70b-versatile MODEL_COMPOSER=groq/llama-3.3-70b-versatile \
  python3 scripts/run_evaluation.py --out evaluation/results/70b.json
```

Each report records the planner it ran against, so a stub run can never be
mistaken for a model run.
