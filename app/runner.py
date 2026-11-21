from __future__ import annotations

from collections import Counter
from html import escape
import json
import os
from pathlib import Path

from app.config import settings
from app.matching import classify, is_relevant_title
from app.models import Job
from app.urls import canonical_job_url
from app.application_queue import enqueue_application
from app.ats_resolver import classify_apply_path, resolve_job_to_ats
from app.funnel import FunnelTracker
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


def fetch_all(*, public_only: bool = False) -> tuple[list[Job], dict[str, int], list[dict[str, str]]]:
    all_jobs: list[Job] = []
    source_counts: dict[str, int] = {}
    source_errors: list[dict[str, str]] = []

    for name, fetch in enabled_sources():
        if public_only and name in {"email_alerts", "google_jobs"}:
            continue
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


def _manual_apply_digest_message(
    manual_cards: list[tuple[Job, int]],
    total_cards: int,
) -> str:
    """Build a 1-tap manual apply digest for high-scoring login-gated job boards."""
    try:
        from app.application_automation import _select_cv_for_job
    except Exception:
        _select_cv_for_job = lambda _item: None

    def safe(value: object, limit: int = 160) -> str:
        return escape(str(value or "")[:limit], quote=True)

    shown = manual_cards[:8]
    lines = [
        "📲 <b>Job Hunter — 1-Tap Manual Apply Cards (LinkedIn / Wuzzuf / Indeed / Glassdoor)</b>",
        "These roles matched your profile on login-gated boards (no external public ATS found):",
    ]
    for idx, (job, score) in enumerate(shown, 1):
        cv_path = _select_cv_for_job({"title": job.title, "company": job.company, "description": job.description})
        cv_name = cv_path.name if cv_path else "Mohamed_Ahmed-FullStack.pdf"
        board = job.source.replace("_alert", "").capitalize()
        lines.extend([
            "",
            f"<b>{idx}. {safe(job.title, 120)} — {safe(job.company, 80)}</b>",
            f"Score: {score}/100 | 📍 {safe(job.location, 80)} | 📄 CV: <code>{safe(cv_name, 80)}</code>",
            f'🔗 <a href="{safe(job.url, 500)}">Tap to Apply on {safe(board, 30)}</a>',
        ])
    if total_cards > len(shown):
        lines.extend(["", f"<i>+{total_cards - len(shown)} more manual-apply cards saved in database.</i>"])
    lines.extend([
        "",
        "<b>Quick-copy links:</b>",
        "• Portfolio: <code>https://mohamed-ahmed-five.vercel.app/</code>",
        "• GitHub: <code>https://github.com/hazalkoom</code>",
        "• LinkedIn: <code>https://www.linkedin.com/in/mohamed-ahmed-mahmoud-766912268/</code>",
    ])
    return "\n".join(lines)[:3900]


def _extract_skills_summary(reasons: list[str]) -> str:
    """Return the matched-skills clause from classifier reasons, if available."""
    for reason in reasons or []:
        text = str(reason or "").strip()
        if text.lower().startswith("relevant skills:"):
            return text.split(":", 1)[1].strip()
    return ""


def _autopilot_job_cards_message(
    cards: list[tuple[Job, int, list[str], str]],
    total_cards: int,
) -> str:
    """Build a clean, high-signal 1-tap Telegram job cards digest for 65+ matches."""
    try:
        from app.application_automation import _select_cv_for_job
    except Exception:
        _select_cv_for_job = lambda _item: None

    def safe(value: object, limit: int = 160) -> str:
        return escape(str(value or "")[:limit], quote=True)

    header = [
        "🎯 <b>Job Hunter — Top Matching Jobs to Apply (Score 65+)</b>",
        "Auto-submit skipped or unavailable for these roles — tap to apply manually:",
    ]
    footer = [
        "",
        "<b>Quick-copy links:</b>",
        "• Portfolio: <code>https://mohamed-ahmed-five.vercel.app/</code>",
        "• GitHub: <code>https://github.com/hazalkoom</code>",
        "• LinkedIn: <code>https://www.linkedin.com/in/mohamed-ahmed-mahmoud-766912268/</code>",
    ]
    footer_len = len("\n".join(footer)) + 80

    shown = cards[:15]
    card_blocks: list[str] = []
    used_len = len("\n".join(header))
    for idx, (job, score, reasons, _apply_path) in enumerate(shown, 1):
        cv_path = _select_cv_for_job({"title": job.title, "company": job.company, "description": job.description})
        cv_name = cv_path.name if cv_path else "Mohamed_Ahmed-FullStack.pdf"
        source_label = (job.source or "listing").replace("_alert", "").replace("_", " ").title()
        skills_text = _extract_skills_summary(reasons)
        block_lines = [
            "",
            f"<b>{idx}. {safe(job.title, 120)} — {safe(job.company, 80)}</b>",
            f"⭐ Score: <b>{score}/100</b> | 📍 {safe(job.location or 'Remote', 80)} | 📄 CV: <code>{safe(cv_name, 80)}</code>",
        ]
        if skills_text:
            block_lines.append(f"🛠 {safe(skills_text, 140)}")
        block_lines.append(f'🔗 <a href="{safe(job.url, 500)}">Tap to Apply ({safe(source_label, 40)})</a>')
        block = "\n".join(block_lines)
        if card_blocks and used_len + len(block) + footer_len > 3900:
            break
        card_blocks.append(block)
        used_len += len(block) + 1

    lines = header + card_blocks
    remaining = max(0, total_cards - len(card_blocks))
    if remaining:
        lines.extend(["", f"<i>+{remaining} more matching jobs saved in database.</i>"])
    lines.extend(footer)
    return "\n".join(lines)[:3950]


def run_once(*, send_notifications: bool = True, apply: bool = True,
             public_only: bool = False, persist_report: bool = True) -> dict:
    init_db()
    jobs, source_counts, source_errors = fetch_all(public_only=True) if public_only else fetch_all()

    rejection_reasons: Counter[str] = Counter()
    status_counts: Counter[str] = Counter()
    funnel = FunnelTracker(fetched_total=sum(source_counts.values()), deduped_total=len(jobs))
    job_alerts_sent = 0
    review_alerts_sent = 0
    newly_seen = 0
    ats_resolved_count = 0
    notification_candidate_found = False
    review_candidates: list[tuple[Job, int, list[str], list[str]]] = []
    manual_apply_cards: list[tuple[Job, int]] = []
    candidate_cards: dict[str, tuple[Job, int, list[str], str]] = {}
    source_effectiveness: dict[str, Counter[str]] = {}

    autonomous_applications = bool(getattr(settings, "auto_apply_enabled", False))
    resolver_options = {"persist_discovered": False} if not apply else {}
    card_min_score = int(getattr(settings, "auto_apply_card_min_score", 65))

    for raw_job in jobs:
        job = raw_job
        if job.source.endswith("_alert") and is_relevant_title(job.title):
            try:
                resolved = resolve_job_to_ats(job, **resolver_options)
                if resolved.url != job.url:
                    ats_resolved_count += 1
                    job = resolved
            except Exception:
                pass

        if is_relevant_title(job.title):
            funnel.record_stage("title_ok", source=job.source)
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
            funnel.record_classification(job.source, status, concerns)
            continue

        apply_path = classify_apply_path(job.url, job.source)
        if apply_path in {"aggregator_redirect", "login_gated"}:
            try:
                resolved = resolve_job_to_ats(job, score=score, **resolver_options)
                if resolved.url != job.url:
                    ats_resolved_count += 1
                    job = resolved
                    apply_path = classify_apply_path(job.url, job.source)
            except Exception:
                pass

        funnel.record_classification(job.source, status, concerns)
        funnel.record_apply_path(job.source, apply_path, resolved=(job.url != raw_job.url))

        is_login_gated_alert = job.source.endswith("_alert") or apply_path == "login_gated"

        if status == "review" and (not settings.notify_review_candidates or autonomous_applications or not send_notifications):
            is_new, _ = upsert_job(job, status, score, reasons, concerns)
            if autonomous_applications and is_new and score >= card_min_score:
                candidate_cards[_canonical_url(job.url) or job.url] = (job, score, reasons, apply_path)
            if autonomous_applications and is_login_gated_alert:
                if is_new and score >= int(getattr(settings, "auto_apply_min_score", 60)):
                    manual_apply_cards.append((job, score))
            else:
                enqueue_application(job, status, score, reasons, concerns, **({"original_url": raw_job.url} if job.url != raw_job.url else {}))
            newly_seen += int(is_new)
            metrics["newly_stored"] += int(is_new)
            continue

        is_new, should_notify = upsert_job(job, status, score, reasons, concerns)
        if autonomous_applications and is_new and score >= card_min_score:
            candidate_cards[_canonical_url(job.url) or job.url] = (job, score, reasons, apply_path)
        if autonomous_applications and is_login_gated_alert:
            if is_new and score >= int(getattr(settings, "auto_apply_min_score", 60)):
                manual_apply_cards.append((job, score))
        else:
            enqueue_application(job, status, score, reasons, concerns, **({"original_url": raw_job.url} if job.url != raw_job.url else {}))
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
    inbox_reconciliation = None
    auto_apply_message_sent = False
    manual_digest_sent = False
    final_cards_count = len(manual_apply_cards)
    if autonomous_applications and apply:
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
        try:
            from app.sources.application_inbox import fetch_and_reconcile_inbox
            inbox_reconciliation = fetch_and_reconcile_inbox(lookback_days=7)
        except Exception:
            inbox_reconciliation = {"confirmed_queue_ids": [], "confirmations": [], "interviews": [], "rejections": []}

        funnel.ingest_auto_apply_report(auto_apply_report)
        email_confirmed_ids = (inbox_reconciliation or {}).get("confirmed_queue_ids") or []
        funnel.record_stage("email_confirmed", count=len(email_confirmed_ids))
        results = (auto_apply_report or {}).get("results", []) or []
        submitted_items = [r for r in results if str(r.get("outcome") or "").lower() == "submitted"]
        submitted_urls = {
            _canonical_url(str(r.get("url") or ""))
            for r in submitted_items
            if r.get("url")
        }
        submitted_keys = {
            (str(r.get("title") or "").strip().casefold(), str(r.get("company") or "").strip().casefold())
            for r in submitted_items
            if r.get("title")
        }

        for r in results:
            if str(r.get("outcome") or "").lower() == "submitted":
                continue
            r_url = str(r.get("url") or "").strip()
            r_score = int(r.get("score") or 0)
            if not r_url or r_score < card_min_score:
                continue
            c_url = _canonical_url(r_url) or r_url
            if c_url not in candidate_cards:
                candidate_cards[c_url] = (
                    Job(
                        source=str(r.get("source") or "autopilot"),
                        source_id=c_url,
                        title=str(r.get("title") or "Untitled Role"),
                        company=str(r.get("company") or "Unknown Company"),
                        location=str(r.get("location") or "Remote"),
                        url=r_url,
                        description="",
                    ),
                    r_score,
                    [],
                    str(r.get("ats_host") or "direct"),
                )

        remaining_cards: list[tuple[Job, int, list[str], str]] = []
        for c_url, card in candidate_cards.items():
            job_obj, _sc, _rs, _ap = card
            title_company_key = (job_obj.title.strip().casefold(), job_obj.company.strip().casefold())
            if c_url in submitted_urls or title_company_key in submitted_keys:
                continue
            remaining_cards.append(card)
        remaining_cards.sort(key=lambda item: (item[1], item[0].posted_at or ""), reverse=True)
        final_cards_count = len(remaining_cards)

        if send_notifications and telegram_configured:
            submitted = int((auto_apply_report or {}).get("submitted", 0)) + len(email_confirmed_ids)
            lines = [
                "<b>Job Hunter — Autopilot Summary</b>",
                f"✅ Applications auto-submitted: <b>{submitted}</b>"
                + (f" (including {len(email_confirmed_ids)} confirmed via Gmail inbox)" if email_confirmed_ids else ""),
                f"📬 Manual job cards ready (65+ score): <b>{final_cards_count}</b>",
            ]
            if (auto_apply_report or {}).get("error"):
                lines.append("⚠️ Note: " + escape(str(auto_apply_report["error"])[:300]))
            elif (auto_apply_report or {}).get("reason") and submitted == 0 and final_cards_count == 0:
                lines.append(escape(str(auto_apply_report["reason"])[:300]))

            for result in submitted_items[:10]:
                title = escape(str(result.get("title") or "Untitled")[:90])
                company = escape(str(result.get("company") or "")[:50])
                url = result.get("url")
                cv_used = result.get("cv_used")
                company_str = f" ({company})" if company else ""
                cv_str = f" [CV: {escape(str(cv_used))}]" if cv_used else ""
                if url:
                    lines.append(f"✅ <a href=\"{escape(str(url), quote=True)}\">{title}</a>{company_str}{cv_str}")
                else:
                    lines.append(f"✅ {title}{company_str}{cv_str}")

            auto_apply_message_sent = send_message("\n".join(lines)[:3900])

            if remaining_cards:
                manual_digest_sent = send_message(
                    _autopilot_job_cards_message(remaining_cards, final_cards_count)
                )

    report = {
        "seen_after_cross_source_dedup": len(jobs),
        "newly_stored": newly_seen,
        "ats_resolved": ats_resolved_count,
        "manual_apply_cards": final_cards_count,
        "confirmed_matches": status_counts["match"],
        "review_candidates": status_counts["review"],
        "rejected": status_counts["reject"],
        "telegram_messages_sent": (
            job_alerts_sent + int(review_digest_sent) + int(status_message_sent) + int(auto_apply_message_sent) + int(manual_digest_sent)
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
        "funnel": funnel.to_dict(),
        "inbox_reconciliation": inbox_reconciliation,
        "auto_apply_summary_message_sent": auto_apply_message_sent,
        "manual_apply_digest_sent": manual_digest_sent,
    }
    if not persist_report:
        return report
    # Keep a latest-run report even on local runs so the diagnostics collector can
    # explain both matcher rejections and application skips without parsing a long
    # journal dump. Persist only the redacted report, never profile answers.
    try:
        from app.automation_diagnostics import sanitize
        report_path = Path(os.getenv("AUTO_APPLY_REPORT_PATH", "logs/latest_run_report.json")).expanduser()
        if not report_path.is_absolute():
            report_path = Path(__file__).resolve().parent.parent / report_path
        report_path.parent.mkdir(parents=True, exist_ok=True)
        safe_report = sanitize(report)
        encoded = (json.dumps(safe_report, ensure_ascii=False, indent=2, default=str) + "\n").encode("utf-8")
        fd = os.open(report_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            os.write(fd, encoded)
            os.fchmod(fd, 0o600)
        finally:
            os.close(fd)
    except Exception:
        # Diagnostics must never interrupt job collection or applications.
        pass
    return report
