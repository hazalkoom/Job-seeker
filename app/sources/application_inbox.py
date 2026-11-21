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

from app.application_queue import _event, _now
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


def summarize_events(events: list[ApplicationEmailEvent]) -> dict[str, Any]:
    return {
        "confirmed_queue_ids": [],
        "unmatched_confirmations": [],
        "confirmations": [e.__dict__ for e in events if e.kind == "confirmed"],
        "interviews": [e.__dict__ for e in events if e.kind == "interview"],
        "rejections": [e.__dict__ for e in events if e.kind == "rejected"],
    }


def _receipt_matches_attempt(received_at: str, attempted_at: str) -> bool:
    if not attempted_at:
        return False
    try:
        delay = datetime.fromisoformat(received_at) - datetime.fromisoformat(attempted_at)
    except (TypeError, ValueError):
        return False
    return timedelta(minutes=-5) <= delay <= timedelta(days=7)


def reconcile_events_with_db(events: list[ApplicationEmailEvent]) -> dict[str, Any]:
    """Record only receipts that identify exactly one prior attempt."""
    init_db()
    result = summarize_events(events)
    with _connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        for ev in events:
            if ev.kind != "confirmed":
                continue
            if ev.message_id and conn.execute(
                "SELECT 1 FROM application_queue WHERE submission_reference=?", (ev.message_id,)
            ).fetchone():
                continue
            company, title = _norm_token(ev.company), _norm_token(ev.title)
            matches = []
            if company and company != "unknown company" and title and ev.message_id:
                rows = conn.execute("""
                    SELECT q.id, q.status, j.company, j.title, MAX(e.created_at) AS attempted_at
                    FROM application_queue q
                    JOIN jobs j ON j.id=q.job_id
                    JOIN application_events e ON e.queue_id=q.id AND e.event_type='application_attempt_started'
                    WHERE q.status IN ('applying','failed','submitted')
                    GROUP BY q.id
                """)
                matches = [
                    row for row in rows
                    if _norm_token(row["company"]) == company and _norm_token(row["title"]) == title
                    and _receipt_matches_attempt(ev.received_at, row["attempted_at"])
                ]
            if len(matches) != 1:
                result["unmatched_confirmations"].append(ev.__dict__)
                continue
            row = matches[0]
            if row["status"] == "submitted":
                continue
            now = _now()
            reason = "Confirmed by email tied to the employer, role, and attempt time."
            conn.execute("""
                UPDATE application_queue SET status='submitted', submitted_at=?, updated_at=?,
                    submission_reference=?, notes=? WHERE id=?
            """, (ev.received_at, now, ev.message_id, reason, row["id"]))
            _event(conn, row["id"], "application_submitted", {"reason": reason, "evidence": "email"})
            result["confirmed_queue_ids"].append(row["id"])
    return result


def fetch_and_reconcile_inbox(lookback_days: int = 7, *, reconcile: bool = True) -> dict[str, Any]:
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

    return reconcile_events_with_db(events) if reconcile else summarize_events(events)
