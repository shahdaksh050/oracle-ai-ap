# AI-native enterprise oracle · AP pilot implementation plan

## Outcome and authority

Deliver one Indian enterprise a day-90 accounts payable pilot. A clerk uploads an invoice, inspects extracted fields and their source, matches each line to purchase orders and goods receipts, resolves exceptions, and submits a versioned proposal. Finance authorizes an internal payment queue entry. Posting and settlement continue in the enterprise finance system. Start with one legal entity, domestic INR purchases, and one supplier cohort. Source: [six-page technical blueprint](ai_native_oracle_blueprint.pdf).

## Schedule, dependencies, and owners

| Days | Owner | Work and exit evidence |
| --- | --- | --- |
| 1–10 | Founder and client finance lead | Select sponsor, AP reviewer, executive approver, and infrastructure contact. Agree eligibility, approval roles, approved hosting, retention, throughput, cost ceiling, and baseline handling time and exceptions. Secure permission for labelled invoices, vendor masters, orders, receipts, and finance decisions. Continue synthetic work if onboarding slips and reforecast the external launch. |
| 11–30 | Infrastructure engineer and architect 1 | Provision PostgreSQL/pgvector, document storage, authenticated tenant context, LangGraph checkpoints and the interceptor. Demonstrate one synthetic queue entry, two-tenant isolation, and crash-safe approval. |
| 31–45 | Architect 2 and AP reviewer | Ingest Tally/CSV exports, PDFs, scans and phone images. Preserve source evidence. Match quantities and amounts, validate versioned GST checks, and route exceptions. Trace every payable line back to evidence. |
| 46–60 | Software/QA engineer and both architects | Deliver React/Tailwind evidence review, approval inbox, queue, and audit. Generate and test a supplier adapter through staging. Demonstrate clean, disputed, and executive cases. |
| 61–80 | Founder and QA | Replay history, then run incoming invoices alongside existing AP without live queue writes. Compare extraction, matching, tax decisions, routing, and amounts. Rehearse restore, replay, and rollback. |
| 81–90 | QA and client finance lead | Enable internal writes for the signed-off team and suppliers. Reconcile counts and amounts daily for five business days. Expand only after finance sign-off. Return to shadow on any isolation, approval, duplicate, or reconciliation failure. |

## Engineering decisions

- Store original documents encrypted by tenant. Keep vendors, invoices, lines, orders, receipts, approvals, queue entries, and their evidence relationships in PostgreSQL. Use tenant-scoped vector retrieval for context. Use fixed-precision financial arithmetic. Keep originals, corrections, reviewer, reason, and source location.
- The LangGraph manager issues a bounded strict JSON plan to Ingestion_Pod, Validation_Pod, Database_Pod and API_Synthesis_Pod. The runtime owns the mandatory Guardrail_Verification_System. Session identity supplies tenant and role. Persist workflow checkpoints and route exhausted work to review.
- Parse generated Python and SQL with explicit allowlists. Run generated integrations against synthetic fixtures in gVisor with a three-second execution budget, 128 MB memory, no production credentials, and blocked network. Enforce deterministic rules at commit. Use forced PostgreSQL row-level security and a restricted application role. Keep models, evidence, telemetry, and backups inside approved infrastructure.
- Default to exact three-way matching. Hold uncertain suppliers, unsupported invoices, tax exceptions, missing or partial receipts, duplicates, and mismatches. Finance approves effective-dated GST policy and any tolerances. Every queue entry needs human approval. A proposal or batch above ₹5,00,000 requires executive approval. Send a limited notification through an approved channel. In-app approval binds exact proposal contents and version. Edits invalidate prior approval.
- Use stable business and request identities, recheck receipt availability and authority under lock, and commit queue entry, allocation, audit and outbox together. Include crash-after-commit and concurrent-reviewer verification.
- Render only validated component specifications through React. Authorize actions server-side. The synthesis worker proposes adapters, schema or API changes. The auditor returns status, risk_score, detected_anomalies, and refactored_code. Rerun inspection, sandbox and regression tests on repairs. Escalate after two failed repairs. QA signs production releases, including telemetry-generated improvements.

## Release gates

| Gate | Evidence |
| --- | --- |
| Accuracy | At least 200 independently finance-labelled held-out invoices covering clean files, poor scans, duplicates, partial receipts, and tax exceptions. At least 98% exact match on critical fields before correction. Report per field, format, and review rate. All ready proposals agree with finance on supplier, amount and receipt match. |
| Authority | Test ₹4,99,999.99, ₹5,00,000.00 and ₹5,00,000.01, changed and expired proposals, duplicate clicks, and concurrent approval. Exactly one valid approval chain per entry. |
| Isolation and recovery | Test tenant boundaries for documents, search, checkpoints, UI actions, logs and exports. Exercise timeout, memory limit, notification outage, worker restart, and backup restore. Zero observed unauthorized writes, leaks or duplicates. |
| Value and capacity | Sustain twice agreed peak for one hour. Compare queue age, errors, review rate, latency, cost per invoice and human handling time to baseline. Target 25% lower median human handling time including corrections. |
| Launch | Client finance and QA approve. Record every reconciliation result. On failure disable new writes, keep intake in shadow, preserve and reconcile committed records, retest failed gate before re-enabling. |

The founder and finance lead ratify numerical targets by day 10 before evaluation. Measure concurrent successful workflows, cost per completion, and time from approved change to tested staging deployment. After the pilot, expand vendor formats and ERP reads, then AR reconciliation, transport ingestion/routing and supplier negotiation drafts. ERP posting and bank initiation are separate releases with authorization, idempotency, reconciliation and reversal procedures.
