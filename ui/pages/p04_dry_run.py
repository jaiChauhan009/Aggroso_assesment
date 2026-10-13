"""
Page 4: Dry Run Dashboard
Execute a deterministic dry run and view results.
"""
from __future__ import annotations

import streamlit as st

from storage.repositories import PlanRepo, ExecutionRepo, QuarantineRepo
from storage.models import PlanStatus
from ui.components.stats_cards import render_stats_cards, render_execution_status
from ui.components.error_table import render_error_table


def render():
    st.title("🧪 Dry Run Dashboard")
    st.markdown(
        "Run a **deterministic dry run** of an approved plan. "
        "No data is written to the target — this is read-only validation."
    )

    # ── Select Approved Plan ────────────────────────────────────────────────
    plans = PlanRepo.get_all()
    approved_plans = [
        p for p in plans
        if (p.status.value if hasattr(p.status, 'value') else p.status) in ("APPROVED", "EXECUTED")
    ]

    if not approved_plans:
        st.warning("⚠️ No approved plans available. Go to **Plan Review** to approve a plan first.")
        return

    plan_options = {
        f"v{p.version} — {p.status.value if hasattr(p.status, 'value') else p.status}": p.id
        for p in approved_plans
    }

    selected_label = st.selectbox("Select an approved plan", options=list(plan_options.keys()))
    selected_id = plan_options[selected_label]

    st.markdown("---")

    # ── Run Dry Run ─────────────────────────────────────────────────────────
    if st.button("🧪 Execute Dry Run", type="primary", use_container_width=True):
        with st.spinner("🔄 Running deterministic dry run... (no data will be written)"):
            try:
                from core.migration_executor import dry_run
                execution = dry_run(selected_id)
                st.session_state["dry_run_execution_id"] = execution.id
                st.success("✅ Dry run completed!")
            except Exception as e:
                st.error(f"Dry run failed: {e}")
                import traceback
                st.code(traceback.format_exc())

    # ── Display Results ─────────────────────────────────────────────────────
    execution_id = st.session_state.get("dry_run_execution_id")
    if not execution_id:
        # Check for previous dry runs
        executions = ExecutionRepo.get_by_plan(selected_id)
        dry_runs = [e for e in executions if e.execution_type.value == "DRY_RUN"]
        if dry_runs:
            st.markdown("### Previous Dry Runs")
            dr_options = {
                f"Run {e.started_at[:19]} — {e.status.value if hasattr(e.status, 'value') else e.status}": e.id
                for e in dry_runs
            }
            dr_label = st.selectbox("View previous dry run", options=list(dr_options.keys()))
            execution_id = dr_options[dr_label]

    if execution_id:
        execution = ExecutionRepo.get(execution_id)
        if execution:
            st.markdown("---")
            st.subheader("📊 Dry Run Results")

            # Execution status
            render_execution_status(execution)
            st.markdown("---")

            # Count cards
            render_stats_cards(execution)
            st.markdown("---")

            # Error details
            quarantine = QuarantineRepo.get_by_execution(execution_id)
            render_error_table(quarantine)

            # Summary
            st.markdown("---")
            status_val = execution.status.value if hasattr(execution.status, 'value') else execution.status
            if execution.rejected_count == 0:
                st.success("🎉 All records passed validation! Ready for live execution.")
            elif status_val == "PARTIAL":
                st.warning(
                    f"⚠️ {execution.rejected_count} records will be quarantined during live migration. "
                    f"{execution.accepted_count} records will be migrated."
                )
            else:
                st.info("Review the errors above and adjust your mapping plan if needed.")
