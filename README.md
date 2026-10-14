# Agentic Data Migration Planner and Reconciliation Workbench

[![Python 3.13](https://img.shields.io/badge/python-3.13-blue.svg)](https://www.python.org/downloads/)
[![Streamlit](https://img.shields.io/badge/frontend-Streamlit-red.svg)](https://streamlit.io/)
[![SQLite](https://img.shields.io/badge/database-SQLite-green.svg)](https://www.sqlite.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

An enterprise-grade, deterministic data migration planner, execution engine, and reconciliation workbench powered by AI-assisted schema mapping and human-in-the-loop validation.

---

## 1. System Architecture & Workflow

The platform bridges legacy or bounded source schemas into modern target schemas through an auditable, deterministic lifecycle:

```
[Source & Target Schemas + Sample Records]
                 │
                 ▼
[Schema Inspector & AI Mapping Agent] ──▶ Proposes Field Mappings & Identifies Risks
                 │
                 ▼
[Human Review & Plan Versioning] ──────▶ Human Approval Gate (DRAFT ➔ APPROVED)
                 │
                 ▼
[Deterministic Dry Run] ───────────────▶ Quarantine Invalid Records & Error Evidence
                 │
                 ▼
[Idempotent Migration Execution] ──────▶ Mock Target Store (Unique Keys Prevent Duplicates)
                 │
                 ▼
[Reconciliation & Safe Rollback] ──────▶ Source == Target + Quarantined & Audit Trail
```

### Core Architecture Layers:
1. **Frontend**: Streamlit UI (`ui/app.py` and modular page components under `ui/pages/`) with comprehensive empty, loading, error, and success states.
2. **AI Agent Layer**: `agent/` with LLM integration (Google Gemini) and resilient heuristic fallback. Operates strictly under read-only inspection tools (`inspect_source_schema`, `get_sample_records`, `list_transformations`, `validate_mapping`, `check_type_compatibility`).
3. **Core Engine**: `core/` containing the deterministic 16-rule transformation catalog, Pydantic v2 validation pipeline, SHA-256 idempotency hasher, migration executor, reconciliation engine, and rollback manager.
4. **Persistence Layer**: Local SQLite database (`storage/database.py` with WAL mode & foreign keys enabled) tracking schemas, sample records, versioned plans, executions, quarantined records, target store records, and append-only audit trail logs.

---

## 2. Completed Scope & Key Features

- **Bounded Dataset Migration**: Configurable bounded sample size (`MAX_SAMPLE_SIZE = 1000` enforced).
- **AI Agent Field Mapping**: Automated mapping proposal, type compatibility check, risk categorization (LOW, MEDIUM, HIGH), and interactive clarification question generator.
- **Human-in-the-Loop Review**: Mandatory approval gate; unapproved plans cannot be executed.
- **Plan Versioning**: Immutable version increments (`v1`, `v2`, ...) with side-by-side plan diffing.
- **Deterministic 16-Rule Transformation Catalog**:
  - `RENAME`, `CAST_INT`, `CAST_FLOAT`, `CAST_STRING`, `CAST_BOOL`
  - `DATE_REFORMAT`, `UPPERCASE`, `LOWERCASE`, `TRIM`, `DEFAULT`
  - `CONCAT`, `SPLIT`, `TRUNCATE`, `MAP_VALUES`, `ROUND`, `DROP`
- **Zero-Write Dry Run**: Verifies all transforms and constraints against target schema with zero mutations to target storage.
- **Quarantine Store & Error Evidence**: Captures record-level and field-level failure metadata (`row_index`, `field_name`, `error_type`, `error_message`, `original_value`).
- **Idempotency & Duplicate Prevention**: SHA-256 key generation `hash(plan_id + sorted_record + row_index)` with SQLite `UNIQUE` constraint and `INSERT OR IGNORE` retry handling.
- **Mathematical Reconciliation**: Validates the invariant `source_count == target_count + quarantine_count`.
- **Atomic Rollback**: Reverts execution records from target store while preserving quarantine evidence for audit compliance.
- **Comprehensive Audit Trail**: Logs every event (`PLAN_CREATED`, `APPROVED`, `DRY_RUN`, `EXECUTED`, `RETRIED`, `ROLLED_BACK`).

---

## 3. Scope Exclusions & Deliberate Limitations

As specified in the assignment constraints:
- **No live cloud connectors / production databases**: Uses local mock SQLite staging store.
- **No arbitrary code execution**: All transforms are strictly confined to the closed 16-rule catalog to prevent injection vulnerabilities.
- **Single Source & Target**: Bounded strictly to one source table and one target table per workspace.
- **No distributed processing**: Optimized for bounded batch datasets rather than multi-node Spark/Flink setups.

---

## 4. Local Installation & Setup

### Prerequisites
- Python 3.10+ (Tested on Python 3.13)
- Git

### Installation Steps
```bash
# 1. Clone repository
git clone https://github.com/jaiChauhan009/Aggroso_assesment.git
cd Aggroso_assesment

# 2. Create and activate a virtual environment
python -m venv venv
# Windows:
.\venv\Scripts\activate
# Linux / macOS:
source venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure Environment
cp .env.example .env
# (Optional) Edit .env to supply your GEMINI_API_KEY.
# If no key is provided, the application automatically uses the built-in heuristic mapping engine.
```

### Running the Workbench
```bash
streamlit run ui/app.py
```
Open your browser at `http://localhost:8501`.

---

## 5. Running the Test Suite

Unit and end-to-end integration tests are implemented with `pytest`:

```bash
# Run all tests
pytest -v

# Run full integration pipeline specifically
python tests/test_integration.py
```

Test coverage includes:
- Schema parsing, validation, and diffing.
- Scalar and composite transformations (all 16 rules).
- Target schema constraint validation and quarantine emission.
- End-to-end integration: schema upload ➔ mapping ➔ approval ➔ dry-run ➔ execution ➔ retry deduplication ➔ reconciliation ➔ rollback.

---

## 6. Deployment Details

### Option A: Streamlit Community Cloud (Recommended & Free)
1. Fork or push this repository to GitHub.
2. Sign in to [Streamlit Community Cloud](https://share.streamlit.io/).
3. Click **New app** and select:
   - Repository: `jaiChauhan009/Aggroso_assesment`
   - Branch: `main`
   - Main file path: `ui/app.py`
4. Under **Advanced Settings**, add secrets if desired:
   ```toml
   GEMINI_API_KEY = "your_key_here"
   ```
5. Click **Deploy**.

### Option B: Docker / Container Deployment
A standard `Dockerfile` is provided:
```bash
docker build -t migration-workbench .
docker run -p 8501:8501 -e GEMINI_API_KEY="your_key" migration-workbench
```

---

## 7. Step-by-Step Walkthrough Guide (Reviewer Instructions)

The application implements a 6-stage lifecycle for predictable data migration.

```
Step 1: 📁 Schema Upload      ➔ Ingest source/target schemas & sample records
Step 2: 🤖 AI Mapping          ➔ AI agent proposes mappings, flags risks & asks questions
Step 3: 📋 Plan Review         ➔ Review versioned plan & provide Human-in-the-Loop APPROVAL
Step 4: 🧪 Dry Run             ➔ Deterministic simulation (zero target writes) & quarantine evidence
Step 5: 🚀 Execute Migration   ➔ Insert accepted records into mock target (idempotent retry check)
Step 6: 📊 Reconciliation      ➔ Verify Source == Target + Quarantined, full audit log & rollback
```

### Pre-loaded Test Datasets
Bundled scenario datasets are located in `schemas/`:
- `source_schema.json`: Legacy `employees` schema (9 fields).
- `target_schema.json`: Modern `staff` schema (8 fields with enums, constraints, formatting).
- `sample_records.json`: 50 sample employee records containing valid data, type mismatches, null violations, and unmapped enum values.

---

### Step-by-Step Reviewer Execution:

#### 1. 📁 Schema Upload & Preview
- In the left sidebar, navigate to **📁 Schema Upload**.
- **Source Schema**: Select *"Use bundled example"* (or upload a custom JSON/CSV) ➔ Click **"Load Bundled Source Schema"**.
- **Target Schema**: Select *"Use bundled example"* (or upload a custom JSON/CSV) ➔ Click **"Load Bundled Target Schema"**.
- **Sample Records** tab: Select *"Use bundled example"* (or upload a custom JSON/CSV) ➔ Click **"Load Bundled Sample Records"**.
- **Preview** tab: Inspect the side-by-side schema diff table to confirm field types, nullability, constraints, and loaded sample records.

#### 2. 🤖 AI-Assisted Mapping
- Navigate to **🤖 AI Mapping**.
- Click **"🚀 Run AI Mapping Agent"**.
- **Agent Output Review**:
  - Review proposed field mappings (e.g., `emp_id` ➔ `staffId` via `CAST_INT`, `dob` ➔ `dateOfBirth` via `DATE_REFORMAT`, `dept_code` ➔ `department` via `MAP_VALUES`).
  - Read agent explanation, risk scores (LOW/MEDIUM/HIGH), and clarification questions.
  - (Optional) Answer clarification questions and click *"Submit Answers & Refine"*, or fine-tune transformations using the **"📝 Edit Mappings"** interactive dropdown table.
- Click **"💾 Save as New Plan Version"** to generate **Plan v1** with status `DRAFT`.

#### 3. 📋 Plan Review & Human-in-the-Loop Approval
- Navigate to **📋 Plan Review**.
- Select **Plan v1 (Status: 📝 DRAFT)**.
- Review the mappings, parameters, and risk notes.
- Enter your approver name (e.g. `reviewer`) and click **"✅ Approve This Plan"**.
- Plan status transitions from `DRAFT` ➔ `APPROVED` (unlocked for execution).

#### 4. 🧪 Deterministic Dry Run
- Navigate to **🧪 Dry Run**.
- Select the approved Plan v1 and click **"🧪 Execute Dry Run"**.
- **Verify Metrics**:
  - **Source Records**: `50`
  - **Transformed**: `50`
  - **Accepted**: `42`
  - **Rejected (Quarantined)**: `8`
  - **Invariant Check**: Confirms `50 = 42 + 8`.
- Inspect the **Quarantine Details Table** to view field-level error evidence (`TYPE_MISMATCH` for invalid salaries, `ENUM_VIOLATION` for unmapped departments, `NULL_NOT_ALLOWED` for missing names).
- *Target database record count remains 0 (zero-write guarantee).*

#### 5. 🚀 Execute Migration & Verify Idempotency
- Navigate to **🚀 Execute Migration**.
- Under *"Ready for Execution"*, click **"🚀 Execute v1"**.
- The 42 accepted records are written to the mock target store; 8 rejected records remain in quarantine.
- Under *"Retry Previously Executed"*, click **"🔁 Retry v1"**.
- **Verify Idempotency**: Target record count does **not** duplicate or increase (verified via unique SHA-256 keys `hash(plan_id + record + row_index)`).

#### 6. 📊 Reconciliation, Audit Trail & Rollback
- Navigate to **📊 Reconciliation**.
- Select the execution and click **"📊 Run Reconciliation"**.
- Confirms mathematical balance: `Source (50) == Target (42) + Quarantined (8)`.
- Scroll to **Full Audit Trail** to view tamper-evident records for every event: `PLAN_CREATED` ➔ `APPROVED` ➔ `DRY_RUN` ➔ `EXECUTED` ➔ `RETRIED`.
- **Test Rollback**: Under *"Rollback"*, check the confirmation box and click **"⏪ Rollback Execution"**. The target store is cleaned back to 0 records while quarantine evidence and audit history are safely preserved.