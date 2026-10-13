"""
Unit tests for validation pipeline and quarantine generation.
"""
from core.validation_pipeline import validate_record, validate_batch
from storage.models import SchemaDefinition, SchemaField, ErrorType

def test_validation_constraints():
    target = SchemaDefinition(
        table="target_users",
        fields=[
            SchemaField(name="user_id", type="integer", nullable=False),
            SchemaField(name="role", type="string", enum=["ADMIN", "USER"]),
            SchemaField(name="code", type="string", max_length=5)
        ]
    )

    # Valid
    valid_rec = {"user_id": 101, "role": "ADMIN", "code": "ABC"}
    assert len(validate_record(valid_rec, target)) == 0

    # Type mismatch and enum violation
    invalid_rec = {"user_id": "not_an_int", "role": "GUEST", "code": "TOOLONGCODE"}
    errors = validate_record(invalid_rec, target)
    err_types = [e.error_type for e in errors]
    assert ErrorType.TYPE_MISMATCH in err_types
    assert ErrorType.ENUM_VIOLATION in err_types
    assert ErrorType.MAX_LENGTH_EXCEEDED in err_types

    # Batch quarantine test
    accepted, quarantine = validate_batch([valid_rec, invalid_rec], target, "test_exec", [valid_rec, invalid_rec])
    assert len(accepted) == 1
    assert len(quarantine) == len(errors)
