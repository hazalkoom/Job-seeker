"""Human-reviewed referral tracking and personalized outreach drafts.

This module deliberately does not scrape professional networks or send messages.
Contacts are entered by the user, and all outreach remains a copy/edit/send action.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import quote_plus
from typing import Any

from app.config import settings
from app.storage import _connect, init_db

OUTREACH_STATUSES = {"draft", "contacted", "replied", "referred", "declined"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def add_contact(
    *, name: str, company: str, role: str = "", profile_url: str = "", notes: str = ""
) -> int:
    name, company = name.strip(), company.strip()
    profile_url = profile_url.strip()
    if not name or not company:
        raise ValueError("Contact name and company are required.")
    if profile_url and not profile_url.startswith(("https://", "http://")):
        raise ValueError("Profile URL must start with https:// or http://")
    init_db()
    with _connect() as conn:
        existing = conn.execute(
            "SELECT id FROM referral_contacts WHERE lower(name)=lower(?) AND lower(company)=lower(?)",
            (name, company),
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE referral_contacts SET role=?, profile_url=?, notes=? WHERE id=?",
                (role.strip(), profile_url, notes.strip(), existing["id"]),
            )
            return int(existing["id"])
        cursor = conn.execute(
            """INSERT INTO referral_contacts(name, company, role, profile_url, notes, added_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (name, company, role.strip(), profile_url, notes.strip(), _now().isoformat()),
        )
        return int(cursor.lastrowid)


def list_contacts(company: str = "") -> list[dict[str, Any]]:
    init_db()
    with _connect() as conn:
        if company.strip():
            rows = conn.execute(
                "SELECT * FROM referral_contacts WHERE lower(company)=lower(?) ORDER BY name",
                (company.strip(),),
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM referral_contacts ORDER BY lower(company), name").fetchall()
    return [dict(row) for row in rows]


def contact_search_links(company: str) -> dict[str, str]:
    """Return human-opened search links; does not scrape either destination."""
    name = company.strip()
    if not name:
        raise ValueError("Company is required.")
    query = f'"{name}" (software engineer OR engineering manager OR recruiter OR talent acquisition)'
    encoded = quote_plus(query)
    return {
        "linkedin_people_search": f"https://www.linkedin.com/search/results/people/?keywords={encoded}",
        "google_public_profiles": f"https://www.google.com/search?q={quote_plus('site:linkedin.com/in ' + query)}",
        "github_organization_members": f"https://github.com/search?q={quote_plus(name)}&type=users",
    }


def _decode_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    try:
        decoded = json.loads(str(value or "[]"))
    except (json.JSONDecodeError, TypeError):
        return []
    return [str(item) for item in decoded] if isinstance(decoded, list) else []


def build_referral_draft(job: dict[str, Any], contact: dict[str, Any]) -> str:
    """Build a personal, transparent referral request from stored job/contact data."""
    title = str(job.get("title") or "the role").strip()
    company = str(job.get("company") or contact.get("company") or "your company").strip()
    contact_name = str(contact.get("name") or "there").strip()
    role = str(contact.get("role") or "").strip()
    if contact.get("company") and company.lower() != str(contact["company"]).lower():
        raise ValueError("The contact's company doesn't match the job's company.")

    reasons = _decode_list(job.get("reasons"))
    skills: list[str] = []
    for reason in reasons:
        match = re.match(r"Relevant skills:\s*(.*)", reason, re.I)
        if match:
            skills = [part.strip() for part in match.group(1).split(",") if part.strip()]
            break
    summary = settings.candidate_summary.strip()
    lines = [
        f"Hi {contact_name.split()[0] if contact_name != 'there' else 'there'},",
        "",
        f"I came across the {title} opening at {company} and noticed your work there. "
        + (f"I saw you work as {role}; " if role else "")
        + "I wanted to ask whether you might be comfortable sharing advice or referring me for the role.",
        "",
        summary,
    ]
    if skills:
        lines.extend(["", "My relevant skills for this role include " + ", ".join(skills[:5]) + "."])
    elif job.get("description"):
        excerpt = re.sub(r"\s+", " ", str(job.get("description"))).strip()[:180]
        if excerpt:
            lines.extend(["", f"The role caught my eye because of its focus: {excerpt}…"])
    lines.extend(["", f"Job link: {job.get('url', '')}"])
    if settings.candidate_linkedin_url:
        lines.append(f"LinkedIn: {settings.candidate_linkedin_url}")
    if settings.candidate_portfolio_url:
        lines.append(f"Portfolio: {settings.candidate_portfolio_url}")
    if settings.candidate_cv_url:
        lines.append(f"CV: {settings.candidate_cv_url}")
    lines.extend([
        "",
        "If you think my background could be a fit and you're comfortable referring me, I'd really appreciate it. "
        "No worries at all if not — advice on the best way to apply would also help.",
        "",
        "Thanks for your time!",
        settings.candidate_display_name or "Best regards",
    ])
    return "\n".join(lines)


def create_outreach_draft(job_id: int, contact_id: int) -> tuple[int, str]:
    init_db()
    with _connect() as conn:
        job_row = conn.execute(
            "SELECT * FROM jobs WHERE id=? AND status IN ('match','review')", (job_id,)
        ).fetchone()
        contact_row = conn.execute(
            "SELECT * FROM referral_contacts WHERE id=?", (contact_id,)
        ).fetchone()
        if not job_row:
            raise ValueError("Job ID not found, or job is rejected. Use a stored match/review job ID.")
        if not contact_row:
            raise ValueError("Contact ID not found. Add the contact first.")
        job, contact = dict(job_row), dict(contact_row)
        if job["company"].strip().lower() != contact["company"].strip().lower():
            raise ValueError("The contact must work at the same company as the selected job.")
        draft = build_referral_draft(job, contact)
        existing = conn.execute(
            "SELECT id, status FROM referral_outreach WHERE job_id=? AND contact_id=?",
            (job_id, contact_id),
        ).fetchone()
        if existing:
            if existing["status"] != "draft":
                raise ValueError(f"Outreach already exists as status '{existing['status']}' (ID {existing['id']}).")
            conn.execute(
                "UPDATE referral_outreach SET message_draft=? WHERE id=?",
                (draft, existing["id"]),
            )
            return int(existing["id"]), draft
        cursor = conn.execute(
            """INSERT INTO referral_outreach(job_id, contact_id, status, message_draft, created_at)
               VALUES (?, ?, 'draft', ?, ?)""",
            (job_id, contact_id, draft, _now().isoformat()),
        )
        return int(cursor.lastrowid), draft


def update_outreach(
    outreach_id: int, status: str, *, followup_days: int = 5, notes: str = ""
) -> None:
    if status not in OUTREACH_STATUSES:
        raise ValueError(f"Status must be one of: {', '.join(sorted(OUTREACH_STATUSES))}")
    init_db()
    now = _now()
    contacted_at = now.isoformat() if status == "contacted" else ""
    followup_at = ""
    if status == "contacted":
        followup_at = (now + timedelta(days=max(1, min(60, followup_days)))).isoformat()
    with _connect() as conn:
        cursor = conn.execute(
            """UPDATE referral_outreach
               SET status=?, contacted_at=CASE WHEN ?='contacted' THEN ? ELSE contacted_at END,
                   next_followup_at=?, notes=CASE WHEN ?='' THEN notes ELSE ? END
               WHERE id=?""",
            (status, status, contacted_at, followup_at, notes.strip(), notes.strip(), outreach_id),
        )
        if cursor.rowcount == 0:
            raise ValueError(f"Outreach ID {outreach_id} was not found.")


def list_outreach(status: str = "") -> list[dict[str, Any]]:
    init_db()
    with _connect() as conn:
        if status:
            rows = conn.execute(
                """SELECT o.*, j.title, j.company, j.url, c.name AS contact_name,
                          c.role AS contact_role, c.profile_url
                   FROM referral_outreach o JOIN jobs j ON j.id=o.job_id
                   JOIN referral_contacts c ON c.id=o.contact_id
                   WHERE o.status=? ORDER BY o.created_at DESC""", (status,)
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT o.*, j.title, j.company, j.url, c.name AS contact_name,
                          c.role AS contact_role, c.profile_url
                   FROM referral_outreach o JOIN jobs j ON j.id=o.job_id
                   JOIN referral_contacts c ON c.id=o.contact_id
                   ORDER BY o.created_at DESC"""
            ).fetchall()
    return [dict(row) for row in rows]


def due_followups() -> list[dict[str, Any]]:
    init_db()
    now = _now().isoformat()
    with _connect() as conn:
        rows = conn.execute(
            """SELECT o.*, j.title, j.company, j.url, c.name AS contact_name,
                      c.role AS contact_role, c.profile_url
               FROM referral_outreach o JOIN jobs j ON j.id=o.job_id
               JOIN referral_contacts c ON c.id=o.contact_id
               WHERE o.status='contacted' AND o.next_followup_at!='' AND o.next_followup_at<=?
               ORDER BY o.next_followup_at""", (now,)
        ).fetchall()
    return [dict(row) for row in rows]
