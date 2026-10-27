#!/usr/bin/env python3
"""One-time retry of selected safe-to-retry application skips.

Dry-run by default. With --apply, records skipped because a form was not discovered
because a public-description enrichment retry is now available, because a form was not discovered,
or because the prior automatic score floor was higher may be retried once. Hard
eligibility, stale-date, missing-description, excessive-experience, CAPTCHA, and
unanswered legal/factual questions are intentionally not retryable here.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.automation_diagnostics import reason_code_for_reason, safe_url  # noqa: E402
from app.application_queue import _event, _now  # noqa: E402
import app.storage as storage  # noqa: E402
from app.storage import _connect  # noqa: E402

ALLOWED_REASON_CODES = {"no_supported_ats_form", "application_form_not_detected", "description_unavailable", "score_below_threshold"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reason-code", action="append", choices=sorted(ALLOWED_REASON_CODES), default=None)
    parser.add_argument("--limit", type=int, default=40)
    parser.add_argument("--max-retries", type=int, default=1)
    parser.add_argument("--apply", action="store_true", help="Actually requeue; without this flag it's a dry run")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    reason_codes = set(args.reason_code or sorted(ALLOWED_REASON_CODES))
    limit = max(1, min(int(args.limit), 100))
    max_retries = max(0, min(int(args.max_retries), 2))
    if max_retries == 0:
        print("max-retries is zero; no candidates will be changed.")
        return 0

    db_path = Path(storage.settings.database_path).expanduser()
    if not db_path.is_absolute():
        db_path = ROOT / db_path
    if not db_path.is_file():
        print("ERROR: Existing Job Hunter database not found; no changes made.", file=sys.stderr)
        return 2
    with _connect() as conn:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {"application_queue", "application_events", "jobs"}.issubset(tables):
            print("ERROR: Application queue tables are missing; no changes made.", file=sys.stderr)
            return 2
        rows = conn.execute(
            "SELECT q.id,q.status,q.notes,q.updated_at,j.title,j.company,j.source,j.url "
            "FROM application_queue q JOIN jobs j ON j.id=q.job_id "
            "WHERE q.status='auto_skipped' AND q.submitted_at IS NULL "
            "ORDER BY q.updated_at DESC LIMIT 500"
        ).fetchall()
        candidates = []
        for row in rows:
            queue_id = int(row["id"])
            reason = str(row["notes"] or "")
            events = conn.execute(
                "SELECT event_type,details FROM application_events WHERE queue_id=? "
                "AND event_type IN ('application_auto_skipped','diagnostic_requeue') ORDER BY id",
                (queue_id,),
            ).fetchall()
            retries = 0
            last_code = ""
            for event in events:
                try:
                    details = json.loads(event["details"] or "{}")
                except json.JSONDecodeError:
                    details = {}
                if event["event_type"] == "diagnostic_requeue":
                    retries += 1
                elif isinstance(details, dict):
                    last_code = str(details.get("reason_code") or last_code)
                    reason = str(details.get("reason") or reason)
            code = last_code or reason_code_for_reason(reason, stage="stored_outcome")
            if code not in reason_codes or retries >= max_retries:
                continue
            candidates.append({
                "queue_id": queue_id,
                "title": str(row["title"] or "")[:180],
                "company": str(row["company"] or "")[:180],
                "source": str(row["source"] or "")[:100],
                "url": safe_url(row["url"]),
                "reason_code": code,
                "previous_reason": reason[:500],
                "previous_diagnostic_retries": retries,
            })
            if len(candidates) >= limit:
                break

        print(json.dumps({
            "mode": "apply" if args.apply else "dry_run",
            "reason_codes": sorted(reason_codes),
            "max_retries": max_retries,
            "candidate_count": len(candidates),
            "candidates": candidates,
        }, ensure_ascii=False, indent=2))
        if not args.apply or not candidates:
            return 0

        now = _now()
        changed = 0
        for item in candidates:
            queue_id = item["queue_id"]
            cursor = conn.execute(
                "UPDATE application_queue SET status='pending_review',preflight_status='not_run',"
                "preflight_blockers='[]',preflight_warnings='[]',reviewed_at=NULL,ready_at=NULL,updated_at=? "
                "WHERE id=? AND status='auto_skipped' AND submitted_at IS NULL",
                (now, queue_id),
            )
            if cursor.rowcount == 1:
                _event(conn, queue_id, "diagnostic_requeue", {
                    "reason_code": item["reason_code"],
                    "previous_reason": item["previous_reason"],
                    "attempt_number": item["previous_diagnostic_retries"] + 1,
                    "max_retries": max_retries,
                    "intent": "Capture apply-link and application-form diagnostics once; not a guarantee of submission.",
                })
                changed += 1
    print(f"Requeued {changed} diagnostic candidate(s). No application was submitted by this script.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
