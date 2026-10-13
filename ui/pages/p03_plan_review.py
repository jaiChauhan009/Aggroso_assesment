"""
Page 3: Plan Review & Approval
View versioned plans, compare versions, approve for execution.
"""
from __future__ import annotations

import json
import streamlit as st

from storage.repositories import PlanRepo, AuditRepo
from storage.models import PlanStatus
from ui.components.mapping_table import render_mapping_summary


def render():
    st.title("📋 Plan Review & Approval")
    st.markdown("Review versioned migration plans, compare changes, and approve for execution.")

    plans = PlanRepo.get_all()

    if not plans:
        st.info("No migration plans created yet. Go to **AI Mapping** page to generate one.")
        return

    # ── Plan Selector ───────────────────────────────────────────────────────
    st.subheader("📑 Migration Plans")

    plan_options = {
        f"v{p.version} — {p.status.value if hasattr(p.status, 'value') else p.status} — {p.created_at[:19]}": p.id
        for p in plans
    }

    selected_label = st.selectbox("Select a plan version", options=list(plan_options.keys()))
    selected_id = plan_options[selected_label]
    plan = PlanRepo.get(selected_id)

    if not plan:
        st.error("Plan not found.")
        return

    # ── Plan Details ────────────────────────────────────────────────────────
    st.markdown("---")

    col1, col2, col3, col4 = st.columns(4)
    status_val = plan.status.value if hasattr(plan.status, 'value') else plan.status
    with col1:
        status_icon = {"DRAFT": "📝", "APPROVED": "✅", "EXECUTED": "🚀", "ROLLED_BACK": "⏪"}.get(status_val, "❓")
        st.metric("Status", f"{status_icon} {status_val}")
    with col2:
        st.metric("Version", plan.version)
    with col3:
        st.metric("Created", plan.created_at[:19] if plan.created_at else "N/A")
    with col4:
        st.metric("Approved", plan.approved_at[:19] if plan.approved_at else "—")

    # ── Mappings ────────────────────────────────────────────────────────────
    st.subheader("🔗 Mappings")
    try:
        mappings = plan.get_mappings()
        render_mapping_summary(mappings)
    except Exception as e:
        st.error(f"Error parsing mappings: {e}")
        st.json(json.loads(plan.mappings_json))

    # ── Risk Notes ──────────────────────────────────────────────────────────
    if plan.risk_notes:
        with st.expander("⚠️ Risk Notes"):
            st.markdown(plan.risk_notes)

    # ── AI Questions & Answers ──────────────────────────────────────────────
    if plan.ai_questions and plan.ai_questions != "[]":
        with st.expander("❓ AI Questions"):
            try:
                questions = json.loads(plan.ai_questions)
                for q in questions:
                    st.markdown(f"- {q}")
            except json.JSONDecodeError:
                st.text(plan.ai_questions)

    if plan.user_answers:
        with st.expander("💬 User Answers"):
            st.text(plan.user_answers)

    # ── Version Comparison ──────────────────────────────────────────────────
    if len(plans) > 1:
        st.markdown("---")
        with st.expander("🔍 Compare with another version"):
            other_options = {
                f"v{p.version} — {p.status.value if hasattr(p.status, 'value') else p.status}": p.id
                for p in plans if p.id != selected_id
            }
            if other_options:
                other_label = st.selectbox("Compare with", options=list(other_options.keys()), key="compare")
                other_plan = PlanRepo.get(other_options[other_label])
                if other_plan:
                    col1, col2 = st.columns(2)
                    with col1:
                        st.markdown(f"**Version {plan.version}**")
                        render_mapping_summary(plan.get_mappings())
                    with col2:
                        st.markdown(f"**Version {other_plan.version}**")
                        render_mapping_summary(other_plan.get_mappings())

    # ── Approval ────────────────────────────────────────────────────────────
    st.markdown("---")
    st.subheader("✅ Approval")

    if status_val == "DRAFT":
        st.warning("This plan is in DRAFT status. Approve it to enable dry-run and execution.")

        approver = st.text_input("Approver name", value="user", key="approver_name")

        if st.button("✅ Approve This Plan", type="primary", use_container_width=True):
            PlanRepo.approve(plan.id, approver)
            st.success(f"✅ Plan v{plan.version} approved by {approver}!")
            st.rerun()

    elif status_val == "APPROVED":
        st.success(f"✅ Approved by **{plan.approved_by}** on {plan.approved_at[:19] if plan.approved_at else 'N/A'}")
        st.info("This plan is ready for **Dry Run** and **Execution**.")

    elif status_val == "EXECUTED":
        st.success("🚀 This plan has been executed. View results on the Reconciliation page.")

    elif status_val == "ROLLED_BACK":
        st.warning("⏪ This plan's execution was rolled back.")

    # ── Audit Trail ─────────────────────────────────────────────────────────
    st.markdown("---")
    with st.expander("📜 Audit Trail for this Plan"):
        entries = AuditRepo.get_by_entity(plan.id)
        if entries:
            rows = []
            for e in entries:
                rows.append({
                    "Timestamp": e.timestamp[:19] if e.timestamp else "",
                    "Action": e.action.value if hasattr(e.action, 'value') else e.action,
                    "Details": e.details_json,
                })
            st.dataframe(rows, use_container_width=True, hide_index=True)
        else:
            st.info("No audit entries yet.")
