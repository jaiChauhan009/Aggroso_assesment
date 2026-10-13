"""
Agentic Data Migration Planner & Reconciliation Workbench
Main Streamlit application entry point.
"""
import sys
from pathlib import Path

# Ensure project root is on the path
PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import streamlit as st
from storage.database import init_db

# ── Page Config ─────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Migration Workbench",
    page_icon="🔄",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Initialize Database ────────────────────────────────────────────────────

init_db()

# ── Sidebar Navigation ─────────────────────────────────────────────────────

st.sidebar.title("🔄 Migration Workbench")
st.sidebar.markdown("---")

page = st.sidebar.radio(
    "Navigate",
    options=[
        "📁 Schema Upload",
        "🤖 AI Mapping",
        "📋 Plan Review",
        "🧪 Dry Run",
        "🚀 Execute Migration",
        "📊 Reconciliation",
    ],
    index=0,
)

st.sidebar.markdown("---")
st.sidebar.caption("Agentic Data Migration Planner")
st.sidebar.caption("v1.0 — Single source → single target")

# ── Route to Pages ──────────────────────────────────────────────────────────

if page == "📁 Schema Upload":
    from ui.pages.p01_schema_upload import render
    render()
elif page == "🤖 AI Mapping":
    from ui.pages.p02_ai_mapping import render
    render()
elif page == "📋 Plan Review":
    from ui.pages.p03_plan_review import render
    render()
elif page == "🧪 Dry Run":
    from ui.pages.p04_dry_run import render
    render()
elif page == "🚀 Execute Migration":
    from ui.pages.p05_execute import render
    render()
elif page == "📊 Reconciliation":
    from ui.pages.p06_reconciliation import render
    render()
