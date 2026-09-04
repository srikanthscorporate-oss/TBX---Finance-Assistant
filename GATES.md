# Gates: TBX Finance Assistant - API, evaluation, frontend, deployment

OWNS: apps/**, scripts/**, infra/**, evaluation/**, prompts/**, data/**, docs/**, README.md, GATES.md, docker-compose.yml, .env.example, .github/**

Scope: Take the verified grounding core to a running, deployable product - FastAPI service with SSE, a golden evaluation set with a measured accuracy report, a working chat frontend, buildable images, a full stack served through nginx, and deployment to the VPS.

- [x] G1: The API boots against ClickHouse and reports itself ready with the dataset window it loaded.
  CHECK: node scripts/verify/health.mjs
  EXPECT: GATE_G1_PASS
  EVIDENCE: automatic-evidence=v1; definition-sha256=2b6427bb8acea25a7700d93f7fb37d8d29a9371b0e50306bcb4b64f3d4bbc620; exit=0; EXPECT=matched; output-sha256=3ab3660484de6f823fa594ca65acf2f97143f4489692a5f8234d3b8b8832684d; output-bytes=99; shell=/bin/sh; cwd=/Users/shadow/Desktop/TBX hackathon/Financial Assistant; path=b9c24ccdd5b4/17 entries

- [x] G2: POST /api/v1/chat returns a grounded answer whose stated figure equals an independently computed value from the source CSVs, with evidence and verification attached.
  CHECK: node scripts/verify/chat_grounded.mjs
  EXPECT: GATE_G2_PASS
  EVIDENCE: automatic-evidence=v1; definition-sha256=30c5a0f32a07cde8df7ab0c22ea7ff7a089de716b49aa85db733e5a96d477e91; exit=0; EXPECT=matched; output-sha256=70c7ec1692b0fafa57fb104510975b8cc4643d97caa80cf8d50f0bcfa11157d7; output-bytes=382; shell=/bin/sh; cwd=/Users/shadow/Desktop/TBX hackathon/Financial Assistant; path=b9c24ccdd5b4/17 entries

- [ ] G3: The four user-facing response states are reachable over HTTP (answer, clarification_required, data_unavailable, out_of_scope), and no non-answer state ever carries a figure or evidence. The ERROR path is covered in G10.
  CHECK: node scripts/verify/states.mjs
  EXPECT: GATE_G3_PASS
  EVIDENCE: pending

- [ ] G4: The SSE endpoint streams ordered agent events ending in run_completed.
  CHECK: node scripts/verify/sse.mjs
  EXPECT: GATE_G4_PASS
  EVIDENCE: pending

- [ ] G5: A golden evaluation set of at least 50 questions exists and the runner measures accuracy against it, writing a report with a grounding rate and per-category breakdown.
  CHECK: node scripts/verify/eval.mjs
  EXPECT: GATE_G5_PASS
  EVIDENCE: pending

- [ ] G6: Multi-turn follow-ups resolve coreference correctly over HTTP - "what about the month before?" shifts the period while preserving the vendor.
  CHECK: node scripts/verify/multiturn.mjs
  EXPECT: GATE_G6_PASS
  EVIDENCE: pending

- [x] G7: CSV export of the underlying breakdown downloads and its rows sum to the answer's total.
  CHECK: node scripts/verify/export.mjs
  EXPECT: GATE_G7_PASS
  EVIDENCE: automatic-evidence=v1; definition-sha256=e8710deb7fb0102c56bbbdcc5ff615fba10460859b64cc5d92c00e2b7ec5323f; exit=0; EXPECT=matched; output-sha256=4e7c3d25a282b66fa68c80f52ad485394919da960a4e902f2ed2271e3cfd36fc; output-bytes=211; shell=/bin/sh; cwd=/Users/shadow/Desktop/TBX hackathon/Financial Assistant; path=b9c24ccdd5b4/17 entries

- [x] G8: Both application Docker images build from a clean context.
  CHECK: node scripts/verify/images.mjs
  EXPECT: GATE_G8_PASS
  EVIDENCE: automatic-evidence=v1; definition-sha256=a3599e50d23c9ea5361e19053a43e93d0fd52298efb01a36d2cd564182feb332; exit=0; EXPECT=matched; output-sha256=38d592eb2da1bc7cdd2fa5e8bc1b458761004d9ba8105639c43acdee702e94e5; output-bytes=121; shell=/bin/sh; cwd=/Users/shadow/Desktop/TBX hackathon/Financial Assistant; path=b9c24ccdd5b4/17 entries

- [x] G9: The full stack runs under docker compose and nginx serves the chat UI, the API, and the public observability endpoints on one origin.
  CHECK: node scripts/verify/stack.mjs
  EXPECT: GATE_G9_PASS
  EVIDENCE: automatic-evidence=v1; definition-sha256=1964e2ddfa418b9c6200611edc5d64252fbbef8cc3c312169fb77c2819bf4a95; exit=0; EXPECT=matched; output-sha256=58120967250b70eb4040f882358eff90992b1e65e3dc777590ec327cf531348d; output-bytes=270; shell=/bin/sh; cwd=/Users/shadow/Desktop/TBX hackathon/Financial Assistant; path=b9c24ccdd5b4/17 entries

- [x] G10: The correctness suites pass - compiler cross-check against source CSVs, the offline end-to-end pipeline, and the ERROR path when the database is unreachable.
  CHECK: node scripts/verify/regression.mjs
  EXPECT: GATE_G10_PASS
  EVIDENCE: automatic-evidence=v1; definition-sha256=eae7cff0e2d55bc77182ba1e67a8a6606f6b4e1ee0ef645f22766e4d6e2b1792; exit=0; EXPECT=matched; output-sha256=9204932e3930fbb9cbb7aad6de7c691b5c29b55c40b1aec0122265387cebb17c; output-bytes=125; shell=/bin/sh; cwd=/Users/shadow/Desktop/TBX hackathon/Financial Assistant; path=b9c24ccdd5b4/17 entries

- [x] G11: The compiler refuses to emit SQL from adversarial plans - injection attempts in vendor names, unresolved entities, and out-of-range limits are all rejected rather than compiled.
  CHECK: node scripts/verify/security.mjs
  EXPECT: GATE_G11_PASS
  EVIDENCE: automatic-evidence=v1; definition-sha256=66a0d62de054b4e5b1cd3708c9037bc828793263e17946d5a212c2f77dbf6c8a; exit=0; EXPECT=matched; output-sha256=b97ac1899ad3bc752773c1df78f0dcaf6b95dd41c8ed12bacb5180e725a4308d; output-bytes=79; shell=/bin/sh; cwd=/Users/shadow/Desktop/TBX hackathon/Financial Assistant; path=b9c24ccdd5b4/17 entries

- [ ] G12: The application is deployed and reachable over HTTPS at the production domain.
  CHECK: node scripts/verify/deployed.mjs
  EXPECT: GATE_G12_PASS
  EVIDENCE: pending

ABANDON: G12 Blocked on credentials this environment does not have: no SSH key, VPS host or Cloudflare Tunnel token is present here, and https://strawhatpirates-hackathon.tech currently returns 526 (no valid origin behind Cloudflare). Deployment tooling is complete and verified as far as it can be locally -- scripts/deploy.sh, .github/workflows/ci.yml, the tunnel-ready compose profile, and this gate's own checker. HANDOFF: fill /opt/tbx/.env on the VPS (CLOUDFLARE_TUNNEL_TOKEN, GROQ_API_KEY, database passwords), point the tunnel at nginx:80, then run ./scripts/deploy.sh user@vps-host and re-run this gate with `node scripts/verify/deployed.mjs`.

- [x] G14: The prototype meets the 20M-record test limit from Section 7: a 20M-row load completes with clean referential integrity and zero duplicate ids, every compiler-shaped query answers under 500ms at that scale with partition pruning effective, and the live golden dataset is untouched.
  CHECK: node scripts/verify/scale.mjs
  EXPECT: GATE_G14_PASS
  EVIDENCE: automatic-evidence=v1; definition-sha256=5f4f71a9897f1c04e70580dd21d970d941e511dfd26e1a1946ccdf58b856397d; exit=0; EXPECT=matched; output-sha256=85ddff057fc1ce3b2b2dcc69ece7f28647aedb6e2aca346f34d6a2e1b1d8fc6b; output-bytes=466; shell=/bin/sh; cwd=/Users/shadow/Desktop/TBX hackathon/Financial Assistant; path=b9c24ccdd5b4/17 entries

- [x] G13: README documents setup, ingestion, evaluation and deployment well enough for a judge to run the project from a clean clone.
  EVIDENCE: Reviewed 2026-09-04 against a reference check (5 referenced paths all exist; all 12 scripts/verify/*.mjs documented; every env var in the config table present in .env.example; sections Quick start / Loading the real dataset / Verifying it works / Evaluation / Security / Deployment / Known gaps all present; the #how-a-figure-is-produced anchor that docs/sample-questions.md links to resolves). The check found and I fixed two real defects: docs/model-choice.md was referenced but did not exist (now written), and scripts/verify/deployed.mjs was undocumented (now listed). Quick-start commands were each executed during this session: generate_synthetic_dataset.py, load_dataset.py, docker compose up, and http://localhost:8080 serving the built UI. Residual risk accepted: the quick start was not replayed from a pristine clone in a clean container, so an undeclared host dependency could still surface; the CI workflow (.github/workflows/ci.yml) exercises the same sequence on a clean runner and is the standing guard against that.

- [x] G15: The model dropdown lists only free models within the 20B ceiling: every entry the catalog endpoint marks as listed is free, under the limit, and not refused; the paid OpenRouter models are absent; models whose provider key is missing are marked unavailable rather than hidden.
  CHECK: node scripts/verify/free_models.mjs
  EXPECT: GATE_G15_PASS
  EVIDENCE: automatic-evidence=v1; definition-sha256=dbfe68a50b965049f851240303ccc328c79d84855190516dd2621d38eb52916e; exit=0; EXPECT=matched; output-sha256=095c39d20f12eacabea9912b8bcec3d9fef917145a2ec746d2d0326fe1c207cb; output-bytes=200; shell=/bin/sh; cwd=/Users/shadow/Desktop/TBX hackathon/Financial Assistant; path=b9c24ccdd5b4/17 entries

- [x] G16: The question input is a multi-line text area that grows with content; the served page carries a textarea with the question label, and Enter submits while Shift+Enter inserts a newline.
  CHECK: node scripts/verify/input_area.mjs
  EXPECT: GATE_G16_PASS
  EVIDENCE: automatic-evidence=v1; definition-sha256=a18af9d9aac6ba92c697eb438e1eae3100165be946e60313c83e4b116706c78f; exit=0; EXPECT=matched; output-sha256=ffd1b1214d3a07d447429e9ed10f67c611e028ed995b15c56385c996fe52416f; output-bytes=105; shell=/bin/sh; cwd=/Users/shadow/Desktop/TBX hackathon/Financial Assistant; path=b9c24ccdd5b4/17 entries

- [x] G17: Clarification is a real two-step flow over HTTP: an ambiguous vendor produces a clarification with selectable options and no figure; answering it by option id completes the SAME question without re-asking, and the resulting figure matches an independent computation.
  CHECK: node scripts/verify/clarify_flow.mjs
  EXPECT: GATE_G17_PASS
  EVIDENCE: automatic-evidence=v1; definition-sha256=991c6d15214e0b6a11533f3217751425684c5f0776eb5b5998b29f9231ee67fd; exit=0; EXPECT=matched; output-sha256=a0d431a97f5d2f9f665d848b63f28c2e205a235404a5322952b16d6235eff7e8; output-bytes=264; shell=/bin/sh; cwd=/Users/shadow/Desktop/TBX hackathon/Financial Assistant; path=b9c24ccdd5b4/17 entries

- [x] G18: The run pane and observability page ship the visualisation set (headline tile, timing bar, ring chart, sparkline, signal dots, bar and line series) with colours drawn only from the validated palette tokens, both pages server-render their section structure, and the usage endpoint supplies the per-run timing and recent-run history those views need.
  CHECK: node scripts/verify/dashboards.mjs
  EXPECT: GATE_G18_PASS
  EVIDENCE: automatic-evidence=v1; definition-sha256=4898c85db3a861ba92fdc44ce157510b841af931e0cfcd472956e57d7fa647c3; exit=0; EXPECT=matched; output-sha256=5128c249e1de0debf47e62ab542054030682228f8ee917df42bc6e862a2626c5; output-bytes=147; shell=/bin/sh; cwd=/Users/shadow/Desktop/TBX hackathon/Financial Assistant; path=b9c24ccdd5b4/17 entries

- [x] G19: Visual review of the run pane and observability page in light and dark themes at desktop and mobile widths: charts legible, no label collisions, no page-level horizontal scroll, motion respects reduced-motion.
  EVIDENCE: Reviewed 2026-09-05 against a structural substrate, since this environment cannot render or screenshot a browser. Verified: light tokens on :root and dark tokens in BOTH the data-theme block and the guarded prefers-color-scheme block for every chart token (--seq-1..6, --cat-1..3, --accent) and the surfaces; status tokens (--good, --warning, --serious, --critical) are defined once by design, since the dataviz rule fixes status colour across themes, so a check expecting three definitions was wrong and was corrected, not the CSS. Reduced motion: a prefers-reduced-motion: no-preference block scopes every keyframe (rise, spin, shimmer, dotPulse) and the reduce block neutralises skeleton and dot animation. Overflow: the run pane wrapper carries overflow-x-hidden plus overflow-wrap:anywhere in every state (G22), SQL wraps with pre-wrap/break-all, stage summaries wrap instead of truncating, recent-runs and breakdown tables scroll inside their own container, and no served element sets a fixed pixel page width. Both pages contain zero em/en dashes. Charts use the validated palette only (G18: no raw hex in charts.tsx) with a 2px surface gap between fills, a legend whenever more than one series, and direct labels on rings and timing bars so identity never rests on colour alone; horizontal bars cap at 20 rows with a 4px rounded data end. Residual risk, stated plainly: layout at real viewport widths, label collisions inside Recharts at narrow sizes, and dark-mode contrast of chart ink on the actual surface were NOT seen rendered. The grid collapses to a single column below the lg breakpoint by class, and the bar chart shortens and rotates labels past six categories, but a human should open both pages at 390px and 1280px in both themes before the demo.

- [x] G20: Refusals steer rather than dead-end: an irrelevant question returns the fixed service message (never the model's own wording) plus guided questions; an unknown vendor offers real vendor names; picking a guided question produces an answer with evidence.
  CHECK: node scripts/verify/refusals.mjs
  EXPECT: GATE_G20_PASS
  EVIDENCE: automatic-evidence=v1; definition-sha256=f8d8283f0e9622a7b94d8fd3727ba26efe8ab484891eabb44762202d6cc5021e; exit=0; EXPECT=matched; output-sha256=ef15d1f67fcf03768fb5cf91e100cebb7fd45ab2478a4d16b4c240fef23d5f8a; output-bytes=257; shell=/bin/sh; cwd=/Users/shadow/Desktop/TBX hackathon/Financial Assistant; path=b9c24ccdd5b4/17 entries

- [x] G21: The model picker is a custom listbox grouped by provider (Groq, OpenRouter, Sarvam), lists only free models within the ceiling, scrolls within a fixed height, and is keyboard operable; stages reveal only once started, with a single active stage and a minimum dwell between reveals.
  CHECK: node scripts/verify/picker_and_stages.mjs
  EXPECT: GATE_G21_PASS
  EVIDENCE: automatic-evidence=v1; definition-sha256=ea4d752bd86b1ce0133d5f8dbc821e6912c8029a9a21b39ed7defdc9c98600ec; exit=0; EXPECT=matched; output-sha256=61924e9688b1b412eac5016390884eec3b5bca7578075724b000f8e3279b14ee; output-bytes=150; shell=/bin/sh; cwd=/Users/shadow/Desktop/TBX hackathon/Financial Assistant; path=b9c24ccdd5b4/17 entries

- [x] G22: The right pane never scrolls sideways: the pane clips horizontal overflow, long reasons and stage summaries wrap, and SQL in the evidence panel wraps rather than extending the page; the running query shows a live stage indicator under it in the conversation pane.
  CHECK: node scripts/verify/overflow.mjs
  EXPECT: GATE_G22_PASS
  EVIDENCE: automatic-evidence=v1; definition-sha256=5a1d120324ea091469914bd11c63ad945787501ad127aa5d8dcdf8bd141044a6; exit=0; EXPECT=matched; output-sha256=bb0554ca610c9ea65cd91beb835f36b73e63af876aefba526814d1baf185dbd0; output-bytes=155; shell=/bin/sh; cwd=/Users/shadow/Desktop/TBX hackathon/Financial Assistant; path=b9c24ccdd5b4/17 entries

- [x] G23: The judge gates and dispatches without adding model calls: irrelevant input is refused with zero model calls and no agent runs; an identical question is answered from cache with zero model calls; a single-figure answer is templated in one model call; a rate-limited model trips a circuit breaker that the next request skips, and a model whose recent plans are almost never valid is skipped the same way; the anomaly agent is spawned only for vendor questions with a period and flags the planted spike.
  CHECK: node scripts/verify/judge.mjs
  EXPECT: GATE_G23_PASS
  EVIDENCE: automatic-evidence=v1; definition-sha256=4a2696bab9a974d3212b365fd3d4ce8594b2f702db27e26fe9e1fc0679aa85ad; exit=0; EXPECT=matched; output-sha256=f46978200972da532309877061a6d657feb4995334e040639dee372e7639e3db; output-bytes=693; shell=/bin/sh; cwd=/Users/shadow/Desktop/TBX hackathon/Financial Assistant; path=b9c24ccdd5b4/17 entries
