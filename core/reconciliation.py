"""
Reconciliation engine comparing source, target, and quarantine records.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from storage.models import ExecutionType
from storage.repositories import ExecutionRepo, QuarantineRepo, TargetStoreRepo


@dataclass
class ReconciliationReport:
    """
    Summary report of data reconciliation across source, target, and quarantine stores.
    """

    execution_id: str
    source_count: int
    target_count: int
    quarantine_count: int
    is_balanced: bool
    discrepancies: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)


def reconcile(execution_id: str) -> ReconciliationReport:
    """
    Compare source, target, and quarantine record counts for a given execution.

    Verifies mathematical consistency:
      source_count == target_count + quarantine_count

    Args:
        execution_id: ID of the Execution record to reconcile.

    Returns:
        ReconciliationReport instance detailing counts, balance status, and any discrepancies.

    Raises:
        ValueError: If the specified execution is not found.
    """
    exe = ExecutionRepo.get(execution_id)
    if not exe:
        raise ValueError(f"Execution '{execution_id}' not found")

    source_count = exe.source_count

    # Determine target count
    stored_target_count = TargetStoreRepo.count_by_execution(execution_id)
    if exe.execution_type == ExecutionType.DRY_RUN:
        # Dry runs simulate writes; use accepted_count as projected target
        target_count = exe.accepted_count
    else:
        target_count = stored_target_count

    # Determine quarantine count (unique quarantined records)
    quarantine_entries = QuarantineRepo.get_by_execution(execution_id)
    unique_quarantined_rows = len({e.row_index for e in quarantine_entries})
    quarantine_count = unique_quarantined_rows if quarantine_entries else exe.rejected_count

    # Mathematical balance check
    is_balanced = source_count == (target_count + quarantine_count)

    discrepancies: list[str] = []
    if not is_balanced:
        diff = source_count - (target_count + quarantine_count)
        discrepancies.append(
            f"Record balance failed: Source records ({source_count}) != "
            f"Target records ({target_count}) + Quarantined records ({quarantine_count}) "
            f"(discrepancy difference: {diff})"
        )

    # Secondary checks
    if exe.execution_type == ExecutionType.LIVE and stored_target_count != exe.accepted_count:
        discrepancies.append(
            f"Database target count ({stored_target_count}) differs from execution accepted count ({exe.accepted_count}). "
            f"Duplicates may have been ignored by idempotency key constraints."
        )

    if exe.rejected_count != quarantine_count:
        discrepancies.append(
            f"Execution rejected count ({exe.rejected_count}) differs from unique quarantined rows ({quarantine_count})."
        )

    details = {
        "execution_type": exe.execution_type.value,
        "execution_status": exe.status.value,
        "stored_target_count": stored_target_count,
        "total_quarantine_error_entries": len(quarantine_entries),
        "started_at": exe.started_at,
        "completed_at": exe.completed_at,
    }

    return ReconciliationReport(
        execution_id=execution_id,
        source_count=source_count,
        target_count=target_count,
        quarantine_count=quarantine_count,
        is_balanced=is_balanced,
        discrepancies=discrepancies,
        details=details,
    )
