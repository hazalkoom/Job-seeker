from collections import Counter, defaultdict

from app.matching import classify
from app.runner import fetch_all


def main() -> None:
    jobs, source_counts, errors = fetch_all()
    status_counts = Counter()
    reasons = Counter()
    examples: dict[str, list[tuple]] = defaultdict(list)
    for job in jobs:
        status, score, positive, concerns = classify(job)
        status_counts[status] += 1
        for reason in concerns:
            reasons[reason] += 1
        if status != "match" and len(examples[status]) < 12:
            examples[status].append((job, score, positive, concerns))

    print("\n=== SOURCE COUNTS ===")
    for name, count in source_counts.items():
        print(f"{name:20} {count:5}")
    print(f"{'TOTAL DEDUPED':20} {len(jobs):5}")
    print("\n=== CLASSIFICATION ===")
    for status in ("match", "review", "reject"):
        print(f"{status:20} {status_counts[status]:5}")
    print("\n=== TOP CONCERNS / REJECTION REASONS ===")
    for reason, count in reasons.most_common(20):
        print(f"{count:5} | {reason}")
    for status in ("review", "reject"):
        print(f"\n=== {status.upper()} EXAMPLES ===")
        for job, score, positive, concerns in examples[status]:
            print(f"\n[{job.source}] {job.title} — {job.company}")
            print(f"Score: {score} | Location: {job.location} | Date: {job.posted_at}")
            print(f"Reasons: {positive}")
            print(f"Concerns: {concerns}")
            print(f"URL: {job.url}")
    if errors:
        print("\n=== SOURCE ERRORS ===")
        for error in errors:
            print(f"{error['source']}: {error['error']}")


if __name__ == "__main__":
    main()
