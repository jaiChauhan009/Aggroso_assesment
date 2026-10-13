"""
Unit tests for schema inspector and comparison logic.
"""
import json
import pytest
from core.schema_inspector import parse_schema, compare_schemas, check_type_compatibility, summarize_schema
from storage.models import SchemaDefinition, SchemaField

def test_parse_schema():
    raw = json.dumps({
        "table": "test_table",
        "fields": [
            {"name": "id", "type": "integer", "primary_key": True},
            {"name": "email", "type": "string", "nullable": False}
        ]
    })
    schema = parse_schema(raw)
    assert schema.table == "test_table"
    assert len(schema.fields) == 2
    assert schema.fields[0].name == "id"

def test_compare_schemas_and_compatibility():
    source = SchemaDefinition(
        table="src",
        fields=[
            SchemaField(name="id", type="string"),
            {"name": "notes", "type": "string"}
        ]
    )
    target = SchemaDefinition(
        table="tgt",
        fields=[
            SchemaField(name="id", type="integer"),
            {"name": "score", "type": "float"}
        ]
    )
    diff = compare_schemas(source, target)
    matched_names = [m["name"] for m in diff["matched"]]
    assert "id" in matched_names
    src_only_names = [f.name for f in diff["source_only"]]
    tgt_only_names = [f.name for f in diff["target_only"]]
    assert "notes" in src_only_names
    assert "score" in tgt_only_names

    comp, note = check_type_compatibility("string", "integer")
    assert comp is True
    assert "CAST_INT" in note
    assert "parsing" in note.lower() or "conversion" in note.lower() or "cast" in note.lower()
