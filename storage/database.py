"""
SQLite database initialization and connection management.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from config import DB_PATH

# ── SQL DDL ─────────────────────────────────────────────────────────────────

_DDL = """
CREATE TABLE IF NOT EXISTS schemas (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    direction   TEXT NOT NULL CHECK(direction IN ('source', 'target')),
    schema_json TEXT NOT NULL,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sample_records (
    id          TEXT PRIMARY KEY,
    schema_id   TEXT NOT NULL REFERENCES schemas(id),
    record_json TEXT NOT NULL,
    row_index   INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS migration_plans (
    id                   TEXT PRIMARY KEY,
    version              INTEGER NOT NULL,
    status               TEXT NOT NULL DEFAULT 'DRAFT'
                         CHECK(status IN ('DRAFT','APPROVED','EXECUTED','ROLLED_BACK')),
    mappings_json        TEXT NOT NULL,
    transformations_json TEXT NOT NULL,
    risk_notes           TEXT DEFAULT '',
    ai_questions         TEXT DEFAULT '',
    user_answers         TEXT DEFAULT '',
    created_at           TEXT NOT NULL,
    approved_at          TEXT,
    approved_by          TEXT
);

CREATE TABLE IF NOT EXISTS executions (
    id                TEXT PRIMARY KEY,
    plan_id           TEXT NOT NULL REFERENCES migration_plans(id),
    execution_type    TEXT NOT NULL CHECK(execution_type IN ('DRY_RUN','LIVE')),
    source_count      INTEGER DEFAULT 0,
    transformed_count INTEGER DEFAULT 0,
    accepted_count    INTEGER DEFAULT 0,
    rejected_count    INTEGER DEFAULT 0,
    started_at        TEXT NOT NULL,
    completed_at      TEXT,
    status            TEXT NOT NULL DEFAULT 'SUCCESS'
                      CHECK(status IN ('SUCCESS','PARTIAL','FAILED'))
);

CREATE TABLE IF NOT EXISTS quarantine (
    id                 TEXT PRIMARY KEY,
    execution_id       TEXT NOT NULL REFERENCES executions(id),
    source_record_json TEXT NOT NULL,
    field_name         TEXT NOT NULL,
    error_type         TEXT NOT NULL,
    error_message      TEXT NOT NULL,
    original_value     TEXT,
    row_index          INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS target_store (
    id              TEXT PRIMARY KEY,
    execution_id    TEXT NOT NULL REFERENCES executions(id),
    idempotency_key TEXT NOT NULL UNIQUE,
    record_json     TEXT NOT NULL,
    inserted_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_log (
    id           TEXT PRIMARY KEY,
    action       TEXT NOT NULL,
    entity_id    TEXT NOT NULL,
    details_json TEXT DEFAULT '{}',
    timestamp    TEXT NOT NULL
);
"""


def get_connection(db_path: Path | str | None = None) -> sqlite3.Connection:
    """Return a new SQLite connection with WAL mode and foreign keys enabled."""
    path = str(db_path or DB_PATH)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: Path | str | None = None) -> None:
    """Create all tables if they do not exist."""
    conn = get_connection(db_path)
    try:
        conn.executescript(_DDL)
        conn.commit()
    finally:
        conn.close()


def reset_db(db_path: Path | str | None = None) -> None:
    """Drop and recreate all tables. USE ONLY FOR TESTING."""
    conn = get_connection(db_path)
    try:
        tables = [
            "audit_log", "target_store", "quarantine",
            "executions", "migration_plans", "sample_records", "schemas",
        ]
        for t in tables:
            conn.execute(f"DROP TABLE IF EXISTS {t}")
        conn.commit()
        conn.executescript(_DDL)
        conn.commit()
    finally:
        conn.close()
