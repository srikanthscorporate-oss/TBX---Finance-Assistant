# StrawHat Finance Assistant

A conversational assistant over bank statement data. Ask in plain language about
spend, receipts, counterparties, balances, or a reference or UTR, and get an
answer with the records behind it.

**The organising principle: the language model does not own financial truth.**
It reads the question and writes the sentence. Every number comes from a
database query, is verified before it is shown, and is traceable back to source
records. When the data cannot support an answer, the assistant says so.

Built for the TBX - BVP Tech Catalyst Hackathon.

Measured over 74 turns of a 64-question golden set against
the offline stub planner on 2026-09-05 (deterministic pipeline only; no live-model
run exists yet for the bank schema): overall 90.5%, grounding 100%, hallucination-free 100%, masking 100%. See [docs/model-choice.md](docs/model-choice.md).

---

## How a figure is produced

```
question
   ↓  LLM call 1 - emits a typed FinanceQueryPlan (never SQL, never a number)
Pydantic validation      closed enums; unknown fields rejected
   ↓
counterparty resolution  deterministic; ambiguity → ask, not guess
account resolution       by last four digits; two matches → ask
date resolution          relative periods anchored to the DATASET, not today
                         (a list with no period → ask, with a period dropdown)
   ↓
query compiler           allowlisted identifiers, bound parameters only
   ↓
ClickHouse               read-only credentials, statement timeout, row cap,
                         entity_id bound on every query
   ↓
verification             blocking checks veto the answer entirely
confidence               computed from data-quality signals, not self-report
evidence package         facts, breakdown, SQL, params, records (UTR decrypted here,
                         account numbers masked to the last four)
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

Every question terminates in exactly one. A non-answer state never carries a
figure or evidence; a clarification carries a dropdown (`clarification.field`
is `counterparty`, `account`, `date_range` or `guided`) and is answered by
sending the chosen option as `resolved_value` on the same `conversation_id`:

| State | When | Example |
|---|---|---|
| `answer` | Data supports it and verification passed | "You spent ₹6,061,435.07 with SWIGGY INSTAMART in July 2026, across 46 transactions." |
| `clarification_required` | Genuinely ambiguous | "“Swiggy” matches 2 names in your transactions. Which one do you mean?" (SWIGGY / SWIGGY INSTAMART) |
| `data_unavailable` | Financial question, absent field | "The records hold bank transactions, accounts and banks, but nothing about reconciliation…" |
| `out_of_scope` | Not answerable from the dataset | "Your input isn't relevant to the services we provide…" |
| `error` | Something failed | "The database could not be queried. I won't guess at the figure." |

See [docs/sample-questions.md](docs/sample-questions.md) for real output.

---

## Quick start

Prerequisites: Docker and Docker Compose. Nothing else - no API key is needed
for the offline demo. `.env` must carry `TBX_DATA_KEY` (32 bytes as 64 hex
characters); the loader refuses to run without it because account numbers and
UTRs are encrypted before they reach ClickHouse.

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
python3 -c "import os;print(os.urandom(32).hex())"    # -> TBX_DATA_KEY in .env
python3 scripts/generate_bank_dataset.py --out data/raw --rows 200000   # stand-in data
docker compose up -d clickhouse mysql redis
TBX_DATA_KEY=... python3 scripts/load_dataset.py     # ingest, encrypt, validate
docker compose up -d --build api web nginx
open http://localhost:8080
```

`infra/clickhouse/004_entity_scoping.sql` is opt-in: it adds a ClickHouse row
policy so the read-only user can only see the entity named in a per-query
setting. It is not applied by default (multi-tenant security is out of scope
for the brief); the API already binds `entity_id` on every query regardless.

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

### The dataset

Three tables, following `docs/TBX - Database Schema.md`: `bank` (code, name),
`account` (entity, account number, program, available balance, bank) and
`transaction` (account, timestamp, debit/credit, narration, amount, reference
id, UTR). The loader also stores on each transaction its `entity_id` and
`bank_code` (copied from the account) and a `counterparty` and `channel`
(NEFT/IMPS/UPI/FT/RTGS/CHEQUE/CHARGES/INTEREST/OTHER) parsed from the narration
by `apps/api/app/services/narration.py`, so name matching never runs on free
text at query time.

Drop the provided CSVs (`bank.csv`, `account.csv`, `transaction.csv`) into
`data/raw/` and run `python3 scripts/load_dataset.py` with `TBX_DATA_KEY` set.
If their column names differ, adjust **`TABLES` in `scripts/load_dataset.py`** -
that map is the only place the schema is named. The loader refuses to import a
file with missing required columns rather than loading partial data.

Everything downstream re-derives itself from what was loaded: the dataset's date
bounds, entities, accounts, counterparties, banks and currency are read from the
database at startup, which is why relative periods stay anchored to the data. A
conversation is scoped to one entity and stays there for its whole life.

### Entity scoping

Nothing is answered before an entity is chosen. The browser never sees a raw
entity id: `/api/v1/entities` returns an AES-256-GCM token per entity plus a
masked label (`********…7555`), the chat request carries the token back as
`entity_id`, and `apps/api/app/services/entity_token.py` decrypts it before the
compiler binds it. The masked form is what appears in evidence and in the UI.

The first token seen on a conversation binds it. A different token arriving on
the same conversation is refused with

> I don't have any Idea what you're talking about.

and an instruction to clear the history and select the entity ID again, because
the earlier turns and any parked plan belong to the first entity. The web UI
enforces the same rule: it prompts for an entity on first load, remembers the
choice and the transcript across reloads, and refuses a switch until
**Clear History** (top right) resets both, server-side and in the browser.

### The assistant asks rather than assumes

A figure that depends on an unstated choice is never guessed. One question per
turn, answered from a dropdown:

| Unstated | Question |
|---|---|
| entity | Whose records should I read? |
| ambiguous or inexact counterparty | Which one do you mean? |
| two accounts sharing the last four digits | Which account? |
| no period on a period-sensitive intent | Which period should I look at? |
| debit or credit not stated | Money out, money in, or both? |

"How much did I **spend** with Zomato" states the side, so only the period is
asked. A balance or a reference lookup is asked for neither.

### Sensitive fields

`account_number` and `utr_number` are plaintext in the CSV and never plaintext
in the database:

- **AES-256-GCM at rest.** `apps/api/app/services/crypto.py` encrypts both with
  `TBX_DATA_KEY` during load (`account_number_enc`, `utr_enc`), a fresh nonce
  per value. The key lives only in the API's environment; it never enters SQL.
- **Blind index for UTR lookup.** A UTR question is answered by equality on
  `utr_hash`, an HMAC-SHA256 of the normalised UTR under a key derived from the
  data key. The plaintext UTR is never a query parameter and the evidence panel
  shows the hash truncated.
- **Decrypt only in the API, only when asked.** The evidence builder decrypts a
  UTR for the record the user looked up. Account numbers are never decrypted
  for display: the loader stores `account_last4` and every response shows
  `XXXXXX1234`. `tests/encryption_at_rest.py` reads the stored rows and proves
  the ciphertext differs from, and decrypts to, the CSV values.

### Bringing your own MySQL database

The **Data Source** page (right of Observability) takes a live MySQL endpoint -
a link such as `mysql://user:password@host:3306/db`, optionally with the port,
database, user and password fields alongside it (they override the link, and a
link carrying everything connects on its own) - and:

1. validates it (a live, readable endpoint with rows shows **Data Available**),
2. lists every table with row counts and a preview you can page through,
3. shows how the tables map onto the assistant's canonical schema, and
4. on **Start Initializing**, ingests them into ClickHouse and points the chat at
   the result.

The mapping (`apps/api/app/services/source_mapping.py`) is a deterministic
synonym table: `txns.amt` becomes `transaction_amount`, `accounts.balance`
becomes `available_balance`, and so on. Both an account table and a transaction
table must resolve; a missing balance is reported, never defaulted to zero. The
endpoint is only ever read, credentials stay in memory, and the ingest runs
through the same encryption and narration parsing as the CSV loader, so nothing
downstream - planner, compiler, verification, evidence - changes.

Initialising loads into a **sibling database** (`tbx_finance_mysql`), never the
bundled `tbx_finance`, and only then repoints the assistant: the demo dataset
stays intact, and the test suite and verify gates - which recompute their
expected values from `data/raw/*.csv` - keep passing while your endpoint is
live. Which database is active is held in `app/services/active_db.py`, persisted
in Redis so it survives a restart, and shown on the page; **Use the bundled
dataset** (or `POST /api/v1/sources/reset`) switches back, leaving the ingested
database in place. The switch happens only after a clean load and is rolled back
if the new tables cannot be read, so a half-loaded source can never become the
thing the chatbot answers from.

To try it locally, the compose stack includes a MySQL service on
`127.0.0.1:13306` (host `mysql` from inside Docker). Seed it from the bundled
CSVs with `apps/api/.venv/bin/python scripts/seed_mysql.py` and enter
`mysql://tbx:change-me-mysql@mysql:3306/tbx_app` on the page.

---

## Verifying it works

The project ships with its own acceptance ledger. Every claim below is
machine-checked:

```bash
node scripts/verify/health.mjs         # G1  API boots, reports its dataset window
node scripts/verify/chat_grounded.mjs  # G2  answer matches an independent computation
node scripts/verify/states.mjs         # G3  all four user-facing states reachable
node scripts/verify/sse.mjs            # G4  ordered streaming events
node scripts/verify/eval.mjs           # G5  golden set accuracy
node scripts/verify/multiturn.mjs      # G6  coreference across three turns
node scripts/verify/export.mjs         # G7  CSV reconciles with the answer
node scripts/verify/stack.mjs          # G9  full stack through nginx
node scripts/verify/regression.mjs     # G10 cross-check + e2e + error path
node scripts/verify/security.mjs       # G11 adversarial plans refused
node scripts/verify/scale.mjs          # G14 20M rows: integrity, latency budget, pruning
node scripts/verify/masking.mjs        # G15 no full account number in any response
node scripts/verify/clarify_flow.mjs   # G17 clarification completes the same question
```

Python suites under `apps/api/tests/` (each prints its own pass token):
`crosscheck.py` (compiler vs. a naive CSV loop), `security.py`, `error_path.py`,
`e2e_offline.py`, `judge_offline.py`, `crypto_roundtrip.py` (cipher round trip,
nonce freshness, blind-index determinism, masking; no database) and
`encryption_at_rest.py` (G16: stored ciphertext differs from and decrypts to
the CSV plaintext, no plaintext column exists).

The cross-checks recompute expected values **from the source CSVs**, by code
sharing nothing with the application (they may import the narration parser and
the cipher, both deterministic) - so they can actually fail.

### Scale: the 20M-record test

Section 7 says the prototype is tested at 20M records. That load goes into a
sibling database so it can never truncate the live dataset:

```bash
python3 scripts/generate_bank_dataset.py --out data/scale_bank --rows 20000000
TBX_DATA_KEY=... python3 scripts/load_dataset.py --raw data/scale_bank --db tbx_finance_scale --version scale-20m
node scripts/verify/scale.mjs      # G14: row count, integrity, latency budget, pruning
```

The generator and loader both stream, holding no per-row state, so memory stays
flat at 20M rows; duplicate and referential checks run inside ClickHouse after
the load. Transactions are partitioned by month and ordered by entity, account
and date, which is what lets a one-entity, one-month question read a fraction
of the table.

Measured (G14): 20,000,166 transactions loaded in 481s with
referential integrity clean and zero duplicate ids; every compiler-shaped query
answered under 210 ms at that size, and a one-month question read a single row
thanks to partition pruning. The ClickHouse container carries a small memory
profile (`infra/clickhouse/memory.xml`) because the default 90%-of-RAM ceiling
was tripped by a bulk load inside Docker Desktop.

### Evaluation

```bash
python3 scripts/build_golden_set.py    # expected values from data/raw/*.csv, default entity
python3 scripts/run_evaluation.py      # 64 questions, 74 turns, 16 categories
python3 scripts/build_sample_questions.py
```

The golden set covers spend and receipts by period (including today, yesterday
and last 7 days), counterparty sums and counts, amount and channel filters,
lists, largest transactions, top counterparties, balances, reference and UTR
lookups, follow-up pairs, ambiguous names, and refusals. Expected values are
computed by `build_golden_set.py` from the CSVs, scoped to the default entity.
A question expected to clarify is scored on the field asked for, then
auto-answered with the expected option and the completed answer scored as its
own turn.

Reports state, intent, counterparty, period and clarification accuracy, numeric
accuracy against the golden values, grounding, verification, hallucination-free
and masking rates, and efficiency (tokens/turn, escalation rate, p50/p95
latency). The report records which planner produced it - numbers from a stub
run measure the deterministic pipeline, not real NLU.

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
  cannot be normalised into a match for a different real counterparty.
- **Account numbers and UTRs encrypted at rest** (AES-256-GCM), UTR lookup by
  HMAC blind index, decryption only inside the API, account numbers shown
  masked. `entity_id` is an encrypted token from the request, never set by the
  model, decrypted server-side and bound on every query; it is shown masked and
  the raw id never leaves the API.
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
infra/           ClickHouse schema, nginx config, MySQL reference schema
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
| `TBX_DATA_KEY` | 64 hex chars. Encrypts account numbers and UTRs at load; required by the loader and the API |
| `TBX_DEFAULT_ENTITY` | Optional. Entity a conversation is scoped to when the request names none; default is the busiest |
| `QUERY_TIMEOUT_SECONDS`, `MAX_QUERY_ROWS` | Query ceilings |
| `RATE_LIMIT_PER_MINUTE` | Per-client chat limit |

## The judge

A deterministic agent that runs around every request without adding a model
call. It decides which agents a run needs and which it does not:

| Decision | Effect |
|---|---|
| Relevance gate | Input with no reference to transactions, counterparties, accounts, amounts or a period is refused before any agent exists: zero model calls, and the right pane says so |
| Plan cache | An identical question reuses its validated plan from Redis: the planner is not spawned |
| Answer cache | An identical validated plan reuses its answer and evidence: no query, no composer |
| Composer choice | A single verified figure is rendered by an intent-aware template, zero tokens; the model composer runs only for grouped or comparative evidence |
| Anomaly agent | Spawned only for a counterparty question with a period; flags a figure that is far outside that counterparty's own monthly history |
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

When the assistant asks a clarifying question, the answer is a dropdown, not
free text: the two counterparties that match "Swiggy" (with transaction counts
as hints), the accounts that share a last-four, or six periods when a list
question names none. Choosing an option completes the same question without a
second planning call.

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
- **No live-model evaluation exists yet for the bank schema.** The figures
  above were measured on the previous dataset; `evaluation/results/latest.json`
  is a stub-planner run and says so. `scripts/evaluate_when_quota_allows.sh`
  re-runs the set against a real model once provider quota recovers.
- **Narrations carry other parties' account numbers.** A NEFT or IMPS
  description names the counterparty's account, as real statements do. The
  entity's own numbers are encrypted and masked; the counterparty's, inside
  narration text, are stored and shown as written.
- The comparison rows in `docs/model-choice.md` are not filled in. One model row
  does not prove a small model was sufficient.
- Langfuse and the worker are defined in compose behind profiles and are not yet
  part of the verified path.
