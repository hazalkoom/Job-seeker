"""Persistent application ledger for review and optional autonomous submission."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from urllib.parse import urlsplit

from app.config import settings
from app.application_profile import (
    ProfileLoadError,
    load_profile_bundle,
    resolve_answer,
)
from app.models import Job
from app.storage import _connect, init_db
from app.urls import ats_posting_key, canonical_job_url

QUEUE_STATUSES = (
    "pending_review",
    "approved",
    "ready",
    "applying",
    "submitted",
    "rejected",
    "withdrawn",
    "auto_skipped",
    "failed",
)
TERMINAL_STATUSES = {"submitted", "rejected", "withdrawn", "auto_skipped", "failed"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_list(value: object) -> list:
    try:
        data = json.loads(str(value or "[]"))
    except (TypeError, json.JSONDecodeError):
        return []
    return data if isinstance(data, list) else []


def _event(
    conn: sqlite3.Connection,
    queue_id: int,
    event_type: str,
    details: dict | None = None,
) -> None:
    conn.execute(
        "INSERT INTO application_events(queue_id,event_type,details,created_at) "
        "VALUES(?,?,?,?)",
        (
            queue_id,
            event_type,
            json.dumps(details or {}, ensure_ascii=False, sort_keys=True),
            _now(),
        ),
    )


def _row_to_dict(row: sqlite3.Row | dict) -> dict:
    item = dict(row)
    for key in (
        "reasons",
        "concerns",
        "preflight_blockers",
        "preflight_warnings",
    ):
        if key in item:
            item[key] = _json_list(item[key])
    return item


def enqueue_application(
    job: Job,
    qualification_status: str,
    score: int,
    reasons: list[str],
    concerns: list[str],
    *,
    original_url: str = "",
) -> int | None:
    """Add a qualified/review listing once, deduplicated by canonical URL.

    Call after ``upsert_job``. Repeated sightings update the existing queue
    record rather than resetting a human decision or creating a second entry.
    Returns the persistent queue ID, or None when the database job/URL is absent.
    """
    if qualification_status not in {"match", "review"}:
        return None
    canonical_url = canonical_job_url(job.url)
    parsed = urlsplit(canonical_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None

    now = _now()
    with _connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        job_row = conn.execute(
            "SELECT id FROM jobs WHERE source=? AND source_id=?",
            (job.source, job.source_id),
        ).fetchone()
        if job_row is None:
            return None
        job_id = int(job_row["id"])
        posting_key = ats_posting_key(canonical_url)
        if posting_key and original_url and canonical_job_url(original_url) != canonical_url:
            conn.execute(
                "UPDATE application_queue SET posting_key=? WHERE canonical_url=? AND posting_key=''",
                (posting_key, canonical_job_url(original_url)),
            )
        existing = conn.execute(
            "SELECT id, status, qualification_status FROM application_queue "
            "WHERE canonical_url=? OR (?<>'' AND posting_key=?) "
            "ORDER BY CASE WHEN canonical_url=? THEN 0 ELSE 1 END, id LIMIT 1",
            (canonical_url, posting_key, posting_key, canonical_url),
        ).fetchone()
        # A verified employer URL can replace an aggregator URL once before any submit attempt.
        if existing and original_url and posting_key and existing["status"] == "auto_skipped":
            old = conn.execute(
                "SELECT canonical_url FROM application_queue WHERE id=?", (existing["id"],)
            ).fetchone()
            if old["canonical_url"] != canonical_url and not conn.execute("""
                SELECT 1 FROM application_events WHERE queue_id=? AND (
                    event_type IN ('application_attempt_started','application_link_recovered') OR
                    (event_type='application_auto_skipped' AND
                     json_extract(details,'$.reason_code') IN ('captcha_or_antibot','manual_verification_required'))
                )
            """, (existing["id"],)).fetchone():
                blocked = conn.execute("""
                    SELECT 1 FROM application_queue WHERE id=? AND (
                        notes LIKE 'No supported%application form%' OR
                        notes LIKE 'No supported public ATS%' OR notes LIKE '%HTTP 403%'
                    )
                """, (existing["id"],)).fetchone()
                if blocked:
                    conn.execute("""
                        UPDATE application_queue SET job_id=?, canonical_url=?, status='pending_review',
                            qualification_status=?, score=?, reasons=?, concerns=?, preflight_status='not_run',
                            preflight_blockers='[]', preflight_warnings='[]', updated_at=? WHERE id=?
                    """, (job_id, canonical_url, qualification_status, score, json.dumps(reasons),
                          json.dumps(concerns), now, existing["id"]))
                    _event(conn, existing["id"], "application_link_recovered")
                    return int(existing["id"])
        if existing:
            queue_id = int(existing["id"])
            updates: tuple = (
                now,
                now,
                queue_id,
            )
            conn.execute(
                "UPDATE application_queue SET sightings_count=sightings_count+1, "
                "last_seen_at=?, updated_at=? WHERE id=?",
                updates,
            )
            if existing["status"] == "pending_review":
                conn.execute(
                    "UPDATE application_queue SET qualification_status=?, score=?, "
                    "reasons=?, concerns=?, updated_at=? WHERE id=?",
                    (
                        qualification_status,
                        int(score),
                        json.dumps(reasons, ensure_ascii=False),
                        json.dumps(concerns, ensure_ascii=False),
                        now,
                        queue_id,
                    ),
                )
            return queue_id

        cursor = conn.execute(
            """INSERT INTO application_queue(
                job_id, canonical_url, status, qualification_status, score,
                reasons, concerns, preflight_status, preflight_blockers,
                preflight_warnings, sightings_count, first_seen_at, last_seen_at,
                updated_at
            ) VALUES(?, ?, 'pending_review', ?, ?, ?, ?, 'not_run', '[]', '[]', 1, ?, ?, ?)""",
            (
                job_id,
                canonical_url,
                qualification_status,
                int(score),
                json.dumps(reasons, ensure_ascii=False),
                json.dumps(concerns, ensure_ascii=False),
                now,
                now,
                now,
            ),
        )
        queue_id = int(cursor.lastrowid)
        conn.execute("UPDATE application_queue SET posting_key=? WHERE id=?", (posting_key, queue_id))
        _event(
            conn,
            queue_id,
            "queued",
            {
                "source": job.source,
                "source_id": job.source_id,
                "qualification_status": qualification_status,
                "score": int(score),
            },
        )
        return queue_id


def list_applications(
    status: str | None = None,
    limit: int = 100,
) -> list[dict]:
    init_db()
    bounded_limit = max(1, min(int(limit), 500))
    query = (
        "SELECT q.*, j.title, j.company, j.location, j.url, j.source, j.source_id, "
        "j.posted_at, j.date_kind, j.description, j.remote, j.eligibility, "
        "j.description_quality, j.employment_type, j.workplace_type "
        "FROM application_queue q JOIN jobs j ON j.id=q.job_id "
    )
    params: list[object] = []
    if status:
        if status not in QUEUE_STATUSES:
            raise ValueError(f"Unsupported application status: {status}")
        query += "WHERE q.status=? "
        params.append(status)
    query += "ORDER BY CASE q.status WHEN 'pending_review' THEN 0 " \
             "WHEN 'approved' THEN 1 WHEN 'ready' THEN 2 ELSE 3 END, " \
             "q.updated_at DESC LIMIT ?"
    params.append(bounded_limit)
    with _connect() as conn:
        rows = conn.execute(query, params).fetchall()
    return [_row_to_dict(row) for row in rows]


def get_application(queue_id: int) -> dict | None:
    init_db()
    with _connect() as conn:
        row = conn.execute(
            "SELECT q.*, j.title, j.company, j.location, j.url, j.source, j.source_id, "
            "j.posted_at, j.date_kind, j.description, j.employment_type, j.workplace_type, "
            "j.remote, j.eligibility, j.description_quality "
            "FROM application_queue q JOIN jobs j ON j.id=q.job_id WHERE q.id=?",
            (int(queue_id),),
        ).fetchone()
    return _row_to_dict(row) if row else None


def application_events(queue_id: int) -> list[dict]:
    init_db()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, queue_id, event_type, details, created_at "
            "FROM application_events WHERE queue_id=? ORDER BY id",
            (int(queue_id),),
        ).fetchall()
    output = []
    for row in rows:
        item = dict(row)
        try:
            item["details"] = json.loads(item["details"] or "{}")
        except json.JSONDecodeError:
            item["details"] = {}
        output.append(item)
    return output


def decide_application(
    queue_id: int,
    decision: str,
    notes: str = "",
) -> dict:
    """Record an explicit human approval/rejection; does not submit anything."""
    decision = decision.strip().lower()
    if decision not in {"approve", "reject"}:
        raise ValueError("Decision must be 'approve' or 'reject'.")
    init_db()
    now = _now()
    with _connect() as conn:
        row = conn.execute(
            "SELECT id, status FROM application_queue WHERE id=?", (int(queue_id),)
        ).fetchone()
        if row is None:
            raise LookupError(f"Application queue item {queue_id} was not found.")
        old_status = row["status"]
        if old_status == "submitted":
            raise ValueError("A submitted application cannot be re-reviewed by this action.")
        if old_status == "withdrawn":
            raise ValueError("A withdrawn application cannot be re-reviewed by this action.")

        new_status = "approved" if decision == "approve" else "rejected"
        if old_status != new_status:
            conn.execute(
                "UPDATE application_queue SET status=?, reviewed_at=?, updated_at=?, "
                "notes=CASE WHEN ?='' THEN notes ELSE ? END, "
                "preflight_status='not_run', preflight_blockers='[]', "
                "preflight_warnings='[]' WHERE id=?",
                (
                    new_status,
                    now if decision == "approve" else None,
                    now,
                    notes.strip(),
                    notes.strip(),
                    int(queue_id),
                ),
            )
            _event(
                conn,
                int(queue_id),
                new_status,
                {"previous_status": old_status, "notes": notes.strip()},
            )
    return get_application(int(queue_id)) or {}


def run_preflight(
    queue_id: int,
    *,
    profile_path: str | None = None,
    answer_bank_path: str | None = None,
) -> dict:
    """Check local profile + job record and return whether a human can proceed."""
    item = get_application(int(queue_id))
    if item is None:
        raise LookupError(f"Application queue item {queue_id} was not found.")

    blockers: list[str] = []
    warnings: list[str] = []
    if item["status"] not in {"approved", "ready"}:
        blockers.append("Review and approve this listing before preparation.")
    if item["status"] in TERMINAL_STATUSES:
        blockers.append(f"Application is already in terminal state: {item['status']}.")

    parsed = urlsplit(str(item.get("url") or ""))
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        blockers.append("Job listing URL is missing or invalid.")
    if not str(item.get("title") or "").strip():
        blockers.append("Job title is missing.")
    if not str(item.get("company") or "").strip() or str(item.get("company")).casefold() == "unknown company":
        blockers.append("Company name is unknown; verify the listing manually.")

    if item.get("qualification_status") == "review":
        warnings.append(
            "This job was initially classified for review, not as a confirmed match; "
            "human approval does not change that original classification."
        )
    if not settings.auto_apply_enabled:
        warnings.append("Automatic submission is disabled in configuration.")

    try:
        if profile_path is None and answer_bank_path is None:
            bundle = load_profile_bundle()
        else:
            from app.application_profile import PROFILE_PATH, ANSWERS_PATH
            bundle = load_profile_bundle(
                profile_path or PROFILE_PATH,
                answer_bank_path or ANSWERS_PATH,
            )
        if bundle.issues:
            blockers.extend(f"Profile validation: {issue}" for issue in bundle.issues)
    except ProfileLoadError as exc:
        blockers.append(str(exc))

    passed = not blockers
    now = _now()
    with _connect() as conn:
        current = conn.execute(
            "SELECT status FROM application_queue WHERE id=?", (int(queue_id),)
        ).fetchone()
        if current is None:
            raise LookupError(f"Application queue item {queue_id} was not found.")
        status = current["status"]
        next_status = status
        ready_at = None
        if passed and status in {"approved", "ready"}:
            next_status = "ready"
            ready_at = now
        elif not passed and status == "ready":
            next_status = "approved"
        conn.execute(
            "UPDATE application_queue SET status=?, preflight_status=?, "
            "preflight_blockers=?, preflight_warnings=?, updated_at=?, "
            "ready_at=COALESCE(?, ready_at) WHERE id=?",
            (
                next_status,
                "passed" if passed else "failed",
                json.dumps(blockers, ensure_ascii=False),
                json.dumps(warnings, ensure_ascii=False),
                now,
                ready_at,
                int(queue_id),
            ),
        )
        _event(
            conn,
            int(queue_id),
            "preflight_passed" if passed else "preflight_failed",
            {"blockers": blockers, "warnings": warnings, "resulting_status": next_status},
        )
    return {
        "queue_id": int(queue_id),
        "passed": passed,
        "status": next_status,
        "blockers": blockers,
        "warnings": warnings,
        "auto_submit_allowed": bool(
            settings.auto_apply_enabled
            and passed
        ),
    }


def resolve_application_question(
    queue_id: int,
    question: str,
    *,
    profile_path: str | None = None,
    answer_bank_path: str | None = None,
    target_country: str | None = None,
    relevant_skills: list[str] | None = None,
):
    """Resolve one form question with the saved answer resolver without storing it."""
    item = get_application(int(queue_id))
    if item is None:
        raise LookupError(f"Application queue item {queue_id} was not found.")
    if item["status"] in TERMINAL_STATUSES:
        raise ValueError("Cannot resolve form answers for a submitted/rejected/withdrawn item.")

    from app.application_profile import PROFILE_PATH, ANSWERS_PATH
    bundle = load_profile_bundle(
        profile_path or PROFILE_PATH,
        answer_bank_path or ANSWERS_PATH,
    )
    if bundle.issues:
        raise ProfileLoadError("Profile validation failed: " + "; ".join(bundle.issues))

    result = resolve_answer(
        question,
        bundle.profile,
        bundle.answer_bank,
        target_country=target_country,
        company=str(item.get("company") or ""),
        job_title=str(item.get("title") or ""),
        relevant_skills=relevant_skills,
    )
    # Audit only the resolver outcome. Never persist the answer itself, which may
    # include personal contact information or draft application text.
    with _connect() as conn:
        _event(
            conn,
            int(queue_id),
            "answer_resolved",
            {"category": result.category, "status": result.status, "source": result.source},
        )
    return result


def _has_attempt_history(conn: sqlite3.Connection, queue_id: int, *, reservation: str = "") -> bool:
    return bool(conn.execute("""
        SELECT 1 FROM application_queue AS current
        JOIN application_queue AS related ON related.id=current.id
            OR (current.posting_key<>'' AND related.posting_key=current.posting_key)
        LEFT JOIN application_events AS history ON history.queue_id=related.id
        WHERE current.id=? AND (
            related.status IN ('submitted','applying') OR
            history.event_type='application_attempt_started' OR
            (history.event_type='workflow_submit_reserved'
             AND NOT (related.id=current.id AND json_extract(history.details,'$.run_id')=?))
        ) LIMIT 1
    """, (queue_id, reservation)).fetchone())


def has_attempt_history(queue_id: int, *, reservation: str = "") -> bool:
    with _connect() as conn:
        return _has_attempt_history(conn, queue_id, reservation=reservation)


def begin_automation_attempt(queue_id: int, *, reservation: str = "") -> bool:
    """Atomically reserve an item before clicking Submit to prevent duplicates."""
    init_db()
    now = _now()
    with _connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        if _has_attempt_history(conn, queue_id, reservation=reservation):
            return False
        cursor = conn.execute(
            "UPDATE application_queue SET status='applying', updated_at=? "
            "WHERE id=? AND status='ready' AND submitted_at IS NULL",
            (now, int(queue_id)),
        )
        if cursor.rowcount != 1:
            return False
        _event(conn, int(queue_id), "application_attempt_started", {"idempotency": "queue status reserved before submit"})
    return True


def recover_interrupted_attempts(max_age_minutes: int = 90) -> int:
    """Mark stale in-flight attempts uncertain, never re-submit them automatically."""
    init_db()
    from datetime import timedelta
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=max(1, int(max_age_minutes)))).isoformat()
    now = _now()
    count = 0
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id FROM application_queue WHERE status='applying' AND updated_at < ?",
            (cutoff,),
        ).fetchall()
        for row in rows:
            queue_id = int(row["id"])
            conn.execute(
                "UPDATE application_queue SET status='failed', updated_at=?, "
                "notes='Worker interrupted during submission; outcome uncertain, not automatically retried.' WHERE id=? AND status='applying'",
                (now, queue_id),
            )
            _event(conn, queue_id, "application_attempt_interrupted", {"retry": False, "reason": "Submission state is uncertain; prevented duplicate application."})
            count += 1
    return count


def automatic_approve_application(queue_id: int, notes: str = "") -> dict:
    """Approve a queue item via configured policy and audit it as automation."""
    init_db()
    now = _now()
    with _connect() as conn:
        row = conn.execute(
            "SELECT status FROM application_queue WHERE id=?", (int(queue_id),)
        ).fetchone()
        if row is None:
            raise LookupError(f"Application queue item {queue_id} was not found.")
        if row["status"] in TERMINAL_STATUSES:
            raise ValueError(f"Cannot automatically approve terminal item: {row['status']}.")
        if row["status"] == "pending_review":
            conn.execute(
                "UPDATE application_queue SET status='approved', reviewed_at=?, updated_at=?, "
                "notes=CASE WHEN ?='' THEN notes ELSE ? END, "
                "preflight_status='not_run', preflight_blockers='[]', preflight_warnings='[]' WHERE id=?",
                (now, now, notes.strip(), notes.strip(), int(queue_id)),
            )
        _event(conn, int(queue_id), "auto_approved", {"notes": notes.strip(), "policy": "configured_autopilot"})
    return get_application(int(queue_id)) or {}


def record_automation_outcome(
    queue_id: int,
    outcome: str,
    *,
    reason: str = "",
    reference: str = "",
    details: dict | None = None,
) -> dict:
    """Persist an automated submission/skip/failure without storing form answers."""
    outcome = outcome.strip().lower()
    if outcome not in {"submitted", "auto_skipped", "failed"}:
        raise ValueError("Unsupported automation outcome.")
    init_db()
    now = _now()
    with _connect() as conn:
        row = conn.execute(
            "SELECT status FROM application_queue WHERE id=?", (int(queue_id),)
        ).fetchone()
        if row is None:
            raise LookupError(f"Application queue item {queue_id} was not found.")
        if row["status"] == "submitted":
            if outcome == "submitted":
                return get_application(int(queue_id)) or {}
            raise ValueError("A submitted application cannot be changed by automation.")
        conn.execute(
            "UPDATE application_queue SET status=?, submitted_at=CASE WHEN ?='submitted' THEN ? ELSE submitted_at END, "
            "submission_reference=CASE WHEN ?='submitted' THEN ? ELSE submission_reference END, "
            "notes=CASE WHEN ?='' THEN notes ELSE ? END, updated_at=? WHERE id=?",
            (outcome, outcome, now, outcome, reference.strip(), reason.strip(), reason.strip(), now, int(queue_id)),
        )
        event_details = dict(details or {})
        if reason:
            event_details["reason"] = reason[:500]
        if reference:
            event_details["reference"] = reference[:200]
        event_name = {
            "submitted": "application_submitted",
            "auto_skipped": "application_auto_skipped",
            "failed": "application_failed",
        }[outcome]
        _event(conn, int(queue_id), event_name, event_details)
    return get_application(int(queue_id)) or {}


def record_manual_submission(
    queue_id: int,
    *,
    reference: str = "",
    notes: str = "",
) -> dict:
    """Record a submission the user has already made elsewhere; never submits it."""
    init_db()
    now = _now()
    with _connect() as conn:
        row = conn.execute(
            "SELECT status, preflight_status FROM application_queue WHERE id=?",
            (int(queue_id),),
        ).fetchone()
        if row is None:
            raise LookupError(f"Application queue item {queue_id} was not found.")
        if row["status"] != "ready" or row["preflight_status"] != "passed":
            raise ValueError(
                "Only a preflight-passed, ready item can be marked submitted. "
                "Run preflight after approval first."
            )
        conn.execute(
            "UPDATE application_queue SET status='submitted', submitted_at=?, "
            "submission_reference=?, notes=CASE WHEN ?='' THEN notes ELSE ? END, "
            "updated_at=? WHERE id=?",
            (
                now,
                reference.strip(),
                notes.strip(),
                notes.strip(),
                now,
                int(queue_id),
            ),
        )
        _event(
            conn,
            int(queue_id),
            "manual_submission_recorded",
            {"reference": reference.strip(), "notes": notes.strip()},
        )
    return get_application(int(queue_id)) or {}


def company_submitted_count_last_30_days(company: str, *, days: int = 30) -> int:
    """Count confirmed submissions to the same employer within the last `days` days."""
    co = (company or "").strip().lower()
    if not co or co in {"unknown", "unknown company", "confidential"}:
        return 0
    init_db()
    from datetime import timedelta
    cutoff = (datetime.now(timezone.utc) - timedelta(days=int(days))).isoformat()
    with _connect() as conn:
        rows = conn.execute(
            """SELECT COUNT(*) AS n
               FROM application_queue q
               JOIN jobs j ON j.id = q.job_id
               WHERE q.status = 'submitted'
                 AND LOWER(TRIM(j.company)) = ?
                 AND COALESCE(q.submitted_at, q.updated_at) >= ?""",
            (co, cutoff),
        ).fetchone()
    return int(rows["n"] if rows else 0)


def prioritize_queue_items(items: list[dict]) -> list[dict]:
    """Order queue items so direct ATS forms run first and aggregators/login-gated boards run last."""
    from app.ats_resolver import classify_apply_path

    path_rank = {
        "direct_ats": 0,
        "custom_or_unknown": 1,
        "aggregator_redirect": 2,
        "login_gated": 3,
        "dead": 4,
    }
    return sorted(
        items,
        key=lambda item: (
            path_rank.get(classify_apply_path(str(item.get("url") or "")), 2),
            0 if str(item.get("description_quality") or "").lower() == "full" else 1,
            -int(item.get("score") or 0),
            -int(item.get("id") or 0),
        ),
    )
