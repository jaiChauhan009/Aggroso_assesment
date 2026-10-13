"""
Rollback mechanisms for reversing live migration executions.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from storage.models import AuditAction, ExecutionStatus, PlanStatus
from storage.repositories import AuditRepo, ExecutionRepo, PlanRepo, TargetStoreRepo


def _now() -> str:
    """Return current UTC timestamp in ISO 8601 format."""
    return datetime.now(timezone.utc).isoformat()


@dataclass
class RollbackResult:
    """Outcome metadata of a migration rollback execution."""

    records_deleted: int
    execution_id: str
    timestamp: str
    plan_id: str
    status: str = "SUCCESS"


def rollback_execution(execution_id: str) -> RollbackResult:
    """
    Rollback a live migration execution by deleting target records and updating statuses.

    Actions:
      1. Delete all records from target_store where execution_id = ?
      2. Update the associated migration plan's status to ROLLED_BACK
      3. Update the execution status to FAILED
      4. Log an immutable ROLLED_BACK entry in the audit trail

    Args:
        execution_id: ID of the Execution record to roll back.

    Returns:
        RollbackResult containing deletion count, timestamps, and status.

    Raises:
        ValueError: If the execution ID does not exist.
    """
    exe = ExecutionRepo.get(execution_id)
    if not exe:
        raise ValueError(f"Execution '{execution_id}' not found")

    # 1. Delete target records inserted by this execution
    records_deleted = TargetStoreRepo.delete_by_execution(execution_id)

    # 2. Update plan status
    PlanRepo.update_status(exe.plan_id, PlanStatus.ROLLED_BACK)

    # 3. Update execution status to FAILED
    exe.status = ExecutionStatus.FAILED
    ExecutionRepo.update(exe)

    # 4. Audit trail logging
    now_ts = _now()
    AuditRepo.log(
        action=AuditAction.ROLLED_BACK,
        entity_id=execution_id,
        details={
            "plan_id": exe.plan_id,
            "records_deleted": records_deleted,
            "timestamp": now_ts,
        },
    )

    return RollbackResult(
        records_deleted=records_deleted,
        execution_id=execution_id,
        timestamp=now_ts,
        plan_id=exe.plan_id,
        status="SUCCESS",
    )
