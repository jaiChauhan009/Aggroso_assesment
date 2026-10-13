"""
Reusable UI component: Schema diff viewer.
Shows source vs target schema side-by-side with field comparison.
"""
from __future__ import annotations

import json
import streamlit as st

from storage.models import SchemaDefinition


def render_schema_summary(schema: SchemaDefinition, title: str) -> None:
    """Render a single schema as a formatted table."""
    st.subheader(title)
    st.caption(f"Table: `{schema.table}` — {len(schema.fields)} fields")

    rows = []
    for f in schema.fields:
        constraints = []
        if f.primary_key:
            constraints.append("🔑 PK")
        if not f.nullable:
            constraints.append("NOT NULL")
        if f.max_length:
            constraints.append(f"max_len={f.max_length}")
        if f.format:
            constraints.append(f"fmt={f.format}")
        if f.enum:
            constraints.append(f"enum={f.enum}")

        rows.append({
            "Field": f.name,
            "Type": f.type,
            "Nullable": "✅" if f.nullable else "❌",
            "Constraints": ", ".join(constraints) if constraints else "—",
        })

    st.dataframe(rows, use_container_width=True, hide_index=True)


def render_schema_diff(source: SchemaDefinition, target: SchemaDefinition) -> None:
    """Render a side-by-side diff of source and target schemas."""
    st.subheader("📊 Schema Comparison")

    source_names = set(f.name for f in source.fields)
    target_names = set(f.name for f in target.fields)

    col1, col2, col3 = st.columns(3)

    with col1:
        st.metric("Source Fields", len(source.fields))
    with col2:
        st.metric("Target Fields", len(target.fields))
    with col3:
        # Simple name overlap (case-insensitive)
        source_lower = {n.lower() for n in source_names}
        target_lower = {n.lower() for n in target_names}
        overlap = len(source_lower & target_lower)
        st.metric("Name Overlap", overlap)

    # Fields only in source
    source_only = source_names - target_names
    if source_only:
        st.warning(f"**Source-only fields** (need mapping): {', '.join(sorted(source_only))}")

    # Fields only in target
    target_only = target_names - source_names
    if target_only:
        st.info(f"**Target-only fields** (need source or default): {', '.join(sorted(target_only))}")

    # Side-by-side
    left, right = st.columns(2)
    with left:
        render_schema_summary(source, "🔵 Source Schema")
    with right:
        render_schema_summary(target, "🟢 Target Schema")
