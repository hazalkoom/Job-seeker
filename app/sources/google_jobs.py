from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from app.config import settings
from app.models import Job
from app.sources.common import get_json, normalize_job

URL = "https://serpapi.com/search.json"
LOG = logging.getLogger(__name__)


def _relative_posted_at(value: Any, *, now: datetime | None = None) -> str:
    """Convert Google Jobs relative dates to ISO UTC so freshness can be checked."""
    raw = str(value or "").strip().lower()
    if not raw:
        return ""

    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)

    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).isoformat()
    except ValueError:
        pass

    if raw in {"today", "just posted", "posted today", "now"}:
        return current.astimezone(timezone.utc).isoformat()

    if raw in {"yesterday", "posted yesterday"}:
        return (current - timedelta(days=1)).astimezone(timezone.utc).isoformat()

    match = re.search(
        r"(?P<count>\d+)\s*\+?\s*(?P<unit>minute|min|hour|hr|day|week|month|year)s?\s+ago",
        raw,
    )
    if not match:
        return ""

    count = int(match.group("count"))
    unit = match.group("unit")

    if unit in {"minute", "min"}:
        delta = timedelta(minutes=count)
    elif unit in {"hour", "hr"}:
        delta = timedelta(hours=count)
    elif unit == "day":
        delta = timedelta(days=count)
    elif unit == "week":
        delta = timedelta(days=count * 7)
    elif unit == "month":
        delta = timedelta(days=count * 30)
    else:
        delta = timedelta(days=count * 365)

    return (current - delta).astimezone(timezone.utc).isoformat()


def _application_url(item: dict[str, Any]) -> str:
    """Prefer the company's application page when Google Jobs supplies one."""
    apply_options = item.get("apply_options") or []

    if isinstance(apply_options, list):
        usable: list[tuple[str, str]] = []

        for option in apply_options:
            if not isinstance(option, dict):
                continue

            link = str(option.get("link") or "").strip()
            label = str(option.get("title") or option.get("source") or "").lower()

            if link.startswith(("https://", "http://")):
                usable.append((label, link))

        for label, link in usable:
            if any(
                word in label
                for word in (
                    "company website",
                    "company site",
                    "employer",
                    "careers page",
                )
            ):
                return link

        if usable:
            return usable[0][1]

    related = item.get("related_links") or []
    if isinstance(related, list):
        for link_item in related:
            if isinstance(link_item, dict):
                link = str(link_item.get("link") or "").strip()
                if link.startswith(("https://", "http://")):
                    return link

    for key in ("share_link", "link"):
        link = str(item.get(key) or "").strip()
        if link.startswith(("https://", "http://")):
            return link

    return ""


def _query_terms(*, now: datetime | None = None) -> list[str]:
    """Run one broad query plus two rotating queries within the API budget.

    The rotation uses two half-day slots so morning and evening runs don't repeat
    the same rotating searches.
    """
    rotating = tuple(getattr(settings, "google_jobs_rotating_queries", ()) or ())
    fixed = str(getattr(settings, "google_jobs_fixed_query", "") or "").strip()

    if not fixed:
        fixed = (
            "junior backend developer OR junior full stack developer "
            "OR software engineer Egypt"
        )

    if not rotating:
        from app.config import DEFAULT_GOOGLE_JOBS_ROTATING_QUERIES

        rotating = DEFAULT_GOOGLE_JOBS_ROTATING_QUERIES

    if len(rotating) <= 2:
        selected = list(rotating)
    else:
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)

        utc_now = current.astimezone(timezone.utc)
        half_day_slot = utc_now.date().toordinal() * 2 + utc_now.hour // 12
        start = half_day_slot % len(rotating)
        selected = [
            rotating[start],
            rotating[(start + 1) % len(rotating)],
        ]

    result: list[str] = []
    for query in (fixed, *selected):
        cleaned = query.strip()
        if cleaned and cleaned not in result:
            result.append(cleaned)

    return result[:3]


def _safe_error(exc: Exception, api_key: str) -> str:
    message = f"{type(exc).__name__}: {exc}"
    if api_key:
        message = message.replace(api_key, "[redacted]")
    return message[:250]


def fetch_jobs() -> list[Job]:
    api_key = str(getattr(settings, "serpapi_api_key", "") or "").strip()
    if not api_key:
        return []

    found: dict[str, Job] = {}
    errors: list[str] = []
    queries = _query_terms()

    for query in queries:
        params = {
            "engine": "google_jobs",
            "q": query,
            "location": "Egypt",
            "gl": "eg",
            "hl": "en",
            "api_key": api_key,
        }

        try:
            data = get_json(URL, params=params)
            if not isinstance(data, dict):
                continue

            if data.get("error"):
                raise RuntimeError(str(data["error"]))

            items = data.get("jobs_results", [])
            if not isinstance(items, list):
                continue

            for item in items:
                if not isinstance(item, dict):
                    continue

                extensions = item.get("detected_extensions") or {}
                if not isinstance(extensions, dict):
                    extensions = {}

                location = str(
                    item.get("location") or "Location not supplied"
                ).strip()
                description = str(item.get("description") or "")

                remote = bool(extensions.get("work_from_home")) or bool(
                    re.search(
                        r"\b(remote|work from home|distributed)\b",
                        f"{location} {description}",
                        re.I,
                    )
                )

                posted_value = (
                    extensions.get("posted_at")
                    or item.get("posted_at")
                    or ""
                )
                posted_at = _relative_posted_at(posted_value)
                application_url = _application_url(item)

                if not application_url:
                    continue

                identity = str(
                    item.get("job_id") or item.get("id") or ""
                ).strip()

                if not identity:
                    fingerprint = "|".join(
                        str(item.get(key) or "").strip().lower()
                        for key in (
                            "title",
                            "company_name",
                            "location",
                            "share_link",
                        )
                    )
                    identity = hashlib.sha256(
                        fingerprint.encode("utf-8")
                    ).hexdigest()[:24]

                job = normalize_job(
                    source="google_jobs",
                    source_id=identity,
                    title=item.get("title"),
                    company=item.get("company_name"),
                    location=location,
                    url=application_url,
                    description=description,
                    posted_at=posted_at,
                    remote=remote,
                    employment_type=extensions.get("schedule_type", ""),
                    eligibility="",
                    date_kind="posted" if posted_at else "unknown",
                )

                if job:
                    found[job.source_id] = job

        except Exception as exc:
            # Keep a single failed search from preventing the other queries.
            safe = _safe_error(exc, api_key)
            errors.append(safe)
            LOG.warning(
                "Google Jobs search failed for query %r: %s",
                query,
                safe,
            )

    if errors and not found and len(errors) == len(queries):
        raise RuntimeError(
            "All Google Jobs searches failed: " + " | ".join(errors[:2])
        )

    return list(found.values())