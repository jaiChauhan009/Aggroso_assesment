"""
Risk analyzer and scoring engine for proposed data migrations.

Evaluates field mappings against source and target schema definitions to detect:
- Type narrowing (e.g. float -> int, leading to decimal loss)
- Nullability mismatches (nullable source to non-nullable target without DEFAULT)
- String truncation and character length overflow
- Lossy date/time reformats (e.g. stripping timestamps to date-only)
- Unmapped required target fields
- Enum constraint violations
"""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Optional, Union

from config import TRANSFORMATION_RULES
from storage.models import FieldMapping, SchemaDefinition, SchemaField, SchemaRecord

logger = logging.getLogger(__name__)


# ── Risk Data Structures ─────────────────────────────────────────────────────

class RiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


@dataclass
class FieldRisk:
    """Risk item associated with a specific field mapping."""
    field_name: str
    target_field: str
    risk_level: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RiskReport:
    """Comprehensive risk assessment report for a migration plan."""
    overall_risk: str  # "LOW", "MEDIUM", "HIGH"
    field_risks: list[FieldRisk] = field(default_factory=list)
    unmapped_source_fields: list[str] = field(default_factory=list)
    unmapped_target_fields: list[str] = field(default_factory=list)
    data_loss_warnings: list[str] = field(default_factory=list)
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "overall_risk": self.overall_risk,
            "field_risks": [r.to_dict() for r in self.field_risks],
            "unmapped_source_fields": self.unmapped_source_fields,
            "unmapped_target_fields": self.unmapped_target_fields,
            "data_loss_warnings": self.data_loss_warnings,
            "summary": self.summary,
        }


# ── Schema Normalization Helper ──────────────────────────────────────────────

def _to_schema_definition(schema: Union[SchemaDefinition, SchemaRecord, dict[str, Any], None]) -> Optional[SchemaDefinition]:
    """Convert various schema representations into a SchemaDefinition instance."""
    if schema is None:
        return None
    if isinstance(schema, SchemaDefinition):
        return schema
    if isinstance(schema, SchemaRecord):
        return schema.to_definition()
    if isinstance(schema, dict):
        # Format might be {"table": "...", "fields": [...]} or raw schema record
        if "schema_json" in schema:
            return SchemaDefinition.model_validate_json(schema["schema_json"])
        table_name = schema.get("table") or schema.get("name") or "unknown"
        raw_fields = schema.get("fields") or []
        fields = []
        for f in raw_fields:
            if isinstance(f, SchemaField):
                fields.append(f)
            elif isinstance(f, dict):
                fields.append(SchemaField.model_validate(f))
        return SchemaDefinition(table=table_name, fields=fields)
    return None


# ── Core Risk Analyzer ───────────────────────────────────────────────────────

def analyze_risks(
    mappings: list[FieldMapping],
    source_schema: Union[SchemaDefinition, SchemaRecord, dict[str, Any], None],
    target_schema: Union[SchemaDefinition, SchemaRecord, dict[str, Any], None],
) -> RiskReport:
    """Analyze proposed mappings and schemas to identify data loss risks and constraint violations.

    Risk factors evaluated:
    - Type narrowing (e.g. float -> int truncation, string -> int cast failure)
    - Nullable source mapped to non-nullable target without DEFAULT fallback
    - String length truncation or potential database overflow
    - Lossy date reformats (e.g. dropping time components)
    - Unmapped required target fields
    - Enum mismatch or lack of fallback mapping
    - Unmapped source fields that will be dropped

    Args:
        mappings: Proposed list of FieldMapping objects.
        source_schema: Source schema definition, record, or dictionary.
        target_schema: Target schema definition, record, or dictionary.

    Returns:
        RiskReport: Complete risk report with overall score and granular field risks.
    """
    src_def = _to_schema_definition(source_schema)
    tgt_def = _to_schema_definition(target_schema)

    field_risks: list[FieldRisk] = []
    data_loss_warnings: list[str] = []

    src_field_map: dict[str, SchemaField] = {f.name: f for f in src_def.fields} if src_def else {}
    tgt_field_map: dict[str, SchemaField] = {f.name: f for f in tgt_def.fields} if tgt_def else {}

    mapped_source_fields: set[str] = set()
    mapped_target_fields: set[str] = set()

    for m in mappings:
        src_field = m.source_field
        tgt_field = m.target_field
        rule = m.transformation
        params = m.params or {}

        if src_field:
            mapped_source_fields.add(src_field)
        if rule == "CONCAT":
            for f in params.get("fields", []):
                mapped_source_fields.add(f)

        if tgt_field and rule != "DROP":
            mapped_target_fields.add(tgt_field)

        src_schema_field = src_field_map.get(src_field)
        tgt_schema_field = tgt_field_map.get(tgt_field)

        # ── 1. Type Narrowing & Precision Loss ──────────────────────────────
        if src_schema_field and tgt_schema_field:
            s_type = src_schema_field.type.lower()
            t_type = tgt_schema_field.type.lower()

            # float -> int truncation
            if s_type in ("float", "double", "decimal", "numeric") and (t_type in ("integer", "int") or rule == "CAST_INT"):
                risk = FieldRisk(
                    field_name=src_field,
                    target_field=tgt_field,
                    risk_level=RiskLevel.HIGH.value,
                    reason=f"Narrowing conversion from float to integer on '{src_field}' -> '{tgt_field}'. Fractional decimal values will be truncated.",
                )
                field_risks.append(risk)
                data_loss_warnings.append(
                    f"Decimal precision loss: '{src_field}' ({s_type}) truncated to '{tgt_field}' ({t_type})."
                )

            # string -> int or float cast risk
            elif s_type in ("string", "text", "varchar") and rule in ("CAST_INT", "CAST_FLOAT"):
                risk = FieldRisk(
                    field_name=src_field,
                    target_field=tgt_field,
                    risk_level=RiskLevel.MEDIUM.value,
                    reason=f"Casting string '{src_field}' to {t_type} via {rule}. Non-numeric strings or uncleaned formatting will cause execution failures.",
                )
                field_risks.append(risk)

        # ── 2. Nullability Mismatch ─────────────────────────────────────────
        if src_schema_field and tgt_schema_field:
            if src_schema_field.nullable and not tgt_schema_field.nullable and rule != "DEFAULT":
                risk = FieldRisk(
                    field_name=src_field,
                    target_field=tgt_field,
                    risk_level=RiskLevel.HIGH.value,
                    reason=f"Source field '{src_field}' allows NULLs but target field '{tgt_field}' is non-nullable and no DEFAULT fallback rule is configured.",
                )
                field_risks.append(risk)

        # ── 3. Truncation & Length Constraints ──────────────────────────────
        if tgt_schema_field and tgt_schema_field.max_length:
            target_max = tgt_schema_field.max_length
            source_max = src_schema_field.max_length if src_schema_field else None

            if rule == "TRUNCATE":
                truncate_limit = params.get("max_length", target_max)
                risk = FieldRisk(
                    field_name=src_field,
                    target_field=tgt_field,
                    risk_level=RiskLevel.MEDIUM.value,
                    reason=f"TRUNCATE rule active on '{src_field}' (limit={truncate_limit}). Text exceeding {truncate_limit} characters will be permanently sliced.",
                )
                field_risks.append(risk)
                data_loss_warnings.append(
                    f"String truncation: '{src_field}' truncated to {truncate_limit} characters for '{tgt_field}'."
                )
            elif source_max is None or source_max > target_max:
                if src_schema_field and src_schema_field.type.lower() in ("string", "text", "varchar"):
                    risk = FieldRisk(
                        field_name=src_field,
                        target_field=tgt_field,
                        risk_level=RiskLevel.HIGH.value,
                        reason=f"Source '{src_field}' has max length {source_max or 'unbounded'} exceeding target max length {target_max} without TRUNCATE rule. Length violations may abort row insertion.",
                    )
                    field_risks.append(risk)

        # ── 4. Lossy Date Reformats ─────────────────────────────────────────
        if rule == "DATE_REFORMAT":
            out_fmt = params.get("output_format", "")
            in_fmt = params.get("input_format", "")
            if not in_fmt:
                risk = FieldRisk(
                    field_name=src_field,
                    target_field=tgt_field,
                    risk_level=RiskLevel.MEDIUM.value,
                    reason=f"DATE_REFORMAT on '{src_field}' lacks explicit 'input_format'. Ambiguous dates (e.g. DD/MM vs MM/DD) may be parsed incorrectly.",
                )
                field_risks.append(risk)
            # Detect loss of time component
            if in_fmt and ("%H" in in_fmt or "%T" in in_fmt) and ("%H" not in out_fmt and "%T" not in out_fmt):
                risk = FieldRisk(
                    field_name=src_field,
                    target_field=tgt_field,
                    risk_level=RiskLevel.MEDIUM.value,
                    reason=f"DATE_REFORMAT on '{src_field}' drops time components (hours/minutes/seconds) when converting to '{tgt_field}'.",
                )
                field_risks.append(risk)
                data_loss_warnings.append(
                    f"Temporal precision loss: Time component discarded when reformating '{src_field}' to '{tgt_field}'."
                )

        # ── 5. Enum & Value Mapping ─────────────────────────────────────────
        if tgt_schema_field and tgt_schema_field.enum:
            if rule != "MAP_VALUES":
                risk = FieldRisk(
                    field_name=src_field,
                    target_field=tgt_field,
                    risk_level=RiskLevel.MEDIUM.value,
                    reason=f"Target field '{tgt_field}' has strict enum constraints {tgt_schema_field.enum} but transformation is '{rule}' rather than MAP_VALUES.",
                )
                field_risks.append(risk)
            elif rule == "MAP_VALUES" and "default" not in params:
                risk = FieldRisk(
                    field_name=src_field,
                    target_field=tgt_field,
                    risk_level=RiskLevel.MEDIUM.value,
                    reason=f"MAP_VALUES on '{src_field}' lacks a 'default' fallback value. Unmatched enum values may trigger constraint rejections.",
                )
                field_risks.append(risk)

        # ── 6. Explicit DROP ────────────────────────────────────────────────
        if rule == "DROP":
            data_loss_warnings.append(f"Explicitly dropped field: Source field '{src_field}' will not be migrated.")

    # ── 7. Unmapped Required Target Fields ──────────────────────────────────
    unmapped_target_fields: list[str] = []
    if tgt_def:
        for f in tgt_def.fields:
            if f.name not in mapped_target_fields:
                unmapped_target_fields.append(f.name)
                # Check if required (non-nullable and no default)
                if not f.nullable and f.default is None:
                    risk = FieldRisk(
                        field_name="",
                        target_field=f.name,
                        risk_level=RiskLevel.HIGH.value,
                        reason=f"Required target field '{f.name}' (non-nullable, no default) is unmapped. Insert operations will fail without a value.",
                    )
                    field_risks.append(risk)

    # ── 8. Unmapped Source Fields ───────────────────────────────────────────
    unmapped_source_fields: list[str] = []
    if src_def:
        for f in src_def.fields:
            if f.name not in mapped_source_fields:
                unmapped_source_fields.append(f.name)
                data_loss_warnings.append(f"Unmapped source field: '{f.name}' will be omitted from the target dataset.")

    # ── 9. Overall Risk Calculation ─────────────────────────────────────────
    high_count = sum(1 for r in field_risks if r.risk_level == RiskLevel.HIGH.value)
    med_count = sum(1 for r in field_risks if r.risk_level == RiskLevel.MEDIUM.value)

    if high_count > 0:
        overall_risk = RiskLevel.HIGH.value
    elif med_count >= 2:
        overall_risk = RiskLevel.HIGH.value
    elif med_count == 1:
        overall_risk = RiskLevel.MEDIUM.value
    else:
        overall_risk = RiskLevel.LOW.value

    # ── 10. Summary Narrative ───────────────────────────────────────────────
    summary_parts = [f"Overall Risk: {overall_risk}."]
    if high_count:
        summary_parts.append(f"Identified {high_count} HIGH-risk items requiring resolution before execution.")
    if med_count:
        summary_parts.append(f"Found {med_count} MEDIUM-risk items (potential truncation or cast errors).")
    if unmapped_target_fields:
        summary_parts.append(f"{len(unmapped_target_fields)} target fields remain unmapped.")
    if unmapped_source_fields:
        summary_parts.append(f"{len(unmapped_source_fields)} source fields will not be migrated.")
    if not field_risks:
        summary_parts.append("All field mappings are type-compatible and constraint-aligned.")

    summary = " ".join(summary_parts)

    return RiskReport(
        overall_risk=overall_risk,
        field_risks=field_risks,
        unmapped_source_fields=unmapped_source_fields,
        unmapped_target_fields=unmapped_target_fields,
        data_loss_warnings=data_loss_warnings,
        summary=summary,
    )
