# Agent memory

## Current handoff for 20 November 2026

**Milestone:** the synthetic AP pilot runs locally. External client onboarding and live acceptance are pending. Start with [setup and operations](README.md) and the [release gates](IMPLEMENTATION_PLAN.md).

| Workstream | Current evidence |
| --- | --- |
| Infrastructure | Local PostgreSQL 16.2 and pgvector 0.6.2. Five checksum-tracked SQL migrations. Restricted application login, forced tenant policies, two isolated synthetic tenants, and encrypted originals. Real PostgreSQL dump restored and reconciled in a separate test database. |
| AP workflow | Browser-tested PDF upload, page evidence, three-way match, clerk submission, separate finance approval and queue. Invoice DC-1042 reconciled to one entry for INR 1,180.00. Tests cover batches, paise boundaries, versioning, receipt allocations, mode changes, and crash-safe replay. |
| Ingestion and agents | LangGraph executes bounded pods with durable PostgreSQL stage checkpoints. Local OCR read the synthetic image text `number: OCR-1042` and retained its page and bounding box. Configurable private vision and UI generation have typed output boundaries. Search uses tenant-scoped pgvector lexical embeddings. |
| Staging and operations | Source auditing, offline synthetic fixture generation, a gVisor runner contract, independent QA release, telemetry, outbox backoff, bounded recovery, and recurring supplier-format proposals are implemented. The single-cycle maintenance worker completed against the local tenant. Notification channel was unconfigured. |
| Evaluation | Held-out scoring and synthetic capacity tools have regression coverage. A one-record capacity smoke test exercised actual PDF intake and matching. Client accuracy, cost, sustained capacity and handling-time reductions remain unmeasured. |

**Working defaults.** The local dashboard is served from the FastAPI process at http://127.0.0.1:8765. Rebuild the frontend before starting that process. The sample invoice, generated sign-in keys, encrypted-document key and local PostgreSQL credentials reside under the ignored .runtime directory. Keep secrets out of this file. The two synthetic tenants start with internal queue writes enabled. Real client tenants start in shadow.

**Next dependencies, by owner.**

1. Founder and client finance lead select the enterprise, supplier cohort and named approvers, sign data and hosting permissions, approve the effective-dated GST policy, and establish the day-10 workload, baseline and budget.
2. Infrastructure and QA run the marked sandbox test on an approved Linux gVisor host with a pinned image. This Windows host has neither Docker nor an installed WSL distribution. Actual CPU/memory containment, a positive staging run and live QA promotion remain open. A test double only verified release-state transitions.
3. Infrastructure configures approved inference, encrypted object storage and notification endpoints, deploys the tenant worker, then tests delivery and full-environment recovery. Local tests exercised OCR, encrypted database storage, and simulated external-service responses.
4. Finance and QA evaluate at least 200 independently labelled invoices, run the one-hour twice-peak test, review handling time and cost, and sign the launch decision. After release, reconcile against the client ledger for five business days. ERP posting, banking, AR and SCM are later releases.

## Historical progress log

### Starting state

The workspace began with ai_native_oracle_blueprint.pdf only. The user selected AP-first, internal approved writes and a pilot client to be selected. IMPLEMENTATION_PLAN.md is the delivery and release contract. The application must never initiate payments.

### Initial decisions

- Planning complete. Read all six pages, recorded the schedule, responsibilities, architecture and release gates.
- Environment discovery complete. Windows, Python launcher, uv and Node available. Docker, psql and installed WSL distributions were absent. Try workspace-local PostgreSQL 16 and pgvector for integration evidence.
- Next task: establish the data model, implement the workflow and verify with two synthetic tenants.
- External dependencies: founder selects client, client approves hosting and provides labelled records, tax policies and sign-off. Keep synthetic and client evidence separate.

### Foundation verified

`uv sync` and `npm.cmd install --prefix web` installed locked dependencies. `uv run python -m ap.admin init` initialized a workspace-local, password-authenticated PostgreSQL 16 cluster with pgvector, applied migration 001, and seeded two tenants. Database port 55439 is loopback-only. Runtime credentials and synthetic access keys are ignored under .runtime. Next verify the AP workflow against the restricted role.


### Operator workflow verified

React production build passed. Playwright drove Chrome against the running FastAPI server: signed in as saffron clerk, uploaded the generated PDF, inspected page-linked fields and GR-230 (10 units), submitted invoice DC-1042, signed in as a separate finance user, and approved it. The payment queue showed INR 1,180.00. Independent admin reconciliation returned one record totalling INR 1180.00. The demo queue contains this synthetic transaction. Next verify boundary, concurrency, crash, isolation and restore cases in a separate test database.


### Financial and operational checks

Fifteen integration tests passed on PostgreSQL. Covered single and aggregate executive thresholds, batch invalidation, receipt allocation races, whole-batch rollback, shadow and expiry, row isolation, document access, saved workflow resumption, notification outage, CSV replay, atomic failure before commit, concurrent retries and pg_dump/pg_restore reconciliation. Adapter AST inspection rejected unsupported code and missing gVisor prevented release. No live channel or client records were used. Next verify OCR and final build, document setup and provide a held-out evaluation runner.


### Final verification

- `uv run python -m pytest -q` finished with **21 passed, 1 skipped**. The conditional gVisor test requires a genuine Linux runner and pinned image.
- `uvx ruff check ap tests` and `uvx ruff format --check ap tests` passed. `uv lock --check` confirmed the Python lockfile. `npm.cmd run build --prefix web` produced the React assets.
- The latest UI reopened the persisted invoice and rendered the Operations view. `python -m ap.admin reconcile` reported one entry for INR 1180.00.
- During verification the capacity smoke test exposed a fixture writer that converted an in-memory stream to a filename. The writer now accepts streams and filesystem paths. The rerun passed.
- Resume external qualification with the owner-specific dependencies above. Use `python -m ap.worker --tenant saffron --once` for a local worker check.

### Windows launcher

Run `.\run.ps1` from PowerShell to start the synthetic workspace. Verified reuse of the running dashboard when invoked from another directory, a frontend build and new server launch on a separate port, authenticated database access as the Saffron clerk, and rejection of an occupied port. The original dashboard remains available on port 8765.
