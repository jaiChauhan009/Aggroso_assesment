"""
Core engine package for Migration Planner & Reconciliation Workbench.
"""
from core.idempotency import generate_key
from core.migration_executor import dry_run, execute_migration
from core.reconciliation import ReconciliationReport, reconcile
from core.rollback import RollbackResult, rollback_execution
from core.schema_inspector import (
    check_type_compatibility,
    compare_schemas,
    parse_schema,
    summarize_schema,
)
from core.transformation_engine import (
    DROP_SENTINEL,
    TransformationError,
    _DROP,
    apply_mappings,
    apply_transformation,
    get_transformation_catalog,
)
from core.validation_pipeline import (
    ValidationError,
    validate_batch,
    validate_record,
)

__all__ = [
    # Schema Inspector
    "parse_schema",
    "compare_schemas",
    "check_type_compatibility",
    "summarize_schema",
    # Transformation Engine
    "apply_transformation",
    "apply_mappings",
    "get_transformation_catalog",
    "TransformationError",
    "DROP_SENTINEL",
    "_DROP",
    # Validation Pipeline
    "validate_record",
    "validate_batch",
    "ValidationError",
    # Idempotency
    "generate_key",
    # Migration Executor
    "dry_run",
    "execute_migration",
    # Reconciliation
    "reconcile",
    "ReconciliationReport",
    # Rollback
    "rollback_execution",
    "RollbackResult",
]
