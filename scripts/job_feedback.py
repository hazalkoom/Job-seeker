#!/usr/bin/env python3
"""List stored candidates and record your feedback without changing match rules."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.feedback import FEEDBACK_TYPES, add_feedback, feedback_summary, list_feedback  # noqa: E402
from app.storage import _connect, init_db  # noqa: E402


def _list_jobs(status: str, limit: int) -> list[dict]:
    init_db()
    with _connect() as conn:
        if status == "all":
            rows = conn.execute(
                "SELECT id, source, title, company, status, score, location, description_quality, url "
                "FROM jobs WHERE status IN ('match','review') ORDER BY score DESC, last_seen_at DESC LIMIT ?",
                (max(1, min(limit, 200)),),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, source, title, company, status, score, location, description_quality, url "
                "FROM jobs WHERE status=? ORDER BY score DESC, last_seen_at DESC LIMIT ?",
                (status, max(1, min(limit, 200))),
            ).fetchall()
    return [dict(row) for row in rows]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    listing = sub.add_parser("list", help="List stored match/review candidates with database IDs")
    listing.add_argument("--status", choices=("match", "review", "all"), default="review")
    listing.add_argument("--limit", type=int, default=30)
    mark = sub.add_parser("mark", help="Record human feedback on a stored candidate")
    mark.add_argument("--job-id", type=int, required=True)
    mark.add_argument("--type", choices=sorted(FEEDBACK_TYPES), required=True)
    mark.add_argument("--notes", default="")
    report = sub.add_parser("report", help="Summarize feedback collected so far")
    report.add_argument("--limit", type=int, default=30)
    args = parser.parse_args()
    init_db()

    if args.command == "list":
        rows = _list_jobs(args.status, args.limit)
        for row in rows:
            print(f"job_id={row['id']} [{row['status']}/{row['score']}] {row['company']} — {row['title']}")
            print(f"  source={row['source']} | description={row['description_quality']} | {row['location']}")
            print(f"  {row['url']}")
        if not rows:
            print("No stored candidates in that category.")
        return 0

    if args.command == "mark":
        feedback_id = add_feedback(args.job_id, args.type, args.notes)
        print(f"Saved feedback ID {feedback_id} for job ID {args.job_id}: {args.type}")
        print("This records feedback for analysis; it does not automatically alter classifier rules or send messages.")
        return 0

    summary = feedback_summary()
    print("=== Feedback summary ===")
    if not summary:
        print("No feedback recorded yet.")
    for kind, count in sorted(summary.items()):
        print(f"{kind:28} {count:5}")
    print("\n=== Recent feedback ===")
    for item in list_feedback(args.limit):
        print(f"feedback_id={item['id']} job_id={item['job_id']} {item['feedback_type']} — {item['company']} / {item['title']}")
        if item['notes']:
            print(f"  Notes: {item['notes']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
