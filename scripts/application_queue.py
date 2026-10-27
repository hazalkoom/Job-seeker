#!/usr/bin/env python3
"""Local CLI for reviewing the Job Hunter application queue.

No command in this script opens or submits a job application. The
mark-submitted command records a submission the user already made manually.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.application_queue import (  # noqa: E402
    decide_application,
    list_applications,
    record_manual_submission,
    resolve_application_question,
    run_preflight,
)


def _print(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Review-first Job Hunter application queue")
    commands = parser.add_subparsers(dest="command", required=True)

    listing = commands.add_parser("list", help="List queued applications")
    listing.add_argument("--status", choices=(
        "pending_review", "approved", "ready", "applying", "submitted", "rejected", "withdrawn",
        "auto_skipped", "failed"
    ))
    listing.add_argument("--limit", type=int, default=100)

    review = commands.add_parser("approve", help="Approve one queue item for manual preparation")
    review.add_argument("queue_id", type=int)
    review.add_argument("--notes", default="")

    reject = commands.add_parser("reject", help="Reject one queue item")
    reject.add_argument("queue_id", type=int)
    reject.add_argument("--notes", default="")

    preflight = commands.add_parser("preflight", help="Check profile and job prerequisites")
    preflight.add_argument("queue_id", type=int)
    preflight.add_argument("--profile", default=None, help="Optional candidate_profile.json path")
    preflight.add_argument("--answer-bank", default=None, help="Optional application_answers.json path")

    answer = commands.add_parser("answer", help="Resolve one application question from the private profile")
    answer.add_argument("queue_id", type=int)
    answer.add_argument("question", help="Exact question shown on the form; quote it in the shell")
    answer.add_argument("--profile", default=None, help="Optional candidate_profile.json path")
    answer.add_argument("--answer-bank", default=None, help="Optional application_answers.json path")
    answer.add_argument("--target-country", default=None)
    answer.add_argument("--skill", action="append", default=[], help="Relevant skill; repeat as needed")

    submitted = commands.add_parser(
        "mark-submitted", help="Record an application you already submitted manually"
    )
    submitted.add_argument("queue_id", type=int)
    submitted.add_argument("--reference", default="", help="Confirmation ID or non-sensitive reference")
    submitted.add_argument("--notes", default="")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "list":
            _print(list_applications(status=args.status, limit=args.limit))
        elif args.command == "approve":
            _print(decide_application(args.queue_id, "approve", args.notes))
        elif args.command == "reject":
            _print(decide_application(args.queue_id, "reject", args.notes))
        elif args.command == "preflight":
            result = run_preflight(
                args.queue_id,
                profile_path=args.profile,
                answer_bank_path=args.answer_bank,
            )
            _print(result)
            return 0 if result["passed"] else 2
        elif args.command == "answer":
            result = resolve_application_question(
                args.queue_id,
                args.question,
                profile_path=args.profile,
                answer_bank_path=args.answer_bank,
                target_country=args.target_country,
                relevant_skills=args.skill,
            )
            _print({
                "status": result.status,
                "category": result.category,
                "answer": result.answer,
                "reason": result.reason,
                "source": result.source,
                "can_auto_fill": result.can_auto_fill,
            })
        elif args.command == "mark-submitted":
            _print(record_manual_submission(
                args.queue_id,
                reference=args.reference,
                notes=args.notes,
            ))
    except (ValueError, LookupError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"Error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
