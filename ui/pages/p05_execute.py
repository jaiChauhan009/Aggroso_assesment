"""
Page 5: Execute Migration
Execute an approved migration into the mock target database.
"""
from __future__ import annotations

import json
import streamlit as st

from storage.repositories import PlanRepo, ExecutionRepo, TargetStoreRepo, AuditRepo
from storage.models import PlanStatus
from ui.components.stats_cards import render_stats_cards, render_execution_status


def render():
    st.title("🚀 Execute Migration")
    st.markdown(
        "Execute an **approved migration plan** into the mock target database. "
        "Idempotency keys prevent duplicate insertions on retry."
    )

    # ── Select Approved Plan ────────────────────────────────────────────────
    plans = PlanRepo.get_all()
    approved_plans = [
        p for p in plans
        if (p.status.value if hasattr(p.status, 'value') else p.status) == "APPROVED"
    ]
    executed_plans = [
        p for p in plans
        if (p.status.value if hasattr(p.status, 'value') else p.status) == "EXECUTED"
    ]

    if not approved_plans and not executed_plans:
        st.warning("⚠️ No approved plans available. Go to **Plan Review** to approve a plan first.")
        return

    st.subheader("📋 Available Plans")

    # Show approved plans
    if approved_plans:
        st.markdown("#### ✅ Ready for Execution")
        for p in approved_plans:
            col1, col2, col3, col4 = st.columns([2, 1, 1, 2])
            with col1:
                st.markdown(f"**Plan v{p.version}**")
            with col2:
                st.markdown(f"Approved: {p.approved_at[:10] if p.approved_at else 'N/A'}")
            with col3:
                mappings = p.get_mappings()
                st.markdown(f"{len(mappings)} mappings")
            with col4:
                if st.button(f"🚀 Execute v{p.version}", key=f"exec_{p.id}", type="primary"):
                    _execute_plan(p.id, p.version)

    # Show executed plans for retry
    if executed_plans:
        st.markdown("---")
        st.markdown("#### 🔁 Retry Previously Executed")
        st.caption("Idempotency keys ensure no duplicates on retry.")

        for p in executed_plans:
            col1, col2, col3 = st.columns([2, 1, 2])
            with col1:
                st.markdown(f"**Plan v{p.version}** (already executed)")
            with col2:
                target_count = TargetStoreRepo.count_all()
                st.markdown(f"{target_count} records in target")
            with col3:
                if st.button(f"🔁 Retry v{p.version}", key=f"retry_{p.id}"):
                    _execute_plan(p.id, p.version, is_retry=True)

    # ── Execution History ───────────────────────────────────────────────────
    st.markdown("---")
    st.subheader("📜 Execution History")

    all_executions = ExecutionRepo.get_all()
    live_executions = [
        e for e in all_executions
        if (e.execution_type.value if hasattr(e.execution_type, 'value') else e.execution_type) == "LIVE"
    ]

    if not live_executions:
        st.info("No live executions yet.")
    else:
        for exe in live_executions:
            with st.expander(
                f"{'🟢' if exe.status.value == 'SUCCESS' else '🟡' if exe.status.value == 'PARTIAL' else '🔴'} "
                f"Execution {exe.started_at[:19]} — {exe.status.value}",
            ):
                render_execution_status(exe)
                render_stats_cards(exe)

    # ── Target Store Preview ────────────────────────────────────────────────
    st.markdown("---")
    st.subheader("🗄️ Target Store Preview")

    target_count = TargetStoreRepo.count_all()
    st.metric("Total Records in Target Store", target_count)

    if target_count > 0:
        with st.expander(f"Preview target records (first 10)"):
            records = TargetStoreRepo.get_all()
            for rec in records[:10]:
                st.json(rec.to_dict())


def _execute_plan(plan_id: str, version: int, is_retry: bool = False):
    """Execute or retry a migration plan."""
    action = "Retrying" if is_retry else "Executing"
    with st.spinner(f"🔄 {action} migration plan v{version}..."):
        try:
            from core.migration_executor import execute_migration
            execution = execute_migration(plan_id)

            st.success(f"✅ Migration {'retried' if is_retry else 'executed'} successfully!")
            st.markdown("---")

            render_execution_status(execution)
            render_stats_cards(execution)

            if execution.rejected_count > 0:
                st.warning(f"⚠️ {execution.rejected_count} records were quarantined. View details on the Dry Run page.")

            # Show idempotency info on retry
            if is_retry:
                st.info(
                    "🔁 Retry completed. Duplicate records were skipped via idempotency keys. "
                    "Check reconciliation for full details."
                )

        except ValueError as e:
            st.error(f"Cannot execute: {e}")
        except Exception as e:
            st.error(f"Migration failed: {e}")
            import traceback
            st.code(traceback.format_exc())
