"""
Page 2: AI-Assisted Mapping
Run the AI agent to propose field mappings, view risks, answer questions.
"""
from __future__ import annotations

import json
import streamlit as st

from storage.repositories import SchemaRepo, SampleRecordRepo, PlanRepo
from storage.models import FieldMapping
from ui.components.mapping_table import render_mapping_table, render_mapping_summary
from config import GEMINI_API_KEY


def render():
    st.title("🤖 AI-Assisted Mapping")
    st.markdown("Let the AI agent analyze your schemas and propose field mappings with transformations.")

    # Check prerequisites
    source_rec = SchemaRepo.get_by_direction("source")
    target_rec = SchemaRepo.get_by_direction("target")

    if not source_rec or not target_rec:
        st.warning("⚠️ Please upload both source and target schemas first (Schema Upload page).")
        return

    source_schema = source_rec.to_definition()
    target_schema = target_rec.to_definition()

    sample_count = SampleRecordRepo.count_by_schema(source_rec.id)
    if sample_count == 0:
        st.warning("⚠️ Please upload sample records first (Schema Upload page).")
        return

    # API key status
    if GEMINI_API_KEY:
        st.success("🔑 Gemini API key configured — AI agent mode active")
    else:
        st.info("💡 No API key found — using heuristic matching (set GEMINI_API_KEY for AI mode)")

    st.markdown("---")

    # ── Agent Controls ──────────────────────────────────────────────────────
    col1, col2 = st.columns([2, 1])

    with col1:
        if st.button("🚀 Run AI Mapping Agent", type="primary", use_container_width=True):
            with st.spinner("🤖 Agent is analyzing schemas and proposing mappings..."):
                try:
                    from agent.mapping_agent import MappingAgent
                    agent = MappingAgent()
                    response = agent.propose_mappings()

                    st.session_state["agent_response"] = response
                    st.session_state["proposed_mappings"] = response.mappings
                    st.success("✅ Agent completed analysis!")
                except Exception as e:
                    st.error(f"Agent error: {e}")
                    import traceback
                    st.code(traceback.format_exc())

    with col2:
        if st.button("🔄 Clear Proposals", use_container_width=True):
            st.session_state.pop("agent_response", None)
            st.session_state.pop("proposed_mappings", None)
            st.rerun()

    # ── Display Agent Response ──────────────────────────────────────────────
    if "agent_response" in st.session_state:
        response = st.session_state["agent_response"]

        # Explanation
        if response.explanation:
            with st.expander("💬 Agent Explanation", expanded=True):
                st.markdown(response.explanation)

        # Warnings
        if response.warnings:
            with st.expander(f"⚠️ Warnings ({len(response.warnings)})", expanded=True):
                for w in response.warnings:
                    st.warning(w)

        # Risks
        if response.risks:
            with st.expander(f"🔴 Risks ({len(response.risks)})", expanded=True):
                for r in response.risks:
                    st.error(r)

        # Questions
        if response.questions:
            with st.expander(f"❓ Clarification Questions ({len(response.questions)})", expanded=True):
                answers = []
                for i, q in enumerate(response.questions):
                    st.markdown(f"**Q{i+1}:** {q}")
                    answer = st.text_input(f"Your answer:", key=f"q_answer_{i}")
                    answers.append(answer)

                if st.button("📤 Submit Answers & Refine"):
                    if any(answers):
                        with st.spinner("🤖 Refining mappings based on your answers..."):
                            try:
                                from agent.mapping_agent import MappingAgent
                                agent = MappingAgent()
                                feedback = "\n".join(
                                    f"Q: {q}\nA: {a}" for q, a in zip(response.questions, answers) if a
                                )
                                refined = agent.refine_mappings(
                                    st.session_state.get("proposed_mappings", []),
                                    feedback,
                                )
                                st.session_state["agent_response"] = refined
                                st.session_state["proposed_mappings"] = refined.mappings
                                st.rerun()
                            except Exception as e:
                                st.error(f"Refinement error: {e}")

        st.markdown("---")

        # ── Mapping Editor ──────────────────────────────────────────────────
        st.subheader("📝 Edit Mappings")

        mappings = st.session_state.get("proposed_mappings", [])
        source_fields = source_schema.field_names()
        target_fields = target_schema.field_names()

        updated = render_mapping_table(
            mappings=mappings,
            source_fields=source_fields,
            target_fields=target_fields,
            editable=True,
        )
        st.session_state["proposed_mappings"] = updated

        st.markdown("---")

        # ── Risk Analysis ───────────────────────────────────────────────────
        if st.button("📊 Run Risk Analysis"):
            with st.spinner("Analyzing risks..."):
                try:
                    from agent.risk_analyzer import analyze_risks
                    risk_report = analyze_risks(updated, source_schema, target_schema)

                    st.markdown(f"### Overall Risk: {'🟢 LOW' if risk_report.overall_risk == 'LOW' else '🟡 MEDIUM' if risk_report.overall_risk == 'MEDIUM' else '🔴 HIGH'}")

                    if risk_report.unmapped_source_fields:
                        st.warning(f"Unmapped source fields: {', '.join(risk_report.unmapped_source_fields)}")
                    if risk_report.unmapped_target_fields:
                        st.error(f"Unmapped target fields (required!): {', '.join(risk_report.unmapped_target_fields)}")

                    for fr in risk_report.field_risks:
                        icon = "🟢" if fr.risk_level == "LOW" else "🟡" if fr.risk_level == "MEDIUM" else "🔴"
                        st.markdown(f"- {icon} **{fr.field_name}**: {fr.reason}")

                    if risk_report.data_loss_warnings:
                        st.error("⚠️ Data Loss Warnings:")
                        for w in risk_report.data_loss_warnings:
                            st.markdown(f"  - {w}")
                except Exception as e:
                    st.error(f"Risk analysis error: {e}")

        st.markdown("---")

        # ── Save as Plan ────────────────────────────────────────────────────
        st.subheader("💾 Save Migration Plan")

        risk_notes = st.text_area(
            "Risk Notes (optional)",
            value="\n".join(response.risks) if response.risks else "",
            key="plan_risk_notes",
        )

        if st.button("💾 Save as New Plan Version", type="primary", use_container_width=True):
            mappings_to_save = st.session_state.get("proposed_mappings", [])
            if not mappings_to_save:
                st.error("No mappings to save!")
            else:
                try:
                    plan = PlanRepo.create(
                        mappings=mappings_to_save,
                        risk_notes=risk_notes,
                        ai_questions=json.dumps(response.questions) if response.questions else "[]",
                    )
                    st.success(f"✅ Plan saved as **version {plan.version}** (status: DRAFT)")
                    st.info("Go to **Plan Review** page to approve it.")
                except Exception as e:
                    st.error(f"Error saving plan: {e}")
