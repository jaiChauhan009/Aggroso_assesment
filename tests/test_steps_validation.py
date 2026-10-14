"""
Comprehensive validation script testing every single step of the workflow:
1. Schema upload & storage verification
2. AI Agent inspection & mapping proposal
3. Plan versioning & Human-in-the-loop approval gate
4. Deterministic Dry Run & Quarantine error evidence
5. Live Migration Execution & Idempotency Duplicate Prevention
6. Reconciliation & Atomic Rollback
"""
import sys
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from storage.database import init_db, reset_db
from storage.models import PlanStatus, ExecutionType, ErrorType
from storage.repositories import (
    SchemaRepo, SampleRecordRepo, PlanRepo, ExecutionRepo,
    QuarantineRepo, TargetStoreRepo, AuditRepo
)
from core.schema_inspector import parse_schema, compare_schemas, summarize_schema
from agent.mapping_agent import MappingAgent
from agent.risk_analyzer import analyze_risks
from core.migration_executor import dry_run, execute_migration
from core.reconciliation import reconcile
from core.rollback import rollback_execution
from config import SCHEMAS_DIR

def run_step_by_step_test():
    print("\n" + "="*70)
    print("🚀 EXECUTING COMPLETE STEP-BY-STEP WORKFLOW VALIDATION")
    print("="*70)

    # Clean test start
    reset_db()
    init_db()
    print("\n[DB] Fresh SQLite database initialized.")

    # -------------------------------------------------------------
    # STEP 1: SCHEMA UPLOAD
    # -------------------------------------------------------------
    print("\n--- [STEP 1: 📁 SCHEMA UPLOAD & PREVIEW] ---")
    source_json = (SCHEMAS_DIR / "source_schema.json").read_text()
    target_json = (SCHEMAS_DIR / "target_schema.json").read_text()
    sample_records = json.loads((SCHEMAS_DIR / "sample_records.json").read_text())

    src_rec = SchemaRepo.save("employees", "source", source_json)
    tgt_rec = SchemaRepo.save("staff", "target", target_json)
    rec_count = SampleRecordRepo.save_batch(src_rec.id, sample_records)

    print(f"✅ Source schema saved: '{src_rec.name}' (ID: {src_rec.id[:8]})")
    print(f"✅ Target schema saved: '{tgt_rec.name}' (ID: {tgt_rec.id[:8]})")
    print(f"✅ Sample records stored: {rec_count} records")

    src_def = src_rec.to_definition()
    tgt_def = tgt_rec.to_definition()
    diff = compare_schemas(src_def, tgt_def)
    print(f"✅ Schema comparison: Matched: {len(diff['matched'])}, "
          f"Source-Only: {len(diff['source_only'])}, Target-Only: {len(diff['target_only'])}")
    assert rec_count == 50, "Sample record count must be 50"

    # -------------------------------------------------------------
    # STEP 2: AI MAPPING & RISK ANALYSIS
    # -------------------------------------------------------------
    print("\n--- [STEP 2: 🤖 AI MAPPING & RISK SCORING] ---")
    agent = MappingAgent()
    agent_resp = agent.propose_mappings()

    print(f"✅ AI Agent executed:")
    print(f"   • Proposed mappings count: {len(agent_resp.mappings)}")
    print(f"   • Risk notes identified: {len(agent_resp.risks)}")
    print(f"   • Clarification questions generated: {len(agent_resp.questions)}")
    for m in agent_resp.mappings:
        print(f"     - `{m.source_field}` ➔ `{m.target_field}` [{m.transformation}] {m.params if m.params else ''}")

    risk_report = analyze_risks(agent_resp.mappings, src_def, tgt_def)
    print(f"✅ Risk Analyzer evaluation: Overall Risk Level = {risk_report.overall_risk}")

    # Save Plan Version 1 (DRAFT)
    plan = PlanRepo.create(
        mappings=agent_resp.mappings,
        risk_notes="\n".join(agent_resp.risks),
        ai_questions=json.dumps(agent_resp.questions)
    )
    print(f"✅ Created Plan Version: v{plan.version} (Status: {plan.status.value})")
    assert plan.status == PlanStatus.DRAFT, "Initial plan status must be DRAFT"

    # -------------------------------------------------------------
    # STEP 3: PLAN REVIEW & HUMAN APPROVAL GATE
    # -------------------------------------------------------------
    print("\n--- [STEP 3: 📋 PLAN REVIEW & APPROVAL GATE] ---")
    # Verify execution is blocked while DRAFT
    try:
        execute_migration(plan.id)
        assert False, "Execution should have failed for unapproved DRAFT plan!"
    except ValueError as ve:
        print(f"✅ Safety Gate Verified: Live execution rejected for unapproved plan: '{ve}'")

    # Human Approves Plan
    PlanRepo.approve(plan.id, approved_by="reviewer_qa")
    approved_plan = PlanRepo.get(plan.id)
    print(f"✅ Human approval granted by '{approved_plan.approved_by}' on {approved_plan.approved_at[:19]}")
    print(f"✅ Plan v{approved_plan.version} status updated to: {approved_plan.status.value}")
    assert approved_plan.status == PlanStatus.APPROVED

    # -------------------------------------------------------------
    # STEP 4: DETERMINISTIC DRY RUN & QUARANTINE EVIDENCE
    # -------------------------------------------------------------
    print("\n--- [STEP 4: 🧪 DETERMINISTIC DRY RUN (ZERO TARGET WRITES)] ---")
    dry_exec = dry_run(approved_plan.id)

    print(f"✅ Dry Run completed:")
    print(f"   • Source Records: {dry_exec.source_count}")
    print(f"   • Transformed:    {dry_exec.transformed_count}")
    print(f"   • Accepted:       {dry_exec.accepted_count}")
    print(f"   • Rejected:       {dry_exec.rejected_count}")

    # Mathematical Invariant check
    assert dry_exec.source_count == dry_exec.accepted_count + dry_exec.rejected_count
    print(f"✅ Mathematical invariant verified: {dry_exec.source_count} == {dry_exec.accepted_count} + {dry_exec.rejected_count}")

    # Target store zero-write guarantee verification
    target_count_during_dry = TargetStoreRepo.count_all()
    print(f"✅ Zero-write guarantee verified: Target store has {target_count_during_dry} records")
    assert target_count_during_dry == 0, "Dry run must NOT write to target store!"

    # Quarantine evidence inspection
    quarantine_records = QuarantineRepo.get_by_execution(dry_exec.id)
    print(f"✅ Field-level Quarantine evidence captured: {len(quarantine_records)} errors logged")
    for q in quarantine_records[:3]:
        print(f"     Row {q.row_index}: field='{q.field_name}' error='{q.error_type}' msg='{q.error_message}' orig='{q.original_value}'")

    # -------------------------------------------------------------
    # STEP 5: LIVE MIGRATION & RETRY DEDUPLICATION (IDEMPOTENCY)
    # -------------------------------------------------------------
    print("\n--- [STEP 5: 🚀 LIVE MIGRATION & RETRY IDEMPOTENCY] ---")
    live_exec = execute_migration(approved_plan.id)

    print(f"✅ Live Migration executed (Execution ID: {live_exec.id[:8]}):")
    print(f"   • Inserted into Target Store: {live_exec.accepted_count}")
    print(f"   • Preserved in Quarantine:   {live_exec.rejected_count}")

    total_in_target = TargetStoreRepo.count_all()
    print(f"✅ Target Store verification: Total records in target = {total_in_target}")
    assert total_in_target == live_exec.accepted_count

    # Test Idempotency Retry
    print("\n--- Testing Retry Deduplication (Idempotency) ---")
    PlanRepo.update_status(approved_plan.id, PlanStatus.APPROVED) # reset to allow retry
    retry_exec = execute_migration(approved_plan.id)
    total_after_retry = TargetStoreRepo.count_all()
    print(f"✅ Retry execution completed.")
    print(f"   • Target store count before retry: {total_in_target}")
    print(f"   • Target store count after retry:  {total_after_retry}")
    assert total_in_target == total_after_retry, "Idempotency failed: duplicate records detected!"
    print(f"✅ IDEMPOTENCY SUCCESS: Zero duplicate insertions on retry via unique SHA-256 keys!")

    # -------------------------------------------------------------
    # STEP 6: RECONCILIATION & SAFE ROLLBACK
    # -------------------------------------------------------------
    print("\n--- [STEP 6: 📊 RECONCILIATION & ATOMIC ROLLBACK] ---")
    recon_report = reconcile(live_exec.id)
    print(f"✅ Reconciliation Report:")
    print(f"   • Source Count:     {recon_report.source_count}")
    print(f"   • Target Count:     {recon_report.target_count}")
    print(f"   • Quarantine Count: {recon_report.quarantine_count}")
    print(f"   • Is Balanced:      {recon_report.is_balanced}")
    assert recon_report.is_balanced is True, "Reconciliation must be mathematically balanced!"

    # Test Atomic Rollback
    print("\n--- Testing Atomic Rollback ---")
    rollback_res = rollback_execution(live_exec.id)
    print(f"✅ Rollback executed: {rollback_res.records_deleted} records deleted from target store")
    target_count_post_rollback = TargetStoreRepo.count_all()
    print(f"✅ Target store post-rollback count: {target_count_post_rollback}")
    assert target_count_post_rollback == 0, "Target store should be empty post-rollback!"

    # Verify quarantine evidence survived rollback
    quarantine_post_rollback = QuarantineRepo.count_by_execution(live_exec.id)
    print(f"✅ Quarantine audit trail preserved post-rollback: {quarantine_post_rollback} error records intact")
    assert quarantine_post_rollback > 0, "Quarantine records must be preserved for audit evidence!"

    # Verify Audit Trail
    audit_entries = AuditRepo.get_all()
    print(f"\n✅ Complete Audit Trail Logged ({len(audit_entries)} actions):")
    for a in reversed(audit_entries):
        act = a.action.value if hasattr(a.action, 'value') else a.action
        print(f"   • [{a.timestamp[:19]}] {act:<14} (Entity: {a.entity_id[:8]}...)")

    print("\n" + "="*70)
    print("🎉 ALL 6 STEPS TESTED & VERIFIED SUCCESSFULLY!")
    print("="*70 + "\n")

if __name__ == "__main__":
    run_step_by_step_test()
