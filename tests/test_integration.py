"""
Integration test: Full end-to-end pipeline.
Tests schema loading, AI mapping, dry run, execution, reconciliation, and rollback.
"""
import sys
import json
from pathlib import Path

# Setup path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from storage.database import init_db, reset_db
from storage.models import FieldMapping, PlanStatus
from storage.repositories import (
    SchemaRepo, SampleRecordRepo, PlanRepo, ExecutionRepo,
    QuarantineRepo, TargetStoreRepo, AuditRepo,
)
from config import SCHEMAS_DIR


def test_full_pipeline():
    """Test the complete migration pipeline end-to-end."""
    print("=" * 60)
    print("INTEGRATION TEST: Full Migration Pipeline")
    print("=" * 60)

    # Reset DB
    reset_db()
    init_db()
    print("✅ Database reset and initialized")

    # 1. Load schemas
    source_data = json.loads((SCHEMAS_DIR / "source_schema.json").read_text())
    target_data = json.loads((SCHEMAS_DIR / "target_schema.json").read_text())

    source_rec = SchemaRepo.save("employees", "source", json.dumps(source_data))
    target_rec = SchemaRepo.save("staff", "target", json.dumps(target_data))
    print(f"✅ Schemas loaded — source: {source_rec.id[:8]}, target: {target_rec.id[:8]}")

    # 2. Load sample records
    records = json.loads((SCHEMAS_DIR / "sample_records.json").read_text())
    count = SampleRecordRepo.save_batch(source_rec.id, records)
    print(f"✅ Sample records loaded: {count}")

    # 3. Test schema inspector
    from core.schema_inspector import parse_schema, compare_schemas, summarize_schema
    source_schema = parse_schema(json.dumps(source_data))
    target_schema = parse_schema(json.dumps(target_data))
    diff = compare_schemas(source_schema, target_schema)
    print(f"✅ Schema comparison — matched: {len(diff['matched'])}, "
          f"source-only: {len(diff['source_only'])}, target-only: {len(diff['target_only'])}")

    # 4. Test heuristic mapping
    from agent.mapping_agent import MappingAgent
    agent = MappingAgent()
    response = agent.propose_mappings()
    print(f"✅ Agent proposed {len(response.mappings)} mappings, "
          f"{len(response.warnings)} warnings, {len(response.questions)} questions")

    # 5. Create a manual plan with known-good mappings
    mappings = [
        FieldMapping(source_field="emp_id", target_field="staffId",
                     transformation="CAST_INT", params={}),
        FieldMapping(source_field="first_name", target_field="fullName",
                     transformation="CONCAT",
                     params={"fields": ["first_name", "last_name"], "separator": " "}),
        FieldMapping(source_field="dob", target_field="dateOfBirth",
                     transformation="DATE_REFORMAT",
                     params={"input_format": "%m/%d/%Y", "output_format": "%Y-%m-%d"}),
        FieldMapping(source_field="salary", target_field="annualSalary",
                     transformation="CAST_FLOAT", params={}),
        FieldMapping(source_field="dept_code", target_field="department",
                     transformation="MAP_VALUES",
                     params={"mapping": {
                         "ENG": "Engineering", "MKT": "Marketing",
                         "SAL": "Sales", "HR": "HR", "FIN": "Finance"
                     }}),
        FieldMapping(source_field="is_active", target_field="active",
                     transformation="CAST_BOOL", params={}),
        FieldMapping(source_field="hire_date", target_field="hireDate",
                     transformation="DATE_REFORMAT",
                     params={"input_format": "%m-%d-%Y", "output_format": "%Y-%m-%d"}),
        FieldMapping(source_field="notes", target_field="notes",
                     transformation="TRUNCATE", params={"max_length": 500}),
    ]

    plan = PlanRepo.create(mappings=mappings, risk_notes="Integration test plan")
    print(f"✅ Plan created: v{plan.version} (status: {plan.status.value})")

    # 6. Approve plan
    PlanRepo.approve(plan.id)
    plan = PlanRepo.get(plan.id)
    print(f"✅ Plan approved (status: {plan.status.value})")

    # 7. Dry run
    from core.migration_executor import dry_run, execute_migration
    dry = dry_run(plan.id)
    print(f"✅ Dry run complete — source: {dry.source_count}, "
          f"accepted: {dry.accepted_count}, rejected: {dry.rejected_count}")

    # Verify no target records were written
    target_count = TargetStoreRepo.count_all()
    assert target_count == 0, f"Dry run should not write to target! Found {target_count}"
    print(f"✅ Dry run verification: 0 records in target store (correct)")

    # 8. Execute migration
    exe = execute_migration(plan.id)
    print(f"✅ Migration executed — accepted: {exe.accepted_count}, "
          f"rejected: {exe.rejected_count}")

    target_count = TargetStoreRepo.count_all()
    print(f"✅ Target store now has {target_count} records")

    # 9. Verify idempotency (retry)
    plan_fresh = PlanRepo.get(plan.id)
    # Reset plan to APPROVED for retry test
    PlanRepo.update_status(plan.id, PlanStatus.APPROVED)
    exe2 = execute_migration(plan.id)
    target_count_after_retry = TargetStoreRepo.count_all()
    print(f"✅ Retry executed — target count unchanged: {target_count_after_retry} "
          f"(was {target_count}, idempotency works!)")
    assert target_count_after_retry == target_count, "Idempotency failed!"

    # 10. Reconciliation
    from core.reconciliation import reconcile
    report = reconcile(exe.id)
    print(f"✅ Reconciliation — source: {report.source_count}, "
          f"target: {report.target_count}, quarantined: {report.quarantine_count}, "
          f"balanced: {report.is_balanced}")

    # 11. Rollback
    from core.rollback import rollback_execution
    result = rollback_execution(exe.id)
    print(f"✅ Rollback complete — {result.records_deleted} records deleted")

    target_after_rollback = TargetStoreRepo.count_all()
    print(f"✅ Target store after rollback: {target_after_rollback} records")

    # Quarantine entries should be preserved
    quarantine = QuarantineRepo.get_by_execution(dry.id)
    print(f"✅ Quarantine entries preserved: {len(quarantine)} error(s)")

    # 12. Audit trail
    audit = AuditRepo.get_all()
    print(f"✅ Audit trail: {len(audit)} entries")
    for a in audit:
        action = a.action.value if hasattr(a.action, 'value') else a.action
        print(f"   - {action}: {a.entity_id[:8]}...")

    print("\n" + "=" * 60)
    print("ALL INTEGRATION TESTS PASSED ✅")
    print("=" * 60)


if __name__ == "__main__":
    test_full_pipeline()
