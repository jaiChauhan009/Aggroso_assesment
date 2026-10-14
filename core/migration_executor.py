"""
Migration execution engine orchestrating dry-run and live pipeline executions.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from core.idempotency import generate_key
from core.transformation_engine import TransformationError, apply_mappings
from core.validation_pipeline import validate_record
from storage.models import (
    AuditAction,
    ErrorType,
    Execution,
    ExecutionStatus,
    ExecutionType,
    PlanStatus,
    QuarantineEntry,
    TargetRecord,
)
from storage.repositories import (
    AuditRepo,
    ExecutionRepo,
    PlanRepo,
    QuarantineRepo,
    SampleRecordRepo,
    SchemaRepo,
    TargetStoreRepo,
)


def _now() -> str:
    """Return current UTC timestamp in ISO 8601 format."""
    return datetime.now(timezone.utc).isoformat()


def _process_records(
    plan_id: str,
    execution_id: str,
    samples: list[Any],
    mappings: list[Any],
    target_schema: Any,
) -> tuple[list[tuple[int, dict[str, Any], dict[str, Any]]], list[QuarantineEntry], int, set[int]]:
    """
    Internal helper to execute transformation and validation over a list of sample records.

    Returns:
        tuple containing:
          - accepted_records: list of (row_index, source_dict, transformed_dict)
          - quarantine_entries: list of QuarantineEntry instances
          - transformed_count: number of records successfully transformed before validation
          - rejected_row_indices: set of row indices that encountered errors
    """
    accepted_records: list[tuple[int, dict[str, Any], dict[str, Any]]] = []
    quarantine_entries: list[QuarantineEntry] = []
    transformed_count = 0
    rejected_row_indices: set[int] = set()

    for idx, sample in enumerate(samples):
        src_dict = sample.to_dict()
        row_idx = getattr(sample, "row_index", idx)

        # 1. Transformation stage
        try:
            transformed = apply_mappings(mappings, src_dict)
            transformed_count += 1
        except TransformationError as exc:
            rejected_row_indices.add(row_idx)
            entry = QuarantineEntry(
                id=str(uuid.uuid4()),
                execution_id=execution_id,
                source_record_json=sample.record_json,
                field_name=exc.field,
                error_type=ErrorType.TRANSFORM_FAILED.value,
                error_message=exc.message,
                original_value=str(exc.original_value) if exc.original_value is not None else None,
                row_index=row_idx,
            )
            quarantine_entries.append(entry)
            continue
        except Exception as exc:
            rejected_row_indices.add(row_idx)
            entry = QuarantineEntry(
                id=str(uuid.uuid4()),
                execution_id=execution_id,
                source_record_json=sample.record_json,
                field_name="transformation",
                error_type=ErrorType.TRANSFORM_FAILED.value,
                error_message=f"Transformation exception: {exc}",
                original_value=None,
                row_index=row_idx,
            )
            quarantine_entries.append(entry)
            continue

        # 2. Validation stage
        validation_errors = validate_record(transformed, target_schema)
        if validation_errors:
            rejected_row_indices.add(row_idx)
            for err in validation_errors:
                entry = QuarantineEntry(
                    id=str(uuid.uuid4()),
                    execution_id=execution_id,
                    source_record_json=sample.record_json,
                    field_name=err.field_name,
                    error_type=err.error_type.value,
                    error_message=err.error_message,
                    original_value=str(err.original_value) if err.original_value is not None else None,
                    row_index=row_idx,
                )
                quarantine_entries.append(entry)
        else:
            accepted_records.append((row_idx, src_dict, transformed))

    return accepted_records, quarantine_entries, transformed_count, rejected_row_indices


def dry_run(plan_id: str) -> Execution:
    """
    Perform a read-only dry-run execution of a migration plan.

    Loads the plan, resolves source and target schemas, executes transformation
    and validation on sample records, logs quarantine errors, and creates an
    Execution record with type DRY_RUN. Does NOT insert records into target_store.

    Args:
        plan_id: The ID of the MigrationPlan to test.

    Returns:
        The completed Execution instance containing metrics.

    Raises:
        ValueError: If the plan or required schemas are missing.
    """
    plan = PlanRepo.get(plan_id)
    if not plan:
        raise ValueError(f"Migration plan '{plan_id}' not found")

    target_schema_rec = SchemaRepo.get_by_direction("target")
    if not target_schema_rec:
        raise ValueError("Target schema not found. Please upload or register a target schema first.")
    target_schema = target_schema_rec.to_definition()

    source_schema_rec = SchemaRepo.get_by_direction("source")
    samples = SampleRecordRepo.get_by_schema(source_schema_rec.id) if source_schema_rec else []

    exe = ExecutionRepo.create(plan_id=plan_id, execution_type=ExecutionType.DRY_RUN)
    mappings = plan.get_mappings()

    accepted_records, quarantine_entries, transformed_count, rejected_row_indices = _process_records(
        plan_id=plan_id,
        execution_id=exe.id,
        samples=samples,
        mappings=mappings,
        target_schema=target_schema,
    )

    # Save quarantine entries
    if quarantine_entries:
        QuarantineRepo.save_batch(quarantine_entries)

    # Update execution record
    exe.source_count = len(samples)
    exe.transformed_count = transformed_count
    exe.accepted_count = len(accepted_records)
    exe.rejected_count = len(rejected_row_indices)
    exe.completed_at = _now()

    if exe.rejected_count == 0:
        exe.status = ExecutionStatus.SUCCESS
    elif exe.accepted_count > 0:
        exe.status = ExecutionStatus.PARTIAL
    else:
        exe.status = ExecutionStatus.FAILED

    ExecutionRepo.update(exe)

    # Log audit trail
    AuditRepo.log(
        action=AuditAction.DRY_RUN,
        entity_id=exe.id,
        details={
            "plan_id": plan_id,
            "source_count": exe.source_count,
            "accepted_count": exe.accepted_count,
            "rejected_count": exe.rejected_count,
            "status": exe.status.value,
        },
    )

    return exe


def execute_migration(plan_id: str) -> Execution:
    """
    Execute a live migration for an approved plan.

    Enforces that the plan must be in APPROVED status. Executes the transformation
    and validation pipeline, inserts accepted records into the target_store using
    deterministic idempotency keys, stores quarantine entries, updates plan status
    to EXECUTED, and logs audit events.

    Args:
        plan_id: The ID of the MigrationPlan to execute.

    Returns:
        The completed Execution instance containing metrics.

    Raises:
        ValueError: If plan is not found, not APPROVED, or schemas are missing.
    """
    plan = PlanRepo.get(plan_id)
    if not plan:
        raise ValueError(f"Migration plan '{plan_id}' not found")

    if plan.status not in (PlanStatus.APPROVED, PlanStatus.EXECUTED):
        raise ValueError(
            f"Plan '{plan_id}' cannot be executed: current status is '{plan.status.value}'. "
            f"Only plans in APPROVED or EXECUTED status can be executed or retried."
        )

    target_schema_rec = SchemaRepo.get_by_direction("target")
    if not target_schema_rec:
        raise ValueError("Target schema not found. Please upload or register a target schema first.")
    target_schema = target_schema_rec.to_definition()

    source_schema_rec = SchemaRepo.get_by_direction("source")
    samples = SampleRecordRepo.get_by_schema(source_schema_rec.id) if source_schema_rec else []

    exe = ExecutionRepo.create(plan_id=plan_id, execution_type=ExecutionType.LIVE)
    mappings = plan.get_mappings()

    accepted_records, quarantine_entries, transformed_count, rejected_row_indices = _process_records(
        plan_id=plan_id,
        execution_id=exe.id,
        samples=samples,
        mappings=mappings,
        target_schema=target_schema,
    )

    # Live insertion into target store
    target_records: list[TargetRecord] = []
    now_ts = _now()
    for row_idx, src_dict, transformed in accepted_records:
        key = generate_key(plan_id, src_dict, row_idx)
        target_records.append(
            TargetRecord(
                id=str(uuid.uuid4()),
                execution_id=exe.id,
                idempotency_key=key,
                record_json=json.dumps(transformed, default=str),
                inserted_at=now_ts,
            )
        )

    if target_records:
        TargetStoreRepo.insert_batch(target_records)

    # Save quarantine entries
    if quarantine_entries:
        QuarantineRepo.save_batch(quarantine_entries)

    # Update execution metrics
    exe.source_count = len(samples)
    exe.transformed_count = transformed_count
    exe.accepted_count = len(accepted_records)
    exe.rejected_count = len(rejected_row_indices)
    exe.completed_at = _now()

    if exe.rejected_count == 0:
        exe.status = ExecutionStatus.SUCCESS
    elif exe.accepted_count > 0:
        exe.status = ExecutionStatus.PARTIAL
    else:
        exe.status = ExecutionStatus.FAILED

    ExecutionRepo.update(exe)

    # Update plan status to EXECUTED
    PlanRepo.update_status(plan_id, PlanStatus.EXECUTED)

    # Audit log
    AuditRepo.log(
        action=AuditAction.EXECUTED,
        entity_id=exe.id,
        details={
            "plan_id": plan_id,
            "source_count": exe.source_count,
            "accepted_count": exe.accepted_count,
            "rejected_count": exe.rejected_count,
            "status": exe.status.value,
        },
    )

    return exe
