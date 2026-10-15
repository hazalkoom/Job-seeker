"""Fetch English-language remote/hybrid roles from the public Nomado24 API.

Nomado24 lists roles for Germany/EU. Its remote-work field describes workplace
arrangement, not whether an applicant located in Egypt is eligible; that remains
unknown unless the listing's other evidence explicitly states otherwise.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from app.config import settings
from app.models import Job
from app.sources.common import first, get_json, normalize_job

URL = "https://api.nomado24.de/api/public/v1/jobs"
PAGE_SIZE = 100
LOG = logging.getLogger(__name__)


def _work_arrangement(item: dict[str, Any]) -> tuple[bool, str]:
    value = str(first(item, "workArrangement", "work_arrangement", default="")).strip().lower()
    is_remote = item.get("remote") is True or value == "remote"
    if is_remote:
        return True, "remote"
    if "hybrid" in value:
        return False, "hybrid"
    if value in {"onsite", "on-site", "office"}:
        return False, "onsite"
    return False, "unknown"


def _safe_location(location: str, remote: bool) -> str:
    """Avoid treating broad aggregator labels like 'Anywhere' as eligibility proof."""
    if remote and re.search(r"\b(worldwide|anywhere|globally|global)\b", location, re.I):
        return "Remote (Germany/EU; applicant eligibility not supplied)"
    return location


def _fetch_query(query: str, max_pages: int) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for page in range(1, max(1, max_pages) + 1):
        params: dict[str, Any] = {
            "page": page,
            "per_page": PAGE_SIZE,
            "language": settings.nomado24_language,
        }
        if query:
            params["q"] = query
        try:
            payload = get_json(URL, params=params)
        except Exception as exc:
            LOG.warning("Nomado24 request failed for query %r page %s: %s", query or "all jobs", page, exc)
            break

        if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
            LOG.warning("Nomado24 returned an unexpected payload for query %r page %s", query or "all jobs", page)
            break

        items = [item for item in payload["data"] if isinstance(item, dict)]
        found.extend(items)
        # meta.count describes the number of rows in this response; a short page
        # means there is no next page for this query.
        if len(items) < PAGE_SIZE:
            break
    return found


def fetch_jobs() -> list[Job]:
    jobs_by_id: dict[str, Job] = {}
    max_pages = max(1, min(int(settings.nomado24_max_pages), 5))
    search_terms = tuple(settings.nomado24_search_terms) or ("developer", "engineer")

    for query in search_terms:
        for item in _fetch_query(query, max_pages):
            title = first(item, "title", default="")
            company = first(item, "companyName", "company_name", default="Unknown company")
            location = str(first(item, "location", default="") or "")
            remote, arrangement = _work_arrangement(item)
            location = _safe_location(location, remote)
            url = first(item, "url", default="")
            source_id = first(item, "slug", "url", default="")
            tags = item.get("tags", [])
            if isinstance(tags, list):
                safe_tags = [
                    str(tag).strip()
                    for tag in tags
                    if str(tag).strip()
                    and not re.fullmatch(r"(?:worldwide|anywhere|global(?:ly)?|all countries)", str(tag).strip(), re.I)
                ]
                tags_text = ", ".join(safe_tags)
            elif tags:
                tags_text = str(tags).strip()
            else:
                tags_text = ""
            description = f"Tags: {tags_text}" if tags_text else ""
            if item.get("source"):
                description = f"{description}. Listed source: {item['source']}" if description else f"Listed source: {item['source']}"

            job = normalize_job(
                source="nomado24",
                source_id=source_id,
                title=title,
                company=company,
                location=location,
                url=url,
                description=description,
                posted_at=first(item, "publishedAt", "published_at", default=""),
                date_kind="posted",
                remote=remote,
                employment_type=first(item, "employmentType", "employment_type", default=""),
                workplace_type=arrangement,
                # This endpoint doesn't expose a candidate-country eligibility field.
                eligibility="",
            )
            if job:
                jobs_by_id[job.source_id] = job

    return list(jobs_by_id.values())
