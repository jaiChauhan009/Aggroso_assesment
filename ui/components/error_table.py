"""
Reusable UI component: Error evidence table.
Displays quarantined records with field-level error details.
"""
from __future__ import annotations

import json
import streamlit as st

from storage.models import QuarantineEntry


def render_error_table(entries: list[QuarantineEntry]) -> None:
    """Render quarantine entries as a searchable table with field-level error evidence."""
    if not entries:
        st.success("🎉 No validation errors — all records passed!")
        return

    st.subheader(f"🔍 Quarantine Details ({len(entries)} errors)")

    # Summary by error type
    error_types: dict[str, int] = {}
    for e in entries:
        error_types[e.error_type] = error_types.get(e.error_type, 0) + 1

    cols = st.columns(len(error_types))
    for i, (etype, count) in enumerate(sorted(error_types.items())):
        with cols[i % len(cols)]:
            st.metric(label=etype, value=count)

    # Filter controls
    col1, col2 = st.columns(2)
    with col1:
        type_filter = st.multiselect(
            "Filter by Error Type",
            options=sorted(error_types.keys()),
            default=list(error_types.keys()),
            key="error_type_filter",
        )
    with col2:
        field_names = sorted(set(e.field_name for e in entries))
        field_filter = st.multiselect(
            "Filter by Field",
            options=field_names,
            default=field_names,
            key="error_field_filter",
        )

    # Build filtered table
    rows = []
    for e in entries:
        if e.error_type in type_filter and e.field_name in field_filter:
            rows.append({
                "Row": e.row_index,
                "Field": e.field_name,
                "Error Type": e.error_type,
                "Message": e.error_message,
                "Original Value": e.original_value or "NULL",
            })

    if rows:
        st.dataframe(rows, use_container_width=True, hide_index=True)
    else:
        st.info("No errors match the current filters.")

    # Expandable: full source records for quarantined rows
    quarantined_rows = sorted(set(e.row_index for e in entries))
    with st.expander(f"📋 View quarantined source records ({len(quarantined_rows)} records)"):
        seen = set()
        for e in entries:
            if e.row_index not in seen:
                seen.add(e.row_index)
                st.markdown(f"**Row {e.row_index}:**")
                try:
                    st.json(json.loads(e.source_record_json))
                except json.JSONDecodeError:
                    st.code(e.source_record_json)
