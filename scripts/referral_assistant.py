#!/usr/bin/env python3
"""CLI for researching contacts and tracking human-sent referral outreach."""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import settings  # noqa: E402
from app.referrals import (  # noqa: E402
    add_contact,
    contact_search_links,
    create_outreach_draft,
    due_followups,
    list_contacts,
    list_outreach,
    update_outreach,
)
from app.storage import init_db  # noqa: E402


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(settings.database_path)
    conn.row_factory = sqlite3.Row
    return conn


def _job_rows(status: str = "match,review", limit: int = 50) -> list[dict]:
    statuses = [s.strip() for s in status.split(",") if s.strip()]
    placeholders = ",".join("?" for _ in statuses)
    init_db()
    with _connect() as conn:
        return [dict(row) for row in conn.execute(
            f"SELECT id, title, company, location, status, score, url, description_quality "
            f"FROM jobs WHERE status IN ({placeholders}) ORDER BY score DESC, last_seen_at DESC LIMIT ?",
            (*statuses, max(1, min(limit, 200))),
        ).fetchall()]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    companies = sub.add_parser("companies", help="List companies with stored match/review jobs")
    companies.add_argument("--limit", type=int, default=80)

    jobs = sub.add_parser("jobs", help="List stored jobs and their internal database IDs")
    jobs.add_argument("--status", choices=("match", "review", "match,review"), default="match,review")
    jobs.add_argument("--limit", type=int, default=50)

    search = sub.add_parser("suggest-contacts", help="Print manual search links for potential referrers")
    search.add_argument("--company", required=True)

    add = sub.add_parser("add-contact", help="Save a contact you found and verified yourself")
    add.add_argument("--name", required=True)
    add.add_argument("--company", required=True)
    add.add_argument("--role", default="")
    add.add_argument("--profile-url", default="")
    add.add_argument("--notes", default="")

    contacts = sub.add_parser("contacts", help="List saved contacts")
    contacts.add_argument("--company", default="")

    draft = sub.add_parser("draft", help="Create a personalized referral message draft; does not send it")
    draft.add_argument("--job-id", type=int, required=True, help="Database ID shown by the jobs command")
    draft.add_argument("--contact-id", type=int, required=True, help="ID shown by contacts command")

    outreach = sub.add_parser("outreach", help="List referral outreach records")
    outreach.add_argument("--status", default="")

    update = sub.add_parser("update", help="Record outreach status after you manually send/reply")
    update.add_argument("--outreach-id", type=int, required=True)
    update.add_argument("--status", required=True, choices=("draft", "contacted", "replied", "referred", "declined"))
    update.add_argument("--followup-days", type=int, default=5)
    update.add_argument("--notes", default="")

    sub.add_parser("followups", help="List contacted people whose follow-up date is due")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    init_db()

    if args.command == "companies":
        rows = _job_rows(limit=args.limit)
        grouped: dict[str, list[dict]] = {}
        for job in rows:
            grouped.setdefault(job["company"] or "Unknown company", []).append(job)
        for company, jobs in sorted(grouped.items(), key=lambda pair: (-len(pair[1]), pair[0].lower())):
            print(f"{company}: {len(jobs)} stored opportunity/opportunities")
            for job in jobs[:2]:
                print(f"  job_id={job['id']} [{job['status']}/{job['score']}] {job['title']} — {job['url']}")
        return 0

    if args.command == "jobs":
        for job in _job_rows(args.status, args.limit):
            print(f"job_id={job['id']} [{job['status']}/{job['score']}] {job['company']} — {job['title']}")
            print(f"  description={job['description_quality']} | {job['location']} | {job['url']}")
        return 0

    if args.command == "suggest-contacts":
        for label, url in contact_search_links(args.company).items():
            print(f"{label}: {url}")
        print("\nVerify the person still works there and is relevant before sending any message.")
        return 0

    if args.command == "add-contact":
        contact_id = add_contact(name=args.name, company=args.company, role=args.role,
                                 profile_url=args.profile_url, notes=args.notes)
        print(f"Saved contact ID {contact_id}: {args.name} — {args.company}")
        return 0

    if args.command == "contacts":
        rows = list_contacts(args.company)
        for contact in rows:
            print(f"contact_id={contact['id']} {contact['name']} — {contact['role'] or 'role not supplied'} @ {contact['company']}")
            if contact["profile_url"]:
                print(f"  {contact['profile_url']}")
            if contact["notes"]:
                print(f"  Notes: {contact['notes']}")
        if not rows:
            print("No contacts saved yet. Use suggest-contacts, then add-contact after verifying a person.")
        return 0

    if args.command == "draft":
        outreach_id, message = create_outreach_draft(args.job_id, args.contact_id)
        print(f"Referral draft saved as outreach ID {outreach_id}. It was NOT sent.\n")
        print("-" * 72)
        print(message)
        print("-" * 72)
        print("Review/edit this draft, then send it manually if appropriate.")
        return 0

    if args.command == "outreach":
        rows = list_outreach(args.status)
        for row in rows:
            print(f"outreach_id={row['id']} [{row['status']}] {row['contact_name']} @ {row['company']} — {row['title']}")
            if row["next_followup_at"]:
                print(f"  follow-up due: {row['next_followup_at']}")
            print(f"  {row['profile_url'] or '(no profile URL saved)'}")
        if not rows:
            print("No outreach records found.")
        return 0

    if args.command == "update":
        update_outreach(args.outreach_id, args.status, followup_days=args.followup_days, notes=args.notes)
        print(f"Outreach {args.outreach_id} updated to {args.status}.")
        if args.status == "contacted":
            print(f"A follow-up will appear after {max(1, min(60, args.followup_days))} days if no reply is recorded.")
        return 0

    if args.command == "followups":
        rows = due_followups()
        for row in rows:
            print(f"outreach_id={row['id']} {row['contact_name']} @ {row['company']} — {row['title']}")
            print(f"  due: {row['next_followup_at']} | job: {row['url']}")
        print(f"\nDue follow-ups: {len(rows)}")
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
