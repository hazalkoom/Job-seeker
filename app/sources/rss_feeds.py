"""Read configured RSS/Atom feeds from sources that publish a public feed."""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

from app.config import settings
from app.models import Job
from app.sources.common import clean_html, get_text, normalize_job


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
    for child in element.iter():
        if _local_name(child.tag) != "link":
            continue
        href = child.attrib.get("href")
        if href:
            return href.strip()
        if child.text and child.text.strip():
            return child.text.strip()
    return ""


def _date(value: str) -> tuple[str, str]:
    if not value:
        return "", "unknown"
    try:
        try:
            dt = parsedate_to_datetime(value)
        except (TypeError, ValueError):
            dt = __import__("datetime").datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            from datetime import timezone
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.isoformat(), "posted"
    except (TypeError, ValueError, OverflowError):
        return "", "unknown"


def fetch_jobs() -> list[Job]:
    jobs: list[Job] = []
    for feed_name, url in settings.rss_feeds:
        xml = get_text(url)
        root = ET.fromstring(xml)
        for item in root.iter():
            if _local_name(item.tag) not in {"item", "entry"}:
                continue
            title = _child_text(item, "title")
            link = _link(item)
            if not title or not link:
                continue
            description = _child_text(item, "description", "summary", "content", "encoded")
            company = _child_text(item, "author", "creator", "source") or feed_name
            posted_raw = _child_text(item, "pubdate", "published", "updated", "date")
            posted_at, date_kind = _date(posted_raw)
            text = f"{title} {clean_html(description)}"
            location_match = re.search(r"\b(Cairo|Mansoura|Egypt|Remote(?: worldwide)?|Worldwide|Hybrid|On[- ]?site)\b", text, re.I)
            location = location_match.group(0) if location_match else "Location not supplied"
            remote = bool(re.search(r"\b(remote|worldwide)\b", location, re.I))
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
                eligibility=location if re.search(r"\b(worldwide|egypt)\b", location, re.I) else "",
            )
            if job:
                jobs.append(job)
    return jobs
