"""
Unit tests for the 16 transformation rules in transformation_engine.
"""
import pytest
from core.transformation_engine import (
    apply_transformation,
    apply_mappings,
    TransformationError,
    _DROP
)
from storage.models import FieldMapping

def test_scalar_transformations():
    rec = {}
    assert apply_transformation("RENAME", "test", {}, rec) == "test"
    assert apply_transformation("CAST_INT", "123", {}, rec) == 123
    assert apply_transformation("CAST_FLOAT", "45.67", {}, rec) == 45.67
    assert apply_transformation("CAST_STRING", 999, {}, rec) == "999"
    assert apply_transformation("CAST_BOOL", "yes", {}, rec) is True
    assert apply_transformation("CAST_BOOL", "no", {}, rec) is False
    assert apply_transformation("UPPERCASE", "hello", {}, rec) == "HELLO"
    assert apply_transformation("LOWERCASE", "WORLD", {}, rec) == "world"
    assert apply_transformation("TRIM", "  spaced  ", {}, rec) == "spaced"
    assert apply_transformation("TRUNCATE", "abcdef", {"max_length": 3}, rec) == "abc"
    assert apply_transformation("ROUND", 3.14159, {"decimals": 2}, rec) == 3.14

def test_default_and_map_values():
    rec = {}
    assert apply_transformation("DEFAULT", None, {"value": "fallback"}, rec) == "fallback"
    assert apply_transformation("MAP_VALUES", "A", {"mapping": {"A": "Alpha"}}, rec) == "Alpha"
    with pytest.raises(TransformationError):
        apply_transformation("MAP_VALUES", "Z", {"mapping": {"A": "Alpha"}}, rec)

def test_concat_split_and_drop():
    rec = {"first": "Jane", "last": "Doe", "full": "Jane_Doe"}
    res = apply_transformation("CONCAT", None, {"fields": ["first", "last"], "separator": " "}, rec)
    assert res == "Jane Doe"

    split_res = apply_transformation("SPLIT", rec["full"], {"delimiter": "_", "index": 0}, rec)
    assert split_res == "Jane"

    drop_res = apply_transformation("DROP", "anything", {}, rec)
    assert drop_res is _DROP

def test_date_reformat():
    rec = {}
    res = apply_transformation("DATE_REFORMAT", "12/25/2024", {"input_format": "%m/%d/%Y", "output_format": "%Y-%m-%d"}, rec)
    assert res == "2024-12-25"
