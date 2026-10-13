"""
Tool definitions and helper functions for the AI Migration Agent.

These are Python functions invoked by the agent orchestration layer to inspect
schemas, fetch sample data, list transformation rules, and validate mapping proposals.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from config import GEMINI_API_KEY, GEMINI_MODEL, TRANSFORMATION_RULES
from storage.models import FieldMapping, SchemaDefinition, SchemaField
from storage.repositories import SampleRecordRepo, SchemaRepo

# Optional imports from core packages if available
try:
    from core.schema_inspector import inspect_schema
except (ImportError, ModuleNotFoundError):
    inspect_schema = None

try:
    from core.transformation_engine import get_transformation_catalog
except (ImportError, ModuleNotFoundError):
    get_transformation_catalog = None

logger = logging.getLogger(__name__)


# ── Built-in Transformation Catalog Fallback ──────────────────────────────────

_DEFAULT_CATALOG: list[dict[str, Any]] = [
    {
        "name": "RENAME",
        "description": "Direct 1-to-1 field mapping from source to target without modifying value or type.",
        "params": {},
        "example": {"transformation": "RENAME", "params": {}},
    },
    {
        "name": "CAST_INT",
        "description": "Cast source value (string or float) to integer.",
        "params": {},
        "example": {"transformation": "CAST_INT", "params": {}},
    },
    {
        "name": "CAST_FLOAT",
        "description": "Cast source value (string or integer) to floating-point number.",
        "params": {},
        "example": {"transformation": "CAST_FLOAT", "params": {}},
    },
    {
        "name": "CAST_STRING",
        "description": "Convert source value of any type to string representation.",
        "params": {},
        "example": {"transformation": "CAST_STRING", "params": {}},
    },
    {
        "name": "CAST_BOOL",
        "description": "Convert truthy/falsy source value ('true', '1', 'yes', 't') to boolean True/False.",
        "params": {},
        "example": {"transformation": "CAST_BOOL", "params": {}},
    },
    {
        "name": "DATE_REFORMAT",
        "description": "Parse date/datetime string and reformat to target format pattern.",
        "params": {
            "output_format": "str (required, e.g. '%Y-%m-%d')",
            "input_format": "str (optional, e.g. '%m/%d/%Y')",
        },
        "example": {
            "transformation": "DATE_REFORMAT",
            "params": {"input_format": "%m/%d/%Y", "output_format": "%Y-%m-%d"},
        },
    },
    {
        "name": "UPPERCASE",
        "description": "Convert string value to uppercase.",
        "params": {},
        "example": {"transformation": "UPPERCASE", "params": {}},
    },
    {
        "name": "LOWERCASE",
        "description": "Convert string value to lowercase.",
        "params": {},
        "example": {"transformation": "LOWERCASE", "params": {}},
    },
    {
        "name": "TRIM",
        "description": "Strip leading and trailing whitespace from string value.",
        "params": {},
        "example": {"transformation": "TRIM", "params": {}},
    },
    {
        "name": "DEFAULT",
        "description": "Provide a fallback value if source field is null, empty, or missing.",
        "params": {"value": "Any (required)"},
        "example": {"transformation": "DEFAULT", "params": {"value": "N/A"}},
    },
    {
        "name": "CONCAT",
        "description": "Concatenate multiple source fields together with a separator string.",
        "params": {
            "fields": "list[str] (required, source field names to concatenate)",
            "separator": "str (optional, default ' ')",
        },
        "example": {
            "transformation": "CONCAT",
            "params": {"fields": ["first_name", "last_name"], "separator": " "},
        },
    },
    {
        "name": "SPLIT",
        "description": "Split source string by delimiter and extract element at index.",
        "params": {
            "delimiter": "str (required)",
            "index": "int (required, 0-based element index)",
        },
        "example": {"transformation": "SPLIT", "params": {"delimiter": " ", "index": 0}},
    },
    {
        "name": "TRUNCATE",
        "description": "Truncate string value to a maximum character length.",
        "params": {"max_length": "int (required, positive integer)"},
        "example": {"transformation": "TRUNCATE", "params": {"max_length": 50}},
    },
    {
        "name": "MAP_VALUES",
        "description": "Map categorical or enum source values to target values using a lookup dictionary.",
        "params": {
            "mapping": "dict[str, Any] (required, lookup dictionary)",
            "default": "Any (optional, fallback if value not in mapping)",
        },
        "example": {
            "transformation": "MAP_VALUES",
            "params": {
                "mapping": {"M": "Male", "F": "Female", "O": "Other"},
                "default": "Unknown",
            },
        },
    },
    {
        "name": "ROUND",
        "description": "Round numeric value to a specified number of decimal places.",
        "params": {"decimals": "int (optional, default 0)"},
        "example": {"transformation": "ROUND", "params": {"decimals": 2}},
    },
    {
        "name": "DROP",
        "description": "Explicitly ignore source field, omitting it from target output.",
        "params": {},
        "example": {"transformation": "DROP", "params": {}},
    },
]


# ── Inspection Tools ─────────────────────────────────────────────────────────

def inspect_source_schema() -> dict[str, Any]:
    """Retrieve and summarize the active source schema from the database.

    Returns:
        dict: A summary dictionary containing table name, schema ID, and list of
              field definitions with types, nullability, constraints, formats, and enums.
    """
    record = SchemaRepo.get_by_direction("source")
    if not record:
        return {"id": "", "name": "", "table": "", "fields": [], "error": "No source schema found"}

    definition = record.to_definition()
    return {
        "id": record.id,
        "name": record.name,
        "table": definition.table,
        "fields": [
            {
                "name": f.name,
                "type": f.type,
                "nullable": f.nullable,
                "primary_key": f.primary_key,
                "max_length": f.max_length,
                "format": f.format,
                "enum": f.enum,
                "default": f.default,
            }
            for f in definition.fields
        ],
    }


def inspect_target_schema() -> dict[str, Any]:
    """Retrieve and summarize the active target schema from the database.

    Returns:
        dict: A summary dictionary containing table name, schema ID, and list of
              field definitions with types, nullability, constraints, formats, and enums.
    """
    record = SchemaRepo.get_by_direction("target")
    if not record:
        return {"id": "", "name": "", "table": "", "fields": [], "error": "No target schema found"}

    definition = record.to_definition()
    return {
        "id": record.id,
        "name": record.name,
        "table": definition.table,
        "fields": [
            {
                "name": f.name,
                "type": f.type,
                "nullable": f.nullable,
                "primary_key": f.primary_key,
                "max_length": f.max_length,
                "format": f.format,
                "enum": f.enum,
                "default": f.default,
            }
            for f in definition.fields
        ],
    }


def get_sample_records(limit: int = 5) -> list[dict[str, Any]]:
    """Retrieve sample source records from the database.

    Args:
        limit: Maximum number of sample records to return (defaults to 5).

    Returns:
        list[dict]: List of parsed source sample record dictionaries.
    """
    source_record = SchemaRepo.get_by_direction("source")
    if not source_record:
        return []

    samples = SampleRecordRepo.get_by_schema(source_record.id)
    return [s.to_dict() for s in samples[:limit]]


def list_transformations() -> list[dict[str, Any]]:
    """Return the complete catalog of supported transformation rules with descriptions and parameters.

    Returns:
        list[dict]: List of transformation descriptors.
    """
    if callable(get_transformation_catalog):
        try:
            catalog = get_transformation_catalog()
            if catalog:
                return catalog
        except Exception as e:
            logger.debug(f"get_transformation_catalog failed ({e}), using default catalog.")

    return _DEFAULT_CATALOG


# ── Validation & Type Compatibility Tools ────────────────────────────────────

def validate_mapping(mapping: dict[str, Any]) -> dict[str, Any]:
    """Validate a single field mapping proposal against schemas and transformation rules.

    Checks:
    - Transformation rule is recognized in TRANSFORMATION_RULES.
    - Required parameters are present and well-formed.
    - Target field exists in the target schema (if target schema exists).
    - Source field(s) exist in the source schema (if source schema exists).

    Args:
        mapping: Mapping proposal dictionary containing 'source_field', 'target_field',
                 'transformation', and optional 'params'.

    Returns:
        dict: {"valid": bool, "errors": list[str]}
    """
    errors: list[str] = []

    source_field = mapping.get("source_field", "")
    target_field = mapping.get("target_field", "")
    transformation = mapping.get("transformation", "")
    params = mapping.get("params") or {}

    # 1. Transformation rule validity
    if not transformation:
        errors.append("Transformation rule cannot be empty.")
    elif transformation not in TRANSFORMATION_RULES:
        errors.append(
            f"Invalid transformation rule '{transformation}'. Must be one of: {', '.join(TRANSFORMATION_RULES)}"
        )

    # 2. Target field validity (DROP does not require target field)
    if transformation != "DROP" and not target_field:
        errors.append("Target field must be specified for non-DROP transformations.")

    # 3. Parameter validation per rule
    if transformation == "DATE_REFORMAT":
        out_fmt = params.get("output_format") or params.get("format")
        if not out_fmt:
            errors.append("DATE_REFORMAT requires 'output_format' parameter.")
    elif transformation == "CONCAT":
        fields = params.get("fields")
        if not isinstance(fields, list) or len(fields) < 2:
            errors.append("CONCAT requires 'fields' parameter containing a list of at least 2 source field names.")
    elif transformation == "SPLIT":
        if "delimiter" not in params:
            errors.append("SPLIT requires 'delimiter' parameter.")
        if "index" not in params or not isinstance(params["index"], int):
            errors.append("SPLIT requires an integer 'index' parameter.")
    elif transformation == "TRUNCATE":
        max_len = params.get("max_length")
        if max_len is None or not isinstance(max_len, int) or max_len <= 0:
            errors.append("TRUNCATE requires a positive integer 'max_length' parameter.")
    elif transformation == "MAP_VALUES":
        mapping_dict = params.get("mapping")
        if not isinstance(mapping_dict, dict) or not mapping_dict:
            errors.append("MAP_VALUES requires a non-empty dictionary 'mapping' parameter.")
    elif transformation == "DEFAULT":
        if "value" not in params:
            errors.append("DEFAULT transformation requires 'value' parameter.")
    elif transformation == "ROUND":
        decimals = params.get("decimals")
        if decimals is not None and (not isinstance(decimals, int) or decimals < 0):
            errors.append("ROUND requires 'decimals' parameter to be a non-negative integer.")

    # 4. Check schema existence if schemas are loaded
    source_schema_info = inspect_source_schema()
    target_schema_info = inspect_target_schema()

    if source_schema_info.get("fields") and transformation not in ("DEFAULT", "DROP"):
        src_names = {f["name"] for f in source_schema_info["fields"]}
        if transformation == "CONCAT":
            for f in params.get("fields", []):
                if f not in src_names:
                    errors.append(f"CONCAT source field '{f}' not found in source schema.")
        elif source_field and source_field not in src_names:
            errors.append(f"Source field '{source_field}' not found in source schema.")

    if target_schema_info.get("fields") and target_field and transformation != "DROP":
        tgt_names = {f["name"] for f in target_schema_info["fields"]}
        if target_field not in tgt_names:
            errors.append(f"Target field '{target_field}' not found in target schema.")

    return {
        "valid": len(errors) == 0,
        "errors": errors,
    }


def check_type_compatibility(source_type: str, target_type: str) -> dict[str, Any]:
    """Check if two data types are compatible and suggest required transformations.

    Args:
        source_type: Data type string of the source field (e.g., 'string', 'integer', 'float', 'boolean', 'date').
        target_type: Data type string of the target field.

    Returns:
        dict: {"compatible": bool, "suggested_transform": str | None, "notes": str}
    """
    s_type = (source_type or "").lower().strip()
    t_type = (target_type or "").lower().strip()

    # Normalization aliases
    type_map = {
        "int": "integer",
        "int32": "integer",
        "int64": "integer",
        "bigint": "integer",
        "float32": "float",
        "float64": "float",
        "double": "float",
        "decimal": "float",
        "numeric": "float",
        "str": "string",
        "text": "string",
        "varchar": "string",
        "char": "string",
        "bool": "boolean",
        "datetime": "timestamp",
    }
    s_norm = type_map.get(s_type, s_type)
    t_norm = type_map.get(t_type, t_type)

    if s_norm == t_norm:
        return {
            "compatible": True,
            "suggested_transform": "RENAME",
            "notes": "Types match directly.",
        }

    # String source conversions
    if s_norm == "string":
        if t_norm == "integer":
            return {
                "compatible": False,
                "suggested_transform": "CAST_INT",
                "notes": "Requires CAST_INT; non-numeric string values will fail casting.",
            }
        if t_norm == "float":
            return {
                "compatible": False,
                "suggested_transform": "CAST_FLOAT",
                "notes": "Requires CAST_FLOAT; non-numeric values will fail casting.",
            }
        if t_norm == "boolean":
            return {
                "compatible": False,
                "suggested_transform": "CAST_BOOL",
                "notes": "Requires CAST_BOOL; evaluates truthy/falsy values ('true', '1', 'yes').",
            }
        if t_norm in ("date", "timestamp"):
            return {
                "compatible": False,
                "suggested_transform": "DATE_REFORMAT",
                "notes": "Requires DATE_REFORMAT with appropriate input and output format patterns.",
            }

    # Numeric source conversions
    if s_norm == "integer":
        if t_norm == "float":
            return {
                "compatible": True,
                "suggested_transform": "CAST_FLOAT",
                "notes": "Safe widening conversion.",
            }
        if t_norm == "string":
            return {
                "compatible": True,
                "suggested_transform": "CAST_STRING",
                "notes": "Safe conversion to string representation.",
            }
        if t_norm == "boolean":
            return {
                "compatible": False,
                "suggested_transform": "CAST_BOOL",
                "notes": "0 converts to False, non-zero converts to True.",
            }

    if s_norm == "float":
        if t_norm == "integer":
            return {
                "compatible": False,
                "suggested_transform": "CAST_INT",
                "notes": "Narrowing conversion; truncates fractional part (potential data loss). Consider ROUND.",
            }
        if t_norm == "string":
            return {
                "compatible": True,
                "suggested_transform": "CAST_STRING",
                "notes": "Safe conversion to string representation.",
            }

    # Boolean source conversions
    if s_norm == "boolean":
        if t_norm == "string":
            return {
                "compatible": True,
                "suggested_transform": "CAST_STRING",
                "notes": "Converts boolean to string ('True' or 'False').",
            }
        if t_norm == "integer":
            return {
                "compatible": False,
                "suggested_transform": "CAST_INT",
                "notes": "Converts True to 1 and False to 0.",
            }

    # Date / Timestamp conversions
    if s_norm in ("date", "timestamp"):
        if t_norm == "string":
            return {
                "compatible": True,
                "suggested_transform": "CAST_STRING",
                "notes": "Safe conversion of date to ISO string.",
            }
        if s_norm == "date" and t_norm == "timestamp":
            return {
                "compatible": True,
                "suggested_transform": "DATE_REFORMAT",
                "notes": "Date expands to timestamp with midnight time component.",
            }
        if s_norm == "timestamp" and t_norm == "date":
            return {
                "compatible": False,
                "suggested_transform": "DATE_REFORMAT",
                "notes": "Discards time component of timestamp (precision loss).",
            }

    return {
        "compatible": False,
        "suggested_transform": "CAST_STRING",
        "notes": f"No direct type compatibility from '{source_type}' to '{target_type}'. Defaulting to string cast.",
    }
