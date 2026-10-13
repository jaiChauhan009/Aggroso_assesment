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

## 7. Sample Data & Reviewer Walkthrough

Bundled scenario data is available in `schemas/`:
1. `source_schema.json`: Legacy `employees` schema (9 fields).
2. `target_schema.json`: Modern `staff` schema (8 fields with enums, constraints, formatting).
3. `sample_records.json`: 50 sample employee records containing valid data, type mismatches, null violations, and unmapped enum values.

### Reviewer Walkthrough:
1. Navigate to **📁 Schema Upload** ➔ Select "Use bundled example" for Source, Target, and Sample Records ➔ Click Save.
2. Navigate to **🤖 AI Mapping** ➔ Click "Run AI Mapping Agent" ➔ Review proposals, warnings, risk scores, and clarification questions ➔ Save as Plan Version.
3. Navigate to **📋 Plan Review** ➔ Click "Approve This Plan".
4. Navigate to **🧪 Dry Run** ➔ Click "Execute Dry Run" ➔ Verify counts (Source: 50, Accepted: 42, Rejected: 8) and examine field-level error evidence.
5. Navigate to **🚀 Execute Migration** ➔ Execute Plan ➔ Test "Retry" to verify idempotency (target count remains unchanged).
6. Navigate to **📊 Reconciliation** ➔ Run reconciliation (`50 = 42 + 8`) ➔ Test "Rollback" to verify safe database clean-up.