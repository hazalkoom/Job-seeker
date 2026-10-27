from __future__ import annotations

from collections import Counter
from html import escape

from app.config import settings
from app.matching import classify
from app.models import Job
from app.urls import canonical_job_url
from app.application_queue import enqueue_application
from app.sources import enabled_sources
from app.storage import init_db, mark_notified, upsert_job
from app.telegram import format_message, send_message


def _canonical_url(value: str) -> str:
    """Compatibility wrapper; URL canonicalization is shared with the queue."""
    return canonical_job_url(value)


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


def run_once(*, send_notifications: bool = True) -> dict:
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

    autonomous_applications = bool(getattr(settings, "auto_apply_enabled", False))

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

        if status == "review" and (not settings.notify_review_candidates or autonomous_applications or not send_notifications):
            is_new, _ = upsert_job(job, status, score, reasons, concerns)
            enqueue_application(job, status, score, reasons, concerns)
            newly_seen += int(is_new)
            metrics["newly_stored"] += int(is_new)
            continue

        is_new, should_notify = upsert_job(job, status, score, reasons, concerns)
        enqueue_application(job, status, score, reasons, concerns)
        newly_seen += int(is_new)
        metrics["newly_stored"] += int(is_new)
        if not should_notify:
            continue

        notification_candidate_found = True
        if autonomous_applications or not send_notifications:
            # In autopilot mode, application outcomes are reported as one summary
            # after the application worker runs, not as a stream of job alerts.
            continue
        if status == "review":
            review_candidates.append((job, score, reasons, concerns))
            continue

        if send_notifications and send_message(format_message(job, status, score, reasons, concerns)):
            mark_notified(job)
            job_alerts_sent += 1

    review_digest_sent = False
    if review_candidates and not autonomous_applications and send_notifications:
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
    if send_notifications and not autonomous_applications and not notification_candidate_found and telegram_configured:
        status_message_sent = send_message(
            _status_message(status_counts["review"], source_errors)
        )

    auto_apply_report = None
    auto_apply_message_sent = False
    if autonomous_applications:
        try:
            from app.application_automation import run_auto_apply
            auto_apply_report = run_auto_apply()
        except Exception as exc:
            auto_apply_report = {
                "enabled": True, "processed": 0, "submitted": 0,
                "skipped": 0, "failed": 1,
                "error": f"{type(exc).__name__}: {str(exc)[:240]}",
                "results": [],
            }
        if send_notifications and telegram_configured:
            from html import escape as _html_escape
            submitted = int((auto_apply_report or {}).get("submitted", 0))
            skipped = int((auto_apply_report or {}).get("skipped", 0))
            failed = int((auto_apply_report or {}).get("failed", 0))
            lines = [
                "<b>Job Hunter — automatic application cycle</b>",
                f"Applications confirmed submitted: <b>{submitted}</b>",
                f"Automatically skipped: {skipped}",
                f"Submission errors/uncertain outcomes: {failed}",
            ]
            if (auto_apply_report or {}).get("error"):
                lines.append("Setup/policy error: " + _html_escape(str(auto_apply_report["error"])[:350]))
            elif (auto_apply_report or {}).get("reason"):
                lines.append(_html_escape(str(auto_apply_report["reason"])[:350]))
            for result in (auto_apply_report or {}).get("results", [])[:5]:
                lines.append(
                    f"• {_html_escape(str(result.get('title') or 'Untitled')[:90])} — "
                    f"{_html_escape(str(result.get('outcome') or 'unknown'))}"
                )
            lines.append("Only supported public forms with known answers are submitted; CAPTCHAs, unknown required answers, and unverified eligibility are skipped.")
            auto_apply_message_sent = send_message("\n".join(lines)[:3900])

    return {
        "seen_after_cross_source_dedup": len(jobs),
        "newly_stored": newly_seen,
        "confirmed_matches": status_counts["match"],
        "review_candidates": status_counts["review"],
        "rejected": status_counts["reject"],
        "telegram_messages_sent": (
            job_alerts_sent + int(review_digest_sent) + int(status_message_sent) + int(auto_apply_message_sent)
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
        "auto_apply": auto_apply_report,
        "auto_apply_summary_message_sent": auto_apply_message_sent,
    }
