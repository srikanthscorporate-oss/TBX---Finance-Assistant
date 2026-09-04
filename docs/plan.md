
PROJECT: StrawHat Finance Assistant
HACKATHON: TBX - BVP Tech Catalyst Hackathon
ENVIRONMENT: Hostinger VPS, Ubuntu
DOMAIN: strawhatpirates-hackathon.tech
EDGE: Cloudflare
IMPLEMENTATION STYLE: Production-engineered, Dockerized, repeatable, modular, AI-centric
PRIMARY GOAL: Accuracy + grounding + agentic UX + explainability + model efficiency

IMPORTANT:
The attached architecture diagram is the authoritative visual reference for the overall system topology.
Use this specification together with that image.
Do not simplify away important architectural components unless there is a strong technical reason.
Do not add unnecessary technologies or services just because they are popular.

============================================================

1. PRODUCT VISION
   ============================================================

Build an AI-native financial intelligence assistant for the TBX hackathon.

The user interacts through a conversational UI and asks natural-language questions about financial data supplied by TBX.

Primary supported capabilities:

1. Spend analysis
2. Vendor payouts
3. Reconciliation
4. Transaction lookup/filtering
5. Date-based comparisons
6. Vendor/category analytics
7. Reports and exports
8. Anomaly detection as an optional bonus capability

The core product principle is:

"THE LLM DOES NOT OWN FINANCIAL TRUTH.
THE DATA LAYER OWNS FINANCIAL TRUTH."

AI is responsible for:

- understanding natural language
- planning
- deciding which tools are needed
- decomposing complex work
- orchestrating specialized agents
- asking clarifying questions
- explaining verified results
- generating report narratives

The AI must NOT be responsible for:

- inventing financial values
- manually calculating final numbers
- guessing missing data
- executing arbitrary SQL
- accessing arbitrary shell commands
- directly modifying financial source data

All financial facts must originate from deterministic queries/calculations against the supplied dataset.

============================================================
2. HACKATHON SCOPE
==================

IN SCOPE:

- Spend
- Vendor payouts
- Reconciliation
- Transactions
- Vendor analysis
- Category analysis
- Date ranges and comparisons
- Multi-turn follow-up questions
- Clarification
- Evidence-backed answers
- Confidence signaling
- Anomaly detection
- Reports
- CSV export
- Excel export
- PDF export
- Live agent execution timeline
- AI usage monitoring
- Model routing
- AI fallback
- Evaluation framework
- Observability

OUT OF SCOPE:

- Live banking API integration
- ERP integrations
- SAP / Oracle / NetSuite integrations
- Payment execution
- Real banking operations
- Stock market information
- Investment advice
- Tax filing
- Payroll
- Arbitrary financial advice
- Multi-tenant architecture
- Application-level end-user authentication
- User registration/login for normal users
- Support for every imaginable financial question

The system must explicitly refuse or explain requests outside the supported domain.

============================================================
3. RESPONSE STATE MODEL
=======================

Every user question must ultimately enter one of these states:

ANSWER
CLARIFICATION_REQUIRED
DATA_UNAVAILABLE
OUT_OF_SCOPE
ERROR

Behavior:

A) ANSWER
If question is supported and required data exists:

- query database
- calculate deterministically
- verify
- produce answer
- attach evidence
- attach confidence
- show execution timeline

B) CLARIFICATION_REQUIRED
If the question is valid but ambiguous:

- do not guess
- ask a concise clarifying question
- offer useful options where appropriate

Example:
"How much did we spend last month?"
Ask:
"Do you mean total spend, vendor spend, or category spend?"

C) DATA_UNAVAILABLE
If the question conceptually fits finance but required data is not present:

- explicitly state that the current dataset does not contain the required field/data
- do not estimate
- do not hallucinate

Example:
"How much GST did we pay?"
If GST data is absent:
"I can't reliably answer that because GST payment data is not present in the current dataset."

D) OUT_OF_SCOPE
If request is outside product capabilities:

- politely explain what the system supports
- suggest an in-scope alternative

Example:
"What is Apple's stock price?"
Response:
"I can analyze spend, vendor payouts, transactions, and reconciliation from the TBX dataset, but I don't have live market data."

============================================================
4. CORE ARCHITECTURE PRINCIPLE
==============================

Use a layered design:

USER
  ↓
NEXT.JS FRONTEND
  ↓
CLOUDFLARE
  ↓
CLOUDFLARE TUNNEL
  ↓
NGINX
  ↓
FASTAPI
  ↓
AGENT ORCHESTRATOR
  ↓
SPECIALIZED AGENTS
  ↓
TYPED FINANCE TOOLS
  ↓
QUERY COMPILER
  ↓
CLICKHOUSE
  ↓
DETERMINISTIC VERIFICATION
  ↓
EVIDENCE PACKAGE
  ↓
RESPONSE AGENT
  ↓
FINAL ANSWER

The LLM never directly owns the database result.

============================================================
5. EDGE / HOSTING
=================

Existing infrastructure:

- Hostinger VPS
- Ubuntu
- Domain: strawhatpirates-hackathon.tech
- Cloudflare already configured

Use:

Cloudflare

- DNS
- SSL/TLS
- WAF
- DDoS protection
- rate limiting
- Cloudflare Tunnel

Run cloudflared in Docker where practical.

Do NOT expose database ports to the public internet.

Preferred traffic:

Internet
  ↓
Cloudflare
  ↓
Cloudflare Tunnel
  ↓
cloudflared
  ↓
Nginx
  ↓
Frontend / API

The VPS should not require publicly exposed:

- PostgreSQL
- ClickHouse
- Redis
- MinIO
- Grafana
- Prometheus
- Loki
- Tempo
- Langfuse
- FastAPI
- Next.js

Only internal Docker networking should be used wherever possible.

============================================================
6. NGINX
========

Run Nginx as a Docker container.

Nginx responsibilities:

- internal reverse proxy
- frontend routing
- API routing
- SSE/WebSocket-compatible proxying where needed
- security headers
- compression
- request limits
- route separation
- dev/prod hostname routing

Production:
https://strawhatpirates-hackathon.tech

Development:
https://dev.strawhatpirates-hackathon.tech

Suggested routes:

/
  -> Next.js

/api/
  -> FastAPI

/events/
  -> FastAPI SSE/event stream

Admin/observability interfaces should NOT be publicly exposed without edge/network protection.

============================================================
7. APPLICATION SERVICES
=======================

Custom application containers:

1. tbx-frontend
2. tbx-api
3. tbx-worker

Do not split the application into dozens of microservices.

Use modular code inside the FastAPI application.

---

tbx-frontend
------------

Technology:

- Next.js
- TypeScript
- Tailwind CSS
- shadcn/ui
- Recharts/ECharts
- modern responsive UI

UX principles:

- premium
- clean
- dense but readable
- professional finance product
- avoid generic AI chatbot styling
- avoid excessive gradients/glow
- avoid "AI magic" marketing language
- use subtle animation
- use strong typography
- use data visualization heavily

Product feel:

- Abacus-style agent activity
- Linear-style interaction quality
- modern finance/BI product
- enterprise dashboard

Important UI features:

- chat
- live agent workflow
- expandable agent steps
- evidence drawer
- data table
- visualizations
- confidence indicator
- clarification UI
- report generation
- CSV/Excel/PDF export
- examples
- dark/light mode
- responsive desktop/mobile

---

tbx-api
-------

Technology:

- Python
- FastAPI
- Pydantic v2
- SQLAlchemy where appropriate
- Alembic
- LangGraph
- LiteLLM
- ClickHouse client
- PostgreSQL client
- Redis client
- OpenTelemetry
- Langfuse SDK

Responsibilities:

- REST API
- SSE streaming
- session management
- orchestration
- agent execution
- query planning
- tool execution
- verification
- evidence generation
- model routing
- fallback
- reporting APIs
- metrics
- audit/event tracking

---

tbx-worker
----------

Background jobs:

- report generation
- CSV ingestion
- validation
- dataset processing
- anomaly analysis
- large exports
- evaluation runs
- scheduled jobs
- cleanup

Use Redis-backed queueing.

Do not block FastAPI request threads/processes with long report generation jobs.

============================================================
8. AGENTIC AI ARCHITECTURE
==========================

The system MUST contain an explicit Agent Orchestrator.

Agent Orchestrator responsibilities:

- understand task complexity
- create a task plan
- determine whether delegation is needed
- delegate to specialized agents
- coordinate results
- monitor failures
- recombine results
- send results to verification
- initiate final response generation

Do NOT require sub-agents for every request.

Simple questions should remain simple.

Examples:

Simple:
"How many unreconciled transactions are there?"
→ orchestrator
→ finance tool
→ ClickHouse
→ verification
→ answer

Complex:
"Compare Acme's July and August payouts, determine if August was unusual based on six-month history, identify the transactions that caused the increase, and generate a report."
→ orchestrator
→ decompose
→ multiple specialists
→ parallel where appropriate
→ combine results
→ verification
→ response/report

---

AGENTS
------

1. Agent Orchestrator
2. Scope Agent
3. Intent & Entity Agent
4. Clarification Agent
5. Finance Query Agent
6. Analysis Agent
7. Verification Agent
8. Report Agent
9. Response Agent

Do not make every deterministic component an LLM agent.

---

DETERMINISTIC TOOLS
-------------------

These should be normal typed Python tools/services:

- resolve_vendor()
- resolve_category()
- get_transactions()
- get_vendor_payouts()
- get_unreconciled_transactions()
- calculate_spend()
- compare_periods()
- calculate_reconciliation_rate()
- detect_anomalies()
- build_evidence()
- verify_result()
- calculate_confidence()
- generate_report()

============================================================
9. LLM ARCHITECTURE
===================

Use a provider abstraction.

Application must NOT directly depend on one provider.

Use LiteLLM abstraction.

Providers:

PRIMARY:
Groq

FALLBACK:
OpenRouter

HEAVY/ADVANCED:
RunPod-hosted model

Routing should consider:

- query complexity
- task type
- latency requirement
- provider health
- cost
- model capability

Example:

LOW COMPLEXITY
→ fast Groq model

MEDIUM
→ stronger Groq model

HIGH
→ stronger model / RunPod

Provider failure:
Groq
  ↓
OpenRouter
  ↓
RunPod

Do not hardcode provider-specific logic throughout the application.

Create a model router abstraction.

IMPORTANT COST NOTE:
Groq/OpenRouter may have free-tier models/usage.
RunPod is NOT inherently free; use it only when credits/budget are available or when specifically configured.
Do not falsely claim RunPod itself is free.

============================================================
10. QUERY PLAN - CRITICAL
==========================

The LLM must produce a strict Pydantic QueryPlan.

Example:

FinanceQueryPlan:

- intent
- vendor_id
- category
- status
- date_range
- metric
- group_by
- currency

Never allow arbitrary free-form query objects.

Example:

User:
"How much did Acme spend last month?"

Model produces structured intent:

{
  intent: "vendor_spend",
  vendor_id: 182,
  date_range: "last_month",
  metric: "sum"
}

Then:

Pydantic validation
  ↓
Query compiler
  ↓
parameterized ClickHouse query

The LLM must NOT directly generate executable arbitrary SQL.

============================================================
11. QUERY COMPILER
==================

Create a dedicated Query Compiler.

Flow:

Natural language
  ↓
FinanceQueryPlan
  ↓
semantic validation
  ↓
authorization/policy validation
  ↓
Query Compiler
  ↓
safe parameterized ClickHouse query
  ↓
execution

Only approved fields/operations are allowed.

Use:

- allowlists
- parameterized queries
- statement timeouts
- result size limits
- read-only credentials
- explicit supported operations

Finance DB credentials must only have necessary permissions.

============================================================
12. CLICKHOUSE
==============

CLICKHOUSE IS THE PRIMARY FINANCIAL ANALYTICS DATABASE.

Store:

- transactions
- vendor payouts
- reconciliation
- vendors
- accounts
- financial data
- analytical structures

Use ClickHouse for:

- aggregation
- filtering
- grouping
- time-based analysis
- comparisons
- anomaly calculations
- reporting queries

Target financial query flow:

User
 ↓
Agent
 ↓
Typed finance tool
 ↓
ClickHouse
 ↓
result
 ↓
verification
 ↓
answer

Do not manually calculate final values in the LLM.

============================================================
13. POSTGRESQL
==============

PostgreSQL is the application/system database.

Store:

- conversations
- messages
- agent runs
- agent events
- report metadata
- evaluation metadata
- system configuration
- application metadata
- audit metadata

DO NOT use PostgreSQL as the main finance analytics engine.

Mental model:

ClickHouse = financial truth / analytics

PostgreSQL = application state

============================================================
14. REDIS
=========

Use Redis for:

- session context
- caching
- background task queues
- rate limiting
- short-lived state
- agent workflow support

Use key namespaces to avoid collisions.

============================================================
15. MINIO
=========

Use MinIO as S3-compatible object storage.

Use it for:

- uploaded datasets
- generated reports
- CSV exports
- Excel exports
- PDF files
- evaluation artifacts
- large evidence artifacts

If compatible with the Langfuse deployment, use separate buckets for:

- TBX application data
- reports
- evaluations
- Langfuse storage

Do not mix application objects with Langfuse internal objects without clear isolation.

============================================================
16. LANGFUSE
============

Use ONLY the self-hosted open-source Langfuse deployment.

No paid Langfuse cloud dependency.
No Enterprise-only features.
No proprietary hosted dependency.

Use Langfuse OSS for:

- LLM traces
- agent traces
- prompts
- generations
- token tracking
- model usage
- latency
- cost estimates
- evaluations
- datasets
- feedback
- experiment comparison
- agent execution observability

Use the official/current self-hosted architecture rather than inventing a custom Langfuse deployment.

Langfuse may use:

- ClickHouse
- PostgreSQL
- Redis/Valkey
- S3-compatible object storage
- Langfuse web
- Langfuse worker

Prefer reusing the existing infrastructure where safe while keeping logical/database isolation.

Do NOT directly manipulate Langfuse internal ClickHouse tables.

Use Langfuse SDK/API.

============================================================
17. OBSERVABILITY
=================

AI observability:
Langfuse OSS

Infrastructure/application observability:

- OpenTelemetry
- Prometheus
- Grafana
- Loki
- Tempo

Architecture:

Application
  ↓
OpenTelemetry
  ├── metrics → Prometheus
  ├── logs → Loki
  └── traces → Tempo

AI calls:
FastAPI / Agent
  ↓
Langfuse SDK
  ↓
Langfuse

Monitor:

- HTTP request rate
- HTTP latency
- p50/p95
- errors
- agent run duration
- LLM latency
- LLM tokens
- LLM cost
- model selection
- fallbacks
- tool execution
- ClickHouse latency
- queue depth
- report generation
- verification failures
- hallucination guard failures
- unsupported request rate

============================================================
18. AI ADMIN / CONTROL ROOM
===========================

There is NO end-user authentication.

Do NOT implement:

- login page
- signup
- user accounts
- password database
- Keycloak
- JWT user authentication
- application RBAC
- multi-tenant identity architecture

However, operational/admin/observability surfaces must not be left publicly exposed.

Use infrastructure/edge-level protection such as Cloudflare Access, private routing, VPN, or local-only access for admin tooling.

The normal application remains unauthenticated.

Admin dashboard should include:

KPI cards:

- AI requests
- tokens
- estimated cost
- average latency
- p95 latency
- fallback rate
- accuracy
- grounding
- verification pass rate

Charts:

- requests over time
- tokens over time
- cost over time
- latency
- provider usage
- model usage
- failures
- fallback frequency
- query complexity distribution

Live AI Control Room:

- currently active runs
- agent steps
- task duration
- selected model
- provider
- failures
- fallback events

Since users are not authenticated:
track:

- anonymous session ID
- conversation ID
- agent run ID

Do not call this "user-level" analytics unless a real authenticated user exists.

============================================================
19. LIVE AGENT UX
=================

The UI should visually show the agent workflow step-by-step.

DO NOT reveal hidden chain-of-thought.

Show auditable actions and outputs instead.

Example:

✓ Understanding request
✓ Resolving vendor
✓ Building query
✓ Querying financial records
✓ 284 records retrieved
✓ Calculating total
✓ Verification: 4/4 passed
✓ Preparing response

Expandable step:

"Vendor Resolution"
Input:
"Acme"

Result:
"Acme Technologies (#182)"

Source:
ClickHouse/vendor lookup

Duration:
83 ms

Another:

"Financial Calculation"
Operation:
SUM(amount)

Records:
284

Result:
₹12,431,842

The user must be able to see the actual work performed, without exposing private model reasoning.

============================================================
20. SSE / STREAMING
===================

Use Server-Sent Events for live agent execution updates unless WebSockets are genuinely necessary.

Possible events:

- run_started
- scope_checked
- intent_detected
- clarification_required
- task_created
- task_started
- tool_started
- tool_completed
- query_executed
- verification_started
- verification_completed
- answer_generated
- fallback_started
- fallback_completed
- run_completed
- run_failed

Frontend renders these events into a timeline.

============================================================
21. EVIDENCE / TRUST LAYER
==========================

Every successful answer must contain:

1. Natural language answer
2. Underlying records or breakdown
3. Calculation
4. Verification status
5. Confidence
6. Evidence/reference ID

Example:

Answer:
₹12,431,842

Details:

- Vendor: Acme Technologies
- Period: August 2026
- Records: 284
- Calculation: SUM(transaction.amount)

Verification:

- date range ✓
- vendor match ✓
- currency consistency ✓
- aggregate consistency ✓

Confidence:
High - 94%

Actions:
[View Evidence]
[Download CSV]
[Export Excel]

Every factual/numeric claim should be traceable to verified data.

============================================================
22. HALLUCINATION GUARDRAILS
============================

Implement multiple layers:

1. Pydantic structured outputs
2. Capability/scope validation
3. Data availability checks
4. Query validation
5. Deterministic computation
6. Verification engine
7. Answer claim validation
8. Evidence linkage

Example:
Database says:
₹12,431,842

LLM says:
₹14,431,842

Reject/regenerate.

The response composer should operate only on verified structured results.

============================================================
23. CONFIDENCE
==============

DO NOT ask the LLM "how confident are you?"

Calculate confidence from deterministic signals.

Example factors:

- exact entity match
- exact date range
- deterministic aggregation
- complete data
- no ambiguity
- verification passed
- currency consistency

Example:
0.90 - 1.00 = High
0.75 - 0.89 = Medium
<0.75 = Low

Confidence must reflect data/evidence quality, not model self-belief.

============================================================
24. DATA INGESTION
==================

Input:
TBX-provided CSV/Parquet files.

Expected data may include:

- transactions
- vendor payouts
- reconciliation status
- chart of accounts
- vendors
- data dictionary

Ingestion flow:

Files
 ↓
schema validation
 ↓
data type validation
 ↓
data cleaning
 ↓
duplicate detection
 ↓
referential checks
 ↓
data quality report
 ↓
ClickHouse

Data dictionary should become part of the system's metadata and scope/capability logic.

============================================================
25. DATA QUALITY
================

Create a data-quality subsystem.

Check:

- missing values
- invalid dates
- duplicate IDs
- invalid amounts
- currency inconsistencies
- invalid vendor references
- invalid account references
- reconciliation inconsistencies

Expose summary:

Rows
Valid %
Duplicates
Nulls
Validation failures

The system should distinguish:
"question is valid but data is insufficient"
from
"question is outside the product scope"

============================================================
26. ANOMALY DETECTION
=====================

Optional bonus capability.

Prefer deterministic/statistical logic:

- rolling average
- standard deviation
- z-score
- median
- ratio to historical average
- threshold checks

Example:

Historical average:
₹2.4L

Current payout:
₹14.2L

System:
5.9x historical average
→ anomaly candidate

LLM only explains the deterministic result.

============================================================
27. REPORTING
=============

Reports should be generated from the SAME finance query engine used by chat.

Do not create a second source of truth.

Flow:

Report request
 ↓
Report planner
 ↓
Finance query engine
 ↓
ClickHouse
 ↓
aggregations
 ↓
DuckDB/Python processing
 ↓
Plotly
 ↓
HTML/PDF/XLSX/CSV
 ↓
MinIO

Use:

- DuckDB
- Plotly
- openpyxl
- Jinja2
- Playwright or equivalent PDF rendering

Report types:

- Executive summary
- Spend overview
- Vendor analysis
- Reconciliation
- Monthly trend
- Category analysis
- Anomaly summary

The web UI should feel somewhat like a lightweight Tableau/Power BI experience.

============================================================
28. EVALUATION
==============

Create a golden evaluation dataset.

Target:
50-100 questions initially.

Categories:

- exact queries
- vendor queries
- date queries
- comparison
- grouping
- reconciliation
- multi-turn
- ambiguous
- unsupported
- missing-data
- adversarial
- complex multi-step

Measure:

- intent accuracy
- query plan accuracy
- vendor/entity resolution accuracy
- numeric accuracy
- grounding rate
- clarification accuracy
- unsupported-query handling
- multi-turn accuracy
- hallucination rate
- latency
- token efficiency
- cost/query

Evaluation must be executable automatically.

When model/prompt/tool schema changes:
run the golden dataset.

Use baseline comparison.

Potential regression thresholds:

- accuracy regression
- grounding regression
- hallucination increase
- latency increase
- token increase

============================================================
29. VERSIONING / REPRODUCIBILITY
================================

Every agent run should be traceable to:

- run ID
- Git commit
- dataset version
- model
- provider
- prompt version
- tool schema version
- query plan version
- timestamp

This makes results reproducible and explainable.

============================================================
30. PROMPTS
===========

Prompts must be versioned.

Examples:

- scope_guard_v1
- intent_classifier_v1
- query_planner_v1
- clarification_v1
- response_composer_v1
- anomaly_explainer_v1
- report_narrator_v1

Prefer storing prompts in a managed/versioned system such as Langfuse where practical.

Never scatter giant prompt strings throughout Python files.

============================================================
31. SECURITY
============

Even without end-user auth, implement strong application security.

Requirements:

- Cloudflare protection
- no public database ports
- Docker network isolation
- read-only finance DB credentials for agent
- parameterized queries
- SQL allowlist
- query timeouts
- row/result limits
- request size limits
- agent step limits
- tool timeouts
- provider timeouts
- API rate limiting
- security headers
- restrictive CORS
- secret management
- dependency scanning
- container scanning
- static analysis
- no secrets in Git
- no raw credentials in prompts
- no shell access from agents

Agent must NEVER be allowed to:

- execute arbitrary shell commands
- execute arbitrary SQL
- access Docker socket
- access environment secrets
- modify financial data

============================================================
32. LOGGING / PRIVACY
=====================

Do not dump raw financial datasets into normal application logs.

Prefer:

- IDs
- metadata
- counts
- timing
- hashes
- trace IDs

Sensitive values should be minimized/redacted in observability payloads when possible.

Store detailed evidence separately and securely.

============================================================
33. DOCKER
==========

Everything should be containerized.

Core custom services:

- tbx-frontend
- tbx-api
- tbx-worker

Infrastructure containers include:

- cloudflared
- nginx
- clickhouse
- postgres
- redis/Valkey
- minio
- langfuse-web
- langfuse-worker
- prometheus
- grafana
- loki
- tempo
- opentelemetry-collector

Do NOT create unnecessary containers for:

- LangGraph
- LiteLLM library
- DuckDB
- Plotly
- Pandas
- OpenPyXL

These can run inside application/worker containers.

Use Docker Compose for the hackathon.

Kubernetes is NOT required initially.

Architecture should remain portable to Kubernetes later.

============================================================
34. DOCKER NETWORKS
===================

Use isolated Docker networks.

Suggested:

tbx-edge

- cloudflared
- nginx

tbx-app

- nginx
- frontend
- api
- worker

tbx-data

- clickhouse
- postgres
- redis
- minio

tbx-observability

- langfuse
- prometheus
- grafana
- loki
- tempo
- otel collector

Only necessary services should join each network.

Example:
nginx must NOT have direct access to ClickHouse.

API/worker may access data networks.

============================================================
35. PERSISTENCE
===============

Use persistent Docker volumes.

Important data:

- ClickHouse
- PostgreSQL
- Redis where required
- MinIO
- Langfuse
- Grafana
- Prometheus
- Loki
- Tempo

Backups:

- database backups
- configuration backups
- important generated artifacts

Do not rely on Docker volume persistence as the only backup strategy.

Document backup and restore commands.

============================================================
36. DEVELOPMENT AND PRODUCTION
==============================

Environment separation is required.

DEV:
https://dev.strawhatpirates-hackathon.tech

PROD:
https://strawhatpirates-hackathon.tech

No dev container may accidentally use prod data.

Use:

- separate databases/schemas
- separate credentials
- separate environment files/secrets
- distinct environment variables
- distinct image tags

Use immutable image tags based on Git commit SHA.

Avoid relying on "latest" for production.

============================================================
37. GITHUB BRANCHING
====================

Use:

main
dev
feature/*

Flow:

feature branch
  ↓
PR
  ↓
dev
  ↓
automatic DEV deployment

dev
  ↓
PR
  ↓
main
  ↓
automatic PROD deployment

============================================================
38. CI/CD
=========

GitHub Actions.

On PR:

- checkout
- lint
- type check
- unit tests
- integration tests
- security scans
- build
- Docker build
- Docker vulnerability scan

Recommended tools:

- Ruff
- MyPy
- Pytest
- Bandit
- pip-audit
- Semgrep
- Trivy

Frontend:

- lint
- TypeScript check
- tests
- build

Deployment:
GitHub Actions
  ↓
build immutable Docker image
  ↓
push image
  ↓
deploy to VPS
  ↓
run migrations
  ↓
health checks
  ↓
smoke test
  ↓
success/rollback

============================================================
39. DEPLOYMENT STRATEGY
=======================

Do not copy source code manually as the normal production deployment mechanism.

Prefer:
GitHub
 ↓
Docker image
 ↓
registry
 ↓
VPS
 ↓
docker compose pull
 ↓
compose up

Production deployment should be repeatable.

Need:

- health checks
- rollback
- deployment logs
- failure notifications

============================================================
40. TERRAFORM
=============

Use Terraform for infrastructure management.

Potential responsibilities:

- Hostinger VPS resources where supported
- Cloudflare DNS/resources
- Cloudflare tunnel configuration where appropriate
- infrastructure-level configuration

Suggested:

infra/
  terraform/
    environments/
      dev/
      prod/
    modules/
      hostinger/
      cloudflare/

Terraform must NOT contain plain-text secrets.

============================================================
41. PROJECT REPOSITORY
======================

Recommended structure:

apps/
  api/
  web/

packages/
  contracts/

data/
  raw/
  processed/
  fixtures/

evaluation/
  golden_questions/
  expected_results/
  reports/

infra/
  docker/
  nginx/
  terraform/
  k8s/

scripts/
  backup
  restore
  seed
  evaluate
  ingest

docs/
  architecture.md
  security.md
  evaluation.md
  demo.md

.github/
  workflows/

prompts/
  ...

============================================================
42. FASTAPI MODULE STRUCTURE
============================

Prefer modular boundaries such as:

apps/api/app/

api/
agents/
auth/              <- DO NOT IMPLEMENT END-USER AUTH
config/
db/
models/
schemas/
services/
tools/
llm/
evaluation/
reports/
observability/
security/

Important service boundaries:

services/query_compiler.py
services/verification.py
services/confidence.py
services/model_router.py
services/evidence.py
services/scope.py
services/audit.py

============================================================
43. FRONTEND PAGES
==================

Public app:

/
 /chat
 /reports
 /transactions
 /vendors
 /reconciliation

Operational/admin surfaces:
 /admin
 /admin/ai-usage
 /admin/models
 /admin/evaluations
 /admin/accuracy
 /admin/system-health
 /admin/audit

Again:
No end-user authentication system.

Protect operational/admin surfaces at the infrastructure/edge level.

============================================================
44. CORE API ENDPOINTS
======================

POST /api/v1/chat
GET  /api/v1/chat/{run_id}
GET  /api/v1/chat/{run_id}/events

GET  /api/v1/conversations
GET  /api/v1/conversations/{id}

GET  /api/v1/transactions
GET  /api/v1/vendors
GET  /api/v1/reconciliation

POST /api/v1/reports
GET  /api/v1/reports/{id}
GET  /api/v1/reports/{id}/download

GET /api/v1/admin/usage
GET /api/v1/admin/models
GET /api/v1/admin/evaluations
GET /api/v1/admin/accuracy
GET /api/v1/admin/health
GET /api/v1/admin/audit

============================================================
45. AGENT STATE
===============

Agent state should explicitly contain things like:

- user_query
- session_id
- conversation_id
- scope_status
- intent
- entities
- query_plan
- tasks
- clarification_required
- tool_results
- verification_result
- evidence
- confidence
- response_type
- final_answer

Do not store private chain-of-thought as application state.

Store structured execution events, not hidden reasoning.

============================================================
46. AGENT TASK DELEGATION
=========================

Use an explicit task model.

Each task should contain:

- task_id
- type
- description
- assigned_agent
- status
- start time
- end time
- result
- error if any
- dependencies

Complex tasks can be decomposed.

Simple tasks remain direct.

Independent tasks may run in parallel.

The orchestrator decides.

============================================================
47. FAILURE HANDLING
====================

Failures must degrade gracefully.

Examples:

Groq unavailable:
→ OpenRouter
→ RunPod

Specialized agent unavailable:
→ retry
→ alternate supported strategy
→ partial answer if safe
→ clearly explain unavailable component

Database query fails:
→ retry if safe
→ do NOT fabricate

Verification fails:
→ do NOT answer as verified
→ regenerate/requery if safe
→ otherwise explain failure

No data:
→ DATA_UNAVAILABLE

Ambiguous:
→ CLARIFICATION_REQUIRED

Unsupported:
→ OUT_OF_SCOPE

============================================================
48. NO HALLUCINATION POLICY
===========================

If the system cannot prove the answer from available data, it must not answer with a number.

Preferred behavior:
"I cannot reliably answer that from the available data."

Never:
"I estimate..."
"Probably..."
"Based on typical spending..."
"I assume..."
unless clearly framed as non-financial illustrative content outside the answer.

For financial factual answers:
verified or refused.

============================================================
49. PERFORMANCE
===============

Optimize simple queries.

Desired behavior:

- low latency for simple lookup/aggregation
- only use additional agent calls when needed
- avoid huge prompts
- avoid sending raw transaction tables to LLM
- summarize results deterministically first
- send only relevant verified facts to response model

Model efficiency is an explicit hackathon scoring category.

============================================================
50. DATA SENT TO LLM
====================

Do NOT send entire datasets to models.

Instead send compact verified structures such as:

{
  vendor: "Acme Technologies",
  period: "2026-08",
  total: 12431842,
  record_count: 284,
  breakdown: [...]
}

Raw records should only be retrieved when genuinely required for evidence.

============================================================
51. REPORT ENGINE
=================

Reports must use the same Query Engine as chat.

No duplicated financial calculation logic.

Chat and reporting should share:

- data access
- business logic
- verification
- evidence

============================================================
52. ACCEPTANCE CRITERIA
=======================

The system is considered successful when all of these work:

"What did we spend with Acme last month?"
→ correct number

"What about the month before?"
→ uses conversation context

"Show unreconciled transactions"
→ deterministic result

"Compare July and August"
→ correct comparison

"How much GST did we pay?"
when GST data is absent
→ DATA_UNAVAILABLE

"What's Apple's stock price?"
→ OUT_OF_SCOPE

"How much did we spend?"
when ambiguity exists
→ CLARIFICATION_REQUIRED

Complex query
→ orchestrator delegates to multiple tasks

Provider failure
→ model fallback works

Every final answer
→ evidence + verification

Admin dashboard
→ tokens/cost/latency/model/fallback/evaluation

Report generation
→ PDF/XLSX/CSV

Git push to dev
→ DEV updates

Merge/push to main
→ PROD updates

All state survives container restart

============================================================
53. TESTING
===========

Write tests for:

Unit:

- Pydantic schemas
- scope classification
- query compiler
- date handling
- vendor resolution
- confidence
- verification
- anomaly detection

Integration:

- ClickHouse queries
- PostgreSQL
- Redis
- report generation
- Langfuse integration
- provider fallback

E2E:

- user question
- agent workflow
- streamed events
- final answer
- evidence
- exports

Evaluation:

- golden dataset
- regression tests

============================================================
54. DOCUMENTATION
=================

Create:

README.md

docs/
  architecture.md
  setup.md
  deployment.md
  security.md
  evaluation.md
  ai-routing.md
  observability.md
  demo-script.md

README must cover:

- architecture
- prerequisites
- local setup
- environment variables
- Docker setup
- database setup
- migrations
- ingestion
- evaluation
- deployment
- backup/restore
- troubleshooting

============================================================
55. CLAUDE CODE WORKING STYLE
=============================

Before writing code:

1. Inspect the current repository.
2. Inspect all existing files.
3. Preserve useful existing work.
4. Do not rewrite functioning components unnecessarily.
5. Identify gaps between current repo and this specification.
6. Propose a phased implementation plan.
7. Then implement incrementally.

Do NOT:

- invent APIs that don't exist
- install unnecessary libraries
- create unnecessary microservices
- add Kubernetes before it is needed
- add authentication
- add arbitrary financial capabilities
- bypass deterministic verification
- let an LLM execute arbitrary SQL
- expose database ports
- hardcode secrets
- use "latest" Docker images blindly in production
- create giant monolithic files

Prefer:

- typed interfaces
- Pydantic schemas
- dependency injection
- modular services
- explicit state machines
- clear domain boundaries
- testable components
- small reusable functions
- configuration-driven behavior
- environment-specific configuration
- immutable deployments

============================================================
56. IMPLEMENTATION ORDER
========================

Phase 1:
Repository + Docker foundation
FastAPI + Next.js
ClickHouse
PostgreSQL
Redis
MinIO

Phase 2:
TBX dataset ingestion
Data validation
Schemas
Finance query engine
ClickHouse queries

Phase 3:
Scope guard
Typed QueryPlan
Query compiler
Verification
Evidence
Confidence

Phase 4:
LangGraph orchestrator
Specialized agents
Task delegation
Multi-turn conversation
Clarification

Phase 5:
LLM routing
Groq
OpenRouter
RunPod
fallbacks
cost/latency tracking

Phase 6:
Live agent timeline
SSE
Evidence UI
tables/charts
polished UX

Phase 7:
Reports
CSV
XLSX
PDF
dashboard analytics

Phase 8:
Langfuse OSS
OpenTelemetry
Prometheus
Grafana
Loki
Tempo

Phase 9:
Evaluation framework
golden questions
accuracy metrics
regression tests

Phase 10:
Terraform
Cloudflare
Docker deployment
GitHub Actions
DEV/PROD automation
backup/restore
security hardening

============================================================
57. DEMO EXPERIENCE
===================

The final demo should feel like an AI finance analyst, not a generic chatbot.

Demo sequence:

Ask:
"How much did we spend with Acme last month?"

Show:

- understanding
- entity resolution
- query
- records
- calculation
- verification
- answer

Ask:
"What about the month before?"

Show:

- context reuse
- comparison
- chart

Ask ambiguous question.

Show clarification.

Ask unsupported question.

Show safe refusal.

Ask complex anomaly/comparison question.

Show orchestrator:

- task decomposition
- parallel subtasks
- tool execution
- results
- verification
- synthesis

Open evidence.

Generate report.

Open AI Control Room.

Show:

- requests
- tokens
- cost
- model
- latency
- fallback
- evaluation
- accuracy

============================================================
58. PRODUCT POSITIONING
=======================

Core positioning:

"An AI-native financial analyst whose answers are grounded in deterministic financial computation."

Key messages:

- Real data, not hallucinated numbers
- AI proposes; data computes
- Every answer is traceable
- Ambiguity triggers clarification
- Missing data triggers transparency
- Unsupported requests are refused safely
- Complex tasks can be delegated to specialized agents
- Model routing optimizes quality, latency and cost
- Full AI observability
- Reproducible Docker deployment
- Open-source/self-hosted architecture
- Built for real business impact

Potential product tagline:

"Ask. Analyze. Verify. Decide."

============================================================
59. IMPORTANT ARCHITECTURAL DISTINCTIONS
========================================

Keep these distinctions clear in code and documentation:

Agent Orchestrator
≠ Model Router

Agent
≠ Deterministic Tool

ClickHouse
= Financial analytics/source of truth

PostgreSQL
= Application state

Langfuse
= AI observability/evaluation

Prometheus/Grafana/Loki/Tempo
= infrastructure/application observability

Cloudflare
= edge protection

Nginx
= reverse proxy

Cloudflare Tunnel
= secure outbound tunnel

Frontend
= presentation

FastAPI
= application/API/orchestration host

Worker
= background processing

============================================================
60. FINAL ENGINEERING RULE
==========================

When choosing between:
"more AI"
and
"more deterministic engineering"

for a financial fact,
choose deterministic engineering.

The system should never be impressive because it talks confidently.

It should be impressive because:

- it understands the question,
- does the correct work,
- proves the result,
- explains the result,
- and knows when NOT to answer.

Build the platform accordingly.
