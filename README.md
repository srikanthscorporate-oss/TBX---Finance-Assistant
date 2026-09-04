# StrawHat Finance Assistant

A conversational assistant for financial data. Ask in plain language about spend,
vendor payouts and reconciliation, and get an answer with the records behind it.

**The organising principle: the language model does not own financial truth.**
It reads the question and writes the sentence. Every number comes from a
database query, is verified before it is shown, and is traceable back to source
records. When the data cannot support an answer, the assistant says so.

Built for the TBX - BVP Tech Catalyst Hackathon.

Measured over 68 turns of a 64-question golden set against
live models: **grounding 100%**, **hallucination-free
100%**, **verification 100%**,
vendor resolution 100%, overall
89.7%. See [docs/model-choice.md](docs/model-choice.md).

---

## How a figure is produced

```
question
   ↓  LLM call 1 - emits a typed FinanceQueryPlan (never SQL, never a number)
Pydantic validation      closed enums; unknown fields rejected
   ↓
vendor resolution        deterministic; ambiguity → ask, not guess
date resolution          relative periods anchored to the DATASET, not today
   ↓
query compiler           allowlisted identifiers, bound parameters only
   ↓
ClickHouse               read-only credentials, statement timeout, row cap
   ↓
verification             blocking checks veto the answer entirely
confidence               computed from data-quality signals, not self-report
evidence package         facts, breakdown, SQL, params, source records
   ↓  LLM call 2 - writes prose containing {{placeholders}} only
placeholder interpolation   server substitutes verified values
   ↓
answer + evidence + confidence
```

Two model calls on the happy path. Everything between them is deterministic
Python. That is what keeps the numbers defensible, the latency low and the token
cost small.

### Why a hallucinated number is structurally impossible

The composing model is never given the opportunity to write a figure. It emits
`{{total}}`, and the server substitutes the verified value after generation.

- A placeholder with no verified fact behind it → the draft is **rejected**.
- A literal number typed anyway → caught by the digit scan and **rejected**.
- Two rejected drafts → a deterministic template built from verified values.

This converts *"we check the model's arithmetic"* into *"the model has no channel
through which to state a number we did not compute."*

### The five response states

Every question terminates in exactly one:

| State | When | Example |
|---|---|---|
| `answer` | Data supports it and verification passed | "You spent ₹7,676,465.01 with Acme Technologies in July 2026…" |
| `clarification_required` | Genuinely ambiguous | "There are 2 vendors matching 'Acme'. Which one?" |
| `data_unavailable` | Financial question, absent field | "This dataset has no GST data…" |
| `out_of_scope` | Not answerable from the dataset | "I don't have market data." |
| `error` | Something failed | "The database could not be queried. I won't guess at the figure." |

See [docs/sample-questions.md](docs/sample-questions.md) for real output.

---

## Quick start

Prerequisites: Docker and Docker Compose. Nothing else - no API key is needed
for the offline demo.

```bash
git clone <repo> && cd "Financial Assistant"
cp .env.example .env            # then add GROQ_API_KEY and OPENROUTER_API_KEY

python3 scripts/generate_synthetic_dataset.py --out data/raw   # stand-in data
docker compose up -d clickhouse postgres redis
python3 scripts/load_dataset.py                                # ingest + validate

docker compose up -d --build api web nginx
open http://localhost:8080
```

Without API keys, set `TBX_USE_STUB_LLM=1` in `.env`. That runs an offline
deterministic planner so the whole product still works for a demo. Evaluation
numbers from such a run measure the deterministic pipeline only, and every
report records which planner produced it.

### Working on the API locally

The backend uses [uv](https://docs.astral.sh/uv/). Dependencies resolve from
`uv.lock`, so a clone reproduces the exact environment:

```bash
cd apps/api
uv sync                                   # creates .venv from the lockfile
uv run uvicorn app.main:app --reload      # or: uv run pytest, uv run ruff check
```

`requirements.txt` is generated from the lock and should never be hand-edited.

### Loading the real dataset

Drop the provided CSVs into `data/raw/` and run `python3 scripts/load_dataset.py`.
If their column names differ, adjust **`TABLES` in `scripts/load_dataset.py`** - that map is the only place the schema is named. The loader refuses to import a
file with missing required columns rather than loading partial data.

Everything downstream re-derives itself from what was loaded: the dataset's date
bounds, vendor list, categories and currency are read from the database at
startup, which is why relative periods stay anchored to the data.

---

## Verifying it works

The project ships with its own acceptance ledger. Every claim below is
machine-checked:

```bash
node scripts/verify/health.mjs         # API boots, reports its dataset window
node scripts/verify/chat_grounded.mjs  # answer matches an independent computation
node scripts/verify/states.mjs         # all four user-facing states reachable
node scripts/verify/sse.mjs            # ordered streaming events
node scripts/verify/multiturn.mjs      # coreference across three turns
node scripts/verify/export.mjs         # CSV reconciles with the answer
node scripts/verify/eval.mjs           # golden set accuracy
node scripts/verify/security.mjs       # adversarial plans refused
node scripts/verify/regression.mjs     # cross-check + e2e + error path
node scripts/verify/stack.mjs          # full stack through nginx
node scripts/verify/images.mjs         # images build and run non-root
node scripts/verify/deployed.mjs       # production domain serves a grounded answer
```

The cross-checks recompute expected values **from the source CSVs**, by code
sharing nothing with the application - so they can actually fail.

### Evaluation

```bash
python3 scripts/run_evaluation.py      # 64 questions, 68 turns, 11 categories
python3 scripts/build_sample_questions.py
```

Reports state accuracy, intent accuracy, vendor resolution, numeric accuracy
against independent computation, grounding rate, hallucination-free rate, and
efficiency (tokens/turn, escalation rate, p50/p95 latency). The report records
which planner produced it - numbers from a stub run measure the deterministic
pipeline, not real NLU.

---

## Security

No end-user authentication by design (explicitly out of scope), but the data path
is locked down:

- **The model never writes SQL.** It emits a typed plan from a closed vocabulary.
- **Allowlisted identifiers.** Nothing from the plan is interpolated into SQL as
  an identifier; every value is a bound parameter. 141 assertions cover this,
  with a positive control proving the suite detects an inlined parameter.
- **Read-only database credentials** with a server-side settings profile capping
  execution time, rows read and memory (`infra/clickhouse/002_readonly_user.sql`).
- **Control characters rejected** at the contract boundary, so a crafted name
  cannot be normalised into a match for a different real vendor.
- **Admin surfaces are not on the public listener.** A source-IP allowlist would
  be useless behind a tunnel - all traffic arrives from a Docker-internal
  address - so `/api/v1/admin` returns 404 publicly and lives on an unpublished
  internal port.
- **No database ports published** in production; isolated Docker networks
  (`edge` / `app` / `data` / `observability`) mean nginx cannot reach ClickHouse.
- Containers run as non-root; agents have no shell and no arbitrary SQL.

---

## Deployment

```bash
./scripts/deploy.sh user@vps-host
```

Ships the source, builds images tagged with the commit SHA, loads the dataset if
the database is empty, starts the stack with the Cloudflare Tunnel, then **waits
for a real health check before reporting success** - and dumps logs if it never
passes. Rollback is `IMAGE_TAG=<old-sha> docker compose up -d`.

The tunnel dials outward, so the VPS needs no inbound firewall rule and no
published database port.

Requires on the server: Docker, Docker Compose, and `/opt/tbx/.env` filled in
from `.env.example` (notably `CLOUDFLARE_TUNNEL_TOKEN` and `GROQ_API_KEY`).

---

## Layout

```
apps/api/app/
  contracts/     typed plan, evidence, response, events - the shared vocabulary
  services/      compiler, dates, resolver, verification, confidence, composer
  agents/        pipeline orchestration + versioned prompt loading
  llm/           provider-agnostic router with usage accounting
  api/v1/        chat (+SSE), data/export, admin metrics
  db/            ClickHouse client - parameters never inlined
prompts/         versioned prompt templates, not string literals in code
evaluation/      golden question set and reports
scripts/         dataset generation, ingestion, evaluation, deploy, verifiers
infra/           ClickHouse schema, nginx config, Postgres init
```

## Configuration

All configuration is environment-driven; see `.env.example`. The values that
matter most:

| Variable | Purpose |
|---|---|
| `MODEL_PLANNER` / `MODEL_COMPOSER` | The small default model (`gpt-oss-20b`) |
| `MODEL_ESCALATION` | Used only after a *measured* small-model failure |
| `MODEL_FALLBACK` | Different provider, free tier only |
| `TBX_USE_STUB_LLM` | Offline deterministic planner; no API key required |
| `QUERY_TIMEOUT_SECONDS`, `MAX_QUERY_ROWS` | Query ceilings |
| `RATE_LIMIT_PER_MINUTE` | Per-client chat limit |

## Interface

Two panes. The conversation sits on the left; the right pane is a live run
inspector that shows the pipeline stage by stage as it executes: what was
resolved, what was queried, what was verified, and the evidence behind the
figure. Selecting any earlier turn loads it back into the inspector.

`/observability` is open, with no authentication, and reports token spend, cost,
latency percentiles, model tier mix and the full evaluation breakdown. These are
operational counters about the assistant, never financial records.

## Known gaps

- **Escalation is running at 44%** (3.04 LLM
  calls per turn against a two-call target). Every escalation is a measured
  small-model failure rather than a guess, so the rate is honest, but it is
  higher than it should be. Two causes have already been found and fixed this
  way; more remain.
- **Numeric accuracy is 85%.** The residual failures are
  the planner adding a date filter the question did not ask for, which narrows
  the result. Grounding is unaffected: the figures reported are correct for the
  query that was run, and every one is verified.
- The comparison rows in `docs/model-choice.md` are not filled in. One model row
  does not prove a small model was sufficient.
- Langfuse and the worker are defined in compose behind profiles and are not yet
  part of the verified path.
