#!/usr/bin/env python3
"""Read-only, human-readable summary of Job Hunter application outcomes.

This command never opens websites, changes the queue, or prints .env values.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.automation_diagnostics import reason_code_for_reason, safe_url  # noqa: E402
from app.config import settings  # noqa: E402


def connect_ro(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=5)


def json_list(value: object) -> list:
    try:
        parsed = json.loads(str(value or "[]"))
    except (TypeError, json.JSONDecodeError):
        return []
    return parsed if isinstance(parsed, list) else []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=40, help="Maximum application records shown")
    parser.add_argument("--json", action="store_true", help="Emit structured JSON instead of a text summary")
    args = parser.parse_args(argv)
    db = Path(settings.database_path).expanduser()
    if not db.is_absolute():
        db = ROOT / db
    if not db.is_file():
        print(f"Database not found (path omitted): {db.name}", file=sys.stderr)
        return 2

    report: dict = {
        "database_exists": True,
        "database_name": db.name,
        "application_log_exists": (ROOT / "logs" / "application_automation.jsonl").is_file(),
        "tables": {},
        "jobs_by_status": {},
        "jobs_by_source_and_status": [],
        "queue_by_status": {},
        "queue_by_qualification": {},
        "automation_events": {},
        "skip_reasons": {},
        "recent_applications": [],
        "recent_audit_events": [],
        "latest_run_report": None,
        "matcher_rejection_reasons": [],
        "source_errors": [],
        "application_run_results": [],
    }
    try:
        with connect_ro(db) as conn:
            conn.row_factory = sqlite3.Row
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            report["tables"] = {name: name in tables for name in ("jobs", "application_queue", "application_events")}
            if "jobs" in tables:
                report["jobs_by_status"] = {str(r[0]): int(r[1]) for r in conn.execute("SELECT status, COUNT(*) FROM jobs GROUP BY status")}
                report["jobs_by_source_and_status"] = [dict(r) for r in conn.execute("SELECT source, status, COUNT(*) AS count FROM jobs GROUP BY source, status ORDER BY source, status")]
            if "application_queue" in tables:
                report["queue_by_status"] = {str(r[0]): int(r[1]) for r in conn.execute("SELECT status, COUNT(*) FROM application_queue GROUP BY status")}
                report["queue_by_qualification"] = {str(r[0]): int(r[1]) for r in conn.execute("SELECT qualification_status, COUNT(*) FROM application_queue GROUP BY qualification_status")}
            if "application_events" in tables:
                report["automation_events"] = {str(r[0]): int(r[1]) for r in conn.execute("SELECT event_type, COUNT(*) FROM application_events GROUP BY event_type ORDER BY COUNT(*) DESC, event_type")}
                for row in conn.execute(
                    "SELECT e.queue_id,e.event_type,e.details,e.created_at FROM application_events e "
                    "WHERE e.event_type LIKE 'application_%' OR e.event_type LIKE 'preflight_%' "
                    "ORDER BY e.id DESC LIMIT 1000"
                ):
                    try:
                        details = json.loads(row["details"] or "{}")
                    except json.JSONDecodeError:
                        details = {}
                    code = str(details.get("reason_code") or "") if isinstance(details, dict) else ""
                    reason = str(details.get("reason") or "") if isinstance(details, dict) else ""
                    if row["event_type"] == "application_auto_skipped" or row["event_type"] == "application_failed":
                        if not code:
                            code = reason_code_for_reason(reason, stage=row["event_type"])
                        report["skip_reasons"][code] = int(report["skip_reasons"].get(code, 0)) + 1
                    if len(report["recent_audit_events"]) < 80:
                        report["recent_audit_events"].append({
                            "queue_id": int(row["queue_id"]), "event": row["event_type"],
                            "created_at": row["created_at"], "reason_code": code or None,
                            "reason": reason[:600] if reason else None,
                            "details": details if isinstance(details, dict) else {},
                        })

            if "application_queue" in tables and "jobs" in tables:
                rows = conn.execute(
                    "SELECT q.id AS queue_id,q.status AS queue_status,q.qualification_status,q.score,"
                    "q.reasons AS queue_reasons,q.concerns,q.notes,q.preflight_status,q.preflight_blockers,"
                    "q.preflight_warnings,q.updated_at,j.title,j.company,j.source,j.source_id,j.url,"
                    "j.location,j.posted_at,j.date_kind,j.description_quality,j.workplace_type,j.employment_type "
                    "FROM application_queue q JOIN jobs j ON j.id=q.job_id "
                    "ORDER BY q.updated_at DESC LIMIT ?", (max(1, min(int(args.limit), 200)),)
                ).fetchall()
                for row in rows:
                    item = dict(row)
                    reason = str(item.get("notes") or "")
                    item["reason_code"] = reason_code_for_reason(reason, stage="stored_outcome") if reason else None
                    item["url"] = safe_url(item.pop("url", ""))
                    item["reasons"] = json_list(item.pop("queue_reasons", "[]"))
                    item["concerns"] = json_list(item.get("concerns"))
                    item["preflight_blockers"] = json_list(item.get("preflight_blockers"))
                    item["preflight_warnings"] = json_list(item.get("preflight_warnings"))
                    for key in ("reasons", "concerns", "preflight_blockers", "preflight_warnings"):
                        item[key] = [str(x)[:500] for x in item[key][:20]]
                    item["notes"] = reason[:800]
                    report["recent_applications"].append(item)
    except sqlite3.Error as exc:
        print(f"Could not inspect database read-only: {type(exc).__name__}", file=sys.stderr)
        return 3

    # Bring in the last runner report so this command explains both matcher
    # rejections and application-attempt skips. The report is already redacted by
    # app.runner before persistence; sanitize again at the read boundary.
    latest_report_path = ROOT / "logs" / "latest_run_report.json"
    if latest_report_path.is_file():
        from app.automation_diagnostics import sanitize
        try:
            latest = json.loads(latest_report_path.read_text(encoding="utf-8", errors="replace"))
            if isinstance(latest, dict):
                latest = sanitize(latest)
                report["matcher_rejection_reasons"] = latest.get("top_rejection_reasons", [])[:20]
                report["source_errors"] = latest.get("source_errors", [])[:40]
                auto = latest.get("auto_apply") or {}
                if isinstance(auto, dict):
                    report["application_run_results"] = [
                        {key: result.get(key) for key in (
                            "queue_id", "title", "company", "source", "outcome",
                            "reason_code", "reason", "ats_host", "apply_links",
                            "diagnostics", "form_diagnostics", "blockers",
                        ) if key in result}
                        for result in auto.get("results", [])[:100]
                        if isinstance(result, dict)
                    ]
                    report["latest_run_report"] = {
                        key: latest.get(key) for key in (
                            "seen_after_cross_source_dedup", "newly_stored", "confirmed_matches",
                            "review_candidates", "rejected", "source_counts", "source_effectiveness",
                            "source_errors", "top_rejection_reasons", "telegram_configured",
                        ) if key in latest
                    }
                    report["latest_run_report"]["auto_apply"] = {
                        key: auto.get(key) for key in (
                            "run_id", "enabled", "processed", "submitted", "skipped", "failed",
                            "reason", "error", "reason_breakdown", "daily_cap",
                        ) if key in auto
                    }
                else:
                    report["latest_run_report"] = {
                        key: latest.get(key) for key in (
                            "seen_after_cross_source_dedup", "newly_stored", "confirmed_matches",
                            "review_candidates", "rejected", "source_counts", "source_effectiveness",
                            "source_errors", "top_rejection_reasons", "telegram_configured",
                        ) if key in latest
                    }
        except (OSError, json.JSONDecodeError):
            report["latest_run_report"] = {"error": "latest run report could not be parsed"}

    log_path = ROOT / "logs" / "application_automation.jsonl"
    if log_path.is_file():
        from app.automation_diagnostics import sanitize
        try:
            lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-500:]
            logs = []
            for line in lines:
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                logs.append(sanitize(event))
            report["recent_audit_events"] = (logs[-80:] + report["recent_audit_events"][:20])[:100]
        except OSError:
            pass

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
        return 0

    print("JOB HUNTER APPLICATION OUTCOME REPORT (READ-ONLY)")
    print(f"Database: present ({report['database_name']}; path intentionally omitted)")
    print(f"Structured audit log: {'present' if report['application_log_exists'] else 'not created yet'}")
    print("\nSaved listing records by status:")
    for status, count in sorted(report["jobs_by_status"].items()):
        print(f"  {status}: {count}")
    print("\nApplication queue by status:")
    for status, count in sorted(report["queue_by_status"].items()):
        print(f"  {status}: {count}")
    print("\nTop automation event types:")
    for name, count in list(report["automation_events"].items())[:15]:
        print(f"  {name}: {count}")
    print("\nSkip/failure reason codes (historical events; repeats are possible):")
    for code, count in sorted(report["skip_reasons"].items(), key=lambda item: (-item[1], item[0])):
        print(f"  {code}: {count}")
    if report.get("latest_run_report"):
        latest = report["latest_run_report"]
        print("\nLatest search report:")
        for key in ("seen_after_cross_source_dedup", "newly_stored", "confirmed_matches", "review_candidates", "rejected"):
            if key in latest:
                print(f"  {key}: {latest[key]}")
        auto = latest.get("auto_apply") or {}
        if auto:
            print("\nLatest automatic-application results:")
            for key in ("enabled", "processed", "submitted", "skipped", "failed", "reason", "error"):
                if key in auto:
                    print(f"  {key}: {auto[key]}")
            print("  reason breakdown:")
            for code, count in (auto.get("reason_breakdown") or {}).items():
                print(f"    {code}: {count}")
    if report.get("matcher_rejection_reasons"):
        print("\nTop matcher rejection reasons from the latest search:")
        for row in report["matcher_rejection_reasons"][:15]:
            if isinstance(row, (list, tuple)) and len(row) >= 2:
                print(f"  {row[0]}: {row[1]}")
    if report.get("source_errors"):
        print("\nLatest source errors:")
        for row in report["source_errors"][:20]:
            if isinstance(row, dict):
                print(f"  {row.get('source', 'unknown')}: {row.get('error', '')}")
    if report.get("application_run_results"):
        print("\nLatest per-listing application outcomes:")
        for item in report["application_run_results"][:min(30, max(1, args.limit))]:
            print(f"  #{item.get('queue_id')} [{item.get('outcome')}] {item.get('title', '')} — {item.get('company', '')}")
            print(f"      reason_code={item.get('reason_code') or '—'} reason={str(item.get('reason') or '')[:260]}")
            links = item.get("apply_links") or (item.get("diagnostics") or {}).get("apply_links", [])
            if links:
                for link in links[:5]:
                    print(f"      apply link: host={link.get('host')} supported_ats={link.get('supported_ats')} url={link.get('url')}")
            form = item.get("form_diagnostics") or {}
            if form:
                print(f"      form diagnostics: forms={form.get('forms_found')} shapes={form.get('form_shapes')}")
    print("\nRecent queue items:")
    for item in report["recent_applications"]:
        print(f"  #{item['queue_id']} [{item['queue_status']}] {item.get('title','')} — {item.get('company','')} ({item.get('source','')})")
        print(f"      score={item.get('score')} posted={item.get('posted_at')} date_kind={item.get('date_kind')} description={item.get('description_quality')} reason_code={item.get('reason_code') or '—'}")
        if item.get("notes"):
            print(f"      reason={item['notes'][:260]}")
        print(f"      url={item.get('url','')}")
    print("\nThe full safe snapshot is available with --json or in the diagnostic ZIP.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
