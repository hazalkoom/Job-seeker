"""In-repo CLI toolkit for Job Hunter (`python -m jobhunter <command>`).

Commands:
- `audit funnel`
- `sources health [--limit N]`
- `ats probe <company>`
- `ats discover <url>`
- `form inspect <url>`
- `questions gaps`
- `inbox status [--days N]`
- `report html [--output PATH]`
- `replay --queue-id N [--dry-run]`
"""
from __future__ import annotations

import argparse
import csv
import html
import json
from pathlib import Path

from app.ats_resolver import classify_apply_path, probe_company_ats
from app.funnel import list_pending_questions
from app.storage import _connect, init_db
from app.tools.discover import discover_from_url, probe_ats_endpoint

ROOT = Path(__file__).resolve().parent.parent


def cmd_audit_funnel(_args: argparse.Namespace) -> int:
    init_db()
    report_path = ROOT / "logs" / "latest_run_report.json"
    if report_path.is_file():
        try:
            data = json.loads(report_path.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    else:
        data = {}

    print("=== Job Hunter 7-Stage Funnel Audit ===")
    if data:
        print(f"Deduped jobs seen:   {data.get('seen_after_cross_source_dedup', 0)}")
        print(f"Confirmed matches:   {data.get('confirmed_matches', 0)}")
        print(f"Review candidates:   {data.get('review_candidates', 0)}")
        print(f"Rejected:            {data.get('rejected', 0)}")
        print(f"ATS resolved:        {data.get('ats_resolved', 0)}")
        print(f"Manual apply cards:  {data.get('manual_apply_cards', 0)}")
        auto = data.get("auto_apply") or {}
        if isinstance(auto, dict) and auto:
            print(
                f"Auto-apply cycle:    processed={auto.get('processed', 0)} "
                f"submitted={auto.get('submitted', 0)} "
                f"skipped={auto.get('skipped', 0)} "
                f"failed={auto.get('failed', 0)}"
            )

    with _connect() as conn:
        rows = conn.execute(
            "SELECT status, COUNT(*) FROM application_queue GROUP BY status ORDER BY COUNT(*) DESC"
        ).fetchall()
        by_src = conn.execute(
            "SELECT COALESCE(j.source, ''), q.canonical_url, q.status "
            "FROM application_queue q LEFT JOIN jobs j ON j.id = q.job_id"
        ).fetchall()

    print("\nQueue Status Breakdown:")
    for status, count in rows:
        print(f"  {status:<18} {count}")

    path_counts: dict[str, int] = {}
    for src, url, _st in by_src:
        kind = classify_apply_path(str(url or ""), str(src or ""))
        path_counts[kind] = path_counts.get(kind, 0) + 1
    if path_counts:
        print("\nQueue Apply-Path Classification:")
        for kind, count in sorted(path_counts.items(), key=lambda x: -x[1]):
            print(f"  {kind:<22} {count}")
    return 0


def cmd_sources_health(args: argparse.Namespace) -> int:
    csv_path = ROOT / "data" / "ats_companies.csv"
    if not csv_path.is_file():
        print("data/ats_companies.csv not found.")
        return 1
    with csv_path.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    limit = int(getattr(args, "limit", 0) or 0)
    if limit > 0:
        rows = rows[:limit]
    ok_count = 0
    dead_count = 0
    print(f"Probing {len(rows)} ATS endpoints...")
    for row in rows:
        ats = str(row.get("ats") or "").strip()
        slug = str(row.get("slug") or "").strip()
        company = str(row.get("company") or "").strip()
        res = probe_ats_endpoint(ats, slug)
        if res.get("ok"):
            ok_count += 1
            print(f"  [OK]   {ats:<15} {slug:<18} ({company}) -> {res.get('job_count', 0)} jobs")
        else:
            dead_count += 1
            print(f"  [DEAD] {ats:<15} {slug:<18} ({company}) -> status={res.get('status_code')}")
    print(f"\nSummary: {ok_count} live, {dead_count} dead/unreachable.")
    return 0


def cmd_ats_probe(args: argparse.Namespace) -> int:
    company = str(getattr(args, "target", "") or "").strip()
    if not company:
        print("Usage: python -m jobhunter ats probe <company>")
        return 1
    found = probe_company_ats(company)
    if found:
        ats, slug, resolved_name = found
        probe = probe_ats_endpoint(ats, slug)
        print(f"Found ATS for {company!r}: ats={ats}, slug={slug}, company={resolved_name}, jobs={probe.get('job_count', 0)}")
        return 0
    print(f"No public ATS board found for {company!r}.")
    return 0


def cmd_ats_discover(args: argparse.Namespace) -> int:
    url = str(getattr(args, "target", "") or "").strip()
    if not url:
        print("Usage: python -m jobhunter ats discover <url>")
        return 1
    results = discover_from_url(url)
    if not results:
        print(f"No ATS links discovered on {url}")
        return 0
    for item in results:
        print(
            f"  ats={item.get('ats')} slug={item.get('slug')} "
            f"ok={item.get('ok')} jobs={item.get('job_count', 0)} url={item.get('url')}"
        )
    return 0


def cmd_form_inspect(args: argparse.Namespace) -> int:
    url = str(getattr(args, "url", "") or "").strip()
    if not url:
        print("Usage: python -m jobhunter form inspect <url>")
        return 1
    from app.application_automation import _answer_for_field, _choose_application_form, _field_text, _labels
    from app.application_profile import load_profile_bundle
    from playwright.sync_api import sync_playwright

    bundle = load_profile_bundle()
    item = {"title": "Software Engineer", "company": "Employer", "url": url}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=25000)
            page.wait_for_timeout(1500)
            form = _choose_application_form(page) or page.locator("body")
            fields = _labels(form)
            print(f"=== Form Inspection for {url} ({len(fields)} controls) ===")
            for f in fields:
                if f.get("type") in {"hidden", "submit", "button", "reset"}:
                    continue
                q = _field_text(f)
                ans, reason = _answer_for_field(q, bundle.profile, bundle.answer_bank, item) if q else (None, "unlabeled")
                req_flag = "REQ" if f.get("required") else "OPT"
                print(f"  [{req_flag}] ({f.get('tag')}/{f.get('type')}) {q[:65]:<65} -> {'mapped' if ans else 'needs review'} ({reason})")
        finally:
            browser.close()
    return 0


def cmd_questions_gaps(_args: argparse.Namespace) -> int:
    pending = list_pending_questions(limit=50)
    if not pending:
        print("No unanswered required questions in the Question Ledger.")
        return 0
    print(f"=== Pending Unanswered Questions ({len(pending)}) ===")
    for idx, q in enumerate(pending, 1):
        print(
            f"{idx}. [{q.get('occurrences', 1)}x] ({q.get('field_type', 'field')}) "
            f"{q.get('question_text', '(unlabeled)')}"
        )
        if q.get("company") or q.get("ats_host"):
            print(f"   Company/Host: {q.get('company', '')} ({q.get('ats_host', '')})")
        if q.get("options"):
            print(f"   Options: {', '.join(str(o) for o in q['options'][:6])}")
        if q.get("html_snippet"):
            print(f"   HTML: {str(q['html_snippet'])[:140]}")
    return 0


def cmd_inbox_status(args: argparse.Namespace) -> int:
    days = int(getattr(args, "days", 7) or 7)
    from app.sources.application_inbox import fetch_and_reconcile_inbox

    res = fetch_and_reconcile_inbox(lookback_days=days, reconcile=args.reconcile)
    print(f"=== Application Inbox Status (last {days} days) ===")
    print(f"Confirmed queue IDs: {res.get('confirmed_queue_ids', [])}")
    print(f"Confirmations seen:  {len(res.get('confirmations', []))}")
    print(f"Unmatched receipts:  {len(res.get('unmatched_confirmations', []))}")
    print(f"Interviews seen:     {len(res.get('interviews', []))}")
    print(f"Rejections seen:     {len(res.get('rejections', []))}")
    return 0


def generate_html_dashboard(output_path: Path | None = None) -> Path:
    init_db()
    out = output_path or (ROOT / "logs" / "dashboard.html")
    out.parent.mkdir(parents=True, exist_ok=True)
    with _connect() as conn:
        q_rows = conn.execute(
            "SELECT q.id, j.title, j.company, j.source, q.status, q.score, q.notes, q.canonical_url "
            "FROM application_queue q LEFT JOIN jobs j ON j.id = q.job_id ORDER BY q.id DESC LIMIT 100"
        ).fetchall()
    pending_qs = list_pending_questions(limit=25)

    rows_html = []
    for r in q_rows:
        rows_html.append(
            f"<tr><td>{r[0]}</td><td>{html.escape(str(r[1] or ''))}</td>"
            f"<td>{html.escape(str(r[2] or ''))}</td><td>{html.escape(str(r[3] or ''))}</td>"
            f"<td><b>{html.escape(str(r[4] or ''))}</b></td><td>{r[5]}</td>"
            f"<td>{html.escape(str(r[6] or '')[:140])}</td></tr>"
        )
    qs_html = []
    for q in pending_qs:
        qs_html.append(
            f"<li><b>{html.escape(str(q.get('question_text') or '(unlabeled)'))}</b> "
            f"({html.escape(str(q.get('field_type') or ''))}, {q.get('occurrences', 1)}x) — "
            f"{html.escape(str(q.get('company') or ''))}</li>"
        )

    doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Job Hunter Funnel & Queue Dashboard</title>
<style>
body {{ font-family: system-ui, sans-serif; margin: 24px; color: #1f2937; }}
table {{ border-collapse: collapse; width: 100%; margin-top: 12px; }}
th, td {{ border: 1px solid #d1d5db; padding: 8px; text-align: left; font-size: 13px; }}
th {{ background: #f3f4f6; }}
</style>
</head>
<body>
<h1>Job Hunter — Funnel & Queue Dashboard</h1>
<h2>Unanswered Required Questions ({len(pending_qs)})</h2>
<ul>{"".join(qs_html) or "<li>None</li>"}</ul>
<h2>Recent Application Queue ({len(q_rows)})</h2>
<table>
<thead><tr><th>ID</th><th>Title</th><th>Company</th><th>Source</th><th>Status</th><th>Score</th><th>Reason / Outcome</th></tr></thead>
<tbody>{"".join(rows_html)}</tbody>
</table>
</body>
</html>
"""
    out.write_text(doc, encoding="utf-8")
    return out


def cmd_report_html(args: argparse.Namespace) -> int:
    raw_out = getattr(args, "output", None)
    out = Path(raw_out) if raw_out else None
    written = generate_html_dashboard(out)
    print(f"Dashboard written to {written}")
    return 0


def cmd_replay(args: argparse.Namespace) -> int:
    queue_id = int(getattr(args, "queue_id", 0) or 0)
    from app.application_queue import get_application

    item = get_application(queue_id)
    if not item:
        print(f"Queue item #{queue_id} not found.")
        return 1
    print(f"Queue item #{queue_id}: {item.get('title')} at {item.get('company')} ({item.get('url')})")
    if getattr(args, "dry_run", True):
        ns = argparse.Namespace(url=str(item.get("url") or ""))
        return cmd_form_inspect(ns)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="jobhunter", description="Job Hunter diagnostic and operations CLI")
    sub = parser.add_subparsers(dest="group")

    from app.run_operations import configure_parser
    configure_parser(sub)

    audit_p = sub.add_parser("audit", help="Audit funnel and queue metrics")
    audit_sub = audit_p.add_subparsers(dest="subcommand")
    audit_sub.add_parser("funnel", help="Show 7-stage funnel breakdown")

    sources_p = sub.add_parser("sources", help="Inspect and probe job sources")
    sources_sub = sources_p.add_subparsers(dest="subcommand")
    sh_p = sources_sub.add_parser("health", help="Probe configured ATS endpoints")
    sh_p.add_argument("--limit", type=int, default=0, help="Max rows to probe")

    ats_p = sub.add_parser("ats", help="Probe or discover ATS endpoints")
    ats_sub = ats_p.add_subparsers(dest="subcommand")
    probe_p = ats_sub.add_parser("probe", help="Probe ATS slugs for a company name")
    probe_p.add_argument("target", help="Company name")
    disc_p = ats_sub.add_parser("discover", help="Discover ATS links from a career page URL")
    disc_p.add_argument("target", help="Career page URL")

    form_p = sub.add_parser("form", help="Dry-run form inspection")
    form_sub = form_p.add_subparsers(dest="subcommand")
    insp_p = form_sub.add_parser("inspect", help="Inspect form fields on a URL without submitting")
    insp_p.add_argument("url", help="Form URL")

    q_p = sub.add_parser("questions", help="Manage the Question Ledger")
    q_sub = q_p.add_subparsers(dest="subcommand")
    q_sub.add_parser("gaps", help="List unanswered required questions")

    inb_p = sub.add_parser("inbox", help="Gmail application inbox tools")
    inb_sub = inb_p.add_subparsers(dest="subcommand")
    st_p = inb_sub.add_parser("status", help="Inspect application confirmations from Gmail")
    st_p.add_argument("--reconcile", action="store_true", help="Update queue entries from exact receipts")
    st_p.add_argument("--days", type=int, default=7, help="Lookback days")

    rep_p = sub.add_parser("report", help="Generate diagnostic reports")
    rep_sub = rep_p.add_subparsers(dest="subcommand")
    html_p = rep_sub.add_parser("html", help="Generate static HTML funnel dashboard")
    html_p.add_argument("--output", default="", help="Output HTML file path")

    replay_p = sub.add_parser("replay", help="Replay or dry-run a queue item")
    replay_p.add_argument("--queue-id", type=int, required=True, help="Queue item ID")
    replay_p.add_argument("--dry-run", action="store_true", default=True, help="Inspect without submitting")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    group = getattr(args, "group", None)
    subcmd = getattr(args, "subcommand", None)

    if group == "run":
        from app.run_operations import run_command
        try:
            return run_command(args)
        except ValueError as exc:
            parser.error(str(exc))
    if group == "audit" and subcmd == "funnel":
        return cmd_audit_funnel(args)
    if group == "sources" and subcmd == "health":
        return cmd_sources_health(args)
    if group == "ats" and subcmd == "probe":
        return cmd_ats_probe(args)
    if group == "ats" and subcmd == "discover":
        return cmd_ats_discover(args)
    if group == "form" and subcmd == "inspect":
        return cmd_form_inspect(args)
    if group == "questions" and subcmd == "gaps":
        return cmd_questions_gaps(args)
    if group == "inbox" and subcmd == "status":
        return cmd_inbox_status(args)
    if group == "report" and subcmd == "html":
        return cmd_report_html(args)
    if group == "replay":
        return cmd_replay(args)

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
