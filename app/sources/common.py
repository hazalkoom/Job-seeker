from __future__ import annotations

import html
import re
from datetime import datetime, timezone
from typing import Any

import httpx

from app.config import settings
from app.models import Job

HEADERS = {
    "User-Agent": "PersonalJobHunter/2.0 (+personal job-search tool)",
    "Accept": "application/json, text/html;q=0.9, */*;q=0.8",
}


def get_json(url: str, *, params: dict[str, Any] | None = None) -> Any:
    with httpx.Client(timeout=settings.request_timeout_seconds, headers=HEADERS, follow_redirects=True) as client:
        response = client.get(url, params=params)
        response.raise_for_status()
        return response.json()


def get_text(url: str) -> str:
    with httpx.Client(timeout=settings.request_timeout_seconds, headers=HEADERS, follow_redirects=True) as client:
        response = client.get(url)
        response.raise_for_status()
        return response.text


def clean_html(value: Any) -> str:
    text = str(value or "")
    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def first(item: dict[str, Any], *keys: str, default: Any = "") -> Any:
    for key in keys:
        value = item.get(key)
        if value not in (None, "", [], {}):
            return value
    return default


def iso_date(value: Any) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, (int, float)):
        seconds = value / 1000 if value > 10_000_000_000 else value
        try:
            return datetime.fromtimestamp(seconds, tz=timezone.utc).isoformat()
        except (ValueError, OSError, OverflowError):
            return ""
    return str(value).strip()


def is_http_url(value: Any) -> bool:
    return str(value or "").startswith(("https://", "http://"))


def workplace(location: str, remote: bool = False, explicit: str = "") -> str:
    text = f"{location} {explicit}".lower()
    if remote or re.search(r"\b(remote|work from home|distributed|anywhere)\b", text):
        return "remote"
    if re.search(r"\bhybrid\b", text):
        return "hybrid"
    if re.search(r"\b(on[- ]?site|in[- ]office|office based|in person)\b", text):
        return "onsite"
    return "unknown"


def normalize_job(
    *, source: str, source_id: Any, title: Any, company: Any, location: Any, url: Any,
    description: Any = "", posted_at: Any = "", remote: bool = False,
    employment_type: Any = "", workplace_type: str = "", eligibility: Any = "", date_kind: str = "posted",
) -> Job | None:
    job_id = str(source_id or url or "").strip()
    title_text = clean_html(title)
    url_text = str(url or "").strip()
    if not job_id or not title_text or not is_http_url(url_text):
        return None
    loc = clean_html(location) or ("Remote (eligibility not supplied)" if remote else "Location not supplied")
    return Job(
        source=source,
        source_id=job_id,
        title=title_text,
        company=clean_html(company) or "Unknown company",
        location=loc,
        url=url_text,
        description=clean_html(description),
        posted_at=iso_date(posted_at),
        date_kind=date_kind if posted_at else "unknown",
        remote=remote,
        employment_type=clean_html(employment_type),
        workplace_type=workplace(loc, remote, workplace_type),
        eligibility=clean_html(eligibility),
    )
