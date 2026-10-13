"""
Transformation engine executing data mapping and conversion rules.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

from storage.models import FieldMapping


class _DropSentinel:
    """Sentinel class indicating a field should be dropped from the target record."""

    def __repr__(self) -> str:
        return "<_DROP>"

    def __str__(self) -> str:
        return "<_DROP>"


_DROP = _DropSentinel()
DROP_SENTINEL = _DROP


class TransformationError(Exception):
    """Exception raised when a field transformation fails."""

    def __init__(self, rule: str, field: str, message: str, original_value: Any = None):
        self.rule = rule
        self.field = field
        self.message = message
        self.original_value = original_value
        super().__init__(f"Transformation [{rule}] on field '{field}' failed: {message}")


def _to_strftime_format(fmt: str) -> str:
    """
    Convert user-friendly date format strings (e.g., 'YYYY-MM-DD', 'MM/DD/YYYY')
    into standard Python strftime/strptime format codes.
    """
    if not fmt:
        return "%Y-%m-%d"
    if "%" in fmt:
        return fmt

    # Replace common patterns
    res = fmt
    res = res.replace("YYYY", "%Y").replace("yyyy", "%Y")
    res = res.replace("YY", "%y").replace("yy", "%y")
    res = res.replace("MM", "%m")
    res = res.replace("DD", "%d").replace("dd", "%d")
    res = res.replace("HH", "%H").replace("hh", "%H")
    res = res.replace("mm", "%M")
    res = res.replace("SS", "%S").replace("ss", "%S")
    return res


def _apply_date_reformat(value: Any, params: dict[str, Any], field_name: str) -> str | None:
    """Execute DATE_REFORMAT transformation."""
    if value is None:
        return None

    str_val = str(value).strip()
    if not str_val:
        return None

    raw_in_fmt = params.get("input_format", "%Y-%m-%d")
    raw_out_fmt = params.get("output_format", "%Y-%m-%d")

    in_fmt = _to_strftime_format(raw_in_fmt)
    out_fmt = _to_strftime_format(raw_out_fmt)

    # If already a date or datetime object
    if isinstance(value, (datetime, date)):
        return value.strftime(out_fmt)

    dt: datetime | None = None
    try:
        dt = datetime.strptime(str_val, in_fmt)
    except ValueError:
        # Fallback formats
        fallbacks = ["%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%m-%d-%Y", "%d-%m-%Y", "%Y/%m/%d"]
        for fb in fallbacks:
            if fb == in_fmt:
                continue
            try:
                dt = datetime.strptime(str_val, fb)
                break
            except ValueError:
                continue

    if dt is None:
        # Try ISO format parse
        try:
            dt = datetime.fromisoformat(str_val)
        except (ValueError, TypeError):
            pass

    if dt is None:
        raise TransformationError(
            rule="DATE_REFORMAT",
            field=field_name,
            message=f"Value '{str_val}' does not match expected date format '{raw_in_fmt}'",
            original_value=value,
        )

    return dt.strftime(out_fmt)


def apply_transformation(
    rule: str,
    value: Any,
    params: dict[str, Any] | None = None,
    source_record: dict[str, Any] | None = None,
    field_name: str = "",
) -> Any:
    """
    Apply a single transformation rule to a field value.

    Args:
        rule: Transformation rule identifier (e.g., 'RENAME', 'CAST_INT', etc.).
        value: Original field value from source record.
        params: Rule parameters (e.g., format strings, delimiters, mappings).
        source_record: Complete source record dictionary (used for CONCAT).
        field_name: Name of the field being transformed (for error context).

    Returns:
        Transformed value, or _DROP sentinel if the field is dropped.

    Raises:
        TransformationError: If the transformation cannot be performed.
    """
    rule_upper = rule.strip().upper()
    params = params or {}
    source_record = source_record or {}

    # 1. RENAME - Passthrough
    if rule_upper == "RENAME":
        return value

    # 2. CAST_INT
    if rule_upper == "CAST_INT":
        if value is None:
            return None
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
        str_val = str(value).strip()
        if not str_val:
            return None
        try:
            if "." in str_val:
                return int(float(str_val))
            return int(str_val)
        except (ValueError, TypeError) as exc:
            raise TransformationError("CAST_INT", field_name, f"Cannot cast '{value}' to int: {exc}", value) from exc

    # 3. CAST_FLOAT
    if rule_upper == "CAST_FLOAT":
        if value is None:
            return None
        if isinstance(value, bool):
            return float(value)
        if isinstance(value, (int, float)):
            return float(value)
        str_val = str(value).strip()
        if not str_val:
            return None
        try:
            return float(str_val)
        except (ValueError, TypeError) as exc:
            raise TransformationError("CAST_FLOAT", field_name, f"Cannot cast '{value}' to float: {exc}", value) from exc

    # 4. CAST_STRING
    if rule_upper == "CAST_STRING":
        if value is None:
            return None
        return str(value)

    # 5. CAST_BOOL
    if rule_upper == "CAST_BOOL":
        if value is None:
            return None
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            if value == 1:
                return True
            if value == 0:
                return False
        str_val = str(value).strip().lower()
        if str_val in ("true", "yes", "y", "t", "1"):
            return True
        if str_val in ("false", "no", "n", "f", "0"):
            return False
        raise TransformationError(
            "CAST_BOOL", field_name, f"Cannot cast '{value}' to boolean (expected true/false, yes/no, 1/0)", value
        )

    # 6. DATE_REFORMAT
    if rule_upper == "DATE_REFORMAT":
        return _apply_date_reformat(value, params, field_name)

    # 7. UPPERCASE
    if rule_upper == "UPPERCASE":
        if value is None:
            return None
        return str(value).upper()

    # 8. LOWERCASE
    if rule_upper == "LOWERCASE":
        if value is None:
            return None
        return str(value).lower()

    # 9. TRIM
    if rule_upper == "TRIM":
        if value is None:
            return None
        return str(value).strip()

    # 10. DEFAULT
    if rule_upper == "DEFAULT":
        if value is None or (isinstance(value, str) and not value.strip()):
            return params.get("value", params.get("default"))
        return value

    # 11. CONCAT
    if rule_upper == "CONCAT":
        fields = params.get("fields", [])
        separator = params.get("separator", " ")
        parts = []
        for f in fields:
            f_val = source_record.get(f)
            parts.append(str(f_val) if f_val is not None else "")
        return separator.join(parts)

    # 12. SPLIT
    if rule_upper == "SPLIT":
        if value is None:
            return None
        delimiter = params.get("delimiter", " ")
        index = int(params.get("index", 0))
        parts = str(value).split(delimiter)
        if 0 <= index < len(parts):
            return parts[index]
        if -len(parts) <= index < 0:
            return parts[index]
        raise TransformationError(
            "SPLIT", field_name, f"Index {index} out of range for split result of length {len(parts)}", value
        )

    # 13. TRUNCATE
    if rule_upper == "TRUNCATE":
        if value is None:
            return None
        max_length = int(params.get("max_length", len(str(value))))
        return str(value)[:max_length]

    # 14. MAP_VALUES
    if rule_upper == "MAP_VALUES":
        mapping = params.get("mapping", {})
        if value in mapping:
            return mapping[value]
        str_val = str(value) if value is not None else ""
        if str_val in mapping:
            return mapping[str_val]
        if "default" in params:
            return params["default"]
        raise TransformationError(
            "MAP_VALUES",
            field_name,
            f"Value '{value}' not found in mapping dictionary",
            value,
        )

    # 15. ROUND
    if rule_upper == "ROUND":
        if value is None:
            return None
        decimals = int(params.get("decimals", 0))
        try:
            num = float(value)
            res = round(num, decimals)
            return int(res) if decimals == 0 else res
        except (ValueError, TypeError) as exc:
            raise TransformationError("ROUND", field_name, f"Cannot round non-numeric value '{value}': {exc}", value) from exc

    # 16. DROP
    if rule_upper == "DROP":
        return _DROP

    raise TransformationError(rule_upper, field_name, f"Unknown transformation rule '{rule}'", value)


def apply_mappings(mappings: list[FieldMapping], source_record: dict[str, Any]) -> dict[str, Any]:
    """
    Apply a list of FieldMappings to a source record to produce a transformed target record.

    Fields with the DROP transformation or resulting in the _DROP sentinel will be omitted
    from the target record.

    Args:
        mappings: List of FieldMapping specifications.
        source_record: Raw dictionary representing one source row.

    Returns:
        Transformed record dictionary for the target schema.

    Raises:
        TransformationError: If any mapping transformation fails.
    """
    target_record: dict[str, Any] = {}

    for mapping in mappings:
        val = source_record.get(mapping.source_field)
        transformed = apply_transformation(
            rule=mapping.transformation,
            value=val,
            params=mapping.params or {},
            source_record=source_record,
            field_name=mapping.source_field,
        )

        if transformed is not _DROP:
            target_record[mapping.target_field] = transformed

    return target_record


def get_transformation_catalog() -> list[dict[str, Any]]:
    """
    Return the comprehensive catalog of all 16 supported transformation rules.

    Returns:
        List of dictionary objects containing id, name, description, required_params, and example.
    """
    return [
        {
            "id": "RENAME",
            "name": "Rename Field",
            "description": "Directly maps the source field value to the target field without modifying the data.",
            "required_params": [],
            "example": {"transformation": "RENAME", "params": {}},
        },
        {
            "id": "CAST_INT",
            "name": "Cast to Integer",
            "description": "Converts source value (string, float, bool) to an integer. Blank strings become null.",
            "required_params": [],
            "example": {"transformation": "CAST_INT", "params": {}},
        },
        {
            "id": "CAST_FLOAT",
            "name": "Cast to Float",
            "description": "Converts source value to a floating point number.",
            "required_params": [],
            "example": {"transformation": "CAST_FLOAT", "params": {}},
        },
        {
            "id": "CAST_STRING",
            "name": "Cast to String",
            "description": "Converts source value to its string representation. Null remains null.",
            "required_params": [],
            "example": {"transformation": "CAST_STRING", "params": {}},
        },
        {
            "id": "CAST_BOOL",
            "name": "Cast to Boolean",
            "description": "Converts truthy values ('true', 'yes', '1') and falsy values ('false', 'no', '0') to bool.",
            "required_params": [],
            "example": {"transformation": "CAST_BOOL", "params": {}},
        },
        {
            "id": "DATE_REFORMAT",
            "name": "Reformat Date",
            "description": "Parses date string with input_format and formats it with output_format.",
            "required_params": ["input_format", "output_format"],
            "example": {
                "transformation": "DATE_REFORMAT",
                "params": {"input_format": "MM/DD/YYYY", "output_format": "YYYY-MM-DD"},
            },
        },
        {
            "id": "UPPERCASE",
            "name": "Uppercase",
            "description": "Converts string characters to uppercase.",
            "required_params": [],
            "example": {"transformation": "UPPERCASE", "params": {}},
        },
        {
            "id": "LOWERCASE",
            "name": "Lowercase",
            "description": "Converts string characters to lowercase.",
            "required_params": [],
            "example": {"transformation": "LOWERCASE", "params": {}},
        },
        {
            "id": "TRIM",
            "name": "Trim Whitespace",
            "description": "Strips leading and trailing whitespace from string value.",
            "required_params": [],
            "example": {"transformation": "TRIM", "params": {}},
        },
        {
            "id": "DEFAULT",
            "name": "Default Value",
            "description": "Substitutes a default value if source field is null or empty string.",
            "required_params": ["value"],
            "example": {"transformation": "DEFAULT", "params": {"value": "UNKNOWN"}},
        },
        {
            "id": "CONCAT",
            "name": "Concatenate Fields",
            "description": "Joins multiple source fields using a designated separator string.",
            "required_params": ["fields", "separator"],
            "example": {
                "transformation": "CONCAT",
                "params": {"fields": ["first_name", "last_name"], "separator": " "},
            },
        },
        {
            "id": "SPLIT",
            "name": "Split String",
            "description": "Splits a string by delimiter and extracts the element at the specified index.",
            "required_params": ["delimiter", "index"],
            "example": {"transformation": "SPLIT", "params": {"delimiter": " ", "index": 0}},
        },
        {
            "id": "TRUNCATE",
            "name": "Truncate String",
            "description": "Cuts string value to a maximum length limit.",
            "required_params": ["max_length"],
            "example": {"transformation": "TRUNCATE", "params": {"max_length": 50}},
        },
        {
            "id": "MAP_VALUES",
            "name": "Map Values",
            "description": "Translates values based on a dictionary lookup table.",
            "required_params": ["mapping"],
            "example": {
                "transformation": "MAP_VALUES",
                "params": {"mapping": {"M": "Male", "F": "Female"}, "default": "Other"},
            },
        },
        {
            "id": "ROUND",
            "name": "Round Number",
            "description": "Rounds a numeric value to a specified number of decimal places.",
            "required_params": ["decimals"],
            "example": {"transformation": "ROUND", "params": {"decimals": 2}},
        },
        {
            "id": "DROP",
            "name": "Drop Field",
            "description": "Excludes this field from the migrated target record.",
            "required_params": [],
            "example": {"transformation": "DROP", "params": {}},
        },
    ]
