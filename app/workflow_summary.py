"""Render the sanitized run report as a GitHub Actions summary."""
import json
from pathlib import Path
import sys
from html import escape


def public_report(report: dict) -> dict:
    """Publish aggregate counts only. Candidate and receipt details stay private."""
    search = report.get("search", report)
    funnel = search.get("funnel", {}).get("stages", {})
    auto = report.get("auto_apply") or {}
    outcome_codes = auto.get("reason_breakdown", {})
    return {
        "fetched": sum(search.get("source_counts", {}).values()),
        "qualified": funnel.get("qualified", 0),
        "direct_ats": funnel.get("apply_path_known", 0),
        "forms_found": sum(bool(r.get("form_diagnostics", {}).get("forms_found"))
                           for r in auto.get("results", [])),
        "attempted": auto.get("attempted", 0),
        "confirmed": auto.get("submitted", 0),
        "email_confirmed": report.get("email_confirmed", 0),
        "source_errors": len(search.get("source_errors", [])),
        "candidate_count": len(report.get("candidates", [])),
        "telegram_delivered": report.get("telegram_delivered", "not requested"),
        "outcome_codes": outcome_codes,
    }


def main() -> None:
    report = public_report(json.loads(Path(sys.argv[1]).read_text()))
    if len(sys.argv) > 2:
        Path(sys.argv[2]).write_text(json.dumps(report, indent=2) + "\n")
    print("## Job Hunter")
    print()
    for key, value in report.items():
        print(f"- {key.replace('_', ' ').capitalize()}: {escape(str(value))}")


if __name__ == "__main__":
    main()
