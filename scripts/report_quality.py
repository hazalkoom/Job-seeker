#!/usr/bin/env python3
"""Summarize stored job quality and referral-funnel state from SQLite."""
from __future__ import annotations

import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import settings  # noqa: E402
from app.storage import init_db  # noqa: E402


def main() -> int:
    init_db()
    conn = sqlite3.connect(settings.database_path)
    try:
        print(f"Database: {settings.database_path}")
        print("\n=== Stored jobs by source/status/description quality ===")
        rows = conn.execute(
            """SELECT source, status, description_quality, COUNT(*)
               FROM jobs GROUP BY source, status, description_quality
               ORDER BY source, status, description_quality"""
        ).fetchall()
        if not rows:
            print("No stored jobs yet. Run python run_once.py first.")
        for source, status, quality, count in rows:
            print(f"{source:34} {status:8} {quality:9} {count:5}")

        print("\n=== Stored qualification status ===")
        status_counts = conn.execute("SELECT status, COUNT(*) FROM jobs GROUP BY status").fetchall()
        for status, count in status_counts:
            print(f"{status:8} {count:5}")
        print("\n=== Notified status ===")
        for row in conn.execute("""SELECT status,
              SUM(CASE WHEN notified_at IS NULL THEN 1 ELSE 0 END) AS pending,
              SUM(CASE WHEN notified_at IS NOT NULL THEN 1 ELSE 0 END) AS notified
              FROM jobs WHERE status IN ('match','review') GROUP BY status"""):
            print(f"{row[0]:8} pending={row[1] or 0:4} notified={row[2] or 0:4}")

        print("\n=== Referral tracker ===")
        try:
            contacts = conn.execute("SELECT COUNT(*) FROM referral_contacts").fetchone()[0]
            outreach = conn.execute("SELECT status, COUNT(*) FROM referral_outreach GROUP BY status").fetchall()
            print(f"contacts: {contacts}")
            for status, count in outreach:
                print(f"outreach {status:10} {count:4}")
        except sqlite3.OperationalError as exc:
            print(f"Referral tables unavailable (run latest init): {exc}")

        print("\n=== Candidate feedback ===")
        try:
            feedback = conn.execute(
                "SELECT feedback_type, COUNT(*) FROM job_feedback GROUP BY feedback_type ORDER BY feedback_type"
            ).fetchall()
            if not feedback:
                print("No feedback recorded yet. Use python scripts/job_feedback.py mark ...")
            for kind, count in feedback:
                print(f"{kind:28} {count:5}")
        except sqlite3.OperationalError as exc:
            print(f"Feedback table unavailable (run latest init): {exc}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
