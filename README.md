# StrawHat Finance Assistant

A conversational assistant for financial data. Ask in plain language about spend,
vendor payouts and reconciliation, and get an answer with the records behind it.

**The organising principle: the language model does not own financial truth.**
It reads the question and writes the sentence. Every number comes from a
database query, is verified before it is shown, and is traceable back to source
records. When the data cannot support an answer, the assistant says so.

Built for the TBX - BVP Tech Catalyst Hackathon.

Measured over 68 turns of a 64-question golden set against
live models on 2026-09-05: **grounding 100%**, **hallucination-free
100%**, **verification 100%**,
vendor resolution 100%, overall
88.2%, 0.32 model calls and 241 tokens per turn. See [docs/model-choice.md](docs/model-choice.md).

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
./start.sh                       # installs Docker if needed, loads data, starts everything
```

`start.sh` works on Ubuntu 24.04 (a bare VPS), macOS on Apple Silicon or Intel,
and Windows through Git Bash or WSL. The host needs only Docker: dataset scripts
run in a throwaway Python container and the web build happens inside its image,
so nothing else is installed on the machine. Put your keys in `.env`
(`GROQ_API_KEY`, `OPENROUTER_API_KEY`) before or after the first run; without a
key it starts with the offline stub planner so the demo still works.

```bash
./start.sh --prod     # also starts the Cloudflare tunnel (CLOUDFLARE_TUNNEL_TOKEN)
./start.sh --stop     # stop everything, keep data
./start.sh --logs     # follow api + web logs
```

The same steps by hand, if you prefer them:

```bash
cp .env.example .env
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
node scripts/verify/scale.mjs          # 20M rows: integrity, latency budget, partition pruning
```

The cross-checks recompute expected values **from the source CSVs**, by code
sharing nothing with the application - so they can actually fail.

### Scale: the 20M-record test

Section 7 says the prototype is tested at 20M records. That load goes into a
sibling database so it can never truncate the live dataset:

```bash
python3 scripts/generate_synthetic_dataset.py --out data/scale --rows 20000000
python3 scripts/load_dataset.py --raw data/scale --db tbx_finance_scale --version scale-20m
node scripts/verify/scale.mjs      # G14: row count, integrity, latency budget, pruning
```

The generator and loader both stream, holding no per-row state, so memory stays
flat at 20M rows; duplicate and referential checks run inside ClickHouse after
the load. Transactions are partitioned by month and ordered by date and vendor,
which is what lets a one-month question read a fraction of the table.

Measured (G14): 20,000,166 transactions loaded in 481s with
referential integrity clean and zero duplicate ids; every compiler-shaped query
answered under 210 ms at that size, and a one-month question read a single row
thanks to partition pruning. The ClickHouse container carries a small memory
profile (`infra/clickhouse/memory.xml`) because the default 90%-of-RAM ceiling
was tripped by a bulk load inside Docker Desktop.

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

### Images

Both services are containers: `apps/api/Dockerfile` (uv-locked Python, non-root
uid 10001) and `apps/web/Dockerfile` (Next.js standalone, non-root uid 10002),
each with a healthcheck, built by `docker compose build api web`. They are
tagged for Docker Hub under `srikanthsdocker/tbx-api` and `srikanthsdocker/tbx-web`
with the commit SHA and `latest`:

```bash
docker login -u srikanthsdocker     # once, on the publishing machine
./scripts/push_images.sh            # tags by image id, pushes sha + latest
```

`.github/workflows/publish.yml` does the same on every merge to `main`, given
`DOCKERHUB_USERNAME` and `DOCKERHUB_TOKEN` repository secrets (use an access
token, never the account password). Neither image contains `.env`, `keys.md`
or any API key; both were scanned before tagging.

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
  agents/
    pipeline.py           orchestration: what happens, in what order
    planner.py            model call one: plan, validate, escalate
    composer_agent.py     model call two: compose, retry, template fallback
    evidence_builder.py   assembling the evidence package
    suggestions.py        chart choice and follow-up prompts
    context.py            run-scoped types shared by the above
    prompts.py            versioned prompt loading
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
| `MODEL_PRIMARY` | Auto mode's first choice. Empty lets the catalog pick the smallest verified model |
| `MODEL_ALTERNATE` | A different model under 20B, used after a *measured* primary failure |
| `MODEL_FALLBACK` | Another provider, for transport failure. Empty by default |
| `MODEL_PARAM_LIMIT_B` | The parameter ceiling (default 20). Startup refuses anything over it |
| `SARVAM_API_KEY` | Optional. Activates the Sarvam AI tier when set; skipped while empty |
| `TBX_USE_STUB_LLM` | Offline deterministic planner; no API key required |
| `QUERY_TIMEOUT_SECONDS`, `MAX_QUERY_ROWS` | Query ceilings |
| `RATE_LIMIT_PER_MINUTE` | Per-client chat limit |

## The judge

A deterministic agent that runs around every request without adding a model
call. It decides which agents a run needs and which it does not:

| Decision | Effect |
|---|---|
| Relevance gate | Input with no reference to spend, vendors, payouts, reconciliation or a period is refused before any agent exists: zero model calls, and the right pane says so |
| Plan cache | An identical question reuses its validated plan from Redis: the planner is not spawned |
| Answer cache | An identical validated plan reuses its answer and evidence: no query, no composer |
| Composer choice | A single verified figure is rendered by an intent-aware template, zero tokens; the model composer runs only for grouped or comparative evidence |
| Anomaly agent | Spawned only for a vendor question with a period; flags a figure that is far outside that vendor's own monthly history |
| Circuit breaker | A rate-limited model is skipped for exactly as long as the provider asked, instead of every request paying the wait |
| Model steering | In Auto, whichever compliant model has the better recent plan-validity rate goes first; never a larger one |
| Verdicts | Every run is scored on grounding, verification, confidence, tokens and calls; the observability page shows the trend |

Keys carry the dataset version, so a reload invalidates cached answers. If
Redis is unreachable the judge degrades to no-ops and the answer is unaffected.

## Interface

Two panes. The conversation sits on the left; the right pane is a live run
inspector that shows the pipeline stage by stage as it executes: what was
resolved, what was queried, what was verified, and the evidence behind the
figure. Selecting any earlier turn loads it back into the inspector.

A model dropdown sits beside the send button. It lists only models under the
20B ceiling, from the catalog the API serves at `/api/v1/models`, with each
one's parameter count shown. **Auto** is the default: the smallest verified model
first, retried with feedback on failure, then a different compliant model, never
a larger one. Choosing a model pins it for that question; the assistant will not
silently switch away from a model you picked.

Conversation state, rate limiting, caches and the judge's memory live in Redis.
For a source-run API outside Docker use `REDIS_URL=redis://127.0.0.1:16379/0`;
the port is published on loopback only.

`/observability` is open, with no authentication, and reports token spend, cost,
latency percentiles, model tier mix and the full evaluation breakdown. These are
operational counters about the assistant, never financial records.

## Known gaps

- **The alternate model is currently quality-open.** ALLaM 2 7B has produced no
  valid plan in its last 24 attempts on this question set, so the judge skips it
  rather than spend calls on a known failure. That leaves Auto with one working
  model under the free-only policy; a throttled primary now yields an honest
  "rate limited, try again in N seconds" instead of a failed answer. A second
  compliant provider is the fix, and the Sarvam slot is wired for it.
- **Both working compliant models live on one provider.** gpt-oss-20b and ALLaM 2 7B
  are both on Groq, so an organisation-level rate limit throttles the alternate
  too, and the only free OpenRouter model under 20B did not pass the planning
  probe. When every model is throttled the assistant now says so and gives the
  retry time, rather than blaming the question; it still never guesses a figure.
  Adding a second compliant provider (Sarvam, once its key and a confirmed model
  id arrive) is the real fix.
- **The 20B ceiling is enforced at startup.** gpt-oss-20b, the primary, is
  20.9B total (3.6B active), which is the nominal 20B class but 0.9B over on a
  strict reading; it is flagged in the log and the dropdown rather than hidden,
  and ALLaM 2 7B is available as a strictly compliant primary.
- **Model switch rate was 44%** (3.04 LLM
  calls per turn against a two-call target). Every switch is a measured primary
  failure rather than a guess, so the rate is honest, but it is higher than it
  should be. Two causes have already been found and fixed this way; more remain.
  There is no larger model to escalate to any more, so a switch now costs a 7B
  call, not a 120B one.
- **Numeric accuracy is 85%.** The residual failures are
  the planner adding a date filter the question did not ask for, which narrows
  the result. Grounding is unaffected: the figures reported are correct for the
  query that was run, and every one is verified.
- The comparison rows in `docs/model-choice.md` are not filled in. One model row
  does not prove a small model was sufficient.
- Langfuse and the worker are defined in compose behind profiles and are not yet
  part of the verified path.
