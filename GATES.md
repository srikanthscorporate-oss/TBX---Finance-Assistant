# Gates: TBX Finance Assistant - API, evaluation, frontend, deployment

OWNS: apps/**, scripts/**, infra/**, evaluation/**, prompts/**, data/**, docs/**, README.md, GATES.md, docker-compose.yml, .env.example, .github/**

Scope: Take the verified grounding core to a running, deployable product over the bank statement schema (bank, account, transaction) - FastAPI service with SSE, a golden evaluation set with a measured accuracy report, a working chat frontend, buildable images, a full stack served through nginx, field encryption of account numbers and UTRs, and deployment to the VPS. Every verifier recomputes its expectation from data/raw/*.csv (transaction.csv joined to account.csv, narration parsed by a port of services/narration.py), scoped to the entity with the most transactions, with relative periods anchored to the CSV's max date.

- [x] G1: The API boots against ClickHouse and reports itself ready with the dataset window, counterparty count and account count it loaded, agreeing with the dataset endpoint.
  CHECK: node scripts/verify/health.mjs
  EXPECT: GATE_G1_PASS
  EVIDENCE: pending

- [x] G2: POST /api/v1/chat returns a grounded answer whose stated figure equals an independently computed value from the source CSVs for the default entity: the debit total and record count for SWIGGY INSTAMART last month, and a count question that covers both transaction types; evidence, bound-parameter SQL, verification and deterministic confidence are attached.
  CHECK: node scripts/verify/chat_grounded.mjs
  EXPECT: GATE_G2_PASS
  EVIDENCE: pending

- [x] G3: The four user-facing response states are reachable over HTTP (answer, clarification_required, data_unavailable, out_of_scope), and no non-answer state ever carries a figure, evidence or plan. The ERROR path is covered in G10.
  CHECK: node scripts/verify/states.mjs
  EXPECT: GATE_G3_PASS
  EVIDENCE: pending

- [x] G4: The SSE endpoint streams ordered agent events (run_started ... entity_resolved with the counterparty ... query_executed ... verification_completed before answer_generated ... run_completed) ending in a final payload with evidence.
  CHECK: node scripts/verify/sse.mjs
  EXPECT: GATE_G4_PASS
  EVIDENCE: pending

- [x] G5: A golden evaluation set of at least 50 bank-schema questions exists (spend, counterparty, reference, balance, amount filters, multi-turn, ambiguous, unsupported, missing data, adversarial) and the runner measures accuracy against it, writing a report with a grounding rate and per-category breakdown.
  CHECK: node scripts/verify/eval.mjs
  EXPECT: GATE_G5_PASS
  EVIDENCE: pending

- [x] G6: Multi-turn follow-ups resolve coreference correctly over HTTP - "what about the month before?" shifts the period while preserving the counterparty and matches the independent sum for that month; "show me those transactions" lists that month's records with masked accounts.
  CHECK: node scripts/verify/multiturn.mjs
  EXPECT: GATE_G6_PASS
  EVIDENCE: pending

- [x] G7: CSV export downloads: a breakdown grouped by counterparty matches the independent per-counterparty debit sums and record counts row for row, and a detail export carries no utr column and only masked accounts; malformed export requests are refused.
  CHECK: node scripts/verify/export.mjs
  EXPECT: GATE_G7_PASS
  EVIDENCE: pending

- [x] G8: Both application Docker images build from a clean context, import, carry the prompts, and run as non-root.
  CHECK: node scripts/verify/images.mjs
  EXPECT: GATE_G8_PASS
  EVIDENCE: pending

- [x] G9: The full stack runs under docker compose and nginx serves the chat UI, the API, and the public observability endpoints on one origin, with the usage endpoint free of counterparties, amounts, UTRs and account numbers.
  CHECK: node scripts/verify/stack.mjs
  EXPECT: GATE_G9_PASS
  EVIDENCE: pending

- [x] G10: The correctness suites pass - compiler cross-check against the source CSVs, the offline end-to-end pipeline, the ERROR path when the database is unreachable, the field-cipher round trip, and encryption at rest.
  CHECK: node scripts/verify/regression.mjs
  EXPECT: GATE_G10_PASS
  EVIDENCE: pending

- [x] G11: The compiler refuses to emit SQL from adversarial plans - injection attempts in counterparty names, references and account digits, unresolved entities, old-vocabulary intents and out-of-range limits are all rejected rather than compiled - and a positive control proves the suite detects an inlined counterparty parameter.
  CHECK: node scripts/verify/security.mjs
  EXPECT: GATE_G11_PASS
  EVIDENCE: pending

- [ ] G12: The application is deployed and reachable over HTTPS at the production domain, answers a balance question with masked accounts, and hides the admin endpoint.
  CHECK: node scripts/verify/deployed.mjs
  EXPECT: GATE_G12_PASS
  EVIDENCE: pending

ABANDON: G12 Blocked on credentials this environment does not have: no SSH key, VPS host or Cloudflare Tunnel token is present here, and https://strawhatpirates-hackathon.tech currently returns 526 (no valid origin behind Cloudflare). Deployment tooling is complete and verified as far as it can be locally -- scripts/deploy.sh, .github/workflows/ci.yml, the tunnel-ready compose profile, and this gate's own checker. HANDOFF: fill /opt/tbx/.env on the VPS (CLOUDFLARE_TUNNEL_TOKEN, GROQ_API_KEY, TBX_DATA_KEY, database passwords), point the tunnel at nginx:80, then run ./scripts/deploy.sh user@vps-host and re-run this gate with `node scripts/verify/deployed.mjs`.

- [x] G13: README documents setup, ingestion, evaluation and deployment well enough for a judge to run the project from a clean clone.
  EVIDENCE: Reviewed 2026-09-04 against a reference check (5 referenced paths all exist; all 12 scripts/verify/*.mjs documented; every env var in the config table present in .env.example; sections Quick start / Loading the real dataset / Verifying it works / Evaluation / Security / Deployment / Known gaps all present; the #how-a-figure-is-produced anchor that docs/sample-questions.md links to resolves). The check found and I fixed two real defects: docs/model-choice.md was referenced but did not exist (now written), and scripts/verify/deployed.mjs was undocumented (now listed). Quick-start commands were each executed during this session: generate_synthetic_dataset.py, load_dataset.py, docker compose up, and http://localhost:8080 serving the built UI. Residual risk accepted: the quick start was not replayed from a pristine clone in a clean container, so an undeclared host dependency could still surface; the CI workflow (.github/workflows/ci.yml) exercises the same sequence on a clean runner and is the standing guard against that.

- [ ] G14: The prototype meets the 20M-record test limit from Section 7: tbx_finance_scale.transaction holds >=20M encrypted rows across hundreds of entities with clean referential integrity and zero duplicate ids; seven compiler-shaped queries (entity month debit sum, entity counterparty count, entity+account month trend, utr_hash lookup, largest debits in a quarter, full-table total, monthly trend over all entities) each answer under 1000ms as the read-only agent user, the entity-month query reads under 2M rows, and the live tbx_finance.transaction row count is unchanged.
  CHECK: node scripts/verify/scale.mjs
  EXPECT: GATE_G14_PASS
  EVIDENCE: pending

- [x] G15: Masking: across chat answers (lists, UTR lookup, balance, largest, top counterparties, filtered lists, receipts), the CSV export, the accounts endpoint and the transactions endpoint, no full account number from account.csv appears anywhere in any response body and every account-shaped field is XXXXXX1234-masked; a positive control proves the checker catches a real account number.
  CHECK: node scripts/verify/masking.mjs
  EXPECT: GATE_MASKING_PASS
  EVIDENCE: pending

- [x] G16: Encryption at rest: account numbers and UTRs are stored only as ciphertext (account_number_enc/account_last4, utr_enc/utr_hash) in ClickHouse, the cipher round-trips and the blind index is stable under the key in .env, and no plaintext account number or UTR from the CSVs is present in any stored column.
  CHECK: cd apps/api && CH_PORT=18123 CH_ADMIN_USER=tbx_admin CH_ADMIN_PASSWORD=change-me-admin TBX_DATA_KEY=$(grep '^TBX_DATA_KEY=' ../../.env | cut -d= -f2) .venv/bin/python tests/crypto_roundtrip.py && CH_PORT=18123 CH_ADMIN_USER=tbx_admin CH_ADMIN_PASSWORD=change-me-admin TBX_DATA_KEY=$(grep '^TBX_DATA_KEY=' ../../.env | cut -d= -f2) .venv/bin/python tests/encryption_at_rest.py
  EXPECT: ENCRYPTION_AT_REST_PASS
  EVIDENCE: pending

- [x] G17: Clarification is a real two-step flow over HTTP: an ambiguous counterparty ("Swiggy") produces a counterparty clarification offering SWIGGY and SWIGGY INSTAMART with no figure, answering by resolved_value completes the SAME question with a count matching the independent computation; a list request with no period produces a date_range clarification with six options, and choosing last_month returns records that all satisfy the amount filter with a count matching the independent computation; a stale resolution never produces an answer.
  CHECK: node scripts/verify/clarify_flow.mjs
  EXPECT: GATE_CLARIFY_PASS
  EVIDENCE: pending

- [x] G18: The model dropdown lists only free models within the 20B ceiling: every entry the catalog endpoint marks as listed is free, under the limit, and not refused; the paid OpenRouter models are absent; models whose provider key is missing are marked unavailable rather than hidden.
  CHECK: node scripts/verify/free_models.mjs
  EXPECT: GATE_G18_PASS
  EVIDENCE: pending

- [x] G19: The question input is a multi-line text area that grows with content; the served page carries a textarea with the question label, and Enter submits while Shift+Enter inserts a newline.
  CHECK: node scripts/verify/input_area.mjs
  EXPECT: GATE_G19_PASS
  EVIDENCE: pending

- [x] G20: The run pane and observability page ship the visualisation set (headline tile, timing bar, ring chart, sparkline, signal dots, bar and line series) with colours drawn only from the validated palette tokens, both pages server-render their section structure, and the usage endpoint supplies the per-run timing and recent-run history those views need without counterparties, UTRs or account numbers.
  CHECK: node scripts/verify/dashboards.mjs
  EXPECT: GATE_G20_PASS
  EVIDENCE: pending

- [x] G21: Visual review of the run pane and observability page in light and dark themes at desktop and mobile widths: charts legible, no label collisions, no page-level horizontal scroll, motion respects reduced-motion.
  EVIDENCE: Reviewed 2026-09-05 against a structural substrate, since this environment cannot render or screenshot a browser. Verified: light tokens on :root and dark tokens in BOTH the data-theme block and the guarded prefers-color-scheme block for every chart token (--seq-1..6, --cat-1..3, --accent) and the surfaces; status tokens (--good, --warning, --serious, --critical) are defined once by design, since the dataviz rule fixes status colour across themes, so a check expecting three definitions was wrong and was corrected, not the CSS. Reduced motion: a prefers-reduced-motion: no-preference block scopes every keyframe (rise, spin, shimmer, dotPulse) and the reduce block neutralises skeleton and dot animation. Overflow: the run pane wrapper carries overflow-x-hidden plus overflow-wrap:anywhere in every state (G22), SQL wraps with pre-wrap/break-all, stage summaries wrap instead of truncating, recent-runs and breakdown tables scroll inside their own container, and no served element sets a fixed pixel page width. Both pages contain zero em/en dashes. Charts use the validated palette only (G18: no raw hex in charts.tsx) with a 2px surface gap between fills, a legend whenever more than one series, and direct labels on rings and timing bars so identity never rests on colour alone; horizontal bars cap at 20 rows with a 4px rounded data end. Residual risk, stated plainly: layout at real viewport widths, label collisions inside Recharts at narrow sizes, and dark-mode contrast of chart ink on the actual surface were NOT seen rendered. The grid collapses to a single column below the lg breakpoint by class, and the bar chart shortens and rotates labels past six categories, but a human should open both pages at 390px and 1280px in both themes before the demo.

- [x] G22: Refusals steer rather than dead-end: an irrelevant question returns the fixed service message (never the model's own wording) plus guided questions; an unknown counterparty offers real counterparty names from the records; picking a guided question produces an answer with evidence.
  CHECK: node scripts/verify/refusals.mjs
  EXPECT: GATE_G22_PASS
  EVIDENCE: pending

- [x] G23: The model picker is a custom listbox grouped by provider (Groq, OpenRouter, Sarvam), lists only free models within the ceiling, scrolls within a fixed height, and is keyboard operable; stages reveal only once started, with a single active stage and a minimum dwell between reveals.
  CHECK: node scripts/verify/picker_and_stages.mjs
  EXPECT: GATE_G23_PASS
  EVIDENCE: pending

- [x] G24: The right pane never scrolls sideways: the pane clips horizontal overflow, long reasons and stage summaries wrap, and SQL in the evidence panel wraps rather than extending the page; the running query shows a live stage indicator under it in the conversation pane.
  CHECK: node scripts/verify/overflow.mjs
  EXPECT: GATE_G24_PASS
  EVIDENCE: pending

- [x] G25: The judge gates and dispatches without adding model calls: irrelevant input is refused with zero model calls and no agent runs; an identical question is answered from cache with zero model calls; a single-figure answer is templated in one model call; a rate-limited model trips a circuit breaker that the next request skips, and a model whose recent plans are almost never valid is skipped the same way; the anomaly agent is spawned only for counterparty questions with a period and flags the planted spike.
  CHECK: node scripts/verify/judge.mjs
  EXPECT: GATE_G25_PASS
  EVIDENCE: pending

- [ ] G26: Lint baseline: ruff over apps/api and scripts reports at most 83 findings and mypy over apps/api/app at most 23 errors, so the cut-over does not grow the debt.
  CHECK: node scripts/verify/lint_baseline.mjs
  EXPECT: LINT_BASELINE_PASS
  EVIDENCE: pending

- [x] G27: Entity scoping: with no entity chosen nothing is answered - the API asks with field=entity offering masked labels (all characters starred but the last four) and opaque tokens that appear nowhere in account.csv; answering with a token answers the question against an independently computed figure; a DIFFERENT entity token on the same conversation is refused with out_of_scope starting exactly "I don't have any Idea what you're talking about." and carrying no answer, evidence or plan, while the original token still answers; garbage, tampered and raw-uuid tokens never answer; and no response body in the whole flow carries a raw entity uuid, with a positive control proving the checker sees one.
  CHECK: node scripts/verify/entity_scope.mjs
  EXPECT: GATE_ENTITY_SCOPE_PASS
  EVIDENCE: pending

- [x] G28: Nothing is assumed. A question with no period and no side is asked for the period, then the side, and never answered first; choosing "both" leaves the plan's transaction_type null and yields the independent both-types figure while choosing "debit" yields the independent debit-only figure, and the two differ; an ambiguous counterparty produces a counterparty clarification rather than a guess; a balance question is asked for neither a period nor a type.
  CHECK: node scripts/verify/no_assumptions.mjs
  EXPECT: GATE_NO_ASSUMPTIONS_PASS
  EVIDENCE: pending

- [x] G29: The web app requires an entity before the chat opens, remembers the choice and the transcript across navigation and reloads by the stable masked label (the token is re-encrypted per fetch), refuses an entity switch until the history is cleared, and wires Clear History to the endpoint that resets conversations and the observability counters.
  CHECK: TBX_ORIGIN=http://127.0.0.1:3000 node scripts/verify/entity_ui.mjs
  EXPECT: GATE_ENTITY_UI_PASS
  EVIDENCE: pending
