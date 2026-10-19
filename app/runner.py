from __future__ import annotations

from collections import Counter
from html import escape
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from app.config import settings
from app.matching import classify
from app.models import Job
from app.sources import enabled_sources
from app.storage import init_db, mark_notified, upsert_job
from app.telegram import format_message, send_message


def _canonical_url(value: str) -> str:
    """Normalize common tracking parameters without dropping real job identifiers."""
    try:
        parsed = urlsplit(value.strip())
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
            return value.strip().lower()
        tracking = {"fbclid", "gclid", "mc_cid", "mc_eid", "ref", "source"}
        query = [
            (key, item) for key, item in parse_qsl(parsed.query, keep_blank_values=True)
            if not key.lower().startswith("utm_") and key.lower() not in tracking
        ]
        return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path.rstrip("/"), urlencode(query, doseq=True), ""))
    except (ValueError, TypeError):
        return value.strip().lower()


def _job_completeness(job: Job) -> tuple[int, int, int, int, int]:
    quality_rank = {"full": 3, "summary": 2, "metadata": 1, "unknown": 0}
    return (
        quality_rank.get(str(getattr(job, "description_quality", "unknown")).lower(), 0),
        min(len(job.description or ""), 5000),
        1 if job.date_kind == "posted" else 0,
        1 if job.eligibility else 0,
        1 if job.company and job.company.lower() != "unknown company" else 0,
    )


def fetch_all() -> tuple[list[Job], dict[str, int], list[dict[str, str]]]:
    all_jobs: list[Job] = []
    source_counts: dict[str, int] = {}
    source_errors: list[dict[str, str]] = []

    for name, fetch in enabled_sources():
        try:
            jobs = fetch()
            source_counts[name] = len(jobs)
            all_jobs.extend(jobs)
        except Exception as exc:
            # A failure in one source must not stop other sources.
            source_counts[name] = 0
            source_errors.append(
                {"source": name, "error": f"{type(exc).__name__}: {str(exc)[:250]}"}
            )

    # Deduplicate by canonical URL, retaining the version with the strongest
    # description/date/eligibility evidence rather than whichever API ran first.
    unique_by_url: dict[str, Job] = {}
    unique_by_key: dict[tuple[str, str], Job] = {}
    for job in all_jobs:
        url_key = _canonical_url(job.url)
        if not url_key:
            continue
        current = unique_by_url.get(url_key)
        if current is None or _job_completeness(job) > _job_completeness(current):
            unique_by_url[url_key] = job
    # Source+ID key is retained for clarity if two distinct URLs have same IDs.
    for job in unique_by_url.values():
        unique_by_key[(job.source, job.source_id)] = job
    return list(unique_by_key.values()), source_counts, source_errors


def _review_digest_message(
    candidates: list[tuple[Job, int, list[str], list[str]]],
    total_candidates: int,
) -> str:
    """Build one bounded Telegram message from review candidates."""
    shown = candidates[: max(1, min(15, int(getattr(settings, "review_digest_size", 5))))]
    lines = [
        "🔎 <b>Job Hunter — review shortlist</b>",
        "These jobs need a quick manual check before applying.",
    ]

    def safe(value: object, limit: int = 160) -> str:
        return escape(str(value or "")[:limit], quote=True)

    for index, (job, score, _reasons, concerns) in enumerate(shown, 1):
        lines.extend([
            "",
            f"<b>{index}. {safe(job.title, 150)} — {safe(job.company, 100)}</b>",
            f"Score: {score}/100 | 📍 {safe(job.location, 100)}",
            f"🗓 {safe(job.posted_at or 'Date unavailable', 50)} ({safe(job.date_kind, 20)})",
            f'🔗 <a href="{safe(job.url, 500)}">Open original listing</a>',
        ])
        if concerns:
            lines.append("Check: " + safe("; ".join(concerns[:2]), 220))
        lines.append("Source: " + safe(job.source, 60))

    remaining = max(0, total_candidates - len(shown))
    if remaining:
        lines.extend(["", f"{remaining} more review candidates remain queued for later runs."])
    lines.extend(["", "These are review candidates, not confirmed matches."])
    # The configured limit and bounded fields keep the message below Telegram's limit.
    return "\n".join(lines)


def _status_message(
    review_count: int,
    source_errors: list[dict[str, str]],
) -> str:
    if source_errors:
        lines = [
            "⚠️ <b>Job Hunter — run completed with source errors</b>",
            "No new job alerts were delivered in this run. Sources that succeeded were still processed.",
        ]
        failed_names = ", ".join(item["source"] for item in source_errors[:8])
        lines.append("Failed sources: " + escape(failed_names))
        if len(source_errors) > 8:
            lines.append(f"Plus {len(source_errors) - 8} additional source errors.")
    else:
        lines = [
            "✅ <b>Job Hunter — search complete</b>",
            "No new matching jobs needed notification on this run.",
        ]

    if review_count and not settings.notify_review_candidates:
        lines.append(
            f"🔎 Saved {review_count} review candidates, but review notifications are disabled. "
            "Set NOTIFY_REVIEW_CANDIDATES=true to receive a capped digest."
        )
    elif review_count:
        lines.append(f"🔎 Review candidates found: {review_count}.")
    return "\n".join(lines)


def run_once() -> dict:
    init_db()
    jobs, source_counts, source_errors = fetch_all()

    rejection_reasons: Counter[str] = Counter()
    status_counts: Counter[str] = Counter()
    job_alerts_sent = 0
    review_alerts_sent = 0
    newly_seen = 0
    notification_candidate_found = False
    review_candidates: list[tuple[Job, int, list[str], list[str]]] = []
    source_effectiveness: dict[str, Counter[str]] = {}

    for job in jobs:
        status, score, reasons, concerns = classify(job)
        status_counts[status] += 1
        metrics = source_effectiveness.setdefault(job.source, Counter())
        metrics["unique_jobs"] += 1
        metrics[status] += 1
        if job.description_quality == "full":
            metrics["full_descriptions"] += 1
        else:
            metrics[f"description_{job.description_quality or 'unknown'}"] += 1
        joined_evidence = " ".join(reasons + concerns).lower()
        if job.remote and "international remote eligibility mentions worldwide/egypt" in joined_evidence:
            metrics["remote_eligibility_confirmed"] += 1
        elif job.remote:
            metrics["remote_eligibility_uncertain"] += 1
        if "mandatory experience requirement exceeds target" in joined_evidence:
            metrics["experience_mismatch"] += 1
        if "posting date" in joined_evidence or "older than" in joined_evidence:
            metrics["freshness_mismatch"] += 1

        if status == "reject":
            for concern in concerns:
                rejection_reasons[concern] += 1
            continue

        if status == "review" and not settings.notify_review_candidates:
            is_new, _ = upsert_job(job, status, score, reasons, concerns)
            newly_seen += int(is_new)
            metrics["newly_stored"] += int(is_new)
            continue

        is_new, should_notify = upsert_job(job, status, score, reasons, concerns)
        newly_seen += int(is_new)
        metrics["newly_stored"] += int(is_new)
        if not should_notify:
            continue

        notification_candidate_found = True
        if status == "review":
            review_candidates.append((job, score, reasons, concerns))
            continue

        if send_message(format_message(job, status, score, reasons, concerns)):
            mark_notified(job)
            job_alerts_sent += 1

    review_digest_sent = False
    if review_candidates:
        review_candidates.sort(
            key=lambda item: (item[1], item[0].posted_at or ""), reverse=True
        )
        limit = max(1, min(15, int(getattr(settings, "review_digest_size", 5))))
        selected = review_candidates[:limit]
        if send_message(_review_digest_message(selected, len(review_candidates))):
            for job, _score, _reasons, _concerns in selected:
                mark_notified(job)
            review_alerts_sent = len(selected)
            review_digest_sent = True

    status_message_sent = False
    telegram_configured = bool(
        settings.telegram_bot_token and settings.telegram_chat_id
    )
    if not notification_candidate_found and telegram_configured:
        status_message_sent = send_message(
            _status_message(status_counts["review"], source_errors)
        )

    return {
        "seen_after_cross_source_dedup": len(jobs),
        "newly_stored": newly_seen,
        "confirmed_matches": status_counts["match"],
        "review_candidates": status_counts["review"],
        "rejected": status_counts["reject"],
        "telegram_messages_sent": (
            job_alerts_sent + int(review_digest_sent) + int(status_message_sent)
        ),
        "job_alerts_sent": job_alerts_sent,
        "review_alerts_sent": review_alerts_sent,
        "review_digest_message_sent": review_digest_sent,
        "telegram_status_message_sent": status_message_sent,
        "source_counts": source_counts,
        "source_effectiveness": {
            source: dict(values) for source, values in sorted(source_effectiveness.items())
        },
        "source_errors": source_errors,
        "top_rejection_reasons": rejection_reasons.most_common(12),
        "telegram_configured": telegram_configured,
    }
