# Gates: bank-schema cut-over with encryption and clarification dropdowns

OWNS: apps/api/**, apps/web/**, scripts/**, infra/clickhouse/**, prompts/**, GATES.md, README.md, CLAUDE.md, docs/final-dataset-plan.md, .env.example, docker-compose.yml, start.sh

Scope: the assistant answers questions over bank/account/transaction (amount filters, relative dates, counterparty questions with a clarification dropdown, UTR or reference lookup returning transaction details), account numbers and UTRs are stored AES-256-GCM encrypted and decrypted only inside the API at query time, and every existing test, gate and the web build pass against the new schema.

- [x] G1: Loader ingests bank/account/transaction with referential integrity and stores no plaintext account number or UTR
  CHECK: CH_PORT=18123 apps/api/.venv/bin/python apps/api/tests/encryption_at_rest.py
  EXPECT: ENCRYPTION_AT_REST_PASS
  EVIDENCE: automatic-evidence=v1; definition-sha256=8b6ac91b09401e11045da74284eeed3ada5e7e5679b59a9d9da82fbd51302590; exit=0; EXPECT=matched; output-sha256=4feb3787481ca2b8e8bdf33c4907f98219174a758257dce44df16f10f5668749; output-bytes=51; shell=/bin/sh; cwd=/Users/shadow/Desktop/TBX hackathon/Financial Assistant; path=b9c24ccdd5b4/17 entries

- [x] G2: AES-256-GCM round trip, HMAC blind index, and wrong-key rejection
  CHECK: apps/api/.venv/bin/python apps/api/tests/crypto_roundtrip.py
  EXPECT: CRYPTO_ROUNDTRIP_PASS
  EVIDENCE: automatic-evidence=v1; definition-sha256=090b8a0fca23830a153710f81ad5784f48bd0c80270015391f00b223a33622af; exit=0; EXPECT=matched; output-sha256=07231a8d4e0f26f28114321023dc9ae503f3ec5ae8ce36a1669054373966f80a; output-bytes=44; shell=/bin/sh; cwd=/Users/shadow/Desktop/TBX hackathon/Financial Assistant; path=b9c24ccdd5b4/17 entries

- [x] G3: Compiler agrees with a naive CSV loop on amount filters, counterparty, channel, reference and grouped queries
  CHECK: CH_PORT=18123 CH_ADMIN_USER=tbx_admin CH_ADMIN_PASSWORD=change-me-admin apps/api/.venv/bin/python apps/api/tests/crosscheck.py
  EXPECT: CROSSCHECK_PASS
  EVIDENCE: automatic-evidence=v1; definition-sha256=1763615641d08f1d11a34c23344978ca2028db0d4ecb2dc452dc2fb757627fda; exit=0; EXPECT=matched; output-sha256=44e8849c906c9a0a2dc041ef51f92676273999715b2c11fad7735260f4fc2379; output-bytes=1247; shell=/bin/sh; cwd=/Users/shadow/Desktop/TBX hackathon/Financial Assistant; path=b9c24ccdd5b4/17 entries

- [x] G4: Offline pipeline: "<500 rupees" list, Swiggy-style ambiguity yields a dropdown, UTR lookup returns details, relative dates and follow-ups, every scenario in its expected state
  CHECK: CH_PORT=18123 apps/api/.venv/bin/python apps/api/tests/e2e_offline.py
  EXPECT: E2E_OFFLINE_PASS
  EVIDENCE: automatic-evidence=v1; definition-sha256=f6754ca209c1aafda6a85eb7fb1b0d00a887da85c8b384acfb92d5d0467162aa; exit=0; EXPECT=matched; output-sha256=1b3619798c6bfdc17af11d67cae89571a7d7029551d708410911b608806df0d2; output-bytes=4222; shell=/bin/sh; cwd=/Users/shadow/Desktop/TBX hackathon/Financial Assistant; path=b9c24ccdd5b4/17 entries

- [x] G5: Adversarial plans refused; positive control proves the suite detects an inlined parameter
  CHECK: apps/api/.venv/bin/python apps/api/tests/security.py
  EXPECT: SECURITY_SUITE_PASS
  EVIDENCE: automatic-evidence=v1; definition-sha256=cdbf1a81bc6cc8fbccd34b039e7e716331c9568855abb57db5ecf6153fd02fc1; exit=0; EXPECT=matched; output-sha256=5712ad24dc90c07e77681112e5f9c407278d0e8726a22f0e8ecf83cbc78041e9; output-bytes=45; shell=/bin/sh; cwd=/Users/shadow/Desktop/TBX hackathon/Financial Assistant; path=b9c24ccdd5b4/17 entries

- [x] G6: Unreachable database ends in error state with no figure
  CHECK: apps/api/.venv/bin/python apps/api/tests/error_path.py
  EXPECT: ERROR_PATH_PASS
  EVIDENCE: automatic-evidence=v1; definition-sha256=85949f436f7a1b5461dad665185d4da3931282252c18ef22d37a1a3fa280b181; exit=0; EXPECT=matched; output-sha256=1301822869cbdb815aa5a3612bab6f6fa8324d388e21f58f9e58d0bc100d491c; output-bytes=444; shell=/bin/sh; cwd=/Users/shadow/Desktop/TBX hackathon/Financial Assistant; path=b9c24ccdd5b4/17 entries

- [x] G7: Running API answers a grounded figure equal to an independent CSV computation
  CHECK: TBX_API=http://127.0.0.1:8010 node scripts/verify/chat_grounded.mjs
  EXPECT: GATE_G2_PASS
  EVIDENCE: automatic-evidence=v1; definition-sha256=86ceae920463ddf3deab6a0d2103068eece7a4f9d3451560fa77914a0ee588a1; exit=0; EXPECT=matched; output-sha256=8ba8c6b16046a1bea3cde158a18602d3598ceb1e38b71481945e0ad75431bacf; output-bytes=327; shell=/bin/sh; cwd=/Users/shadow/Desktop/TBX hackathon/Financial Assistant; path=b9c24ccdd5b4/17 entries

- [x] G8: Running API: ambiguous counterparty yields options; choosing one completes the answer without re-planning
  CHECK: TBX_API=http://127.0.0.1:8010 node scripts/verify/clarify_flow.mjs
  EXPECT: GATE_CLARIFY_PASS
  EVIDENCE: automatic-evidence=v1; definition-sha256=74d1d8a0072640dbd0dd6dd6e3580af3b3bea6613f78634f05dae53bf04c413e; exit=0; EXPECT=matched; output-sha256=5c63cacef22699d9e754c72e54e0cbec1d339e2f7d179e6b2c75bcc7c3658fef; output-bytes=410; shell=/bin/sh; cwd=/Users/shadow/Desktop/TBX hackathon/Financial Assistant; path=b9c24ccdd5b4/17 entries

- [x] G9: Running API never emits a full account number in any response field; positive control included
  CHECK: TBX_API=http://127.0.0.1:8010 node scripts/verify/masking.mjs
  EXPECT: GATE_MASKING_PASS
  EVIDENCE: automatic-evidence=v1; definition-sha256=df428288c1158eb3b945447c44a7d7d414b7021ac05e6321ad134a19fd35dcff; exit=0; EXPECT=matched; output-sha256=a3f31d6e7349d3093cd4cddecc489a0574a1178599a6d63588ff508a458c3378; output-bytes=839; shell=/bin/sh; cwd=/Users/shadow/Desktop/TBX hackathon/Financial Assistant; path=b9c24ccdd5b4/17 entries

- [x] G10: Web typecheck and production build pass with the new response types
  CHECK: sh -c 'cd apps/web && npm run typecheck && npm run build'
  EXPECT: Compiled successfully
  EVIDENCE: automatic-evidence=v1; definition-sha256=9d6944f2a20d4bd7776e91d8b1ab980bb69127cef23a116a1b7b3638f29f0c48; exit=0; EXPECT=matched; output-sha256=5754f59d9ba0c78b6438bed4b0d31bd1dba98b383a62f3b379fa3b13d14f5042; output-bytes=1118; shell=/bin/sh; cwd=/Users/shadow/Desktop/TBX hackathon/Financial Assistant; path=b9c24ccdd5b4/17 entries

- [x] G11: Lint and type baseline not worsened (ruff findings <= 83, mypy errors <= 23)
  CHECK: node scripts/verify/lint_baseline.mjs
  EXPECT: LINT_BASELINE_PASS
  EVIDENCE: automatic-evidence=v1; definition-sha256=becb7e73ccff2e358d7209d911b61194a8b85c27e5da887f845bbe671e659632; exit=0; EXPECT=matched; output-sha256=669df22363ec4728b86754e8a760e12baafe59ca7aea2c4ccaec143da5a38208; output-bytes=84; shell=/bin/sh; cwd=/Users/shadow/Desktop/TBX hackathon/Financial Assistant; path=b9c24ccdd5b4/17 entries

- [x] G12: 20M encrypted rows load into the sibling DB and every assistant query shape completes under one second as the read-only user
  CHECK: node scripts/verify/scale.mjs
  EXPECT: GATE_G14_PASS
  EVIDENCE: automatic-evidence=v1; definition-sha256=5f4f71a9897f1c04e70580dd21d970d941e511dfd26e1a1946ccdf58b856397d; exit=0; EXPECT=matched; output-sha256=b3756e1d52d09141dea98a90bb8d5d725465b65ad06fc3f6339567f9c2919e80; output-bytes=661; shell=/bin/sh; cwd=/Users/shadow/Desktop/TBX hackathon/Financial Assistant; path=b9c24ccdd5b4/17 entries
