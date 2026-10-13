"""
Pydantic models for all domain entities.
"""
from __future__ import annotations

import json
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator


# ── Enums ───────────────────────────────────────────────────────────────────

class PlanStatus(str, Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    EXECUTED = "EXECUTED"
    ROLLED_BACK = "ROLLED_BACK"


class ExecutionType(str, Enum):
    DRY_RUN = "DRY_RUN"
    LIVE = "LIVE"


class ExecutionStatus(str, Enum):
    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


class AuditAction(str, Enum):
    PLAN_CREATED = "PLAN_CREATED"
    PLAN_UPDATED = "PLAN_UPDATED"
    APPROVED = "APPROVED"
    DRY_RUN = "DRY_RUN"
    EXECUTED = "EXECUTED"
    RETRIED = "RETRIED"
    ROLLED_BACK = "ROLLED_BACK"


class ErrorType(str, Enum):
    TYPE_MISMATCH = "TYPE_MISMATCH"
    NULL_NOT_ALLOWED = "NULL_NOT_ALLOWED"
    VALUE_OUT_OF_RANGE = "VALUE_OUT_OF_RANGE"
    PATTERN_VIOLATION = "PATTERN_VIOLATION"
    TRANSFORM_FAILED = "TRANSFORM_FAILED"
    ENUM_VIOLATION = "ENUM_VIOLATION"
    MAX_LENGTH_EXCEEDED = "MAX_LENGTH_EXCEEDED"


# ── Schema Models ───────────────────────────────────────────────────────────

class SchemaField(BaseModel):
    """A single field in a source or target schema."""
    name: str
    type: str  # "string", "integer", "float", "boolean"
    nullable: bool = False
    primary_key: bool = False
    max_length: Optional[int] = None
    format: Optional[str] = None  # e.g. "YYYY-MM-DD", "MM/DD/YYYY"
    enum: Optional[list[str]] = None
    default: Optional[Any] = None


class SchemaDefinition(BaseModel):
    """Complete schema for a source or target table."""
    table: str
    fields: list[SchemaField]

    def field_names(self) -> list[str]:
        return [f.name for f in self.fields]

    def get_field(self, name: str) -> Optional[SchemaField]:
        for f in self.fields:
            if f.name == name:
                return f
        return None


class SchemaRecord(BaseModel):
    """Stored schema entity."""
    id: str
    name: str
    direction: str  # "source" or "target"
    schema_json: str
    created_at: str

    def to_definition(self) -> SchemaDefinition:
        return SchemaDefinition.model_validate_json(self.schema_json)


# ── Sample Record ───────────────────────────────────────────────────────────

class SampleRecord(BaseModel):
    """A single sample row from the source data."""
    id: str
    schema_id: str
    record_json: str
    row_index: int

    def to_dict(self) -> dict[str, Any]:
        return json.loads(self.record_json)


# ── Mapping & Transformation ───────────────────────────────────────────────

class FieldMapping(BaseModel):
    """Maps one source field to one target field with a transformation."""
    source_field: str
    target_field: str
    transformation: str  # One of TRANSFORMATION_RULES
    params: dict[str, Any] = Field(default_factory=dict)
    # params examples:
    #   DATE_REFORMAT: {"input_format": "MM/DD/YYYY", "output_format": "YYYY-MM-DD"}
    #   CONCAT: {"fields": ["first_name", "last_name"], "separator": " "}
    #   MAP_VALUES: {"mapping": {"M": "Male", "F": "Female"}}
    #   TRUNCATE: {"max_length": 500}
    #   DEFAULT: {"value": "N/A"}
    #   SPLIT: {"delimiter": " ", "index": 0}
    #   ROUND: {"decimals": 2}


class MigrationPlan(BaseModel):
    """A versioned migration plan."""
    id: str
    version: int
    status: PlanStatus = PlanStatus.DRAFT
    mappings_json: str  # JSON-serialized list[FieldMapping]
    transformations_json: str  # same as mappings, kept for clarity
    risk_notes: str = ""
    ai_questions: str = ""
    user_answers: str = ""
    created_at: str = ""
    approved_at: Optional[str] = None
    approved_by: Optional[str] = None

    def get_mappings(self) -> list[FieldMapping]:
        raw = json.loads(self.mappings_json)
        return [FieldMapping.model_validate(m) for m in raw]


# ── Execution ───────────────────────────────────────────────────────────────

class Execution(BaseModel):
    """Record of a dry-run or live migration execution."""
    id: str
    plan_id: str
    execution_type: ExecutionType
    source_count: int = 0
    transformed_count: int = 0
    accepted_count: int = 0
    rejected_count: int = 0
    started_at: str = ""
    completed_at: Optional[str] = None
    status: ExecutionStatus = ExecutionStatus.SUCCESS


# ── Quarantine ──────────────────────────────────────────────────────────────

class QuarantineEntry(BaseModel):
    """A record that failed validation, with field-level error evidence."""
    id: str
    execution_id: str
    source_record_json: str
    field_name: str
    error_type: str
    error_message: str
    original_value: Optional[str] = None
    row_index: int = 0

    def source_record(self) -> dict[str, Any]:
        return json.loads(self.source_record_json)


# ── Target Store ────────────────────────────────────────────────────────────

class TargetRecord(BaseModel):
    """A successfully migrated record in the mock target database."""
    id: str
    execution_id: str
    idempotency_key: str
    record_json: str
    inserted_at: str

    def to_dict(self) -> dict[str, Any]:
        return json.loads(self.record_json)


# ── Audit Log ───────────────────────────────────────────────────────────────

class AuditLogEntry(BaseModel):
    """Immutable audit trail entry."""
    id: str
    action: AuditAction
    entity_id: str
    details_json: str = "{}"
    timestamp: str = ""

    def details(self) -> dict[str, Any]:
        return json.loads(self.details_json)
