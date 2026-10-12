"""Import job-alert emails the user has explicitly subscribed to.

This avoids scraping logged-in or restricted job-board pages. Supported alert links:
WUZZUF, LinkedIn, Indeed, Bayt, and employer career pages.
"""
from __future__ import annotations

import imaplib
import re
from datetime import datetime, timedelta, timezone
from email import message_from_bytes
from email.header import decode_header
from email.utils import parsedate_to_datetime
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from bs4 import BeautifulSoup

from app.config import settings
from app.models import Job
from app.sources.common import clean_html, normalize_job

ALLOWED_DOMAINS = {
    "wuzzuf.net": "wuzzuf_alert",
    "linkedin.com": "linkedin_alert",
    "indeed.com": "indeed_alert",
    "bayt.com": "bayt_alert",
}
GENERIC_LINK_TEXT = {
    "apply", "apply now", "view job", "view jobs", "see job", "see jobs",
    "learn more", "click here", "view opportunity", "open job", "job details",
}
POSTED_RELATIVE = re.compile(
    r"(?:posted\s*)?(\d+)\s*(hours?|hrs?|h|days?|d|weeks?|w)\s*ago", re.I
)


def _decode_header(value: str) -> str:
    parts = []
    for chunk, encoding in decode_header(value or ""):
        if isinstance(chunk, bytes):
            parts.append(chunk.decode(encoding or "utf-8", errors="replace"))
        else:
            parts.append(chunk)
    return "".join(parts)


def _email_datetime(message) -> datetime:
    raw = message.get("Date", "")
    try:
        parsed = parsedate_to_datetime(raw)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError, OverflowError):
        return datetime.now(timezone.utc)


def _body_parts(message) -> tuple[str, str]:
    plain_parts: list[str] = []
    html_parts: list[str] = []
    payloads = message.walk() if message.is_multipart() else [message]
    for part in payloads:
        if part.get_content_maintype() == "multipart":
            continue
        content_type = part.get_content_type()
        if content_type not in {"text/plain", "text/html"}:
            continue
        payload = part.get_payload(decode=True)
        if payload is None:
            continue
        charset = part.get_content_charset() or "utf-8"
        text = payload.decode(charset, errors="replace")
        (html_parts if content_type == "text/html" else plain_parts).append(text)
    return "\n".join(plain_parts), "\n".join(html_parts)


def _domain_source(url: str) -> str | None:
    host = (urlparse(url).hostname or "").lower()
    for domain, source in ALLOWED_DOMAINS.items():
        if host == domain or host.endswith("." + domain):
            return source
    return None


def _unwrap_url(url: str) -> str:
    """Unwrap common email tracking links only when they contain a full destination URL."""
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    for key in ("url", "u", "redirect", "redirect_url", "target", "dest", "destination"):
        candidate = (query.get(key) or [""])[0]
        if candidate.startswith(("https://", "http://")) and _domain_source(candidate):
            return candidate
    return url


def _looks_like_job_url(url: str, source: str) -> bool:
    parsed = urlparse(url)
    path = parsed.path.lower()
    if source == "wuzzuf_alert":
        return "/jobs/p/" in path
    if source == "linkedin_alert":
        return "/jobs/view/" in path or "/comm/jobs/view/" in path
    if source == "indeed_alert":
        return "viewjob" in path or bool(parse_qs(parsed.query).get("jk"))
    if source == "bayt_alert":
        return "/jobs/" in path or "/job/" in path
    return False



def _canonical_job_url(url: str, source: str) -> str:
    """Strip tracking parameters so repeated alert digests deduplicate to one job."""
    parsed = urlparse(url)
    path = parsed.path.rstrip("/") or "/"
    query = ""
    if source == "indeed_alert":
        params = parse_qs(parsed.query)
        # Indeed's jk identifies the job; the remaining query parameters are usually tracking.
        job_key = params.get("jk") or params.get("vjk")
        if job_key:
            query = urlencode({"jk" if params.get("jk") else "vjk": job_key[0]})
    return urlunparse((parsed.scheme.lower(), parsed.netloc.lower(), path, "", query, ""))


def _posted_date(context: str, email_date: datetime) -> str:
    text = context.lower()
    if re.search(r"\b(just posted|posted today|today)\b", text):
        return email_date.isoformat()
    if re.search(r"\b(yesterday|posted yesterday)\b", text):
        return (email_date - timedelta(days=1)).isoformat()
    match = POSTED_RELATIVE.search(text)
    if match:
        amount = int(match.group(1))
        unit = match.group(2).lower()
        if unit.startswith("h"):
            delta = timedelta(hours=amount)
        elif unit.startswith("w"):
            delta = timedelta(weeks=amount)
        else:
            delta = timedelta(days=amount)
        return (email_date - delta).isoformat()
    # Parse common absolute dates shown in alert cards; don't substitute email date
    # when the actual posting date isn't present.
    for pattern in (r"\b(\d{4}-\d{2}-\d{2})\b", r"\b(\d{1,2}\s+[A-Z][a-z]{2,8}\s+\d{4})\b"):
        found = re.search(pattern, context)
        if found:
            for fmt in ("%Y-%m-%d", "%d %B %Y", "%d %b %Y"):
                try:
                    return datetime.strptime(found.group(1), fmt).replace(tzinfo=timezone.utc).isoformat()
                except ValueError:
                    pass
    return ""


def _card_text(anchor) -> str:
    """Return nearby text for one listing, avoiding a whole-email ancestor with many jobs."""
    node = anchor
    fallback = ""
    for _ in range(7):
        if node is None:
            break
        text = node.get_text(" | ", strip=True)
        if text and len(text) <= 900:
            if len(text) >= 35 and not fallback:
                fallback = text
            has_listing_metadata = bool(
                re.search(r"\b(?:hours?|days?|weeks?|months?)\s+ago\b|\b(?:today|yesterday)\b", text, re.I)
                or re.search(r"\b(?:Cairo|Mansoura|Alexandria|Giza|Egypt|Remote|Hybrid|On[- ]?site)\b", text, re.I)
            )
            if len(text) >= 35 and has_listing_metadata:
                return text
        elif text and len(text) > 900:
            # Higher ancestors are likely to contain several job cards.
            break
        node = node.parent
    return fallback or anchor.get_text(" ", strip=True)


def _company_from_context(context: str, title: str) -> str:
    text = context.replace(title, " | ", 1)
    explicit = re.search(r"\b(?:company|employer)\s*[:\-]\s*([^|•\n]{2,90})", text, re.I)
    if explicit:
        candidate = explicit.group(1).strip(" |:-")
        if candidate:
            return candidate
    segments = [part.strip(" |•\t\r\n:-") for part in re.split(r"\s*\|\s*|\n+", text) if part.strip()]
    for segment in segments:
        # WUZZUF often places company, country, and neighborhood on one line, e.g.
        # "Prometeon tyres group – Egypt - Ameria, Alexandria". Keep the company part.
        location_match = re.search(
            r"\b(?:Ameria|Amreya|Alexandria|Giza|Maadi|Nasr City|New Cairo|Heliopolis|6th of October|October City|Sheikh Zayed|Obour|Tanta|Bolkly|Cairo|Mansoura)\b",
            segment,
            re.I,
        )
        if location_match:
            segment = segment[:location_match.start()].strip(" |•\t\r\n:-–—")
            segment = re.sub(r"\s*[–—-]\s*Egypt\s*$", "", segment, flags=re.I)
            segment = segment.strip(" |•\t\r\n:-–—")
        low = segment.lower()
        if segment == title or len(segment) < 2 or len(segment) > 90:
            continue
        if any(word in low for word in ("cairo", "mansoura", "egypt", "remote", "hybrid", "on-site", "onsite", "posted", "day ago", "hour ago", "apply now")):
            continue
        if low in GENERIC_LINK_TEXT:
            continue
        if "http" in low or "www." in low:
            continue
        return segment
    return "Unknown company"


def _location_from_context(context: str) -> str:
    patterns = [
        r"\b(?:Cairo|Mansoura)(?:,\s*(?:Egypt|Giza))?\b(?:\s*[-|,]\s*(?:Hybrid|On[- ]?site|Remote))?",
        r"\b(?:Ameria|Amreya|Alexandria|Giza|Maadi|Nasr City|New Cairo|Heliopolis|6th of October|October City|Sheikh Zayed|Obour|Tanta|Bolkly)(?:,\s*(?:Alexandria|Cairo|Giza|Egypt))?\b",
        r"\bRemote(?:\s*[-|,]\s*(?:Worldwide|Egypt|EMEA|Europe|US|USA|Canada))?\b",
        r"\b(?:Hybrid|On[- ]?site|Onsite)\s*(?:[-|,]\s*[A-Z][A-Za-z .-]+)?",
        r"\b(?:Worldwide|Anywhere|Egypt|EMEA)\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, context, re.I)
        if match:
            return clean_html(match.group(0))
    return "Location not supplied"


def parse_alert_message(raw: bytes) -> list[Job]:
    message = message_from_bytes(raw)
    email_date = _email_datetime(message)
    plain, html = _body_parts(message)
    soup = BeautifulSoup(html, "html.parser") if html else BeautifulSoup(plain, "html.parser")
    jobs: list[Job] = []
    seen: set[str] = set()
    for anchor in soup.find_all("a", href=True):
        url = _unwrap_url(anchor.get("href", "").strip())
        source = _domain_source(url)
        if not source or not _looks_like_job_url(url, source):
            continue
        title = clean_html(anchor.get_text(" ", strip=True))
        if not title or title.lower() in GENERIC_LINK_TEXT or len(title) < 5 or len(title) > 160:
            continue
        canonical = _canonical_job_url(url, source)
        if canonical in seen:
            continue
        seen.add(canonical)
        context = _card_text(anchor)
        location = _location_from_context(context)
        posted_at = _posted_date(context, email_date)
        company = _company_from_context(context, title)
        remote = bool(re.search(r"\bremote\b", location, re.I))
        eligibility = location if re.search(r"\b(worldwide|egypt|emea|anywhere)\b", location, re.I) else ""
        job = normalize_job(
            source=source,
            source_id=canonical,
            title=title,
            company=company,
            location=location,
            url=canonical,
            description=context,
            posted_at=posted_at,
            remote=remote,
            eligibility=eligibility,
            employment_type="",
            workplace_type="remote" if remote else "unknown",
            date_kind="posted" if posted_at else "unknown",
        )
        if job:
            jobs.append(job)
    return jobs


def fetch_jobs() -> list[Job]:
    required = (
        settings.email_alerts_imap_host,
        settings.email_alerts_username,
        settings.email_alerts_password,
    )
    if not all(required):
        return []
    since = (datetime.now(timezone.utc) - timedelta(days=settings.email_alerts_lookback_days)).strftime("%d-%b-%Y")
    jobs: list[Job] = []
    mailbox = settings.email_alerts_mailbox or "INBOX"
    client = imaplib.IMAP4_SSL(settings.email_alerts_imap_host, settings.email_alerts_imap_port)
    try:
        client.login(settings.email_alerts_username, settings.email_alerts_password)
        status, _ = client.select(mailbox, readonly=True)
        if status != "OK":
            raise RuntimeError(f"Could not select IMAP mailbox: {mailbox}")
        # Search by sender domain first. This prevents a busy Indeed inbox from pushing
        # WUZZUF/LinkedIn/Bayt digests out of the message cap. Keep a recent-inbox fallback
        # for newsletters whose sender domain differs from the domain in their job links.
        selected_ids: set[bytes] = set()
        for domain in ALLOWED_DOMAINS:
            status, data = client.search(None, "SINCE", since, "FROM", domain)
            if status != "OK":
                continue
            ids = (data[0] or b"").split()
            selected_ids.update(ids[-settings.email_alerts_max_messages:])

        status, data = client.search(None, "SINCE", since)
        if status != "OK":
            raise RuntimeError("IMAP search for recent alert emails failed")
        recent_ids = (data[0] or b"").split()
        selected_ids.update(recent_ids[-min(settings.email_alerts_max_messages, 100):])

        # Fetch newest message IDs first. The per-domain cap above applies independently
        # to each supported board; the small fallback covers unusual sender addresses.
        message_ids = sorted(selected_ids, key=lambda value: int(value), reverse=True)
        for message_id in message_ids:
            status, payload = client.fetch(message_id, "(BODY.PEEK[])")
            if status != "OK" or not payload:
                continue
            raw = next((part[1] for part in payload if isinstance(part, tuple) and isinstance(part[1], bytes)), None)
            if raw:
                jobs.extend(parse_alert_message(raw))
    finally:
        try:
            client.logout()
        except Exception:
            pass
    # Deduplicate links across repeated alert emails.
    unique: dict[tuple[str, str], Job] = {}
    for job in jobs:
        unique[(job.source, job.source_id)] = job
    return list(unique.values())
