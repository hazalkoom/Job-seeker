"""Read-only IMAP scanner for application confirmation, interview, and rejection emails.

When an ATS (Ashby, Greenhouse, Lever, Workable, Workday, or direct employer) sends a
confirmation email such as "Thanks for applying to Supabase", this module reconciles
any matching queue item that the browser marked as `failed` (submission_uncertain)
into `submitted`.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email import message_from_bytes
from typing import Any
import imaplib
import re

from app.application_queue import record_automation_outcome
from app.config import settings
from app.sources.common import clean_html
from app.sources.email_alerts import _body_parts, _decode_header, _email_datetime
from app.storage import _connect, init_db


@dataclass(frozen=True)
class ApplicationEmailEvent:
    kind: str  # "confirmed" | "interview" | "rejected"
    company: str
    title: str
    subject: str
    sender: str
    received_at: str
    message_id: str


_CONFIRM_SUBJECT_PATTERNS = (
    re.compile(r"thank(?:s|\s+you)\s+for\s+applying\s+(?:to|at|with)\s+([^\r\n!🚀|–—-]+)", re.I),
    re.compile(r"your\s+application\s+was\s+sent\s+to\s+([^\r\n!|–—-]+)", re.I),
    re.compile(r"application\s+received\s*(?:[-–—:|]\s*([^\r\n!]+))?", re.I),
    re.compile(r"we(?:'ve|\s+have)\s+got\s+your\s+application", re.I),
    re.compile(r"application\s+confirmation", re.I),
    re.compile(r"^indeed\s+application:\s*(.+)$", re.I),
)

_BODY_ROLE_COMPANY_PATTERNS = (
    re.compile(
        r"thank(?:s|\s+you)\s+(?:so\s+much\s+)?for\s+(?:applying|submitting\s+your\s+application)\s+"
        r"(?:for|to)\s+the\s+(?:position\s+of\s+)?(?P<title>[^.!?\r\n]{3,90}?)"
        r"(?:\s+(?:role|position))?(?:\s+(?:at|with)\s+(?P<company>[A-Z][A-Za-z0-9 .&-]{1,50}?))?[.!,\r\n]",
        re.I,
    ),
    re.compile(
        r"received\s+your\s+application\s+for\s+(?:the\s+)?(?P<title>[^.!?\r\n]{3,90}?)"
        r"(?:\s+(?:role|position))?\s+(?:at|with)\s+(?P<company>[A-Z][A-Za-z0-9 .&-]{1,50}?)[.!,\r\n]",
        re.I,
    ),
)

_REJECTION_MARKERS = re.compile(
    r"decided\s+not\s+to\s+move\s+forward|"
    r"move\s+forward\s+with\s+other\s+candidates|"
    r"unfortunately[, ]+we\s+will\s+not\s+be\s+proceeding|"
    r"not\s+been\s+selected\s+to\s+move\s+forward|"
    r"pursue\s+other\s+candidates",
    re.I,
)

_INTERVIEW_MARKERS = re.compile(
    r"invite\s+you\s+to\s+an?\s+interview|"
    r"schedule\s+an?\s+(?:interview|introductory\s+call|screening\s+call)|"
    r"like\s+to\s+schedule\s+a\s+time\s+to\s+speak|"
    r"next\s+step\s+in\s+our\s+interview\s+process",
    re.I,
)

_INCOMPLETE_MARKERS = re.compile(
    r"finish\s+your\s+application|your\s+application\s+isn['’]t\s+complete\s+yet|"
    r"complete\s+your\s+application",
    re.I,
)

_IGNORE_SENDERS = (
    "jobalerts-noreply@linkedin.com",
    "donotreply@jobalert.indeed.com",
    "noreply@glassdoor.com",
    "invitations@linkedin.com",
    "newsletters-noreply@linkedin.com",
    "messages-noreply@linkedin.com",
)


def _clean_company(raw: str) -> str:
    cleaned = re.sub(r"\s+Hiring\s+Team\b.*$", "", raw or "", flags=re.I)
    cleaned = re.sub(r"\s+Careers\b.*$", "", cleaned, flags=re.I)
    cleaned = re.sub(r"\s+Recruiting\b.*$", "", cleaned, flags=re.I)
    cleaned = re.sub(r"\s+Labs\b.*$", "", cleaned, flags=re.I)
    cleaned = re.sub(r"^.*?\bfrom\s+", "", cleaned, flags=re.I)
    return clean_html(cleaned).strip(" 🚀!|:-–—\"'")


def _company_from_sender(from_header: str) -> str:
    display = from_header.split("<", 1)[0].strip().strip("\"'")
    if display and display.lower() not in {"workable", "indeed apply", "linkedin", "greenhouse", "ashby", "lever"}:
        co = _clean_company(display)
        if co and len(co) >= 2:
            return co
    match = re.search(r"@([a-z0-9-]+)\.[a-z.]+", (from_header or "").lower())
    if match:
        domain_root = match.group(1)
        if domain_root not in {"ashbyhq", "workablemail", "greenhouse", "lever", "indeed", "linkedin", "myworkday", "gmail"}:
            return domain_root.capitalize()
    return ""


def parse_application_email(raw: bytes) -> ApplicationEmailEvent | None:
    """Parse a single raw RFC822 message into an ApplicationEmailEvent, or None if unrelated."""
    message = message_from_bytes(raw)
    from_header = _decode_header(message.get("From", "")).strip()
    from_low = from_header.lower()
    if any(ignored in from_low for ignored in _IGNORE_SENDERS):
        return None
    if "@wuzzuf.net" in from_low:
        return None

    subject = clean_html(_decode_header(message.get("Subject", "")))
    if not subject:
        return None

    plain, html = _body_parts(message)
    body = clean_html(plain or html)
    combined = f"{subject}\n{body}"

    if _INCOMPLETE_MARKERS.search(subject) or _INCOMPLETE_MARKERS.search(body[:300]):
        return None

    email_dt = _email_datetime(message)
    msg_id = (message.get("Message-ID") or "").strip() or f"{email_dt.isoformat()}:{subject[:40]}"

    company = ""
    title = ""

    body_match = None
    for pat in _BODY_ROLE_COMPANY_PATTERNS:
        body_match = pat.search(body)
        if body_match:
            title = clean_html(body_match.groupdict().get("title") or "").strip(" .,-")
            if body_match.groupdict().get("company"):
                company = _clean_company(body_match.group("company"))
            break

    for pat in _CONFIRM_SUBJECT_PATTERNS:
        m = pat.search(subject)
        if m:
            if pat.pattern.startswith("^indeed"):
                title = title or clean_html(m.group(1))
            elif m.lastindex and m.group(1):
                company = company or _clean_company(m.group(1))
            break

    if not company:
        company = _company_from_sender(from_header)

    if _REJECTION_MARKERS.search(combined):
        if not company and not title:
            return None
        return ApplicationEmailEvent(
            kind="rejected",
            company=company or "Unknown company",
            title=title,
            subject=subject,
            sender=from_header,
            received_at=email_dt.isoformat(),
            message_id=msg_id,
        )

    if _INTERVIEW_MARKERS.search(combined):
        if not company and not title:
            return None
        return ApplicationEmailEvent(
            kind="interview",
            company=company or "Unknown company",
            title=title,
            subject=subject,
            sender=from_header,
            received_at=email_dt.isoformat(),
            message_id=msg_id,
        )

    is_confirmation = any(pat.search(subject) for pat in _CONFIRM_SUBJECT_PATTERNS) or bool(
        re.search(
            r"thank(?:s|\s+you)\s+for\s+(?:applying|submitting\s+your\s+application)|"
            r"we\s+confirm\s+that\s+we\s+have\s+received\s+your\s+application|"
            r"your\s+application\s+is\s+complete",
            body[:600],
            re.I,
        )
    )
    if is_confirmation and (company or title):
        return ApplicationEmailEvent(
            kind="confirmed",
            company=company or "Unknown company",
            title=title,
            subject=subject,
            sender=from_header,
            received_at=email_dt.isoformat(),
            message_id=msg_id,
        )

    return None


def _norm_token(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (value or "").lower()).strip()


def reconcile_events_with_db(events: list[ApplicationEmailEvent]) -> dict[str, Any]:
    """Match parsed email events to `application_queue` rows and promote confirmed submissions."""
    init_db()
    confirmed_ids: list[int] = []
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT q.id, q.status, q.updated_at, j.title, j.company
            FROM application_queue q
            JOIN jobs j ON j.id = q.job_id
            ORDER BY q.updated_at DESC
            """
        ).fetchall()

    queue_items = [dict(r) for r in rows]
    used_queue_ids: set[int] = set()

    for ev in events:
        if ev.kind != "confirmed":
            continue
        ev_co = _norm_token(ev.company)
        ev_title = _norm_token(ev.title)
        if not ev_co or ev_co == "unknown company":
            continue

        candidates = []
        for item in queue_items:
            if item["id"] in used_queue_ids:
                continue
            item_co = _norm_token(item["company"])
            if not item_co:
                continue
            if ev_co in item_co or item_co in ev_co:
                candidates.append(item)

        if not candidates:
            continue

        chosen = None
        if ev_title:
            for item in candidates:
                item_title = _norm_token(item["title"])
                if ev_title in item_title or item_title in ev_title:
                    chosen = item
                    break

        if chosen is None:
            # Prefer an item that was attempted (`failed` / `applying` / `ready`) before `submitted`
            for preferred_status in ("failed", "applying", "ready", "approved", "pending_review"):
                for item in candidates:
                    if item["status"] == preferred_status:
                        chosen = item
                        break
                if chosen:
                    break

        if chosen and chosen["status"] != "submitted":
            qid = int(chosen["id"])
            record_automation_outcome(
                qid,
                "submitted",
                reason=f"Confirmed by email: {ev.subject[:140]}",
                reference=ev.message_id[:120],
            )
            used_queue_ids.add(qid)
            confirmed_ids.append(qid)
            chosen["status"] = "submitted"

    return {
        "confirmed_queue_ids": confirmed_ids,
        "confirmations": [e.__dict__ for e in events if e.kind == "confirmed"],
        "interviews": [e.__dict__ for e in events if e.kind == "interview"],
        "rejections": [e.__dict__ for e in events if e.kind == "rejected"],
    }


def fetch_and_reconcile_inbox(lookback_days: int = 7) -> dict[str, Any]:
    """Connect to IMAP read-only, scan recent application emails, and reconcile queue statuses."""
    required = (
        settings.email_alerts_imap_host,
        settings.email_alerts_username,
        settings.email_alerts_password,
    )
    if not all(required):
        return {"confirmed_queue_ids": [], "confirmations": [], "interviews": [], "rejections": []}

    since = (datetime.now(timezone.utc) - timedelta(days=max(1, lookback_days))).strftime("%d-%b-%Y")
    mailbox = settings.email_alerts_mailbox or "INBOX"
    events: list[ApplicationEmailEvent] = []

    client = imaplib.IMAP4_SSL(settings.email_alerts_imap_host, settings.email_alerts_imap_port)
    try:
        client.login(settings.email_alerts_username, settings.email_alerts_password)
        status, _ = client.select(mailbox, readonly=True)
        if status != "OK":
            return {"confirmed_queue_ids": [], "confirmations": [], "interviews": [], "rejections": []}

        selected_ids: set[bytes] = set()
        for keyword in ("applying", "application", "interview"):
            st, data = client.search(None, f'(SUBJECT "{keyword}" SINCE {since})')
            if st == "OK" and data and data[0]:
                selected_ids.update(data[0].split()[-100:])

        for mid in sorted(selected_ids, key=lambda x: int(x), reverse=True):
            st, payload = client.fetch(mid, "(BODY.PEEK[])")
            if st != "OK" or not payload:
                continue
            raw = next((p[1] for p in payload if isinstance(p, tuple) and isinstance(p[1], bytes)), None)
            if raw:
                ev = parse_application_email(raw)
                if ev:
                    events.append(ev)
    except Exception:
        pass
    finally:
        try:
            client.logout()
        except Exception:
            pass

    return reconcile_events_with_db(events)
