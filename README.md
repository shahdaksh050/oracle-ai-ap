# Enterprise Oracle · AI-Native Accounts Payable (AP)

> **Blueprint Reference:** Faithfully aligned with [ai_native_oracle_blueprint.pdf](ai_native_oracle_blueprint.pdf)  
> **Domain:** Indian Enterprise Accounts Payable (AP), 3-Way Matching, GST Compliance & Zero-Trust Guardrails.

---

## Project Contributors & Submission Info

- **Primary Builder:** Daksh (Candidate / Applicant)
- **Cobuilder:** *(Optional Co-Applicant)*
- **Target Remote:** WildCatter GitHub Repository
- **Evaluation Deployment:** Live Demo Ready via Render / Docker Compose / Native Desktop App

---

## 1. Executive Summary

This platform implements an **AI-Native Accounts Payable (AP) Automation Platform** specifically tailored for Indian enterprises handling domestic INR purchases, PO matching, and strict statutory GST policies. 

Instead of legacy static ERP menus, the suite operates as an **agentic workspace** governed by:
1. **Hierarchical Swarm (LangGraph):** Sequential pods (`Ingestion_Pod` → `Validation_Pod` → `Database_Pod` → `API_Synthesis_Pod`) with durable PostgreSQL checkpoints.
2. **Three-Stage Security Interceptor:** Zero-trust code and transaction validation (AST parser → gVisor container sandbox contract → hardcoded rule matrix).
3. **Strict Financial Precision:** 3-way matching across Invoices, Purchase Orders (PO), and Goods Receipts (GRN) calculated using Python's `Decimal` with paise rounding (`ROUND_HALF_UP`) and PostgreSQL Row-Level Security (RLS).
4. **Dual Modality (Desktop + Web):** Functions natively both as a **standalone desktop application** (dedicated OS window / PWA) and a **cloud-ready web application** with live deployment on Render.
5. **Open Extensible APIs:** Full OpenAPI 3.1 REST API specification enabling external autonomous agents, ERPs, and third-party developers to build over this platform.

---

## 2. Architecture & Blueprint Mapping

```mermaid
flowchart TD
    subgraph Client Layer
        A["Enterprise User / Evaluator"] --> B["Natural Language Search (JIT UI)"]
        A --> C["React / Tailwind Dashboard"]
        A --> D["Native Desktop App (Edge/Chrome App Mode)"]
    end

    subgraph Layer 2: Hierarchical Multi-Agent Bus (LangGraph)
        B --> E["Prompt A: Orchestrator / Dispatcher"]
        E --> F["Ingestion_Pod<br/>(Gemini/OpenAI Vision + RapidOCR)"]
        F --> G["Validation_Pod<br/>(3-Way Match & Paise Math)"]
        G --> H["Database_Pod<br/>(PostgreSQL 16 + pgvector)"]
        E --> I["API_Synthesis_Pod<br/>(Supplier Adapters)"]
        E --> J["Telemetrist / Self-Healing Agent<br/>(Anomaly Detection & Maintenance)"]
    end

    subgraph Layer 3: The Oracle Security Interceptor
        I --> K["Stage 1: Static AST Firewall<br/>(Allowlist & SELECT-only SQL)"]
        K --> L["Stage 2: Virtual Sandbox<br/>(runsc / gVisor: 3s, 128MB, No Net)"]
        L --> M["Stage 3: Deterministic Rule Matrix<br/>(₹5,00,000 Cap, Forced RLS)"]
    end

    subgraph Layer 1: Relational & Vector Storage
        H --> N[("PostgreSQL + pgvector<br/>Tenant RLS Isolation")]
        M --> O[("Authorized Internal<br/>Payment Queue")]
    end
```

### Direct Alignment with `ai_native_oracle_blueprint.pdf`

| Blueprint Component | Specification | Code Implementation | Status |
| :--- | :--- | :--- | :---: |
| **Layer 1: AI-ETL & Hybrid Graph** | pgvector dynamic storage & context RAG | `ap/documents.py`, `migrations/001_pilot.sql` | **Active** |
| **Layer 2: Agent Swarm** | LangGraph bounded execution bus | `ap/workflows.py` (`StateGraph`, checkpoints) | **Active** |
| **Stage 1 AST Firewall** | Block system calls (`os.system`, `subprocess`) & check SQL | `ap/adapters.py` (`audit()`, `inspect_sql()`) | **Active** |
| **Stage 2 Virtual Sandbox** | gVisor micro-VM (3s ceiling, 128 MB RAM, `--network=none`) | `ap/adapters.py` (`sandbox()`, `rules.json`) | **Active** |
| **Stage 3 Hardcoded Matrix** | Movements > ₹5,00,000 freeze state for Executive approval | `ap/policy.py`, `migrations/001_pilot.sql` | **Active** |
| **Driver-Level Partitioning** | Force `tenant_id` & `user_role` injection via session | `ap/db.py` (`set_config`), Postgres `FORCE RLS` | **Active** |
| **Just-In-Time UI** | Dynamic React/Tailwind frontend | `web/src/main.jsx` (JIT cards & query engine) | **Active** |
| **Desktop Application** | Native desktop OS window / PWA manifest | `desktop.py`, `run.ps1 -Desktop`, `manifest.json` | **Active** |
| **External APIs** | REST endpoints with interactive Swagger docs | `ap/api.py` (`/docs`, `/openapi.json`) | **Active** |

---

## 3. How Autonomous AI Agents Eliminate Manual AP Work

This solution is **100% AI-native**, orchestrated through LangGraph state machines and autonomous background workers to systematically eliminate manual, physical, and error-prone Accounts Payable labor:

| Manual Accounts Payable Step | Autonomous AI Agent Replacing It | Mechanism in Code |
| :--- | :--- | :--- |
| **Manual Data Entry & Keying** | **Ingestion Pod (Vision AI + OCR)** | `ap/documents.py`: Employs Gemini 1.5 / OpenAI Vision and RapidOCR to transcribe PDFs/images into validated `Invoice` Pydantic models with page-level bounding boxes. Zero re-typing. |
| **Manual 3-Way Matching** | **Validation Pod (Rule Engine)** | `ap/workflows.py`: Automatically correlates line items against seeded Purchase Orders (`PO-410`) and Goods Receipts (`GR-230`), calculating exact price discrepancies and unbilled quantities. |
| **Tax & GST Calculation** | **Statutory Tax Compliance Agent** | `ap/policy.py`: Enforces domestic Indian GST rates (CGST + SGST or IGST) with strict paise rounding (`ROUND_HALF_UP`) using Python `Decimal`. |
| **Writing Vendor Parsers** | **API Synthesis Pod (Auto-Coding)** | `ap/adapters.py`: Automatically generates and synthesizes declarative Python projection code when a new supplier format is encountered. |
| **Runtime Error Diagnostics** | **Telemetrist & Self-Healing Agent** | `ap/worker.py`: Runs every 5 minutes; detects repeated clerk corrections for unfamiliar labels, automatically stages adapter corrections, and resumes stalled jobs. |
| **Code & SQL Security Auditing** | **Security Interceptor Agent** | `ap/adapters.py`: Validates all proposed adapter scripts against a static AST whitelist and SQL abstract syntax tree before execution. |
| **Manual Menu Traversal** | **JIT NLP Orchestrator (Prompt A)** | `ap/api.py` (`/api/view`): Evaluates natural language queries (e.g., *"show pending approvals"*, *"show telemetry"*) and synthesizes tailored UI views on-the-fly. |

---

## 4. Quickstart Guide (Desktop & Web)

### Option A: Desktop Application Mode (Windows)
Run the desktop launcher to open the application in a standalone OS window (without browser navigation bars or tabs):
```powershell
.\run.ps1 -Desktop
# or
python desktop.py
```
*Also supports Progressive Web App (PWA) installation directly from Chrome/Edge via the `Install App` address bar icon.*

### Option B: Web Application Mode (Local Browser)
```powershell
.\run.ps1
```
*Starts PostgreSQL with pgvector, compiles the frontend bundle, and hosts the workspace at `http://127.0.0.1:8765`.*

### Option C: Docker Compose (Cross-Platform / Linux / macOS)
```bash
docker compose up --build
```
*Runs an isolated `pgvector/pgvector:pg16` cluster alongside the application container on port `8765`.*

### Option D: Linux / macOS (Native Shell)
```bash
chmod +x run.sh
./run.sh
```

### Option E: 1-Click Live Cloud Demo on Render
The repository includes a ready-to-deploy [render.yaml](render.yaml) blueprint:
1. Push this repository to GitHub.
2. Sign in to **[Render.com](https://render.com)**.
3. Click **New +** → **Blueprint** → Select your GitHub repository.
4. Render automatically provisions the Docker container and launches your public live demo URL (e.g., `https://oracle-ai-ap.onrender.com`).

---

## 5. Developer & Agent API (Build Over This Platform)

The platform is designed API-first. Any external autonomous agent, ERP system, or third-party service can build on top of our endpoints:

- **Interactive Swagger Documentation:** [http://127.0.0.1:8765/docs](http://127.0.0.1:8765/docs)
- **Raw OpenAPI 3.1 JSON Schema:** [http://127.0.0.1:8765/openapi.json](http://127.0.0.1:8765/openapi.json)

### Core Integration Endpoints

| Endpoint | Method | Description |
| :--- | :---: | :--- |
| `/api/workflows` | `POST` | Ingest and process an invoice document (PDF / image) |
| `/api/workflows` | `GET` | List active workflows, extraction states, and 3-way match statuses |
| `/api/workflows/{id}/submit` | `POST` | Programmatically transition an invoice to pending approval |
| `/api/workflows/{id}/approve` | `POST` | Authorize and commit an invoice to the internal payment queue |
| `/api/queue` | `GET` | Fetch authorized payment queue ledger |
| `/api/view?q={query}` | `GET` | Natural Language dynamic JIT view routing for external chatbots |
| `/api/security/audit` | `POST` | Programmatically audit arbitrary Python / SQL against the 3-Stage AST Firewall |

### Integration Code Snippet (Python Example)

```python
import httpx

API_BASE = "http://127.0.0.1:8765/api"
CLERK_KEY = "Mx_-YEv-3sSdg9bGM1ej-6jiBVAuTFQJmCYjSS-gA2M"
headers = {"Authorization": f"Bearer {CLERK_KEY}"}

# 1. Ingest an invoice programmatically
with open("invoice.pdf", "rb") as f:
    res = httpx.post(f"{API_BASE}/workflows", headers=headers, files={"file": f})
workflow_id = res.json()["workflow_id"]

# 2. Query extraction and 3-way match status
status = httpx.get(f"{API_BASE}/workflows/{workflow_id}", headers=headers).json()
print("3-Way Match Status:", status["fields"]["status"])

# 3. Query via Natural Language JIT engine
view = httpx.get(
    f"{API_BASE}/view",
    headers=headers,
    params={"q": "show pending approvals"},
).json()
print("Target Component:", view["component"])
```

---

## 6. Evaluator Test Drive (5-Minute Tour)

Open **[http://127.0.0.1:8765](http://127.0.0.1:8765)** in your browser or desktop app window.

### Pre-Configured Demo Accounts (`.runtime/demo-keys.json`)

| Role | Username | Access Key | Permissions |
| :--- | :--- | :--- | :--- |
| **AP Clerk** | `saffron-clerk` | `Mx_-YEv-3sSdg9bGM1ej-6jiBVAuTFQJmCYjSS-gA2M` | Ingest invoices, edit corrections, submit proposals |
| **Finance Approver** | `saffron-finance` | `C8vu2IYed5X7uw9V24oTkzLnGpFsm4g6SzVKsKC-5rs` | Authorize proposals up to ₹5,00,000.00 |
| **Executive** | `saffron-executive` | `nKgDGoY1U_6Ak9LrOJKCEpd5dmXekUp-hl9CsB3CmzY` | Authorize high-value proposals > ₹5,00,000.00 |
| **QA Engineer** | `saffron-qa` | `yM5paJ7ZX0IZhZNljbK1U50hFsp3bsdykDeiZmOB4_o` | Release staged supplier adapters after sandboxing |

---

### Step-by-Step Test Scenarios

#### Scenario 1: Invoice Ingestion & 3-Way Matching
1. Sign in as **`saffron-clerk`**.
2. Upload `.runtime/supplier-invoice.pdf` (or any PNG/JPEG scan).
3. Line items are automatically matched against **PO-410** and warehouse receipt **GR-230**.
4. Click any extracted field link (e.g., `p.1`) to inspect source document coordinates.
5. Click **"Submit for approval"** (transitions state from `ready` → `pending`).

#### Scenario 2: Separation of Duties & Financial Caps
1. Sign out and sign in as **`saffron-finance`**.
2. Open the submitted invoice from the inbox.
3. Click **"Approve and queue"**. Receipt units are allocated under transactional database lock and committed to the **Payment Queue**.
4. Check the **"Payment queue"** tab to view the ledger.
5. *Executive Escalation Test:* Any batch or invoice exceeding ₹5,00,000 automatically freezes finance autonomy and requires **`saffron-executive`** credentials to approve.

#### Scenario 3: The 3-Stage Security Interceptor & AST Firewall
The 3-stage security architecture can be tested via Swagger UI at **`/docs#/default/security_audit_api_security_audit_post`** or automated tests (`tests/test_sandbox.py`):
1. **Malicious OS Call Audit:** Send `POST /api/security/audit` with payload `{"code": "def adapt(row):\n    import os\n    os.system('cat /etc/passwd')\n    return {'number': row['bill_no']}"}`
   * *Result:* **Stage 1 AST Firewall rejects it immediately** with `Risk Score: 1.0` and flags `Adapter exceeds the approved projection grammar`.
2. **Unauthorized SQL Modification Audit:** Send `POST /api/security/audit` with payload `{"sql": "DELETE FROM vendor WHERE 1=1"}`
   * *Result:* **SQL Struct Checker terminates the transaction**, rejecting write statements and permitting only read queries.
3. **Approved Clean Projection Audit:** Send clean Python adapter projection with valid `aliases`.
   * *Result:* **Approved** with `Risk Score: 0.0`.

#### Scenario 4: Natural Language Workspace Querying (JIT UI)
1. In the top search bar, type plain English queries:
   * `"show pending approvals"` → automatically navigates and filters the inbox to awaiting approvals.
   * `"show telemetry"` → routes to the Operations p95 latency monitor.
2. The dynamic router resolves queries to structured view specifications (`GET /api/view?q=...`) with zero hardcoded routing tables.

#### Scenario 5 (Optional): Live Vision AI with Gemini / OpenAI
* Set your API key in your environment before starting:
  ```bash
  export GEMINI_API_KEY="your-google-ai-studio-key"
  # or
  export OPENAI_API_KEY="your-openai-key"
  ```
* Upload any random, unstructured invoice document. The system will automatically use multi-modal vision to transcribe fields and map source evidence in real time.

---

## 7. Operator Workflow

- **Intake and evidence.** Upload a PDF of up to 12 pages, or a PNG/JPEG, up to 8 MiB. The local parser handles labelled invoice fields. The bundled OCR reads scanned documents and records page coordinates. A configured private vision model can read unfamiliar layouts. Uncertain results go to the clerk with the original. Review fields and record an evidence page and reason, or dismiss a duplicate. The audit history retains previous values.
- **Matching.** The policy covers domestic INR purchases of goods with matched vendor, buyer, order terms, HSN, GST components, quantities and receipts. Monetary computations use decimals and paise rounding. Unsupported cases remain in review. The seeded order is PO-410 for BR-20, with receipt GR-230.
- **Approval.** Submit a ready invoice, or select two or more ready rows to form a batch. Above ₹5,00,000, use the executive account. Inspect batch members and their total before approving. Edits invalidate the pending authorization. The write rechecks quantities, reserves receipts and commits approval, queue, audit and outbox together. Replayed approvals are idempotent.
- **Shadow and rollback.** Run `uv run python -m ap.admin shadow --tenant saffron`. Intake and review continue. Toggling queue mode advances the authority version. Previously pending proposals require fresh review and submission. Use `enable` to reopen the synthetic queue after rehearsal. Inspect the internal count and amount with `reconcile`. Pass an independent cumulative finance ledger with columns `business_key,amount` using `reconcile --tenant saffron --file ledger.csv`. Any difference returns a failing exit code and switches that tenant to shadow mode.
- **History and operations.** Workspace search can select the queue, approval inbox, exception list, telemetry, or tenant-scoped vector history. The synthetic embedding is a 128-dimensional lexical hash. Operations reports worker p95 latency, queue age, workflow counts, and notification delivery failures. Start `python -m ap.worker --tenant TENANT` under the approved process supervisor. It delivers notifications every 15 seconds and runs maintenance every five minutes. Use `--once` for a single cycle. Each run resumes at most one stalled workflow and sends persistent failures to review. The telemetrist detects repeated, finance-approved corrections for an unfamiliar PDF label and stages a supplier adapter through the same sandbox and independent QA release path.
- **Supplier adapters.** A clerk can stage a supplier label mapping. The Python AST auditor accepts only the declared projection. Generated SQL is limited to the tenant-bound vendor read shape. A separate QA user can release a mapping after its synthetic fixture passes the gVisor runtime. The extraction service applies the approved declarative mapping. Set `AP_GVISOR_TEST_IMAGE` to the pinned image digest reference on the dedicated runner to exercise positive execution, timeout and memory enforcement in the test suite. Blocked adapters remain visible for investigation.

---

## 8. Import Master Data

Use `uv run python -m ap.admin import --tenant saffron --file master.csv`. Export Tally or SQL master data to the CSV contract below. Put vendor rows first, then order rows, then receipts. Replaying identical data is idempotent. A conflicting key aborts the transaction for reconciliation.

```csv
kind,gstin,name,po,sku,ordered,price,gst_rate,hsn,grn,qty
vendor,27AAACV1234A1Z2,Deccan Components,,,,,,,,
order,27AAACV1234A1Z2,,PO-410,BR-20,10000,100,18,8482,,
receipt,,,PO-410,BR-20,,,,,GR-230,8000
```

---

## 9. Verification & Evaluation

Run the comprehensive test suite and code quality checks locally:

```powershell
# Run all 27 unit, integration, and security edge tests
uv run python -m pytest -q

# Run strict code quality & formatting checks
uvx ruff check ap tests; uvx ruff format --check ap tests

# Verify React production build
npm.cmd run build --prefix web

# Verify database ledger reconciliation
uv run python -m ap.admin reconcile
```

- **Pytest Suite:** 26 passed, 1 skipped *(conditional Linux gVisor runner)* in ~30s.
- **Ruff Linter & Formatter:** 0 errors across 22 Python files.
- **Vite Production Build:** 0 warnings, optimized static chunks in 1.5s.
- **Ledger Reconciliation:** Matches cumulative finance ledger (`{"entries": 2, "amount": "2360.00"}`).

---

## 10. Approved Infrastructure Configuration

| Setting or dependency | Behavior |
| --- | --- |
| Database | Provision PostgreSQL with pgvector in the client-approved boundary. Set `AP_ADMIN_DSN` and `AP_RUNTIME_PASSWORD` in the migration process, then run `python -m ap.admin migrate`. Provision one `ap.controls` row per tenant with buyer GSTIN, approved vendor list and queue disabled. The application connects as `ap_runtime`. Admin credentials belong to the operator process. |
| Application secrets | Point `AP_CONFIG` to a protected JSON file provisioned by the enterprise secrets manager. It contains `dsn`, a Fernet `key`, and `accounts` entries with tenant, user, role, and SHA-256 digest of an individually issued high-entropy token. Use `environment: pilot` and HTTPS for secure session cookies. Development initialization provisions synthetic credentials only. |
| Finance policy | Supply `tax_approvals` keyed by tenant, each with `version: domestic-po-v1`, accountable `owner`, and ISO dates `from` and `through`. Finance validates the actual rules against its transactions before recording approval. Cases outside the approved rule period go to review. |
| Document storage | The local repository stores encrypted originals transactionally in PostgreSQL. Configure `bucket` and optionally `s3_endpoint` for enterprise S3-compatible storage with workload identity. Objects are encrypted before upload and addressed by tenant and digest. Include object storage, encryption keys and the actual database in backup/restore drills. |
| Inference | Optional `model` object supplies an approved private chat-completions `url` and `name` supporting image inputs and JSON output. Restrict egress to that service in deployment. The local OCR uses packaged models. Graph execution disables LangSmith tracing. |
| Adapter staging | Supply a dedicated Linux gVisor runner with a Docker CLI/daemon, registered `runsc` runtime, and locally present Python image pinned by `sandbox_image` digest. Start the staging service with access only to its dedicated runner. Containers use a read-only root, no credentials or network, a three-second execution ceiling and a 128 MiB memory ceiling. An unavailable runner blocks promotion. |
| Notifications | Configure tenant-specific approved `slack_webhooks` and HTTPS `public_origin`. The tenant worker drains the outbox. Use `python -m ap.admin notify --tenant TENANT` to process a delivery manually. The delivery command processes one event per invocation and backs off after failure. The message contains a workflow link. Approval takes place in the authenticated application. |
| Rollout | Use a dedicated shadow tenant for replay. After finance and QA sign-off, enable internal writes only for the approved supplier cohort. Preserve the audit trail and reconcile daily for five business days. The service exposes no bank transfer or ERP posting operation. |

---

## 11. Instructions to Push to WildCatter's GitHub

Once permissions are granted to your GitHub account:

```bash
# 1. Initialize git (if not already done)
git init -b main

# 2. Stage all tracked project files
git add .

# 3. Commit the project
git commit -m "feat: AI-Native Enterprise Oracle Accounts Payable (AP) Platform"

# 4. Connect to WildCatter repository
git remote add origin https://github.com/WildCatter/<YOUR-ASSIGNED-REPO>.git

# 5. Push to main branch
git push -u origin main
```
