from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from typing import Iterator
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


@contextmanager
def connect(db_path: str | Path) -> Iterator[sqlite3.Connection]:
    """Open a short-lived SQLite connection and always close it."""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=10, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path: str | Path) -> None:
    with connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS leads (
                id TEXT PRIMARY KEY,
                name TEXT,
                company TEXT,
                email TEXT,
                phone TEXT,
                requirement TEXT,
                budget_amount INTEGER,
                budget_currency TEXT DEFAULT 'INR',
                timeline_days INTEGER,
                decision_maker INTEGER,
                score INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'cold',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS calls (
                id TEXT PRIMARY KEY,
                lead_id TEXT NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
                started_at TEXT NOT NULL,
                ended_at TEXT,
                language TEXT DEFAULT 'en',
                sentiment TEXT DEFAULT 'neutral',
                summary TEXT DEFAULT '',
                handoff_required INTEGER NOT NULL DEFAULT 0,
                handoff_reason TEXT DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS messages (
                id TEXT PRIMARY KEY,
                call_id TEXT NOT NULL REFERENCES calls(id) ON DELETE CASCADE,
                role TEXT NOT NULL CHECK(role IN ('customer', 'agent', 'system')),
                content TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS evidence (
                id TEXT PRIMARY KEY,
                lead_id TEXT NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
                call_id TEXT REFERENCES calls(id) ON DELETE SET NULL,
                field TEXT NOT NULL,
                value TEXT NOT NULL,
                quote TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'verified',
                confidence REAL NOT NULL DEFAULT 1.0,
                created_at TEXT NOT NULL,
                UNIQUE(lead_id, field)
            );

            CREATE TABLE IF NOT EXISTS appointments (
                id TEXT PRIMARY KEY,
                lead_id TEXT NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
                start_time TEXT NOT NULL,
                end_time TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'booked',
                idempotency_key TEXT UNIQUE,
                notes TEXT DEFAULT '',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS knowledge_chunks (
                id TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_leads_status ON leads(status);
            CREATE INDEX IF NOT EXISTS idx_calls_lead ON calls(lead_id);
            CREATE INDEX IF NOT EXISTS idx_messages_call ON messages(call_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_evidence_lead ON evidence(lead_id);
            CREATE INDEX IF NOT EXISTS idx_appointments_time ON appointments(start_time, end_time);
            """
        )


def seed_demo_lead(db_path: str | Path) -> None:
    with connect(db_path) as conn:
        existing = conn.execute("SELECT id FROM leads WHERE id = 'lead_demo_rahul'").fetchone()
        if not existing:
            now = utc_now()
            conn.execute(
                """INSERT INTO leads
                   (id, name, company, score, status, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                ("lead_demo_rahul", "Rahul Sharma", "Northstar Digital", 0, "cold", now, now),
            )


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None
