"""Explicit commands used by operators and GitHub Actions."""
from __future__ import annotations

import argparse
from dataclasses import replace
from html import escape
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit

from app import storage
from app.application_queue import get_application, has_attempt_history, list_applications, prioritize_queue_items
from app.automation_diagnostics import safe_url, sanitize
from app.ats_resolver import classify_apply_path

_PENDING = {"pending_review", "approved", "ready"}


def _inspect_form(url: str) -> dict:
    from playwright.sync_api import Error, sync_playwright
    from app.application_automation import _choose_application_form, _is_challenge, _labels, _requires_manual_verification

    if urlsplit(url).scheme not in {"http", "https"} or classify_apply_path(url) == "login_gated":
        return {"reason": "no_public_application_url"}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page(accept_downloads=False)
            page.route("**/*", lambda route: route.continue_() if route.request.method in {"GET", "HEAD"} else route.abort())
            response = page.goto(url, wait_until="domcontentloaded", timeout=20000)
            if response and response.status >= 400:
                return {"http_status": response.status}
            body = page.locator("body").inner_text(timeout=5000)
            if _requires_manual_verification(page, body) or _is_challenge(page, body):
                return {"reason": "manual_verification_required"}
            form = _choose_application_form(page)
            return {
                "form_found": form is not None,
                "required_fields": [{"label": field.get("label"), "type": field.get("type")}
                                    for field in _labels(form) if field.get("required")] if form else [],
            }
        except Error as exc:
            return {"reason": type(exc).__name__}
        finally:
            browser.close()


def _dry_run(queue_id: int | None) -> dict:
    from app.runner import run_once

    if queue_id is not None:
        db_path = Path(storage.settings.database_path).resolve()
        import sqlite3
        with sqlite3.connect(db_path.as_uri() + "?mode=ro", uri=True) as lookup:
            row = lookup.execute("""
                SELECT q.status, j.url FROM application_queue q JOIN jobs j ON j.id=q.job_id WHERE q.id=?
            """, (queue_id,)).fetchone()
        if not row:
            raise ValueError("Queue ID not found")
        return {"queue_id": queue_id, "status": row[0], "form": _inspect_form(row[1])}
    previous = storage.settings
    with TemporaryDirectory() as work:
        storage.settings = replace(previous, database_path=str(Path(work) / "jobs.sqlite3"))
        try:
            return run_once(send_notifications=False, apply=False, public_only=True, persist_report=False)
        finally:
            storage.settings = previous


def _candidates(queue_id: int | None, limit: int) -> list[int]:
    from app.application_automation import _reason_for_auto_skip

    items = [get_application(queue_id)] if queue_id else prioritize_queue_items(
        [item for status in sorted(_PENDING) for item in list_applications(status=status, limit=500)]
    )
    eligible = [
        item["id"] for item in items if item and item["status"] in _PENDING
        and classify_apply_path(item["url"], item["source"]) == "direct_ats"
        and not has_attempt_history(item["id"]) and not _reason_for_auto_skip(item)
    ]
    return eligible[:limit]


def _telegram_summary(report: dict) -> bool:
    from app.telegram import send_message

    auto = report.get("auto_apply", {})
    search = report.get("search", {})
    funnel = search.get("funnel", {}).get("stages", {})
    lines = [
        "<b>Job Hunter — application cycle</b>",
        f"Fetched {sum(search.get('source_counts', {}).values())} · "
        f"qualified {funnel.get('qualified', 0)} · direct ATS {funnel.get('apply_path_known', 0)}",
        f"Forms found {sum(bool(r.get('form_diagnostics', {}).get('forms_found')) for r in auto.get('results', []))} · "
        f"submit attempts {auto.get('attempted', 0)} · browser confirmations {auto.get('submitted', 0)} · "
        f"email confirmations {report.get('email_confirmed', 0)}",
    ]
    for row in auto.get("results", [])[:5]:
        title = escape(str(row.get("title") or "Application")[:100])
        reason = escape(str(row.get("reason_code") or row.get("outcome"))[:80])
        url = safe_url(row.get("url"))
        if urlsplit(url).scheme in {"http", "https"}:
            title = f'<a href="{escape(url, quote=True)}">{title}</a>'
        cv = escape(str(row.get("cv_used") or ""))
        lines.append(f"• {title} — {reason}" + (f" · {cv}" if cv and row.get("outcome") == "submitted" else ""))
    if auto.get("reason"):
        lines.append(escape(str(auto["reason"])[:250]))
    if "auto_apply" not in report:
        lines.append("Eligible direct ATS jobs for review:")
        for item in report.get("candidates", [])[:10]:
            title = escape(str(item["title"])[:100])
            company = escape(str(item["company"])[:70])
            url = escape(safe_url(item["url"]), quote=True)
            lines.append(f'• #{item["id"]} <a href="{url}">{title}</a> at {company}')
    return send_message("\n".join(lines))


def run_command(args: argparse.Namespace) -> int:
    from app.application_automation import run_auto_apply
    from app.runner import run_once
    from app.workflow_state import hold_unresolved, reserve, reserved_ids

    mode, queue_id = args.mode, args.queue_id
    if queue_id is not None and queue_id <= 0:
        raise ValueError("Queue ID must be positive")
    if mode == "dry-run":
        report = _dry_run(queue_id)
    elif mode == "submit-one":
        if not queue_id:
            raise ValueError("--queue-id is required in submit-one mode")
        report = run_auto_apply(max_items=1, queue_ids=[queue_id], send_notifications=False)
    elif mode == "prepare":
        if not args.reservation or not args.output:
            raise ValueError("prepare requires --reservation and --output")
        search_report = run_once(send_notifications=False, apply=False, persist_report=False)
        candidates = _candidates(queue_id, 20 if args.inspect_only else 5)
        report = {
            "search": search_report,
            "reserved": [] if args.inspect_only else reserve(candidates, args.reservation),
            "candidates": [
                {field: item[field] for field in ("id", "title", "company", "score", "url")}
                for candidate in candidates
                if (item := get_application(candidate))
            ],
        }
    else:
        if not args.reservation or not args.output:
            raise ValueError("submit-reserved requires --reservation and --output")
        report = json.loads(args.output.read_text())
        queue_ids = reserved_ids(args.reservation)
        if queue_ids != report["reserved"]:
            raise ValueError("Reserved queue differs from the preparation report")
        report["auto_apply"] = run_auto_apply(
            max_items=len(queue_ids), queue_ids=queue_ids, reservation=args.reservation,
            send_notifications=False,
        ) if queue_ids else {"reason": "No eligible direct ATS jobs were reserved.", "attempted": 0, "submitted": 0}
        hold_unresolved(args.reservation)
        from app.sources.application_inbox import fetch_and_reconcile_inbox
        try:
            report["email_confirmed"] = len(fetch_and_reconcile_inbox()["confirmed_queue_ids"])
        except Exception as exc:
            report["inbox_error"] = type(exc).__name__
        report["telegram_delivered"] = _telegram_summary(report)

    if mode == "prepare" and args.inspect_only:
        report["telegram_delivered"] = _telegram_summary(report)

    payload = json.dumps(sanitize(report), indent=2, ensure_ascii=False, default=str) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload)
    else:
        print(payload, end="")
    if mode == "dry-run" and queue_id is None and not sum(report.get("source_counts", {}).values()):
        return 1
    if mode == "submit-one":
        return 0 if report.get("submitted") == 1 else 1
    if mode == "submit-reserved" and queue_id and report["auto_apply"].get("submitted") != 1:
        return 1
    return 0


def configure_parser(subparsers) -> None:
    parser = subparsers.add_parser("run", help="Run an isolated inspection or a bounded application cycle")
    parser.add_argument("--mode", required=True, choices=("dry-run", "submit-one", "prepare", "submit-reserved"))
    parser.add_argument("--queue-id", type=int, metavar="ID")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--inspect-only", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--reservation", default=os.getenv("GITHUB_RUN_ID", ""))
