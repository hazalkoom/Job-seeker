"""Store human feedback about Job Hunter classifications for later review."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.storage import _connect, init_db

FEEDBACK_TYPES = {
    "good_fit",
    "too_experienced",
    "not_eligible_from_egypt",
    "stale_or_closed",
    "irrelevant",
    "applied",
    "interview",
    "rejected_by_employer",
}


def add_feedback(job_id: int, feedback_type: str, notes: str = "") -> int:
    kind = feedback_type.strip().lower()
    if kind not in FEEDBACK_TYPES:
        raise ValueError(f"Feedback type must be one of: {', '.join(sorted(FEEDBACK_TYPES))}")
    init_db()
    with _connect() as conn:
        exists = conn.execute("SELECT id FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not exists:
            raise ValueError(f"Job ID {job_id} was not found in the local database.")
        cursor = conn.execute(
            "INSERT INTO job_feedback(job_id, feedback_type, notes, created_at) VALUES (?, ?, ?, ?)",
            (job_id, kind, notes.strip(), datetime.now(timezone.utc).isoformat()),
        )
        return int(cursor.lastrowid)


def list_feedback(limit: int = 100) -> list[dict[str, Any]]:
    init_db()
    with _connect() as conn:
        rows = conn.execute(
            """SELECT f.*, j.title, j.company, j.status AS job_status, j.score, j.url
               FROM job_feedback f JOIN jobs j ON j.id=f.job_id
               ORDER BY f.created_at DESC LIMIT ?""",
            (max(1, min(int(limit), 500)),),
        ).fetchall()
    return [dict(row) for row in rows]


def feedback_summary() -> dict[str, int]:
    init_db()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT feedback_type, COUNT(*) AS amount FROM job_feedback GROUP BY feedback_type"
        ).fetchall()
    return {str(row["feedback_type"]): int(row["amount"]) for row in rows}
