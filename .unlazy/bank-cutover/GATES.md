# Gates: bank-schema cut-over with encryption and clarification dropdowns

OWNS: apps/api/**, apps/web/**, scripts/**, infra/clickhouse/**, prompts/**, GATES.md, README.md, CLAUDE.md, docs/final-dataset-plan.md, .env.example, docker-compose.yml, start.sh

Scope: the assistant answers questions over bank/account/transaction (amount filters, relative dates, counterparty questions with a clarification dropdown, UTR or reference lookup returning transaction details), account numbers and UTRs are stored AES-256-GCM encrypted and decrypted only inside the API at query time, and every existing test, gate and the web build pass against the new schema.

- [ ] G1: Loader ingests bank/account/transaction with referential integrity and stores no plaintext account number or UTR
  CHECK: CH_PORT=18123 apps/api/.venv/bin/python apps/api/tests/encryption_at_rest.py
  EXPECT: ENCRYPTION_AT_REST_PASS
  EVIDENCE: pending

- [ ] G2: AES-256-GCM round trip, HMAC blind index, and wrong-key rejection
  CHECK: apps/api/.venv/bin/python apps/api/tests/crypto_roundtrip.py
  EXPECT: CRYPTO_ROUNDTRIP_PASS
  EVIDENCE: pending

- [ ] G3: Compiler agrees with a naive CSV loop on amount filters, counterparty, channel, reference and grouped queries
  CHECK: CH_PORT=18123 CH_ADMIN_USER=tbx_admin CH_ADMIN_PASSWORD=change-me-admin apps/api/.venv/bin/python apps/api/tests/crosscheck.py
  EXPECT: CROSSCHECK_PASS
  EVIDENCE: pending

- [ ] G4: Offline pipeline: "<500 rupees" list, Swiggy-style ambiguity yields a dropdown, UTR lookup returns details, relative dates and follow-ups, every scenario in its expected state
  CHECK: CH_PORT=18123 apps/api/.venv/bin/python apps/api/tests/e2e_offline.py
  EXPECT: E2E_OFFLINE_PASS
  EVIDENCE: pending

- [ ] G5: Adversarial plans refused; positive control proves the suite detects an inlined parameter
  CHECK: apps/api/.venv/bin/python apps/api/tests/security.py
  EXPECT: SECURITY_SUITE_PASS
  EVIDENCE: pending

- [ ] G6: Unreachable database ends in error state with no figure
  CHECK: apps/api/.venv/bin/python apps/api/tests/error_path.py
  EXPECT: ERROR_PATH_PASS
  EVIDENCE: pending

- [ ] G7: Running API answers a grounded figure equal to an independent CSV computation
  CHECK: TBX_API=http://127.0.0.1:8010 node scripts/verify/chat_grounded.mjs
  EXPECT: GATE_G2_PASS
  EVIDENCE: pending

- [ ] G8: Running API: ambiguous counterparty yields options; choosing one completes the answer without re-planning
  CHECK: TBX_API=http://127.0.0.1:8010 node scripts/verify/clarify_flow.mjs
  EXPECT: GATE_CLARIFY_PASS
  EVIDENCE: pending

- [ ] G9: Running API never emits a full account number in any response field; positive control included
  CHECK: TBX_API=http://127.0.0.1:8010 node scripts/verify/masking.mjs
  EXPECT: GATE_MASKING_PASS
  EVIDENCE: pending

- [ ] G10: Web typecheck and production build pass with the new response types
  CHECK: npm run typecheck && npm run build
  EXPECT: Compiled successfully
  CWD: apps/web
  EVIDENCE: pending

- [ ] G11: Lint and type baseline not worsened (ruff findings <= 83, mypy errors <= 23)
  CHECK: node scripts/verify/lint_baseline.mjs
  EXPECT: LINT_BASELINE_PASS
  EVIDENCE: pending

- [ ] G12: 20M encrypted rows load into the sibling DB and every assistant query shape completes under one second as the read-only user
  CHECK: node scripts/verify/scale.mjs
  EXPECT: GATE_G14_PASS
  EVIDENCE: pending
