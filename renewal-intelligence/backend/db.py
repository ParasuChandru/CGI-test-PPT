"""SQLite persistence for the Renewal Intelligence POC."""
from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "renewal_intelligence.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS policies (
    policy_id TEXT PRIMARY KEY,
    line TEXT, segment TEXT, region TEXT, cover_level TEXT,
    tenure_years REAL, product_count INTEGER,
    sum_insured REAL, prior_premium REAL, renewal_quote REAL,
    premium_change_pct REAL, discount_applied INTEGER, discount_source TEXT,
    claim_count_3y INTEGER, claims_declined_count INTEGER, claims_partial_count INTEGER,
    last_claim_days_before_renewal INTEGER, avg_settlement_days REAL,
    portal_logins_90d INTEGER, notice_opened INTEGER, inbound_contacts_90d INTEGER,
    complaints_12m INTEGER,
    outcome_renewed INTEGER, final_bound REAL,
    funnel_contacted INTEGER, funnel_engaged INTEGER,
    renewal_month TEXT
);

CREATE TABLE IF NOT EXISTS scores (
    policy_id TEXT PRIMARY KEY REFERENCES policies(policy_id),
    score REAL NOT NULL,
    model_version TEXT NOT NULL,
    scored_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS attributions (
    policy_id TEXT REFERENCES policies(policy_id),
    driver TEXT,
    contribution_pct REAL,
    status TEXT,
    model_version TEXT,
    PRIMARY KEY (policy_id, driver)
);

CREATE TABLE IF NOT EXISTS recommendations (
    rec_id TEXT PRIMARY KEY,
    policy_id TEXT REFERENCES policies(policy_id),
    dominant_driver TEXT,
    action TEXT,
    is_price_action INTEGER,
    concession_value REAL,
    save_probability REAL,
    expected_value REAL,
    suppressed INTEGER DEFAULT 0,
    suppressed_reason TEXT,
    holdout_group TEXT,       -- 'treatment' | 'control' | NULL (not at-risk)
    status TEXT DEFAULT 'pending',  -- pending|approved|rejected|modified
    simulated_outcome_renewed INTEGER,  -- demo-only: for FR-408 uplift illustration
    created_at REAL
);

CREATE TABLE IF NOT EXISTS decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rec_id TEXT REFERENCES recommendations(rec_id),
    actor_role TEXT, actor_id TEXT,
    decision TEXT, reason TEXT,
    decided_at REAL
);

CREATE TABLE IF NOT EXISTS overrides (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    policy_id TEXT REFERENCES policies(policy_id),
    actor_role TEXT, actor_id TEXT,
    original_score REAL, override_score REAL,
    reason TEXT NOT NULL,
    created_at REAL
);

CREATE TABLE IF NOT EXISTS transcripts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT, policy_id TEXT,
    turn_index INTEGER, sender TEXT, message TEXT,
    escalated INTEGER DEFAULT 0,
    created_at REAL
);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    actor_role TEXT, actor_id TEXT,
    action TEXT, resource TEXT,
    created_at REAL
);

CREATE TABLE IF NOT EXISTS model_meta (
    model_version TEXT PRIMARY KEY,
    trained_at REAL,
    auc REAL, precision_at_10 REAL, calibration_error REAL,
    base_lapse_rate REAL,
    coefficients_json TEXT,
    feature_means_json TEXT
);
"""


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with get_conn() as conn:
        conn.executescript(SCHEMA)


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def is_seeded() -> bool:
    if not DB_PATH.exists():
        return False
    with get_conn() as conn:
        row = conn.execute("SELECT COUNT(*) AS c FROM policies").fetchone()
        return row["c"] > 0


def log_audit(actor_role: str, actor_id: str, action: str, resource: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO audit_log (actor_role, actor_id, action, resource, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (actor_role, actor_id, action, resource, time.time()),
        )


def dumps(obj) -> str:
    return json.dumps(obj)


def loads(s: str):
    return json.loads(s) if s else None
