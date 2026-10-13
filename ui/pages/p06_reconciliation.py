"""
Page 6: Reconciliation & Rollback
Compare source vs target totals, view audit trail, rollback migrations.
"""
from __future__ import annotations

import json
import streamlit as st

from storage.repositories import (
    PlanRepo, ExecutionRepo, QuarantineRepo,
    TargetStoreRepo, AuditRepo, SampleRecordRepo, SchemaRepo,
)
from storage.models import PlanStatus
from ui.components.stats_cards import render_stats_cards


def render():
    st.title("📊 Reconciliation & Rollback")
    st.markdown(
        "Compare source and target totals, verify migration integrity, "
        "and rollback if needed. Full audit trail preserved."
    )

    # ── Reconciliation ──────────────────────────────────────────────────────
    st.subheader("🔍 Reconciliation Report")

    all_executions = ExecutionRepo.get_all()
    live_executions = [
        e for e in all_executions
        if (e.execution_type.value if hasattr(e.execution_type, 'value') else e.execution_type) == "LIVE"
    ]

    if not live_executions:
        st.info("No live executions to reconcile. Execute a migration first.")
    else:
        exe_options = {
            f"Execution {e.started_at[:19]} — {e.status.value if hasattr(e.status, 'value') else e.status}": e.id
            for e in live_executions
        }

        selected_label = st.selectbox("Select execution to reconcile", options=list(exe_options.keys()))
        execution_id = exe_options[selected_label]

        if st.button("📊 Run Reconciliation", type="primary"):
            with st.spinner("🔄 Comparing source vs target..."):
                try:
                    from core.reconciliation import reconcile
                    report = reconcile(execution_id)

                    # Display reconciliation
                    col1, col2, col3 = st.columns(3)
                    with col1:
                        st.metric("📥 Source Count", report.source_count)
                    with col2:
                        st.metric("✅ Target Count", report.target_count)
                    with col3:
                        st.metric("❌ Quarantined", report.quarantine_count)

                    if report.is_balanced:
                        st.success(
                            f"✅ **Balanced!** {report.source_count} = "
                            f"{report.target_count} (target) + {report.quarantine_count} (quarantined)"
                        )
                    else:
                        st.error(
                            f"⚠️ **IMBALANCED!** Source ({report.source_count}) ≠ "
                            f"Target ({report.target_count}) + Quarantined ({report.quarantine_count}) "
                            f"= {report.target_count + report.quarantine_count}"
                        )

                    if report.discrepancies:
                        st.markdown("**Discrepancies:**")
                        for d in report.discrepancies:
                            st.warning(d)

                    st.session_state["reconciliation_execution_id"] = execution_id

                except Exception as e:
                    st.error(f"Reconciliation failed: {e}")
                    import traceback
                    st.code(traceback.format_exc())

        # Show execution details
        execution = ExecutionRepo.get(execution_id)
        if execution:
            with st.expander("📊 Execution Details"):
                render_stats_cards(execution)

    # ── Rollback ────────────────────────────────────────────────────────────
    st.markdown("---")
    st.subheader("⏪ Rollback")

    rollback_executions = [
        e for e in live_executions
        if (e.status.value if hasattr(e.status, 'value') else e.status) in ("SUCCESS", "PARTIAL")
    ] if live_executions else []

    if not rollback_executions:
        st.info("No executions available for rollback.")
    else:
        rb_options = {
            f"Execution {e.started_at[:19]} — {e.status.value if hasattr(e.status, 'value') else e.status} "
            f"({e.accepted_count} records in target)": e.id
            for e in rollback_executions
        }

        rb_label = st.selectbox("Select execution to rollback", options=list(rb_options.keys()), key="rb_select")
        rb_id = rb_options[rb_label]

        st.warning(
            "⚠️ **Rollback will DELETE all records inserted by this execution from the target store.** "
            "Quarantine records will be preserved for evidence."
        )

        # Confirmation
        confirm = st.checkbox("I understand this action is destructive and want to proceed", key="rb_confirm")

        if confirm:
            if st.button("⏪ Rollback Execution", type="primary", use_container_width=True):
                with st.spinner("⏪ Rolling back..."):
                    try:
                        from core.rollback import rollback_execution
                        result = rollback_execution(rb_id)
                        st.success(
                            f"✅ Rollback completed! "
                            f"**{result.records_deleted}** records deleted from target store."
                        )
                        st.rerun()
                    except Exception as e:
                        st.error(f"Rollback failed: {e}")
                        import traceback
                        st.code(traceback.format_exc())

    # ── Full Audit Trail ────────────────────────────────────────────────────
    st.markdown("---")
    st.subheader("📜 Full Audit Trail")

    audit_entries = AuditRepo.get_all()
    if not audit_entries:
        st.info("No audit entries yet.")
    else:
        rows = []
        for e in audit_entries:
            rows.append({
                "Timestamp": e.timestamp[:19] if e.timestamp else "",
                "Action": e.action.value if hasattr(e.action, 'value') else e.action,
                "Entity ID": e.entity_id[:8] + "..." if len(e.entity_id) > 8 else e.entity_id,
                "Details": e.details_json,
            })

        st.dataframe(rows, use_container_width=True, hide_index=True)

        # Stats
        col1, col2 = st.columns(2)
        with col1:
            action_counts = {}
            for e in audit_entries:
                action = e.action.value if hasattr(e.action, 'value') else e.action
                action_counts[action] = action_counts.get(action, 0) + 1
            st.markdown("**Actions Summary:**")
            for action, count in sorted(action_counts.items()):
                st.markdown(f"- {action}: {count}")

        with col2:
            st.metric("Total Audit Entries", len(audit_entries))
            if audit_entries:
                st.metric("Latest Action",
                          audit_entries[0].action.value if hasattr(audit_entries[0].action, 'value') else audit_entries[0].action)

    # ── Overall Summary ────────────────────────────────────────────────────
    st.markdown("---")
    st.subheader("📈 Overall Summary")

    source_rec = SchemaRepo.get_by_direction("source")
    sample_count = SampleRecordRepo.count_by_schema(source_rec.id) if source_rec else 0
    target_count = TargetStoreRepo.count_all()

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Source Records", sample_count)
    with col2:
        st.metric("Target Records", target_count)
    with col3:
        plans = PlanRepo.get_all()
        st.metric("Plan Versions", len(plans))
    with col4:
        st.metric("Total Executions", len(all_executions) if all_executions else 0)
