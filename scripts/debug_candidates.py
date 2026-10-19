#!/usr/bin/env python3
"""Fetch and classify current source data without writing SQLite or sending Telegram messages."""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.matching import classify  # noqa: E402
from app.runner import fetch_all  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--show", type=int, default=12, help="Examples per status (default 12)")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    args = parser.parse_args()

    jobs, source_counts, source_errors = fetch_all()
    by_status: dict[str, list[dict]] = defaultdict(list)
    source_status: dict[str, Counter] = defaultdict(Counter)
    rejection_reasons: Counter[str] = Counter()

    for job in jobs:
        status, score, reasons, concerns = classify(job)
        source_status[job.source][status] += 1
        if status == "reject":
            rejection_reasons.update(concerns)
        by_status[status].append({
            "source": job.source,
            "source_id": job.source_id,
            "title": job.title,
            "company": job.company,
            "location": job.location,
            "url": job.url,
            "posted_at": job.posted_at,
            "date_kind": job.date_kind,
            "description_quality": job.description_quality,
            "description_chars": len(job.description or ""),
            "status": status,
            "score": score,
            "reasons": reasons,
            "concerns": concerns,
            "description_excerpt": (job.description or "")[:500],
        })

    report = {
        "fetched_source_counts": source_counts,
        "unique_jobs_after_cross_source_dedup": len(jobs),
        "classification_counts": {name: len(by_status[name]) for name in ("match", "review", "reject")},
        "source_effectiveness": {name: dict(counts) for name, counts in sorted(source_status.items())},
        "top_rejection_reasons": rejection_reasons.most_common(20),
        "source_errors": source_errors,
        "examples": {status: sorted(items, key=lambda item: item["score"], reverse=True)[:max(1, min(args.show, 50))]
                     for status, items in by_status.items()},
    }
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0

    print("=== SOURCE COUNTS (fetched) ===")
    for name, count in sorted(source_counts.items()):
        states = source_status.get(name, Counter())
        print(f"{name:32} fetched={count:4} unique={sum(states.values()):4} match={states['match']:3} review={states['review']:3} reject={states['reject']:4}")
    print(f"\nTOTAL UNIQUE: {len(jobs)}")
    print("CLASSIFICATION:", report["classification_counts"])
    print("\nTOP REJECTION REASONS:")
    for reason, count in report["top_rejection_reasons"]:
        print(f"{count:5}  {reason}")

    if source_errors:
        print("\nSOURCE ERRORS:")
        for item in source_errors:
            print(f"{item['source']}: {item['error']}")

    for status in ("match", "review", "reject"):
        print(f"\n=== {status.upper()} EXAMPLES ===")
        examples = report["examples"].get(status, [])
        for item in examples:
            print(f"[{item['source']}] {item['title']} — {item['company']} | score={item['score']} | desc={item['description_quality']}/{item['description_chars']} chars")
            print(f"  Location: {item['location']} | date: {item['posted_at']} ({item['date_kind']})")
            if item["reasons"]:
                print("  Reasons: " + "; ".join(item["reasons"][:5]))
            if item["concerns"]:
                print("  Concerns: " + "; ".join(item["concerns"][:5]))
            print(f"  URL: {item['url']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
