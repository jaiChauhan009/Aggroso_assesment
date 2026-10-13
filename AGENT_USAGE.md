# AGENT_USAGE.md: AI Agent Specification and Evaluation Log

This document details the architecture, tool bindings, representative prompts, delegated tasks, observed edge cases/mistakes, and output verification mechanisms for the AI Agent integrated within the **Agentic Data Migration Planner and Reconciliation Workbench**.

---

## 1. Agent Architecture & Role Definition

The AI agent functions strictly as a **Data Migration Specialist & Planner**.
To guarantee safety, reliability, and auditability:
- **Zero Execution Privileges**: The agent cannot directly mutate database state, write to the target store, or execute arbitrary Python code.
- **Tool-Bound Observation**: All information intake is gated through dedicated read-only inspection tools.
- **Proposal-Only Mode**: Output from the LLM represents candidate mappings and risk reports, requiring explicit Human-in-the-Loop approval before any downstream dry run or execution.

```
┌────────────────────────────────────────────────────────┐
│                      AI Agent Layer                    │
│                                                        │
│  [System Prompt: Specialist & Closed Tool Boundaries] │
│                           │                            │
│                           ▼                            │
│                   Gemini 2.0 Flash                     │
│                  (Heuristic Fallback)                  │
└───────────────────────────┬────────────────────────────┘
                            │ Calls Inspection Tools
                            ▼
┌────────────────────────────────────────────────────────┐
│                Bounded Inspection Tools                │
│                                                        │
│  • inspect_source_schema()    • list_transformations() │
│  • inspect_target_schema()    • validate_mapping()     │
│  • get_sample_records()       • check_type_compat()    │
└────────────────────────────────────────────────────────┘
```

---

## 2. Tool Bindings

The agent is equipped with 6 purpose-built inspection and validation tools located in `agent/tools.py`:

| Tool | Purpose | Output Structure |
|------|---------|------------------|
| `inspect_source_schema()` | Reads active source table structure | Table name, field list, data types, nullability, primary key indicators, formats |
| `inspect_target_schema()` | Reads active target table structure | Target field names, required vs optional fields, type requirements, enum constraints, string length limits |
| `get_sample_records(limit=5)` | Inspects raw sample values | Array of dictionary records demonstrating real-world value representations |
| `list_transformations()` | Returns the allowed 16-rule catalog | Rule IDs, descriptions, parameter schemas (`fields`, `format`, `mapping`, `max_length`, `value`, `decimals`) |
| `validate_mapping(mapping)` | Verifies a proposed field mapping | Boolean `valid`, array of constraint failure error strings |
| `check_type_compatibility(src, tgt)` | Evaluates type casting safety | Compatibility boolean, recommended transformation rule, safety notes |

---

## 3. Representative Prompts

### 3.1 System Prompt (`agent/prompts.py`)
```text
You are an expert Data Migration Specialist and Schema Alignment AI Agent.
Your role is to analyze a source dataset schema, target dataset schema, sample source records,
and propose a migration mapping plan using ONLY the provided catalog of supported transformation rules.

CORE RULES:
1. You are an ADVISORY agent. You propose mappings and identify risks. You NEVER execute data migrations directly.
2. Use ONLY supported transformation rules from the catalog. Do NOT invent new transformation rules or code.
3. Every required target field must either have a source mapping or a DEFAULT transformation.
4. Flag all potential data loss, truncation, type mismatches, and nullability conflicts.
5. Generate clear, actionable clarification questions for ambiguous mappings.
6. Return output strictly in the requested JSON format.
```

### 3.2 Mapping Generation Prompt Template
```text
Given:
- Source Schema Summary: {source_schema_summary}
- Target Schema Summary: {target_schema_summary}
- Sample Source Records Preview: {sample_records_preview}
- Supported Transformations Catalog: {transformation_catalog}

Propose an optimal migration plan matching each target field with appropriate source fields and transformation rules.
Identify any risks, unmapped fields, or ambiguities requiring user input.
```

### 3.3 Output Schema Enforced
```json
{
  "mappings": [
    {
      "source_field": "string",
      "target_field": "string",
      "transformation": "RULE_NAME",
      "params": {}
    }
  ],
  "warnings": ["string"],
  "risks": ["string"],
  "questions": ["string"],
  "explanation": "string"
}
```

---

## 4. Delegated Work & Division of Responsibility

| Task | Delegated to AI | Handled Deterministically by Engine |
|------|-----------------|--------------------------------------|
| **Schema Field Association** | ✅ Semantic matching (`first_name + last_name ➔ fullName`, `dept_code ➔ department`) | ❌ |
| **Ambiguity Detection** | ✅ Generating targeted business questions | ❌ |
| **Risk Identification** | ✅ Detecting implicit data loss risks | ❌ |
| **Constraint Validation** | ❌ | ✅ Pydantic v2 & validation pipeline |
| **Transformation Execution** | ❌ | ✅ Rule-based transformation engine (no LLM in runtime path) |
| **Idempotency Key Generation** | ❌ | ✅ Deterministic SHA-256 hash |
| **Approval Gate** | ❌ | ✅ Human operator sign-off in UI |
| **Reconciliation & Rollback** | ❌ | ✅ SQL aggregation & atomic delete |

---

## 5. Agent Mistakes & Rejected Suggestions (Observed & Resolved)

During testing and iterative evaluation, several critical agent tendencies were detected and mitigated:

### 1. Hallucinating Non-Existent Transformation Rules
- **Observed Behavior**: The LLM initially suggested transformation names like `STR_TO_DATE`, `COMBINE_FIELDS`, and `LOOKUP` rather than the exact IDs in the closed catalog (`DATE_REFORMAT`, `CONCAT`, `MAP_VALUES`).
- **Resolution**:
  - Bound the prompt with exact enum names from `config.TRANSFORMATION_RULES`.
  - Added programmatic validation via `validate_mapping()` which checks proposed rules against `TRANSFORMATION_RULES` and rejects invalid rule IDs immediately.

### 2. Missing Composite Concatenation Context
- **Observed Behavior**: When proposing `first_name` ➔ `fullName`, the agent only supplied `source_field: "first_name"` without specifying the companion `last_name` in parameters.
- **Resolution**:
  - Enforced a parameter schema requirement for `CONCAT`: `{"fields": ["first_name", "last_name"], "separator": " "}`.
  - The deterministic transformation engine reads `params["fields"]` and extracts both keys from the source dictionary.

### 3. Unchecked Enum Violations
- **Observed Behavior**: For `dept_code` ➔ `department`, the agent initially proposed a plain `RENAME`, assuming the target system would accept raw legacy codes like `"ENG"` into an enum expecting `"Engineering"`.
- **Resolution**:
  - Prompt instructions explicitly emphasize checking target `enum` constraints.
  - The deterministic validation pipeline flags any transformed value outside the target enum with `ErrorType.ENUM_VIOLATION` and routes it to quarantine.

---

## 6. Output Verification & Guardrails

To prevent faulty LLM outputs from corrupting the target store:

1. **Structured Parsing Guard**: LLM responses are parsed with JSON mode and validated against Pydantic schema models (`FieldMapping`). Any unparseable payload automatically degrades to the deterministic heuristic matcher.
2. **Deterministic Dry-Run Verification**: Every plan is tested in memory on the sample dataset with zero target database writes. The results (including exact counts and quarantined error evidence) are rendered on the UI before the human approves.
3. **Mandatory Human Approval Gate**: The UI prevents live execution unless an operator explicitly reviews the mappings, answers questions, and records their approval in the versioned plan.
