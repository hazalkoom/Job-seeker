"""Read configured public RSS/Atom job feeds independently of one another."""
from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from urllib.parse import parse_qs, urlparse

from app.config import settings
from app.models import Job
from app.sources.common import clean_html, get_text, normalize_job

logger = logging.getLogger(__name__)


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _child_text(element: ET.Element, *names: str) -> str:
    wanted = {name.lower() for name in names}
    for child in element.iter():
        if child is element:
            continue
        if _local_name(child.tag) in wanted and (child.text or "").strip():
            return (child.text or "").strip()
    return ""


def _link(element: ET.Element) -> str:
    """Read RSS text links and prefer Atom's alternate link over self/enclosure."""
    fallback = ""
    for child in element.iter():
        if _local_name(child.tag) != "link":
            continue
        href = child.attrib.get("href", "").strip()
        text = (child.text or "").strip()
        candidate = href or text
        if not candidate:
            continue
        rel = child.attrib.get("rel", "").strip().lower()
        if rel in {"", "alternate"}:
            return candidate
        if not fallback:
            fallback = candidate
    return fallback


def _date_value(element: ET.Element) -> tuple[str, str]:
    """Return a date and its evidence type without calling an update a posting date."""
    # Prefer an original publication date when the feed supplies one.
    for name in ("pubdate", "published", "date"):
        value = _child_text(element, name)
        if value:
            return value, "posted"
    for name in ("updated", "lastbuilddate"):
        value = _child_text(element, name)
        if value:
            return value, "updated"
    return "", "unknown"


def _date(value: str) -> str:
    if not value:
        return ""
    try:
        try:
            dt = parsedate_to_datetime(value)
        except (TypeError, ValueError):
            from datetime import datetime
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            from datetime import timezone
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.isoformat()
    except (TypeError, ValueError, OverflowError):
        return ""


def _is_remote_feed(feed_name: str, url: str) -> bool:
    """Use the feed's documented scope to identify remote workplace, not eligibility."""
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    host = (parsed.hostname or "").lower()
    path = parsed.path.lower()
    remote_filter = any(value.strip().lower() == "remote" for value in query.get("workplace", []))
    return (
        host.endswith("weworkremotely.com")
        or remote_filter
        or "/remote-" in path
        or "remote" in feed_name.lower()
    )


def fetch_jobs() -> list[Job]:
    jobs: list[Job] = []
    for feed_name, url in settings.rss_feeds:
        # A single unavailable or malformed feed must not suppress other feeds.
        try:
            xml = get_text(url)
            root = ET.fromstring(xml)
        except Exception as exc:
            logger.warning("RSS feed %r failed (%s): %s", feed_name, url, exc)
            continue

        remote_feed = _is_remote_feed(feed_name, url)
        for item in root.iter():
            if _local_name(item.tag) not in {"item", "entry"}:
                continue
            title = _child_text(item, "title")
            link = _link(item)
            if not title or not link:
                continue

            description = _child_text(item, "description", "summary", "content", "encoded")
            company = _child_text(item, "author", "creator", "source") or feed_name
            posted_raw, date_kind = _date_value(item)
            posted_at = _date(posted_raw)
            text = f"{title} {clean_html(description)}"

            # A generic mention of "worldwide" or "Egypt" in a description is
            # not evidence of applicant eligibility. Require it to be tied to a
            # remote-work phrase before filling the eligibility field.
            worldwide_remote = re.search(
                r"\b(?:remote\s*(?:[-–,:]\s*|\s+)(?:worldwide|anywhere|globally)|worldwide remote|work from anywhere|anywhere in the world)\b",
                text,
                re.I,
            )
            egypt_remote = re.search(
                r"\b(?:remote\s*(?:[-–,:]\s*|\s+)(?:(?:from|in)\s+)?Egypt|work from Egypt|Egypt-based remote)\b",
                text,
                re.I,
            )

            if worldwide_remote:
                location = "Remote worldwide"
                eligibility = "Remote worldwide"
                remote = True
            elif egypt_remote:
                location = "Remote Egypt"
                eligibility = "Remote Egypt"
                remote = True
            else:
                # Prefer workplace evidence over a city/country mentioned in the
                # description, which may refer to customers or company headquarters.
                remote_mentioned = bool(re.search(r"\b(remote|work from home|distributed)\b", text, re.I))
                location_match = None
                if not remote_mentioned and not remote_feed:
                    location_match = re.search(
                        r"\b(Cairo|Mansoura|Giza|Egypt|Germany|Poland|Netherlands|France|Greece)\b",
                        text,
                        re.I,
                    )

                if remote_feed or remote_mentioned:
                    location = "Remote (eligibility not supplied)"
                    remote = True
                elif location_match:
                    location = location_match.group(0)
                    remote = False
                else:
                    location = "Location not supplied"
                    remote = False
                eligibility = ""
            job = normalize_job(
                source=f"rss:{feed_name.lower().replace(' ', '_')}",
                source_id=link,
                title=title,
                company=company,
                location=location,
                url=link,
                description=description,
                posted_at=posted_at,
                date_kind=date_kind,
                remote=remote,
                eligibility=eligibility,
                description_quality="summary",
            )
            if job:
                jobs.append(job)
    return jobs
