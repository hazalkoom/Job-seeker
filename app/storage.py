from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from app.config import settings
from app.models import Job


def _connect() -> sqlite3.Connection:
    path = Path(settings.database_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=20)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                source_id TEXT NOT NULL,
                title TEXT NOT NULL,
                company TEXT NOT NULL,
                location TEXT NOT NULL,
                url TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                posted_at TEXT NOT NULL DEFAULT '',
                date_kind TEXT NOT NULL DEFAULT 'posted',
                remote INTEGER NOT NULL DEFAULT 0,
                workplace_type TEXT NOT NULL DEFAULT 'unknown',
                employment_type TEXT NOT NULL DEFAULT '',
                eligibility TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'review',
                score INTEGER NOT NULL DEFAULT 0,
                reasons TEXT NOT NULL DEFAULT '[]',
                concerns TEXT NOT NULL DEFAULT '[]',
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                notified_at TEXT,
                UNIQUE(source, source_id)
            )"""
        )
        # Upgrade databases created by earlier versions without deleting saved history.
        existing_columns = {row[1] for row in conn.execute("PRAGMA table_info(jobs)").fetchall()}
        migrations = {
            "date_kind": "TEXT NOT NULL DEFAULT 'posted'",
            "workplace_type": "TEXT NOT NULL DEFAULT 'unknown'",
            "eligibility": "TEXT NOT NULL DEFAULT ''",
            "status": "TEXT NOT NULL DEFAULT 'review'",
            "score": "INTEGER NOT NULL DEFAULT 0",
            "reasons": "TEXT NOT NULL DEFAULT '[]'",
            "concerns": "TEXT NOT NULL DEFAULT '[]'",
            "first_seen_at": "TEXT NOT NULL DEFAULT ''",
            "last_seen_at": "TEXT NOT NULL DEFAULT ''",
            "notified_at": "TEXT",
        }
        for column, definition in migrations.items():
            if column not in existing_columns:
                conn.execute(f"ALTER TABLE jobs ADD COLUMN {column} {definition}")
        # Old schemas used created_at; preserve it and backfill the new timestamp fields.
        columns = {row[1] for row in conn.execute("PRAGMA table_info(jobs)").fetchall()}
        if "created_at" in columns:
            conn.execute("UPDATE jobs SET first_seen_at=created_at WHERE first_seen_at=''")
            conn.execute("UPDATE jobs SET last_seen_at=created_at WHERE last_seen_at=''")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_last_seen ON jobs(last_seen_at)")


def upsert_job(job: Job, status: str, score: int, reasons: list[str], concerns: list[str]) -> tuple[bool, bool]:
    """Persist a listing. Returns (is_new, should_notify)."""
    now = datetime.now(timezone.utc).isoformat()
    with _connect() as conn:
        existing = conn.execute(
            "SELECT id, notified_at FROM jobs WHERE source=? AND source_id=?",
            (job.source, job.source_id),
        ).fetchone()
        values = (
            job.title, job.company, job.location, job.url, job.description, job.posted_at, job.date_kind,
            int(job.remote), job.workplace_type, job.employment_type, job.eligibility,
            status, score, json.dumps(reasons, ensure_ascii=False),
            json.dumps(concerns, ensure_ascii=False), now,
        )
        if existing:
            conn.execute(
                """UPDATE jobs SET title=?, company=?, location=?, url=?, description=?, posted_at=?, date_kind=?,
                   remote=?, workplace_type=?, employment_type=?, eligibility=?, status=?, score=?,
                   reasons=?, concerns=?, last_seen_at=? WHERE source=? AND source_id=?""",
                values + (job.source, job.source_id),
            )
            # Notify once per job; if a previous run found it but Telegram failed, it remains unnotified.
            return False, existing["notified_at"] is None and status in {"match", "review"}
        insert_columns = [
            "source", "source_id", "title", "company", "location", "url", "description",
            "posted_at", "date_kind", "remote", "workplace_type", "employment_type",
            "eligibility", "status", "score", "reasons", "concerns", "first_seen_at", "last_seen_at",
        ]
        insert_values = [
            job.source, job.source_id, job.title, job.company, job.location, job.url,
            job.description, job.posted_at, job.date_kind, int(job.remote), job.workplace_type,
            job.employment_type, job.eligibility, status, score,
            json.dumps(reasons, ensure_ascii=False), json.dumps(concerns, ensure_ascii=False), now, now,
        ]
        columns_now = {row[1] for row in conn.execute("PRAGMA table_info(jobs)").fetchall()}
        # Older versions may have a required created_at column; populate it when present.
        if "created_at" in columns_now:
            insert_columns.append("created_at")
            insert_values.append(now)
        placeholders = ", ".join("?" for _ in insert_columns)
        conn.execute(
            f"INSERT INTO jobs ({', '.join(insert_columns)}) VALUES ({placeholders})",
            insert_values,
        )
        return True, status in {"match", "review"}


def mark_notified(job: Job) -> None:
    with _connect() as conn:
        conn.execute(
            "UPDATE jobs SET notified_at=? WHERE source=? AND source_id=?",
            (datetime.now(timezone.utc).isoformat(), job.source, job.source_id),
        )


def list_jobs(status: str | None = None, limit: int = 100) -> list[dict]:
    init_db()
    with _connect() as conn:
        if status:
            rows = conn.execute(
                "SELECT * FROM jobs WHERE status=? ORDER BY last_seen_at DESC LIMIT ?",
                (status, max(1, min(limit, 500))),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM jobs ORDER BY last_seen_at DESC LIMIT ?",
                (max(1, min(limit, 500)),),
            ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["reasons"] = json.loads(item["reasons"] or "[]")
        item["concerns"] = json.loads(item["concerns"] or "[]")
        result.append(item)
    return result
