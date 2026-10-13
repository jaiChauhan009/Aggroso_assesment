"""
Repository (CRUD) layer for all database entities.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Optional

from storage.database import get_connection
from storage.models import (
    AuditAction,
    AuditLogEntry,
    Execution,
    ExecutionStatus,
    ExecutionType,
    FieldMapping,
    MigrationPlan,
    PlanStatus,
    QuarantineEntry,
    SampleRecord,
    SchemaRecord,
    TargetRecord,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _uuid() -> str:
    return str(uuid.uuid4())


# ── Schemas ─────────────────────────────────────────────────────────────────

class SchemaRepo:
    @staticmethod
    def save(name: str, direction: str, schema_json: str) -> SchemaRecord:
        rec = SchemaRecord(
            id=_uuid(), name=name, direction=direction,
            schema_json=schema_json, created_at=_now(),
        )
        conn = get_connection()
        try:
            conn.execute(
                "INSERT INTO schemas (id, name, direction, schema_json, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (rec.id, rec.name, rec.direction, rec.schema_json, rec.created_at),
            )
            conn.commit()
        finally:
            conn.close()
        return rec

    @staticmethod
    def get_by_direction(direction: str) -> Optional[SchemaRecord]:
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT * FROM schemas WHERE direction = ? ORDER BY created_at DESC LIMIT 1",
                (direction,),
            ).fetchone()
            return SchemaRecord(**dict(row)) if row else None
        finally:
            conn.close()

    @staticmethod
    def get_all() -> list[SchemaRecord]:
        conn = get_connection()
        try:
            rows = conn.execute("SELECT * FROM schemas ORDER BY created_at DESC").fetchall()
            return [SchemaRecord(**dict(r)) for r in rows]
        finally:
            conn.close()

    @staticmethod
    def delete_by_direction(direction: str) -> None:
        conn = get_connection()
        try:
            conn.execute("DELETE FROM schemas WHERE direction = ?", (direction,))
            conn.commit()
        finally:
            conn.close()


# ── Sample Records ──────────────────────────────────────────────────────────

class SampleRecordRepo:
    @staticmethod
    def save_batch(schema_id: str, records: list[dict]) -> int:
        conn = get_connection()
        try:
            for i, rec in enumerate(records):
                conn.execute(
                    "INSERT INTO sample_records (id, schema_id, record_json, row_index) "
                    "VALUES (?, ?, ?, ?)",
                    (_uuid(), schema_id, json.dumps(rec), i),
                )
            conn.commit()
            return len(records)
        finally:
            conn.close()

    @staticmethod
    def get_by_schema(schema_id: str) -> list[SampleRecord]:
        conn = get_connection()
        try:
            rows = conn.execute(
                "SELECT * FROM sample_records WHERE schema_id = ? ORDER BY row_index",
                (schema_id,),
            ).fetchall()
            return [SampleRecord(**dict(r)) for r in rows]
        finally:
            conn.close()

    @staticmethod
    def count_by_schema(schema_id: str) -> int:
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT COUNT(*) as cnt FROM sample_records WHERE schema_id = ?",
                (schema_id,),
            ).fetchone()
            return row["cnt"] if row else 0
        finally:
            conn.close()

    @staticmethod
    def delete_by_schema(schema_id: str) -> None:
        conn = get_connection()
        try:
            conn.execute("DELETE FROM sample_records WHERE schema_id = ?", (schema_id,))
            conn.commit()
        finally:
            conn.close()


# ── Migration Plans ─────────────────────────────────────────────────────────

class PlanRepo:
    @staticmethod
    def create(
        mappings: list[FieldMapping],
        risk_notes: str = "",
        ai_questions: str = "",
    ) -> MigrationPlan:
        conn = get_connection()
        try:
            # Get next version number
            row = conn.execute("SELECT MAX(version) as mv FROM migration_plans").fetchone()
            next_version = (row["mv"] or 0) + 1

            mappings_json = json.dumps([m.model_dump() for m in mappings])
            plan = MigrationPlan(
                id=_uuid(),
                version=next_version,
                status=PlanStatus.DRAFT,
                mappings_json=mappings_json,
                transformations_json=mappings_json,
                risk_notes=risk_notes,
                ai_questions=ai_questions,
                created_at=_now(),
            )
            conn.execute(
                "INSERT INTO migration_plans "
                "(id, version, status, mappings_json, transformations_json, "
                "risk_notes, ai_questions, user_answers, created_at, approved_at, approved_by) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (plan.id, plan.version, plan.status.value, plan.mappings_json,
                 plan.transformations_json, plan.risk_notes, plan.ai_questions,
                 plan.user_answers, plan.created_at, plan.approved_at, plan.approved_by),
            )
            conn.commit()

            # Audit
            AuditRepo.log(AuditAction.PLAN_CREATED, plan.id, {"version": next_version})
            return plan
        finally:
            conn.close()

    @staticmethod
    def get(plan_id: str) -> Optional[MigrationPlan]:
        conn = get_connection()
        try:
            row = conn.execute("SELECT * FROM migration_plans WHERE id = ?", (plan_id,)).fetchone()
            return MigrationPlan(**dict(row)) if row else None
        finally:
            conn.close()

    @staticmethod
    def get_latest() -> Optional[MigrationPlan]:
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT * FROM migration_plans ORDER BY version DESC LIMIT 1"
            ).fetchone()
            return MigrationPlan(**dict(row)) if row else None
        finally:
            conn.close()

    @staticmethod
    def get_all() -> list[MigrationPlan]:
        conn = get_connection()
        try:
            rows = conn.execute(
                "SELECT * FROM migration_plans ORDER BY version DESC"
            ).fetchall()
            return [MigrationPlan(**dict(r)) for r in rows]
        finally:
            conn.close()

    @staticmethod
    def approve(plan_id: str, approved_by: str = "user") -> None:
        now = _now()
        conn = get_connection()
        try:
            conn.execute(
                "UPDATE migration_plans SET status = ?, approved_at = ?, approved_by = ? WHERE id = ?",
                (PlanStatus.APPROVED.value, now, approved_by, plan_id),
            )
            conn.commit()
            AuditRepo.log(AuditAction.APPROVED, plan_id, {"approved_by": approved_by})
        finally:
            conn.close()

    @staticmethod
    def update_status(plan_id: str, status: PlanStatus) -> None:
        conn = get_connection()
        try:
            conn.execute(
                "UPDATE migration_plans SET status = ? WHERE id = ?",
                (status.value, plan_id),
            )
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def update_answers(plan_id: str, answers: str) -> None:
        conn = get_connection()
        try:
            conn.execute(
                "UPDATE migration_plans SET user_answers = ? WHERE id = ?",
                (answers, plan_id),
            )
            conn.commit()
        finally:
            conn.close()


# ── Executions ──────────────────────────────────────────────────────────────

class ExecutionRepo:
    @staticmethod
    def create(plan_id: str, execution_type: ExecutionType) -> Execution:
        exe = Execution(
            id=_uuid(),
            plan_id=plan_id,
            execution_type=execution_type,
            started_at=_now(),
        )
        conn = get_connection()
        try:
            conn.execute(
                "INSERT INTO executions "
                "(id, plan_id, execution_type, source_count, transformed_count, "
                "accepted_count, rejected_count, started_at, completed_at, status) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (exe.id, exe.plan_id, exe.execution_type.value,
                 exe.source_count, exe.transformed_count,
                 exe.accepted_count, exe.rejected_count,
                 exe.started_at, exe.completed_at, exe.status.value),
            )
            conn.commit()
        finally:
            conn.close()
        return exe

    @staticmethod
    def update(exe: Execution) -> None:
        conn = get_connection()
        try:
            conn.execute(
                "UPDATE executions SET source_count=?, transformed_count=?, "
                "accepted_count=?, rejected_count=?, completed_at=?, status=? WHERE id=?",
                (exe.source_count, exe.transformed_count, exe.accepted_count,
                 exe.rejected_count, exe.completed_at, exe.status.value, exe.id),
            )
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def get(execution_id: str) -> Optional[Execution]:
        conn = get_connection()
        try:
            row = conn.execute("SELECT * FROM executions WHERE id = ?", (execution_id,)).fetchone()
            return Execution(**dict(row)) if row else None
        finally:
            conn.close()

    @staticmethod
    def get_by_plan(plan_id: str) -> list[Execution]:
        conn = get_connection()
        try:
            rows = conn.execute(
                "SELECT * FROM executions WHERE plan_id = ? ORDER BY started_at DESC",
                (plan_id,),
            ).fetchall()
            return [Execution(**dict(r)) for r in rows]
        finally:
            conn.close()

    @staticmethod
    def get_all() -> list[Execution]:
        conn = get_connection()
        try:
            rows = conn.execute("SELECT * FROM executions ORDER BY started_at DESC").fetchall()
            return [Execution(**dict(r)) for r in rows]
        finally:
            conn.close()


# ── Quarantine ──────────────────────────────────────────────────────────────

class QuarantineRepo:
    @staticmethod
    def save(entry: QuarantineEntry) -> None:
        conn = get_connection()
        try:
            conn.execute(
                "INSERT INTO quarantine "
                "(id, execution_id, source_record_json, field_name, error_type, "
                "error_message, original_value, row_index) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (entry.id, entry.execution_id, entry.source_record_json,
                 entry.field_name, entry.error_type, entry.error_message,
                 entry.original_value, entry.row_index),
            )
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def save_batch(entries: list[QuarantineEntry]) -> None:
        if not entries:
            return
        conn = get_connection()
        try:
            conn.executemany(
                "INSERT INTO quarantine "
                "(id, execution_id, source_record_json, field_name, error_type, "
                "error_message, original_value, row_index) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [(e.id, e.execution_id, e.source_record_json, e.field_name,
                  e.error_type, e.error_message, e.original_value, e.row_index)
                 for e in entries],
            )
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def get_by_execution(execution_id: str) -> list[QuarantineEntry]:
        conn = get_connection()
        try:
            rows = conn.execute(
                "SELECT * FROM quarantine WHERE execution_id = ? ORDER BY row_index",
                (execution_id,),
            ).fetchall()
            return [QuarantineEntry(**dict(r)) for r in rows]
        finally:
            conn.close()

    @staticmethod
    def count_by_execution(execution_id: str) -> int:
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT COUNT(*) as cnt FROM quarantine WHERE execution_id = ?",
                (execution_id,),
            ).fetchone()
            return row["cnt"] if row else 0
        finally:
            conn.close()


# ── Target Store ────────────────────────────────────────────────────────────

class TargetStoreRepo:
    @staticmethod
    def insert(record: TargetRecord) -> bool:
        """Insert a record. Returns False if idempotency_key already exists."""
        conn = get_connection()
        try:
            cursor = conn.execute(
                "INSERT OR IGNORE INTO target_store "
                "(id, execution_id, idempotency_key, record_json, inserted_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (record.id, record.execution_id, record.idempotency_key,
                 record.record_json, record.inserted_at),
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    @staticmethod
    def insert_batch(records: list[TargetRecord]) -> int:
        """Insert records, skipping duplicates. Returns count of newly inserted."""
        if not records:
            return 0
        conn = get_connection()
        try:
            inserted = 0
            for rec in records:
                cursor = conn.execute(
                    "INSERT OR IGNORE INTO target_store "
                    "(id, execution_id, idempotency_key, record_json, inserted_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (rec.id, rec.execution_id, rec.idempotency_key,
                     rec.record_json, rec.inserted_at),
                )
                inserted += cursor.rowcount
            conn.commit()
            return inserted
        finally:
            conn.close()

    @staticmethod
    def get_by_execution(execution_id: str) -> list[TargetRecord]:
        conn = get_connection()
        try:
            rows = conn.execute(
                "SELECT * FROM target_store WHERE execution_id = ? ORDER BY inserted_at",
                (execution_id,),
            ).fetchall()
            return [TargetRecord(**dict(r)) for r in rows]
        finally:
            conn.close()

    @staticmethod
    def count_by_execution(execution_id: str) -> int:
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT COUNT(*) as cnt FROM target_store WHERE execution_id = ?",
                (execution_id,),
            ).fetchone()
            return row["cnt"] if row else 0
        finally:
            conn.close()

    @staticmethod
    def count_all() -> int:
        conn = get_connection()
        try:
            row = conn.execute("SELECT COUNT(*) as cnt FROM target_store").fetchone()
            return row["cnt"] if row else 0
        finally:
            conn.close()

    @staticmethod
    def delete_by_execution(execution_id: str) -> int:
        """Delete all records for an execution (rollback). Returns count deleted."""
        conn = get_connection()
        try:
            cursor = conn.execute(
                "DELETE FROM target_store WHERE execution_id = ?", (execution_id,),
            )
            conn.commit()
            return cursor.rowcount
        finally:
            conn.close()

    @staticmethod
    def get_all() -> list[TargetRecord]:
        conn = get_connection()
        try:
            rows = conn.execute("SELECT * FROM target_store ORDER BY inserted_at").fetchall()
            return [TargetRecord(**dict(r)) for r in rows]
        finally:
            conn.close()


# ── Audit Log ───────────────────────────────────────────────────────────────

class AuditRepo:
    @staticmethod
    def log(action: AuditAction, entity_id: str, details: dict | None = None) -> AuditLogEntry:
        entry = AuditLogEntry(
            id=_uuid(),
            action=action,
            entity_id=entity_id,
            details_json=json.dumps(details or {}),
            timestamp=_now(),
        )
        conn = get_connection()
        try:
            conn.execute(
                "INSERT INTO audit_log (id, action, entity_id, details_json, timestamp) "
                "VALUES (?, ?, ?, ?, ?)",
                (entry.id, entry.action.value, entry.entity_id,
                 entry.details_json, entry.timestamp),
            )
            conn.commit()
        finally:
            conn.close()
        return entry

    @staticmethod
    def get_all() -> list[AuditLogEntry]:
        conn = get_connection()
        try:
            rows = conn.execute("SELECT * FROM audit_log ORDER BY timestamp DESC").fetchall()
            return [AuditLogEntry(**dict(r)) for r in rows]
        finally:
            conn.close()

    @staticmethod
    def get_by_entity(entity_id: str) -> list[AuditLogEntry]:
        conn = get_connection()
        try:
            rows = conn.execute(
                "SELECT * FROM audit_log WHERE entity_id = ? ORDER BY timestamp DESC",
                (entity_id,),
            ).fetchall()
            return [AuditLogEntry(**dict(r)) for r in rows]
        finally:
            conn.close()
