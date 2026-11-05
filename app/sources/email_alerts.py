"""Import job-alert emails the user has explicitly subscribed to.

This avoids scraping logged-in or restricted job-board pages. Supported alert links:
WUZZUF, LinkedIn, Indeed, Bayt, Glassdoor, and employer career pages.
"""
from __future__ import annotations

import imaplib
import re
from datetime import datetime, timedelta, timezone
from email import message_from_bytes
from email.header import decode_header
from email.utils import parsedate_to_datetime
from urllib.parse import parse_qs, unquote, urlencode, urlparse, urlunparse

from bs4 import BeautifulSoup

from app.config import settings
from app.models import Job
from app.sources.common import clean_html, normalize_job

ALLOWED_DOMAINS = {
    "wuzzuf.net": "wuzzuf_alert",
    "linkedin.com": "linkedin_alert",
    "indeed.com": "indeed_alert",
    "bayt.com": "bayt_alert",
    "glassdoor.com": "glassdoor_alert",
}
GENERIC_LINK_TEXT = {
    "apply", "apply now", "view job", "view jobs", "see job", "see jobs",
    "learn more", "click here", "view opportunity", "open job", "job details",
    "here", "view all jobs", "manage this job alert", "unsubscribe", "find jobs", "sign in",
    "see more jobs", "more jobs", "create", "create job alert", "create alert",
}
NOISE_BADGES = re.compile(
    r"\b(?:easy apply|actively recruiting|fast growing|be an early applicant|1-click apply|promoted|viewed)\b",
    re.I,
)
POSTED_RELATIVE = re.compile(
    r"(?:posted\s*)?(\d+)\s*(hours?|hrs?|h|days?|d|weeks?|w|months?|mo)\s*ago", re.I
)
SHORT_AGE_TOKEN = re.compile(
    r"(?:^|\|\s*|\s)(\d{1,2})\s*(h|d|w)\b(?:\s*\||$)", re.I
)
STAR_RATING = re.compile(r"^\d+(?:[.,]\d+)?\s*★?$")


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
    raw = str(url or "").strip()
    # AWS SES click tracking: https://.../L0/https:%2F%2Fwuzzuf.net%2Fjobs%2Fp%2F.../1/010201...
    if "/L0/http" in raw:
        after_l0 = raw.split("/L0/", 1)[1]
        # Strip trailing AWS SES "/1/<token>/<sig>" suffix before decoding
        encoded_target = re.split(r"/[12]/[0-9a-fA-F]{10,}", after_l0, maxsplit=1)[0]
        decoded = unquote(encoded_target)
        if decoded.startswith(("https://", "http://")) and _domain_source(decoded):
            return decoded

    parsed = urlparse(raw)
    query = parse_qs(parsed.query)
    for key in ("url", "u", "redirect", "redirect_url", "target", "dest", "destination"):
        candidate = (query.get(key) or [""])[0]
        if candidate.startswith(("https://", "http://")) and _domain_source(candidate):
            return candidate
    return raw


def _looks_like_job_url(url: str, source: str) -> bool:
    parsed = urlparse(url)
    path = parsed.path.lower()
    if source == "wuzzuf_alert":
        return "/jobs/p/" in path
    if source == "linkedin_alert":
        return "/jobs/view/" in path or "/comm/jobs/view/" in path
    if source == "indeed_alert":
        return (
            "viewjob" in path
            or "/rc/clk" in path
            or "/pagead/clk" in path
            or bool(parse_qs(parsed.query).get("jk") or parse_qs(parsed.query).get("vjk"))
        )
    if source == "bayt_alert":
        return "/jobs/" in path or "/job/" in path
    if source == "glassdoor_alert":
        return ("joblisting" in path or "job-listing" in path) and "rjtredirect" not in path
    return False


def _canonical_job_url(url: str, source: str) -> str:
    """Strip tracking parameters so repeated alert digests deduplicate to one job."""
    parsed = urlparse(url)
    path = parsed.path.rstrip("/") or "/"
    query = ""
    if source == "indeed_alert":
        params = parse_qs(parsed.query)
        job_key = params.get("jk") or params.get("vjk")
        if job_key:
            query = urlencode({"jk" if params.get("jk") else "vjk": job_key[0]})
    elif source == "glassdoor_alert":
        params = parse_qs(parsed.query)
        gd_key = params.get("jobListingId") or params.get("jl")
        if gd_key:
            query = urlencode({"jobListingId": gd_key[0]})
        elif params.get("ao") and params.get("pos"):
            query = urlencode({"ao": params["ao"][0], "pos": params["pos"][0]})
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
        elif unit.startswith("mo"):
            delta = timedelta(days=amount * 30)
        else:
            delta = timedelta(days=amount)
        return (email_date - delta).isoformat()
    short_match = SHORT_AGE_TOKEN.search(context)
    if short_match:
        amount = int(short_match.group(1))
        unit = short_match.group(2).lower()
        delta = (
            timedelta(hours=amount) if unit == "h"
            else timedelta(weeks=amount) if unit == "w"
            else timedelta(days=amount)
        )
        return (email_date - delta).isoformat()
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
        if node is None or getattr(node, "name", "") in {"body", "html", "[document]"}:
            break
        text = node.get_text(" | ", strip=True)
        if node is not anchor and node is not anchor.parent and "noticed that you just applied to" in text.lower():
            break
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
            break
        node = node.parent
    return fallback or anchor.get_text(" ", strip=True)


def _clean_badge_noise(value: str) -> str:
    cleaned = NOISE_BADGES.sub(" ", value or "")
    return re.sub(r"\s+", " ", cleaned).strip(" |•·:-\t\r\n")


def _company_from_context(context: str, title: str) -> str:
    text = context.replace(title, " | ", 1)
    explicit = re.search(r"\b(?:company|employer)\s*[:\-]\s*([^|•\n]{2,90})", text, re.I)
    if explicit:
        candidate = explicit.group(1).strip(" |:-")
        if candidate:
            return candidate
    segments = [part.strip(" |•\t\r\n:-") for part in re.split(r"\s*\|\s*|\n+", text) if part.strip()]
    for segment in segments:
        location_match = re.search(
            r"\b(?:Ameria|Amreya|Alexandria|Giza|Maadi|Nasr City|Nasser City|New Cairo|Heliopolis|6th of October|October City|Sheikh Zayed|Obour|10th of Ramadan|Tanta|Bolkly|Cairo|Mansoura)\b",
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
        if any(word in low for word in ("cairo", "mansoura", "egypt", "remote", "hybrid", "on-site", "onsite", "posted", "day ago", "days ago", "hour ago", "month ago", "apply now", "easy apply", "actively recruiting", "fast growing", "full time", "entry level", "experienced", "noticed that you", "just applied", "based on your profile", "application submitted", "application sent", "your application", "your job listings")):
            continue
        if low in GENERIC_LINK_TEXT:
            continue
        if "http" in low or "www." in low:
            continue
        return segment
    return "Unknown company"


def _location_from_context(context: str) -> str:
    patterns = [
        r"\b(?:Ameria|Amreya|Giza|Maadi|Nasr City|Nasser City|New Cairo|Heliopolis|6th of October|October City|Sheikh Zayed|Obour|10th of Ramadan(?:\s+City)?|Tanta|Bolkly)(?:,\s*(?:Alexandria|Cairo|Giza|Egypt))?\b(?:\s*\((?:Hybrid|On[- ]?site|Remote)\))?",
        r"\b(?:Cairo|Mansoura|Giza|Alexandria)(?:,\s*(?:Egypt|Giza|Cairo))?\b(?:\s*(?:[-|,]\s*|\s*\()(?:Hybrid|On[- ]?site|Remote)\)?)?",
        r"\bEgypt\s*\((?:Remote|Hybrid|On[- ]?site)\)",
        r"\bRemote(?:\s*[-|,]\s*(?:Worldwide|Egypt|EMEA|Europe|US|USA|Canada))?\b",
        r"\b(?:Hybrid|On[- ]?site|Onsite)\s*(?:[-|,]\s*[A-Z][A-Za-z .-]+)?",
        r"\b(?:Worldwide|Anywhere|Egypt|EMEA)\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, context, re.I)
        if match:
            return clean_html(match.group(0))
    return "Location not supplied"


def _parse_wuzzuf_slug_fallback(url: str, title: str) -> tuple[str, str]:
    """Extract (company, location) from Wuzzuf /jobs/p/<id>-<title>-<company>-<city>-<country>."""
    path = urlparse(url).path
    if "/jobs/p/" not in path:
        return "Unknown company", "Location not supplied"
    slug = path.split("/jobs/p/", 1)[1].strip("/")
    parts = slug.split("-")
    if len(parts) < 4:
        return "Unknown company", "Location not supplied"
    # Drop the leading random job ID token (e.g. "9h9agrsmqdfd")
    rest = "-".join(parts[1:])
    title_slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    if title_slug and rest.startswith(title_slug + "-"):
        rest = rest[len(title_slug) + 1:]

    location = "Location not supplied"
    for suffix, loc_label in (
        ("-new-cairo-cairo-egypt", "New Cairo, Cairo, Egypt"),
        ("-nasr-city-cairo-egypt", "Nasr City, Cairo, Egypt"),
        ("-maadi-cairo-egypt", "Maadi, Cairo, Egypt"),
        ("-heliopolis-cairo-egypt", "Heliopolis, Cairo, Egypt"),
        ("-cairo-egypt", "Cairo, Egypt"),
        ("-giza-egypt", "Giza, Egypt"),
        ("-alexandria-egypt", "Alexandria, Egypt"),
        ("-mansoura-egypt", "Mansoura, Egypt"),
        ("-egypt", "Egypt"),
        ("-riyadh-saudi-arabia", "Riyadh, Saudi Arabia"),
        ("-saudi-arabia", "Saudi Arabia"),
        ("-dubai-united-arab-emirates", "Dubai, UAE"),
    ):
        if rest.endswith(suffix):
            location = loc_label
            rest = rest[: -len(suffix)]
            break

    company = " ".join(w.capitalize() for w in rest.split("-") if w) if rest else "Unknown company"
    return (company or "Unknown company"), location


def _parse_alert_card(anchor, source: str, url: str, context: str) -> tuple[str, str, str]:
    """Return (title, company, location) tailored to each job board's alert HTML structure."""
    pipe_parts = [clean_html(p) for p in anchor.get_text(" | ", strip=True).split("|") if clean_html(p)]

    if source == "linkedin_alert" and len(pipe_parts) >= 2:
        raw_title = _clean_badge_noise(pipe_parts[0])
        company = "Unknown company"
        location = ""
        for part in pipe_parts[1:]:
            if "·" in part:
                co_part, loc_part = part.split("·", 1)
                company = _clean_badge_noise(co_part) or "Unknown company"
                location = _clean_badge_noise(loc_part)
                break
        if not location:
            location = _location_from_context(context)
        if company == "Unknown company":
            company = _company_from_context(context, raw_title)
        return raw_title, company, location or "Location not supplied"

    if source == "glassdoor_alert" and len(pipe_parts) >= 3:
        company = pipe_parts[0]
        idx = 1
        if idx < len(pipe_parts) and STAR_RATING.match(pipe_parts[idx]):
            idx += 1
        raw_title = pipe_parts[idx] if idx < len(pipe_parts) else ""
        location = pipe_parts[idx + 1] if idx + 1 < len(pipe_parts) else _location_from_context(context)
        return _clean_badge_noise(raw_title), _clean_badge_noise(company) or "Unknown company", location or "Location not supplied"

    raw_title = _clean_badge_noise(clean_html(anchor.get_text(" ", strip=True)))
    # Handle single-line LinkedIn card text where Company · Location is inline without pipe breaks
    if source == "linkedin_alert" and "·" in raw_title:
        before_dot, after_dot = raw_title.split("·", 1)
        location = _clean_badge_noise(after_dot) or _location_from_context(context)
        # Split title vs company if possible, otherwise keep title
        tokens = before_dot.strip().split()
        if len(tokens) >= 3:
            raw_title = before_dot.strip()
        company = _company_from_context(context, raw_title)
        return raw_title, company, location

    company = _company_from_context(context, raw_title)
    location = _location_from_context(context)

    if source == "wuzzuf_alert" and (company == "Unknown company" or location == "Location not supplied"):
        slug_co, slug_loc = _parse_wuzzuf_slug_fallback(url, raw_title)
        if company == "Unknown company" and slug_co != "Unknown company":
            company = slug_co
        if location == "Location not supplied" and slug_loc != "Location not supplied":
            location = slug_loc

    return raw_title, company, location


def _is_known_alert_sender(from_header: str) -> bool:
    low = (from_header or "").lower()
    return any(
        domain in low
        for domain in ("linkedin.com", "indeed.com", "wuzzuf.net", "glassdoor.com", "bayt.com")
    )


def parse_alert_message(raw: bytes) -> list[Job]:
    message = message_from_bytes(raw)
    subject = _decode_header(message.get("Subject", "")).strip()
    if re.search(
        r"^indeed application\s*:|your application was sent to|application submitted|"
        r"thanks for applying|thank you for applying|we've got your application",
        subject,
        re.I,
    ):
        return []
    email_date = _email_datetime(message)
    from_header = _decode_header(message.get("From", ""))
    known_sender = _is_known_alert_sender(from_header)
    plain, html = _body_parts(message)
    soup = BeautifulSoup(html, "html.parser") if html else BeautifulSoup(plain, "html.parser")
    jobs: list[Job] = []
    seen: set[str] = set()
    for anchor in soup.find_all("a", href=True):
        url = _unwrap_url(anchor.get("href", "").strip())
        source = _domain_source(url)
        if not source or not _looks_like_job_url(url, source):
            continue
        parent_text = anchor.parent.get_text(" ", strip=True) if anchor.parent else ""
        if re.search(r"noticed that you just applied to|you recently applied to", parent_text, re.I):
            continue
        context = _card_text(anchor)
        title, company, location = _parse_alert_card(anchor, source, url, context)
        if not title or title.lower() in GENERIC_LINK_TEXT or len(title) < 4 or len(title) > 160:
            continue
        canonical = _canonical_job_url(url, source)
        if canonical in seen:
            continue
        seen.add(canonical)
        posted_at = _posted_date(context, email_date)
        date_kind = "posted" if posted_at else "unknown"
        if not posted_at and known_sender:
            posted_at = email_date.isoformat()
            date_kind = "posted"
        remote = bool(re.search(r"\bremote\b", f"{location} {title}", re.I))
        workplace_mode = (
            "remote" if remote
            else "hybrid" if re.search(r"\bhybrid\b", location, re.I)
            else "onsite" if re.search(r"\bon[- ]?site\b", location, re.I)
            else "unknown"
        )
        eligibility = location if re.search(r"\b(worldwide|egypt|emea|anywhere|cairo|giza|mansoura)\b", location, re.I) else ""
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
            description_quality="summary",
            employment_type="",
            workplace_type=workplace_mode,
            date_kind=date_kind,
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
        selected_ids: set[bytes] = set()
        per_domain_limit = min(settings.email_alerts_max_messages, 30)
        for domain in ALLOWED_DOMAINS:
            status, data = client.search(None, "SINCE", since, "FROM", domain)
            if status != "OK":
                continue
            ids = (data[0] or b"").split()
            selected_ids.update(ids[-per_domain_limit:])

        status, data = client.search(None, "SINCE", since)
        if status != "OK":
            raise RuntimeError("IMAP search for recent alert emails failed")
        recent_ids = (data[0] or b"").split()
        selected_ids.update(recent_ids[-min(settings.email_alerts_max_messages, 25):])

        message_ids = sorted(selected_ids, key=lambda value: int(value), reverse=True)[:min(settings.email_alerts_max_messages, 90)]
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

    unique: dict[str, Job] = {}
    for job in jobs:
        unique.setdefault(job.url, job)
    return list(unique.values())
