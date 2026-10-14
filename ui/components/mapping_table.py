"""
Reusable UI component: Interactive mapping table.
Displays proposed field mappings and allows editing.
"""
from __future__ import annotations

import json
import streamlit as st

from storage.models import FieldMapping
from config import TRANSFORMATION_RULES


def render_mapping_table(
    mappings: list[FieldMapping],
    source_fields: list[str],
    target_fields: list[str],
    editable: bool = True,
    key_prefix: str = "mapping",
) -> list[FieldMapping]:
    """
    Render a mapping table. If editable, returns modified mappings.
    Otherwise returns the original mappings unchanged.
    """
    st.subheader("🔗 Field Mappings")

    # Initialize mappings in session_state if needed
    session_key = f"{key_prefix}_list"
    if session_key not in st.session_state:
        st.session_state[session_key] = [m.model_copy() for m in mappings]

    current_mappings: list[FieldMapping] = st.session_state[session_key]

    if not current_mappings:
        st.info("No mappings configured. Run the AI agent or use the form below to add mappings.")

    rules_list = list(TRANSFORMATION_RULES)
    changed = False

    # 1. Existing Mappings List with edit and remove
    for i, m in enumerate(list(current_mappings)):
        with st.expander(
            f"#{i+1}: `{m.source_field}` → `{m.target_field}` [{m.transformation}]",
            expanded=False,
        ):
            if editable:
                col1, col2, col3 = st.columns(3)

                with col1:
                    src_idx = source_fields.index(m.source_field) if m.source_field in source_fields else 0
                    src = st.selectbox(
                        "Source Field",
                        options=source_fields,
                        index=src_idx,
                        key=f"{key_prefix}_src_{i}",
                    )

                with col2:
                    tgt_idx = target_fields.index(m.target_field) if m.target_field in target_fields else 0
                    tgt = st.selectbox(
                        "Target Field",
                        options=target_fields,
                        index=tgt_idx,
                        key=f"{key_prefix}_tgt_{i}",
                    )

                with col3:
                    rule_idx = rules_list.index(m.transformation) if m.transformation in rules_list else 0
                    rule = st.selectbox(
                        "Transformation",
                        options=rules_list,
                        index=rule_idx,
                        key=f"{key_prefix}_rule_{i}",
                    )

                params_str = st.text_input(
                    "Parameters (JSON)",
                    value=json.dumps(m.params) if m.params else "{}",
                    key=f"{key_prefix}_params_{i}",
                )
                try:
                    params = json.loads(params_str)
                except json.JSONDecodeError:
                    st.error("Invalid JSON syntax for parameters")
                    params = m.params

                col_update, col_del, _ = st.columns([1, 1, 3])
                with col_update:
                    if st.button("💾 Apply Change", key=f"{key_prefix}_upd_btn_{i}"):
                        current_mappings[i] = FieldMapping(
                            source_field=src,
                            target_field=tgt,
                            transformation=rule,
                            params=params,
                        )
                        st.session_state[session_key] = current_mappings
                        st.success(f"Updated #{i+1}!")
                        st.rerun()

                with col_del:
                    if st.button("🗑️ Delete", key=f"{key_prefix}_del_btn_{i}"):
                        current_mappings.pop(i)
                        st.session_state[session_key] = current_mappings
                        st.rerun()
            else:
                st.markdown(f"**Source:** `{m.source_field}` | **Target:** `{m.target_field}` | **Rule:** `{m.transformation}`")
                if m.params:
                    st.json(m.params)

    # 2. Add New Mapping Form - Always open and directly visible
    if editable:
        st.markdown("---")
        st.subheader("➕ Add New Field Mapping")
        with st.form(f"{key_prefix}_new_form", clear_on_submit=False):
            st.markdown("Select source, target, and transformation to add to your plan:")
            c1, c2, c3 = st.columns(3)
            with c1:
                new_src = st.selectbox("Source Field", options=source_fields, key=f"{key_prefix}_new_src")
            with c2:
                new_tgt = st.selectbox("Target Field", options=target_fields, key=f"{key_prefix}_new_tgt")
            with c3:
                new_rule = st.selectbox("Transformation Rule", options=rules_list, key=f"{key_prefix}_new_rule")

            new_params_str = st.text_input(
                "Parameters (JSON, e.g. for DATE_REFORMAT or CONCAT)",
                value="{}",
                key=f"{key_prefix}_new_params",
            )

            submitted = st.form_submit_button("➕ Add This Mapping to Plan", use_container_width=True, type="primary")
            if submitted:
                try:
                    new_params = json.loads(new_params_str) if new_params_str.strip() else {}
                except json.JSONDecodeError:
                    st.error("Invalid JSON syntax in Parameters field!")
                    new_params = {}

                new_mapping_obj = FieldMapping(
                    source_field=new_src,
                    target_field=new_tgt,
                    transformation=new_rule,
                    params=new_params,
                )
                current_mappings.append(new_mapping_obj)
                st.session_state[session_key] = current_mappings
                st.session_state["proposed_mappings"] = current_mappings
                st.success(f"✅ Added mapping: `{new_src}` ➔ `{new_tgt}` [{new_rule}]!")
                st.rerun()

    return current_mappings


def render_mapping_summary(mappings: list[FieldMapping]) -> None:
    """Render a compact summary table of mappings."""
    if not mappings:
        return

    rows = []
    for m in mappings:
        rows.append({
            "Source": m.source_field,
            "→": "→",
            "Target": m.target_field,
            "Transform": m.transformation,
            "Params": json.dumps(m.params) if m.params else "—",
        })

    st.dataframe(rows, use_container_width=True, hide_index=True)
