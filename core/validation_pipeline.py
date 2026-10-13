"""
Validation pipeline for verifying transformed records against target schemas.
"""
from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from storage.models import ErrorType, QuarantineEntry, SchemaDefinition


@dataclass
class ValidationError:
    """Represents a validation violation on a specific field of a record."""

    field_name: str
    error_type: ErrorType
    error_message: str
    original_value: Any


def _check_format(value: str, fmt: str) -> bool:
    """
    Check if a string value complies with the format specification.

    Supports date/time patterns (YYYY-MM-DD, MM/DD/YYYY, etc.), standard strftime
    patterns, or arbitrary regular expressions.
    """
    if not fmt or not value:
        return True

    # If fmt is a regex (e.g. starts with ^ or contains typical regex syntax)
    if fmt.startswith("^") or fmt.endswith("$"):
        return bool(re.match(fmt, value))

    # Common date formats to regex mappings
    date_patterns: dict[str, str] = {
        "YYYY-MM-DD": r"^\d{4}-\d{2}-\d{2}$",
        "YYYY/MM/DD": r"^\d{4}/\d{2}/\d{2}$",
        "MM/DD/YYYY": r"^\d{2}/\d{2}/\d{4}$",
        "DD/MM/YYYY": r"^\d{2}/\d{2}/\d{4}$",
        "MM-DD-YYYY": r"^\d{2}-\d{2}-\d{4}$",
        "DD-MM-YYYY": r"^\d{2}-\d{2}-\d{4}$",
    }
    if fmt in date_patterns:
        return bool(re.match(date_patterns[fmt], value))

    # Try strftime parsing if format contains %
    if "%" in fmt:
        try:
            datetime.strptime(value, fmt)
            return True
        except ValueError:
            return False

    # Fallback to regex pattern match
    try:
        return bool(re.match(fmt, value))
    except re.error:
        return True


def validate_record(record: dict[str, Any], target_schema: SchemaDefinition) -> list[ValidationError]:
    """
    Validate a single transformed record against the target SchemaDefinition.

    Checks:
      1. Nullability & presence constraints
      2. Type compatibility
      3. Maximum length constraints (strings)
      4. Enum membership constraints
      5. Format pattern constraints (e.g., date formats)

    Args:
        record: Transformed dictionary representing target record fields.
        target_schema: Target SchemaDefinition to validate against.

    Returns:
        List of ValidationError instances. Empty if the record is fully valid.
    """
    errors: list[ValidationError] = []

    for field in target_schema.fields:
        field_name = field.name
        is_present = field_name in record
        value = record.get(field_name)

        # 1. Nullability and presence
        if not is_present or value is None:
            if not field.nullable and field.default is None:
                errors.append(
                    ValidationError(
                        field_name=field_name,
                        error_type=ErrorType.NULL_NOT_ALLOWED,
                        error_message=f"Field '{field_name}' is required and cannot be null",
                        original_value=value,
                    )
                )
            continue

        # 2. Type compatibility
        field_type = field.type.strip().lower()

        if field_type in ("string", "text", "varchar", "char"):
            if not isinstance(value, str):
                errors.append(
                    ValidationError(
                        field_name=field_name,
                        error_type=ErrorType.TYPE_MISMATCH,
                        error_message=f"Field '{field_name}' expects string, got {type(value).__name__}",
                        original_value=value,
                    )
                )
        elif field_type in ("integer", "int", "bigint", "smallint"):
            if not isinstance(value, int) or isinstance(value, bool):
                errors.append(
                    ValidationError(
                        field_name=field_name,
                        error_type=ErrorType.TYPE_MISMATCH,
                        error_message=f"Field '{field_name}' expects integer, got {type(value).__name__}",
                        original_value=value,
                    )
                )
        elif field_type in ("float", "double", "decimal", "numeric", "real", "number"):
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                errors.append(
                    ValidationError(
                        field_name=field_name,
                        error_type=ErrorType.TYPE_MISMATCH,
                        error_message=f"Field '{field_name}' expects float/numeric, got {type(value).__name__}",
                        original_value=value,
                    )
                )
        elif field_type in ("boolean", "bool"):
            if not isinstance(value, bool):
                errors.append(
                    ValidationError(
                        field_name=field_name,
                        error_type=ErrorType.TYPE_MISMATCH,
                        error_message=f"Field '{field_name}' expects boolean, got {type(value).__name__}",
                        original_value=value,
                    )
                )
        elif field_type in ("date", "datetime"):
            if not isinstance(value, (str, datetime, date)):
                errors.append(
                    ValidationError(
                        field_name=field_name,
                        error_type=ErrorType.TYPE_MISMATCH,
                        error_message=f"Field '{field_name}' expects date or datetime, got {type(value).__name__}",
                        original_value=value,
                    )
                )

        # 3. Maximum string length constraint
        if field.max_length is not None and isinstance(value, str):
            if len(value) > field.max_length:
                errors.append(
                    ValidationError(
                        field_name=field_name,
                        error_type=ErrorType.MAX_LENGTH_EXCEEDED,
                        error_message=(
                            f"Field '{field_name}' length ({len(value)}) exceeds maximum allowed ({field.max_length})"
                        ),
                        original_value=value,
                    )
                )

        # 4. Enum constraint
        if field.enum is not None and len(field.enum) > 0:
            allowed_values = [str(item) for item in field.enum]
            if str(value) not in allowed_values:
                errors.append(
                    ValidationError(
                        field_name=field_name,
                        error_type=ErrorType.ENUM_VIOLATION,
                        error_message=f"Field '{field_name}' value '{value}' is not in allowed enum values {field.enum}",
                        original_value=value,
                    )
                )

        # 5. Format pattern constraint
        if field.format is not None and isinstance(value, str):
            if not _check_format(value, field.format):
                errors.append(
                    ValidationError(
                        field_name=field_name,
                        error_type=ErrorType.PATTERN_VIOLATION,
                        error_message=f"Field '{field_name}' value '{value}' does not match required format '{field.format}'",
                        original_value=value,
                    )
                )

    return errors


def validate_batch(
    records: list[dict[str, Any]],
    target_schema: SchemaDefinition,
    execution_id: str,
    source_records: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], list[QuarantineEntry]]:
    """
    Validate a batch of transformed records against the target schema.

    Enforces the all-or-nothing record quarantine rule:
      - If a record has ANY validation error, the entire record is excluded from accepted records
      - One QuarantineEntry is generated for each field validation error on that record

    Args:
        records: List of transformed records destined for the target schema.
        target_schema: Target SchemaDefinition.
        execution_id: Execution ID associated with this batch run.
        source_records: Optional list of raw source records corresponding to each row.
                        If omitted, the transformed record itself is stored for audit.

    Returns:
        Tuple of (accepted_records, quarantine_entries).
    """
    accepted_records: list[dict[str, Any]] = []
    quarantine_entries: list[QuarantineEntry] = []

    for row_idx, record in enumerate(records):
        errors = validate_record(record, target_schema)

        if not errors:
            accepted_records.append(record)
        else:
            # Source record representation for quarantine context
            if source_records and row_idx < len(source_records):
                source_repr = source_records[row_idx]
            else:
                source_repr = record

            source_json = json.dumps(source_repr, default=str)

            for err in errors:
                entry = QuarantineEntry(
                    id=str(uuid.uuid4()),
                    execution_id=execution_id,
                    source_record_json=source_json,
                    field_name=err.field_name,
                    error_type=err.error_type.value,
                    error_message=err.error_message,
                    original_value=str(err.original_value) if err.original_value is not None else None,
                    row_index=row_idx,
                )
                quarantine_entries.append(entry)

    return accepted_records, quarantine_entries
