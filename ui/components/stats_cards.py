"""
Reusable UI component: Statistics cards.
Displays source, transformed, accepted, and rejected counts.
"""
from __future__ import annotations

import streamlit as st

from storage.models import Execution


def render_stats_cards(execution: Execution) -> None:
    """Render the 4 key count metrics as cards."""
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric(
            label="📥 Source Records",
            value=execution.source_count,
            help="Total records in the source sample",
        )

    with col2:
        st.metric(
            label="🔄 Transformed",
            value=execution.transformed_count,
            delta=None,
            help="Records that successfully went through transformation",
        )

    with col3:
        st.metric(
            label="✅ Accepted",
            value=execution.accepted_count,
            delta=f"{_pct(execution.accepted_count, execution.source_count)}%",
            delta_color="normal",
            help="Records that passed all validations and were accepted",
        )

    with col4:
        st.metric(
            label="❌ Rejected",
            value=execution.rejected_count,
            delta=f"{_pct(execution.rejected_count, execution.source_count)}%",
            delta_color="inverse",
            help="Records quarantined due to validation errors",
        )

    # Invariant check
    if execution.source_count > 0:
        total = execution.accepted_count + execution.rejected_count
        if total == execution.source_count:
            st.success(f"✅ Invariant holds: {execution.source_count} = {execution.accepted_count} accepted + {execution.rejected_count} rejected")
        else:
            st.error(f"⚠️ Invariant BROKEN: {execution.source_count} ≠ {execution.accepted_count} + {execution.rejected_count} = {total}")


def render_execution_status(execution: Execution) -> None:
    """Render execution metadata."""
    status_colors = {
        "SUCCESS": "🟢",
        "PARTIAL": "🟡",
        "FAILED": "🔴",
    }
    icon = status_colors.get(execution.status.value if hasattr(execution.status, 'value') else execution.status, "⚪")

    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown(f"**Status:** {icon} {execution.status.value if hasattr(execution.status, 'value') else execution.status}")
    with col2:
        st.markdown(f"**Type:** {'🧪 Dry Run' if execution.execution_type.value == 'DRY_RUN' else '🚀 Live'}")
    with col3:
        st.markdown(f"**Started:** {execution.started_at[:19] if execution.started_at else 'N/A'}")


def _pct(part: int, total: int) -> str:
    """Calculate percentage string."""
    if total == 0:
        return "0"
    return f"{(part / total * 100):.1f}"
