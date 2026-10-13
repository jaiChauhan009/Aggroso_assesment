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

    if not mappings:
        st.info("No mappings proposed yet. Run the AI agent to generate mapping suggestions.")
        return mappings

    updated_mappings = []
    rules_list = list(TRANSFORMATION_RULES)

    for i, m in enumerate(mappings):
        with st.expander(
            f"{'🟢' if m.transformation != 'DROP' else '🔴'} "
            f"`{m.source_field}` → `{m.target_field}` [{m.transformation}]",
            expanded=False,
        ):
            if editable:
                col1, col2, col3 = st.columns(3)

                with col1:
                    src = st.selectbox(
                        "Source Field",
                        options=source_fields,
                        index=source_fields.index(m.source_field) if m.source_field in source_fields else 0,
                        key=f"{key_prefix}_src_{i}",
                    )

                with col2:
                    tgt = st.selectbox(
                        "Target Field",
                        options=target_fields,
                        index=target_fields.index(m.target_field) if m.target_field in target_fields else 0,
                        key=f"{key_prefix}_tgt_{i}",
                    )

                with col3:
                    rule = st.selectbox(
                        "Transformation",
                        options=rules_list,
                        index=rules_list.index(m.transformation) if m.transformation in rules_list else 0,
                        key=f"{key_prefix}_rule_{i}",
                    )

                # Params editor
                params_str = st.text_input(
                    "Parameters (JSON)",
                    value=json.dumps(m.params) if m.params else "{}",
                    key=f"{key_prefix}_params_{i}",
                )
                try:
                    params = json.loads(params_str)
                except json.JSONDecodeError:
                    st.error("Invalid JSON for parameters")
                    params = m.params

                delete_col, _ = st.columns([1, 4])
                with delete_col:
                    if st.button("🗑️ Remove Mapping", key=f"{key_prefix}_del_{i}"):
                        continue

                updated_mappings.append(FieldMapping(
                    source_field=src,
                    target_field=tgt,
                    transformation=rule,
                    params=params,
                ))
            else:
                st.markdown(f"**Source:** `{m.source_field}`")
                st.markdown(f"**Target:** `{m.target_field}`")
                st.markdown(f"**Transform:** `{m.transformation}`")
                if m.params:
                    st.json(m.params)
                updated_mappings.append(m)

    if editable:
        st.markdown("")
        if st.button("➕ Add Custom Field Mapping", key=f"{key_prefix}_add_new"):
            default_src = source_fields[0] if source_fields else "unmapped"
            default_tgt = target_fields[0] if target_fields else "unmapped"
            updated_mappings.append(FieldMapping(
                source_field=default_src,
                target_field=default_tgt,
                transformation="RENAME",
                params={},
            ))
            st.rerun()

    return updated_mappings


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
