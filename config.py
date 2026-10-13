"""
Configuration constants for the Migration Workbench.
"""
import os
from pathlib import Path

# ── Paths ───────────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).parent
DATA_DIR = PROJECT_ROOT / "data"
SCHEMAS_DIR = PROJECT_ROOT / "schemas"
DB_PATH = DATA_DIR / "migration.db"

# ── Limits ──────────────────────────────────────────────────────────────────
MAX_SAMPLE_SIZE = 1000  # Maximum number of sample records allowed

# ── AI Agent ────────────────────────────────────────────────────────────────
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = "gemini-2.0-flash"

# ── Migration ───────────────────────────────────────────────────────────────
PLAN_STATUSES = ("DRAFT", "APPROVED", "EXECUTED", "ROLLED_BACK")
EXECUTION_TYPES = ("DRY_RUN", "LIVE")
EXECUTION_STATUSES = ("SUCCESS", "PARTIAL", "FAILED")
AUDIT_ACTIONS = (
    "PLAN_CREATED",
    "PLAN_UPDATED",
    "APPROVED",
    "DRY_RUN",
    "EXECUTED",
    "RETRIED",
    "ROLLED_BACK",
)

# ── Supported Transformation Rule IDs ───────────────────────────────────────
TRANSFORMATION_RULES = (
    "RENAME",
    "CAST_INT",
    "CAST_FLOAT",
    "CAST_STRING",
    "CAST_BOOL",
    "DATE_REFORMAT",
    "UPPERCASE",
    "LOWERCASE",
    "TRIM",
    "DEFAULT",
    "CONCAT",
    "SPLIT",
    "TRUNCATE",
    "MAP_VALUES",
    "ROUND",
    "DROP",
)

# Ensure data directory exists
DATA_DIR.mkdir(parents=True, exist_ok=True)
