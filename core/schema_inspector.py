"""
Schema inspection and comparison tools for migration planning.
"""
from __future__ import annotations

import json
from typing import Any

from storage.models import SchemaDefinition, SchemaField

# Type mapping aliases to canonical categories
_TYPE_ALIASES: dict[str, str] = {
    "str": "string",
    "string": "string",
    "text": "string",
    "varchar": "string",
    "char": "string",
    "int": "integer",
    "integer": "integer",
    "bigint": "integer",
    "smallint": "integer",
    "tinyint": "integer",
    "float": "float",
    "double": "float",
    "decimal": "float",
    "numeric": "float",
    "real": "float",
    "number": "float",
    "bool": "boolean",
    "boolean": "boolean",
    "date": "date",
    "datetime": "datetime",
    "timestamp": "datetime",
}


def parse_schema(json_str: str) -> SchemaDefinition:
    """
    Parse a SchemaDefinition from a JSON string.

    Args:
        json_str: JSON formatted string representing a SchemaDefinition.

    Returns:
        SchemaDefinition instance.

    Raises:
        ValueError: If JSON is invalid or does not match the schema structure.
    """
    if not json_str or not json_str.strip():
        raise ValueError("Schema JSON string is empty")

    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON syntax in schema definition: {exc}") from exc

    if isinstance(data, list):
        # Case where a list of fields was passed directly
        return SchemaDefinition(table="unnamed_table", fields=[SchemaField.model_validate(f) for f in data])

    if isinstance(data, dict):
        if "table" not in data and "fields" in data:
            data["table"] = "unnamed_table"
        try:
            return SchemaDefinition.model_validate(data)
        except Exception as exc:
            raise ValueError(f"Schema data does not match SchemaDefinition structure: {exc}") from exc

    raise ValueError(f"Unsupported schema JSON format: expected object or list, got {type(data).__name__}")


def check_type_compatibility(source_type: str, target_type: str) -> tuple[bool, str]:
    """
    Detect type compatibility between source and target field types.

    Args:
        source_type: Source field type (e.g., 'string', 'integer', 'float', 'boolean', 'date').
        target_type: Target field type (e.g., 'string', 'integer', 'float', 'boolean', 'date').

    Returns:
        A tuple of (compatible: bool, reason_or_suggestion: str).
    """
    src = _TYPE_ALIASES.get(source_type.strip().lower(), source_type.strip().lower())
    tgt = _TYPE_ALIASES.get(target_type.strip().lower(), target_type.strip().lower())

    if src == tgt:
        return True, "Types are identical"

    # String target can accept almost anything
    if tgt == "string":
        return True, f"Type '{source_type}' can be converted to String with CAST_STRING"

    # Widening conversions
    if src == "integer" and tgt == "float":
        return True, "Integer can be widened to Float losslessly"

    # Narrowing conversions requiring care
    if src == "float" and tgt == "integer":
        return True, "Float can be converted to Integer with precision loss (use ROUND or CAST_INT)"

    if src == "boolean" and tgt == "integer":
        return True, "Boolean can be converted to Integer (0/1)"

    if src == "integer" and tgt == "boolean":
        return True, "Integer can be converted to Boolean (0=False, non-zero=True)"

    # String source parsing
    if src == "string":
        if tgt == "integer":
            return True, "String can be parsed to Integer with CAST_INT"
        if tgt == "float":
            return True, "String can be parsed to Float with CAST_FLOAT"
        if tgt == "boolean":
            return True, "String can be parsed to Boolean with CAST_BOOL"
        if tgt in ("date", "datetime"):
            return True, "String can be parsed to Date with DATE_REFORMAT"

    # Date to Datetime
    if src == "date" and tgt == "datetime":
        return True, "Date can be promoted to DateTime"

    if src == "datetime" and tgt == "date":
        return True, "DateTime can be converted to Date (time component truncated)"

    return False, f"Incompatible types: '{source_type}' cannot be directly converted to '{target_type}'"


def compare_schemas(source_schema: SchemaDefinition, target_schema: SchemaDefinition) -> dict[str, Any]:
    """
    Compare source and target schemas to find matched, source-only, and target-only fields.

    Args:
        source_schema: Source SchemaDefinition.
        target_schema: Target SchemaDefinition.

    Returns:
        A dictionary containing:
          - matched: list of matched field comparison details
          - source_only: list of SchemaField objects present only in source
          - target_only: list of SchemaField objects present only in target
          - matched_field_names: list of names present in both schemas
          - source_only_names: list of names present only in source
          - target_only_names: list of names present only in target
          - is_identical: bool indicating exact schema identity
    """
    source_fields_map = {f.name: f for f in source_schema.fields}
    target_fields_map = {f.name: f for f in target_schema.fields}

    source_names = set(source_fields_map.keys())
    target_names = set(target_fields_map.keys())

    common_names = sorted(source_names & target_names)
    source_only_names = sorted(source_names - target_names)
    target_only_names = sorted(target_names - source_names)

    matched = []
    for name in common_names:
        sf = source_fields_map[name]
        tf = target_fields_map[name]
        compatible, note = check_type_compatibility(sf.type, tf.type)
        matched.append({
            "name": name,
            "source_field": sf,
            "target_field": tf,
            "source_type": sf.type,
            "target_type": tf.type,
            "type_compatible": compatible,
            "notes": note,
        })

    is_identical = (
        len(source_only_names) == 0
        and len(target_only_names) == 0
        and all(m["source_type"] == m["target_type"] for m in matched)
    )

    return {
        "matched": matched,
        "source_only": [source_fields_map[name] for name in source_only_names],
        "target_only": [target_fields_map[name] for name in target_only_names],
        "matched_field_names": common_names,
        "source_only_names": source_only_names,
        "target_only_names": target_only_names,
        "is_identical": is_identical,
    }


def summarize_schema(schema: SchemaDefinition) -> dict[str, Any]:
    """
    Summarize a schema including field counts, types breakdown, nullable fields, and constraints.

    Args:
        schema: SchemaDefinition to inspect.

    Returns:
        A summary dictionary with:
          - table: table name
          - field_count: total fields
          - fields: list of field names
          - types_breakdown: count per field type
          - nullable_fields: names of nullable fields
          - required_fields: names of non-nullable fields
          - primary_keys: primary key field names
          - constraints: list of constraint descriptors for constrained fields
    """
    types_breakdown: dict[str, int] = {}
    nullable_fields: list[str] = []
    required_fields: list[str] = []
    primary_keys: list[str] = []
    constraints: list[dict[str, Any]] = []

    for f in schema.fields:
        # Types breakdown
        canonical_type = _TYPE_ALIASES.get(f.type.lower(), f.type.lower())
        types_breakdown[canonical_type] = types_breakdown.get(canonical_type, 0) + 1

        # Nullability
        if f.nullable:
            nullable_fields.append(f.name)
        else:
            required_fields.append(f.name)

        # Primary Key
        if f.primary_key:
            primary_keys.append(f.name)

        # Constraints
        field_constraints: dict[str, Any] = {"field": f.name}
        has_constraint = False

        if f.max_length is not None:
            field_constraints["max_length"] = f.max_length
            has_constraint = True
        if f.format is not None:
            field_constraints["format"] = f.format
            has_constraint = True
        if f.enum is not None:
            field_constraints["enum"] = f.enum
            has_constraint = True
        if f.default is not None:
            field_constraints["default"] = f.default
            has_constraint = True

        if has_constraint:
            constraints.append(field_constraints)

    return {
        "table": schema.table,
        "field_count": len(schema.fields),
        "fields": schema.field_names(),
        "types_breakdown": types_breakdown,
        "nullable_fields": nullable_fields,
        "required_fields": required_fields,
        "primary_keys": primary_keys,
        "constraints": constraints,
    }
