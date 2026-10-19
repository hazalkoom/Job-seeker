#!/usr/bin/env python3
"""Re-evaluate stored SQLite rows with current Job Hunter matching rules.

This command performs no network requests and sends no Telegram messages. It
preserves notified_at and referral history. Back up jobs.sqlite3 before using.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.matching import classify  # noqa: E402
from app.models import Job  # noqa: E402
from app.storage import _connect, init_db  # noqa: E402


def main() -> int:
    init_db()
    counts: Counter[str] = Counter()
    changed = 0
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM jobs ORDER BY id").fetchall()
        for row in rows:
            item = dict(row)
            job = Job(
                source=str(item.get("source") or "unknown"),
                source_id=str(item.get("source_id") or item.get("id") or ""),
                title=str(item.get("title") or ""),
                company=str(item.get("company") or "Unknown company"),
                location=str(item.get("location") or ""),
                url=str(item.get("url") or ""),
                description=str(item.get("description") or ""),
                posted_at=str(item.get("posted_at") or ""),
                date_kind=str(item.get("date_kind") or "unknown"),
                remote=bool(item.get("remote")),
                employment_type=str(item.get("employment_type") or ""),
                workplace_type=str(item.get("workplace_type") or "unknown"),
                eligibility=str(item.get("eligibility") or ""),
                description_quality=str(item.get("description_quality") or "unknown"),
            )
            status, score, reasons, concerns = classify(job)
            counts[status] += 1
            if (
                item.get("status") != status
                or item.get("score") != score
                or item.get("reasons") != json.dumps(reasons, ensure_ascii=False)
                or item.get("concerns") != json.dumps(concerns, ensure_ascii=False)
            ):
                changed += 1
            conn.execute(
                "UPDATE jobs SET status=?, score=?, reasons=?, concerns=? WHERE id=?",
                (
                    status,
                    score,
                    json.dumps(reasons, ensure_ascii=False),
                    json.dumps(concerns, ensure_ascii=False),
                    item["id"],
                ),
            )

    print(f"Database reclassified: {len(rows)} stored rows")
    print(f"Rows whose classification/details changed: {changed}")
    for status in ("match", "review", "reject"):
        print(f"{status:8} {counts[status]:5}")
    print("No jobs were fetched and no Telegram messages were sent.")
    print("Existing notified_at values and referral records were preserved.")
    print("Review rows with description_quality=unknown may need to be fetched again to obtain complete source data.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
