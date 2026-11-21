"""Render the sanitized run report as a GitHub Actions summary."""
import json
from pathlib import Path
import sys
from html import escape


def main() -> None:
    report = json.loads(Path(sys.argv[1]).read_text())
    search = report.get("search", {})
    auto = report.get("auto_apply", {})
    print("## Job Hunter")
    print()
    print(f"- Listings fetched: {sum(search.get('source_counts', {}).values())}")
    print(f"- Qualified listings: {search.get('funnel', {}).get('stages', {}).get('qualified', 0)}")
    print(f"- Submit attempts: {auto.get('attempted', 0)}")
    print(f"- Browser confirmed: {auto.get('submitted', 0)}")
    print(f"- Email confirmed: {report.get('email_confirmed', 0)}")
    print(f"- Telegram delivered: {report.get('telegram_delivered', 'not requested')}")
    print(f"- Outcome: {escape(str(auto.get('reason') or auto.get('reason_breakdown') or 'See candidates'))}")
    if report.get("candidates"):
        print("\n### Candidates\n")
        for item in report["candidates"]:
            print(f"- #{int(item['id'])} {escape(item['title'])} at {escape(item['company'])} ({item['score']})")


if __name__ == "__main__":
    main()
