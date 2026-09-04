> **Status, 2026-09-05.** This is the day-one review of `plan.md`, kept as written.
> Several of its recommendations were overruled or overtaken, and a reader should
> know which:
>
> - **Section 7 arrived** (20B parameter ceiling, 20M-record test). Both are now
>   enforced in code: the model catalog refuses anything over the ceiling at
>   startup, and G14 verifies 20,000,166 rows with every query under 210 ms.
> - **ClickHouse was kept** (the review suggested DuckDB) and is validated at scale;
>   DuckDB is not used anywhere, so the single-engine rule holds.
> - **The escalation tier is gone**, not capped. Recovery is retry-same-model, then
>   a different compliant model. Larger-by-default is scored down.
> - **A deterministic judge** now gates relevance, caches plans and answers in
>   Redis, chooses template versus model composition, spawns the anomaly agent,
>   and breaks circuits on rate limits. None of that adds a model call.
> - **Langfuse** is defined behind a compose profile and not part of the verified
>   path; observability is served by the app's own `/observability` page.
> - The placeholder-interpolation composer, dataset-anchored dates, vendor
>   ambiguity handling, and the golden evaluation set were all built as proposed.
>
> The sections below are unchanged from 2026-09-04.

# Plan Review & Required Changes

**Reviewed:** `problem statement.pdf`, `architecture.png`, `plan.md`, `solution-design_*.html`
**Date:** 2026-09-04
**Verdict:** Core AI design is excellent and directly targets the highest-weighted criteria. Infrastructure scope is roughly 3x what the rubric rewards and is the main risk to shipping. The HTML solution design contradicts `plan.md` in ways that must be resolved before code is written.

---

## 0. BLOCKER - Missing spec, ask the organizers today

The problem statement references **"Section 8, Assumptions and Constraints"** twice (in the Must-Have list, calling the lightweight-model constraint "a scored requirement, not a suggestion"). **The PDF ends at Section 6. Section 7 and 8 do not exist in the file we have.**

Model efficiency is **20% of the total score** and we do not have its definition. Ask before anything else:

1. What qualifies as "lightweight"? Parameter count ceiling, cost-per-query ceiling, latency ceiling, or local-hostability?
2. Is model efficiency measured per-query (tokens/cost/latency) or as a property of the chosen model?
3. Does an API-hosted small model (Groq Llama-3.1-8B) count, or must it be locally hostable?
4. Are agent-internal LLM calls counted, or only the user-facing answer call?

The answer changes the model-routing design materially. Also request the **starter dataset now** - row counts and the data dictionary drive several decisions below.

---

## 1. Scoring reality check

| Criterion | Weight | Where the plan spends effort |
|---|---|---|
| Accuracy & grounding | **30%** | Well covered (§10, §11, §21, §22, §23, §48) - strongest part of the plan |
| Model efficiency | **20%** | **Barely covered.** One passing section (§49). No budget, no measurement, no target |
| NL understanding | 15% | Covered (§8, §10) - but multi-turn coreference is underspecified |
| Functionality | 15% | Over-covered |
| User experience | 10% | Well covered (§19, §43) |
| Presentation | 5% | **Deck is nowhere in the plan** |
| Business impact | 5% | Covered (§58) |

**Zero percent of the score goes to infrastructure.** Terraform, Prometheus, Grafana, Loki, Tempo, OTel Collector, MinIO, dual DEV/PROD environments, Trivy/Semgrep/Bandit scanning, and Kubernetes-portability all earn nothing directly. They cost days and they are the things most likely to be half-finished on demo day.

**Rebalance:** move the effort saved into (a) a measured model-efficiency story, (b) the golden evaluation set, (c) the demo and deck.

---

## 2. Contradictions between the three documents - resolve these first

The HTML solution design describes a **different system** from `plan.md` and `architecture.png`. Pick one and update the others.

| # | `plan.md` / diagram says | HTML solution design says | Fix |
|---|---|---|---|
| C1 | 9 agents incl. **Verification Agent** | 5 agents, **no Verification Agent at all** | HTML is wrong. Verification is the mechanism for the 30% criterion. Add it. |
| C2 | Clarification Agent; `CLARIFICATION_REQUIRED` state (§3) | No clarification path anywhere | HTML is wrong. Ambiguity handling is an explicit Must-Have. |
| C3 | Confidence computed deterministically (§23); diagram shows a confidence indicator | Confidence never mentioned | Add to HTML. It is a scored Bonus. |
| C4 | "Agent Orchestrator ≠ Model Router" (§59) | AD-3: Router does intent classification **and** model selection | Split them. Model routing is a service, not an agent. |
| C5 | PostgreSQL = application state (§13) | AD-6: "PostgreSQL is transactional backup" | HTML is wrong. PG is not a backup of ClickHouse. |
| C6 | No authentication, no users, no RBAC (§18) | AD-4 "check user permissions", "unauthorized data access", "compliance violations"; session state has `user_id` | Delete all permission/compliance language. Use `session_id` only. |
| C7 | Orchestrator decomposes complex work, runs specialists in parallel (§8) | AD-1/AD-5: strictly sequential, "no dynamic replanning" | Genuine design decision - see §3 below. Decide explicitly. |
| C8 | Report Agent, Analysis Agent, Finance Query Agent | Named "Execution Agent", "Query Planner"; no Analysis or Report agent | Unify the names now. Mismatched names in the deck and diagram read as sloppiness. |
| C9 | DuckDB used in the report engine (§27) while §51 says "no second source of truth" and §12 says ClickHouse owns truth | n/a | Two query engines contradicts the single-source-of-truth principle. See §4. |

Also fix in the HTML: it is styled with a purple gradient template that does not match the diagram's brand. If it goes in the submission, restyle it.

---

## 3. The single most valuable change: make hallucinated numbers structurally impossible

`plan.md` §22 currently *detects* hallucination - compare the LLM's number against the DB and reject on mismatch. Upgrade this to *prevention*:

> **The response composer LLM is never given the freedom to emit a figure.** It writes prose containing typed placeholders - `{{total}}`, `{{record_count}}`, `{{vendor.name}}`, `{{period}}` - and the server interpolates the verified values from the evidence package after generation. Any placeholder not present in the evidence package fails the response and triggers a regenerate.

Why this matters: it converts "we check the model's arithmetic" into "the model cannot state a number we did not compute." That is a one-sentence claim a judge remembers, and it is the cleanest possible answer to the 30% criterion. It is also *cheaper* - the composer can be a very small model, which feeds the 20% criterion. Add it as a new section and put it on a deck slide.

Keep the existing post-hoc numeric check as a second layer for anything that slips through (e.g. a number written out in words).

---

## 4. Data layer - simplify

**ClickHouse is likely wrong for this dataset.** The HTML's own figure is "10k transactions/day"; a hackathon starter CSV is realistically 10k - 500k rows total. Every query here is a filter + group-by + sum over a small table.

Recommendation: **use DuckDB as the finance engine.** It is embedded (no container, no ingestion service, no ports), reads the provided CSV/Parquet directly, is genuinely fast at this scale, and gives sub-50ms answers. This removes a container, the ClickHouse client, a network, and a class of ingestion bugs - and it resolves contradiction **C9**, since the report engine already wanted DuckDB.

Counter-argument, honestly stated: ClickHouse is a stronger story in the deck and Langfuse needs it anyway if you self-host Langfuse. If you keep ClickHouse for narrative reasons, that is defensible - but then **remove DuckDB from §27** so there is exactly one engine.

Either way: **do not run both.**

**Cut MinIO.** Its only real job is holding generated exports. A Docker volume plus a `/api/v1/reports/{id}/download` endpoint does this. (Unless you self-host Langfuse, which wants S3 - another reason to reconsider Langfuse, see §6.)

---

## 5. Correctness gaps that will produce wrong answers

These are not in `plan.md` and each one is a realistic demo-day failure:

**5.1 - "Last month" relative to what?**
The dataset is historical. If `last_month` resolves against *today's* date, every relative-date query returns zero rows. **All relative date ranges must resolve against the dataset's max transaction date**, and the answer must state the resolved absolute range ("August 2026, 1-31 Aug"). Put this in the query compiler, test it, and show the resolved range in the evidence panel.

**5.2 - Vendor resolution ambiguity.**
`resolve_vendor("Acme")` matching both "Acme Technologies" and "Acme Logistics" must return `CLARIFICATION_REQUIRED` with both options, not silently pick the top fuzzy match. Define the policy: exact match → proceed; single fuzzy match above threshold → proceed but lower confidence; multiple matches → clarify; no match → `DATA_UNAVAILABLE`. This is a scored behaviour and an easy demo moment.

**5.3 - Multi-turn coreference is underspecified.**
"What about the month before?" is an explicit Must-Have and a listed acceptance criterion, but neither doc says how it works. Specify it concretely: **carry the previous turn's validated `FinanceQueryPlan` forward and have the LLM emit a *delta* against it** (change `date_range`, keep `vendor_id` and `metric`), rather than re-planning from raw chat history. This is more accurate, uses far fewer tokens, and is trivially testable. Add 8-10 multi-turn pairs to the golden set.

**5.4 - Currency.**
`plan.md` examples hardcode `₹`. Do not assume - read the currency from the dataset and carry it through the evidence package. Keep the existing "currency consistency" verification check; it is a good one.

**5.5 - Timezone / date-only.**
Decide once whether transaction dates are date-only or timestamps and whether month boundaries are inclusive. Off-by-one at month boundaries is the classic way a finance demo produces a subtly wrong number.

---

## 6. Model efficiency - build a real story for the 20%

Currently this is one paragraph (§49). It should be a named workstream with an artifact. Changes:

**6.1 - Invert the routing default.** The plan escalates to bigger models on complexity (`HIGH → RunPod GPU`). That optimises against the criterion being scored. Instead: **default to the smallest model that passes the golden set, and escalate only on a measured trigger** (planner validation failure, or low-confidence entity resolution). Then report the escalation rate - "94% of queries answered by an 8B model" is the winning sentence.

**6.2 - Cap LLM calls on the happy path at two.** A 9-agent chain with an LLM call per agent is slow *and* token-expensive - it loses points on both efficiency (20%) and "answers instantly." Make Scope, Intent, and Entity resolution a **single** structured planning call (they all produce fields of the same `FinanceQueryPlan`), then one composition call. Verification, confidence, evidence, and query compilation are deterministic code with zero LLM calls. Target: **2 LLM calls, <1.5s P95** on simple queries. Reserve the multi-agent decomposition path for genuinely complex questions and show it once in the demo.

**6.3 - Publish the numbers.** The Bonus explicitly asks for "a short note on model choice: which model, why, and what accuracy looked like against a sample question set." Produce `docs/model-choice.md` with a table:

| Model | Golden-set accuracy | Grounding rate | Avg tokens/query | Avg cost/query | P95 latency |
|---|---|---|---|---|---|

Run at least three models (e.g. an 8B, a 20-30B, and one large baseline) so the table *proves* the small model was sufficient rather than asserting it. This single table addresses a Bonus item, the 20% criterion, and gives the deck its best slide.

**6.4 - Drop RunPod.** It is not free, needs GPU provisioning, adds a day of ops, and pushes against the efficiency criterion. Groq primary + OpenRouter fallback is sufficient and keeps the LiteLLM abstraction intact. If a heavy tier is wanted later, add it behind the existing router with no other changes. (`plan.md` §9's honesty note about RunPod not being free is good - keep that discipline.)

---

## 7. Scope cuts - recommended

Cut or defer these. Each earns ~0 rubric points and costs meaningful time:

- **Terraform** (§40) - one VPS, configured once, by hand. IaC for a 48h project is theatre.
- **Prometheus + Grafana + Loki + Tempo + OTel Collector** (§17) - five containers of infra observability for a demo with one user. Keep structured JSON logs and Langfuse.
- **Dual DEV/PROD environments** (§36) - one production deploy plus local Docker Compose. Halves the CI/CD, DNS, secrets, and database work.
- **MinIO** (§15) - see §4.
- **PDF export via Playwright** (§27) - heavy container, brittle. Ship **CSV export** (explicitly Good-to-Have, ~1 hour) and XLSX if time allows. Skip PDF.
- **Full security scanning suite** (§38: Bandit, Semgrep, pip-audit, Trivy) - keep Ruff + MyPy + Pytest in CI. Note the others as "production roadmap" on a slide.
- **Kubernetes manifests / `infra/k8s/`** (§41) - remove the directory.
- **The BI/Tableau-like reporting UI** (§27) - the challenge explicitly says answers should come *without touching a dashboard*. Building a dashboard product cuts against the pitch. Keep charts inline in chat answers.
- **Admin AI Control Room** (§18) - trim to a single read-only page: requests, tokens, cost, model mix, escalation rate, latency, eval accuracy. That page directly evidences the 20% criterion and takes hours, not days. Cut the rest.

**Langfuse - judgement call.** Self-hosted Langfuse OSS pulls in ClickHouse + Postgres + Redis + S3 and is a real deployment. It is genuinely useful for the trace-explorer demo moment and for the token/cost table in §6.3. Two viable paths: (a) keep it, accept the infra cost, and use it as your observability story; or (b) drop it and log traces to Postgres yourself in ~half a day, rendering them in the admin page. **Given the numbers in §6.3 are needed regardless, (b) is lower-risk.** Decide explicitly rather than defaulting.

---

## 8. Missing submission deliverables

The problem statement lists five required submissions. `plan.md`'s 10-phase order does not contain three of them:

| Required | Status in plan | Action |
|---|---|---|
| Working prototype (chat + backend) | Covered | - |
| Architecture diagram | `architecture.png` exists and is good | Update after the cuts above - it currently shows MinIO, Prometheus, Grafana, Loki, Tempo, RunPod, Terraform-era infra |
| README with setup instructions | §54 | Move earlier; write as you build |
| **Sample questions + the answers produced** | **Absent** | Create `docs/sample-questions.md`, auto-generated from the golden-set run so it is real output, not hand-written |
| **Presentation deck** (problem, approach, model rationale, demo flow) | **Absent** | Add as an explicit phase. Reserve the final 4 hours for deck + rehearsal |

---

## 9. Revised phase order

Current order defers evaluation to Phase 9 and the model story to Phase 5. Both are load-bearing for 50% of the score and must run early and continuously.

| Phase | Content | Rationale |
|---|---|---|
| **0** | Dataset in hand; data dictionary read; **golden question set drafted (30 questions to start)** | Write the test before the system. Fixes the target. |
| **1** | Docker Compose skeleton, FastAPI + Next.js, chosen finance DB, Postgres, Redis; dataset ingested and validated | Foundation only. No observability stack. |
| **2** | `FinanceQueryPlan` schema, query compiler, deterministic tools, **dataset-relative date resolution**, vendor resolution + ambiguity policy | The correctness core. |
| **3** | Verification engine, evidence package, deterministic confidence, **placeholder-interpolation composer (§3)**, the five response states | The 30% criterion, complete. |
| **4** | **Golden-set runner + accuracy report, running from here on every change** | Turns the rest of the build into measured iteration. |
| **5** | Model router, Groq + OpenRouter, small-model-first policy, token/cost/latency capture; **`docs/model-choice.md` table** | The 20% criterion. |
| **6** | Multi-turn plan-delta, clarification flow, orchestrator decomposition for complex queries | NL understanding, 15%. |
| **7** | Chat UI, live agent timeline (SSE), evidence drawer, inline charts, CSV export | UX, 10%. Highest visible payoff per hour. |
| **8** | Deploy to VPS behind Cloudflare Tunnel; simple GitHub Actions build + deploy; admin metrics page | Ship it. |
| **9** | Anomaly callouts (Bonus), XLSX export, trace explorer - **only if time remains** | Genuinely optional. |
| **10** | README, `sample-questions.md`, updated diagram, **deck, demo rehearsal** | Non-negotiable, timeboxed at the end. |

Run 5-7 in parallel across the team where possible.

---

## 10. Suggested team split

Five branches exist (`dennis`, `rahul`, `srikanth`, `wasi`, `dev`). A workable division that minimises merge conflicts:

- **Data + query engine** - ingestion, schema, compiler, deterministic tools, date/vendor resolution (Phases 1-2)
- **Grounding** - verification, evidence, confidence, composer, response states (Phase 3)
- **Model + eval** - router, golden set, accuracy/cost harness, `model-choice.md` (Phases 4-5)
- **Frontend** - chat, timeline, evidence drawer, charts, export (Phase 7)
- **Infra + orchestration** - Compose, Cloudflare, deploy, CI, then multi-turn/orchestrator (Phases 6, 8)

Agree the `FinanceQueryPlan` and evidence-package schemas **on day one, in a shared `packages/contracts/`**, before anyone builds against them. `plan.md` §41 already has this directory - use it as the first commit.

---

## 11. What to keep, unchanged

The plan gets the hard part right. Do not water these down:

- **"The LLM does not own financial truth; the data layer does"** (§1) - the correct organising principle and a strong pitch line.
- **Typed `FinanceQueryPlan` + query compiler + allowlist, never LLM-generated SQL** (§10, §11) - this is the single best engineering decision in the document and the direct answer to the 30% criterion.
- **Five explicit response states** (§3: ANSWER / CLARIFICATION_REQUIRED / DATA_UNAVAILABLE / OUT_OF_SCOPE / ERROR) - maps 1:1 onto the Must-Haves and makes the demo legible.
- **Deterministic confidence, never "how confident are you?"** (§23) - exactly right, and rarer than it should be.
- **Send compact verified structures to the LLM, never raw tables** (§50) - correct for both grounding and token efficiency.
- **"Verified or refused"** (§48) - the right posture for the stated stakes.
- **Auditable steps in the UI without exposing chain-of-thought** (§19) - good instinct, and the timeline is the most demo-able feature in the plan.
- **The architecture diagram itself** - clear, well-organised, and better than most hackathon submissions. Just prune it to match the reduced scope.

---

## 12. Summary of actions

**Today**
1. Ask organizers for the missing Section 7-8 (model constraint definition).
2. Request the starter dataset; check row counts and the data dictionary.
3. Resolve contradictions C1 - C9; make `plan.md` the single source of truth and regenerate the HTML from it.

**Before writing code**
4. Freeze `FinanceQueryPlan` + evidence-package schemas in `packages/contracts/`.
5. Decide: DuckDB vs ClickHouse (one, not both). Decide: keep or drop Langfuse.
6. Draft the first 30 golden questions.

**Design changes to fold into `plan.md`**
7. Add placeholder-interpolation composer (§3 of this doc) as a new section.
8. Add dataset-relative date resolution, vendor ambiguity policy, currency handling.
9. Add multi-turn plan-delta mechanism.
10. Invert model routing to small-first-with-escalation; cap happy path at 2 LLM calls.
11. Add `docs/model-choice.md` and `docs/sample-questions.md` as required deliverables.
12. Add the presentation deck as an explicit, timeboxed phase.

**Cuts**
13. Terraform, Prometheus/Grafana/Loki/Tempo/OTel, MinIO, RunPod, PDF export, k8s, dual environments, the BI dashboard, the full security-scan suite. Trim the admin surface to one metrics page.
