from __future__ import annotations

from collections import Counter

from app.config import settings
from app.matching import classify
from app.models import Job
from app.sources import enabled_sources
from app.storage import init_db, mark_notified, upsert_job
from app.telegram import format_message, send_message


def fetch_all() -> tuple[list[Job], dict[str, int], list[dict[str, str]]]:
    all_jobs: list[Job] = []
    source_counts: dict[str, int] = {}
    source_errors: list[dict[str, str]] = []
    for name, fetch in enabled_sources():
        try:
            jobs = fetch()
            source_counts[name] = len(jobs)
            all_jobs.extend(jobs)
        except Exception as exc:  # each source is isolated so one outage won't stop the run
            source_counts[name] = 0
            source_errors.append({"source": name, "error": f"{type(exc).__name__}: {str(exc)[:250]}"})
    # Cross-source dedup: prefer a source's own ID, otherwise use canonical URL.
    unique: dict[tuple[str, str], Job] = {}
    url_seen: set[str] = set()
    for job in all_jobs:
        url_key = job.url.split("?", 1)[0].rstrip("/").lower()
        if url_key in url_seen:
            continue
        url_seen.add(url_key)
        unique[(job.source, job.source_id)] = job
    return list(unique.values()), source_counts, source_errors


def run_once() -> dict:
    init_db()
    jobs, source_counts, source_errors = fetch_all()
    rejection_reasons: Counter[str] = Counter()
    status_counts: Counter[str] = Counter()
    sent = 0
    newly_seen = 0
    for job in jobs:
        status, score, reasons, concerns = classify(job)
        status_counts[status] += 1
        if status == "reject":
            for concern in concerns:
                rejection_reasons[concern] += 1
            continue
        if status == "review" and not settings.notify_review_candidates:
            # Persist review candidates, but don't alert unless the option is enabled.
            upsert_job(job, status, score, reasons, concerns)
            continue
        is_new, should_notify = upsert_job(job, status, score, reasons, concerns)
        newly_seen += int(is_new)
        if should_notify and send_message(format_message(job, status, score, reasons, concerns)):
            mark_notified(job)
            sent += 1
    return {
        "seen_after_cross_source_dedup": len(jobs),
        "newly_stored": newly_seen,
        "confirmed_matches": status_counts["match"],
        "review_candidates": status_counts["review"],
        "rejected": status_counts["reject"],
        "telegram_messages_sent": sent,
        "source_counts": source_counts,
        "source_errors": source_errors,
        "top_rejection_reasons": rejection_reasons.most_common(12),
        "telegram_configured": bool(settings.telegram_bot_token and settings.telegram_chat_id),
    }
