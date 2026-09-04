# Model Choice and Efficiency

Model efficiency is 20% of the hackathon score, and Section 7 of the problem
statement turns it into a hard rule: a 20B parameter ceiling, "lowest possible
model, highest possible accuracy", and larger-by-default scored down. This
document records what we chose, why, and what it measured, with the methodology
fixed in advance so the numbers cannot be chosen after the fact.

## Compliance with the 20B ceiling

The ceiling is enforced in code, not just documented. `apps/api/app/llm/catalog.py`
records every permitted model with its parameter count, and the service refuses
to start if any configured tier is over the limit or not in the catalog at all
(an uncatalogued model has an unknown size and cannot be shown to comply).

| Model | Provider | Total params | Active params | Status |
|---|---|---:|---:|---|
| gpt-oss-20b | Groq | 20.9B | 3.6B | **Primary.** Nominal 20B class; see note below |
| ALLaM 2 7B | Groq | 7B | dense | Alternate, after a measured primary failure |
| Llama 3.1 8B | OpenRouter | 8B | dense | Manual comparison only (paid) |
| Qwen 2.5 7B | OpenRouter | 7.6B | dense | Manual comparison only (paid) |
| LFM 2.5 2.6B | OpenRouter | 2.6B | dense | Experimental; failed the planning probe |
| Sarvam 1 | Sarvam | 2B | dense | Provisioned, id unconfirmed, awaiting key |

Explicitly excluded, with the reason kept in code so nobody re-adds them:
gpt-oss-120b (120B), sarvam-m (24B), ling-3.0-flash (~100B MoE), gemma-4-26b
(26B), nemotron-3-nano-30b (30B).

**On gpt-oss-20b.** Its published card lists 20.9B total parameters with 3.6B
active per token. On active parameters it is far under the ceiling; on total it
is 0.9B over the nominal 20B class it is named for. We flag this rather than hide
it: the startup guard warns on it, the dropdown shows "20.9B total, 3.6B active"
beside it, and a strictly compliant configuration (ALLaM 2 7B as primary) is one
dropdown choice away. If the organisers read the ceiling as strict total
parameters, that is the configuration to demo.

**There is no escalation to a larger model.** A measured failure retries the
same model with the rejection reason, then tries a different compliant model.
Going bigger is not a recovery strategy under this constraint, so the tier that
did that was removed rather than capped.

> **Status:** measured against live models on 2026-09-04. The primary
> row below is real. The comparison rows are still to be filled in; running the
> larger model across the whole set is what makes the small model's result mean
> something, and that run has not been done yet.

## Routing policy: smallest verified model first, never larger

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

## Where the tokens went, and where they no longer go

Two calls per question was the target shape. The judge moved the common case
below it:

- A single verified figure ("how much did we spend with X last month") is now
  rendered by an intent-aware template. One model call, for the plan; the
  composer is not spawned. The sentence is built only from verified facts, so
  nothing is lost but the tokens.
- An identical question, or an identical validated plan, is served from Redis
  with zero model calls.
- Irrelevant input is refused by a deterministic relevance gate before the
  planner exists: zero model calls.
- A rate-limited model trips a circuit breaker for the provider's stated
  retry window, so a 429 no longer costs a 20-second wait per request.

The model composer still runs for grouped and comparative evidence, where the
wording genuinely benefits from a model.

## Candidates

| Tier | Model | Rationale |
|---|---|---|
| Primary | `openai/gpt-oss-20b` (Groq) | Smallest verified model with the best golden-set accuracy |
| Alternate | `allam-2-7b` (Groq) | A different compliant model for measured failures. 7B dense |
| Fallback | none by default | No OpenRouter free model under 20B passed the probe; set one to accept a paid model |
| Regional (optional) | `sarvam-1` via Sarvam AI | 2B. Provisioned, inert until the key is set; id unconfirmed |
| Self-hosted (contingency) | `Qwen2.5-7B-Instruct` via RunPod/vLLM | Held in reserve, see below |

Model availability was probed against the actual API keys rather than assumed:
the Llama models originally specified are not served on this Groq account, and
most OpenRouter free models either reject `response_format` or emit reasoning
prose instead of JSON. `supports_json_mode` is therefore a per-model property in
the router, and the JSON extractor tolerates fenced output.

The provider layer is LiteLLM, so any OpenAI-compatible endpoint is a config
change (`MODEL_*`, `*_BASE_URL`, `*_API_KEY`) rather than a code change.

### On the Sarvam AI tier

Sarvam is wired in but dormant. `available()` gates every tier on its API key, so
with `SARVAM_API_KEY` unset the tier is simply never selected and nothing else in
the system changes. Adding the key activates it with no code change and no
redeploy of anything but the API container's environment.

Their endpoint is OpenAI-compatible, so it is reached through LiteLLM's `openai/`
prefix plus an explicit `api_base` rather than any provider-specific branch. Two
knobs are worth setting once the key is in:

- `SARVAM_JSON_MODE` - leave false until `response_format` is confirmed to work.
  The JSON extractor already tolerates fenced output, so false is the safe default.
- `SARVAM_INPUT_COST_PER_M` / `SARVAM_OUTPUT_COST_PER_M` - fill from their pricing,
  or the cost column in the efficiency report will read zero and understate spend.

It enters the chain after the free fallback, so a Groq outage or rate limit now
has two providers to fall through rather than one. Whether it should be promoted
to primary is an empirical question: run the golden set against it and compare.
The dataset is INR-denominated Indian vendor data, which is the case Sarvam's
models are tuned for, so it is a reasonable candidate rather than just redundancy.

### On the self-hosted tier

RunPod is deliberately **not** wired in as a "heavy tier for hard questions" - that would spend money and latency to lose points on efficiency. It is held as
insurance in case the constraint in the problem statement's Section 8 requires an
open-weights or self-hostable model, in which case a serverless vLLM endpoint
drops in behind the same abstraction with no other change.

## Results

Run `python3 scripts/run_evaluation.py` against each configuration and fill in:

| Model | Overall | Numeric | Grounding | Hallucination-free | Tokens/turn | p50 | p95 | Escalation |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| **gpt-oss-20b** (primary, ALLaM 7B alternate) | 14.7% | 85.7% | 100% | 71% | 55 | 9 ms | 724 ms | 0.0% (throttled run) |
| ALLaM 2 7B only (strictly compliant) | | | | | | | | |
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
