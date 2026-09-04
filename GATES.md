# Gates: TBX Finance Assistant - API, evaluation, frontend, deployment

OWNS: apps/**, scripts/**, infra/**, evaluation/**, prompts/**, docker-compose.yml, .github/**, docs/README.md

Scope: Take the verified grounding core to a running, deployable product - FastAPI service with SSE, a golden evaluation set with a measured accuracy report, a working chat frontend, buildable images, a full stack served through nginx, and deployment to the VPS.

- [x] G1: The API boots against ClickHouse and reports itself ready with the dataset window it loaded.
  CHECK: node scripts/verify/health.mjs
  EXPECT: GATE_G1_PASS
  EVIDENCE: automatic-evidence=v1; definition-sha256=2b6427bb8acea25a7700d93f7fb37d8d29a9371b0e50306bcb4b64f3d4bbc620; exit=0; EXPECT=matched; output-sha256=3ab3660484de6f823fa594ca65acf2f97143f4489692a5f8234d3b8b8832684d; output-bytes=99; shell=/bin/sh; cwd=/Users/shadow/Desktop/TBX hackathon/Financial Assistant; path=b9c24ccdd5b4/17 entries

- [ ] G2: POST /api/v1/chat returns a grounded answer whose stated figure equals an independently computed value from the source CSVs, with evidence and verification attached.
  CHECK: node scripts/verify/chat_grounded.mjs
  EXPECT: GATE_G2_PASS
  EVIDENCE: pending

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

- [x] G13: README documents setup, ingestion, evaluation and deployment well enough for a judge to run the project from a clean clone.
  EVIDENCE: Reviewed 2026-09-04 against a reference check (5 referenced paths all exist; all 12 scripts/verify/*.mjs documented; every env var in the config table present in .env.example; sections Quick start / Loading the real dataset / Verifying it works / Evaluation / Security / Deployment / Known gaps all present; the #how-a-figure-is-produced anchor that docs/sample-questions.md links to resolves). The check found and I fixed two real defects: docs/model-choice.md was referenced but did not exist (now written), and scripts/verify/deployed.mjs was undocumented (now listed). Quick-start commands were each executed during this session: generate_synthetic_dataset.py, load_dataset.py, docker compose up, and http://localhost:8080 serving the built UI. Residual risk accepted: the quick start was not replayed from a pristine clone in a clean container, so an undeclared host dependency could still surface; the CI workflow (.github/workflows/ci.yml) exercises the same sequence on a clean runner and is the standing guard against that.
