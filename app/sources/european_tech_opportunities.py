"""Fetch curated European software-engineering internships and new-grad roles.

The provider's firstSeenAt timestamp is immutable but may approximate the original
posting time. We use it for recency filtering while marking its date semantics as
unknown so the matching engine can keep candidates in review when appropriate.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from app.config import settings
from app.models import Job
from app.sources.common import first, get_json, normalize_job

URL = "https://techopportunities.eu/api/v1/opportunities"
PAGE_SIZE = 100
CATEGORIES = ("software-engineering", "machine-learning")
LOG = logging.getLogger(__name__)


def _first_seen_window(max_age_days: int) -> str:
    """Map our freshness preference onto the windows supported by the API."""
    if max_age_days <= 1:
        return "24-hours"
    if max_age_days <= 7:
        return "7-days"
    if max_age_days <= 30:
        return "30-days"
    return ""


def _is_remote(title: str, location: str) -> bool:
    return bool(re.search(r"\b(remote|work from home|distributed|telecommute|anywhere)\b", f"{title} {location}", re.I))


def _safe_location(location: str, remote: bool) -> str:
    """Don't convert a generic location label into proof of worldwide eligibility."""
    if remote and re.search(r"\b(worldwide|anywhere|globally|global)\b", location, re.I):
        return "Remote (eligibility not supplied)"
    return location


def _fetch_category(category: str, max_pages: int) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    params_base: dict[str, Any] = {
        "category": category,
        "sort": "first-seen-desc",
        "page-size": PAGE_SIZE,
    }
    recency = _first_seen_window(settings.max_posting_age_days)
    if recency:
        params_base["first-seen"] = recency

    for page in range(1, max(1, max_pages) + 1):
        params = {**params_base, "page": page}
        try:
            data = get_json(URL, params=params)
        except Exception as exc:
            # Keep results from other pages/categories if one request fails.
            LOG.warning("European Tech Opportunities request failed for %s page %s: %s", category, page, exc)
            break

        if not isinstance(data, dict) or not isinstance(data.get("data"), list):
            LOG.warning("European Tech Opportunities returned an unexpected payload for category %s page %s", category, page)
            break

        page_items = [item for item in data["data"] if isinstance(item, dict)]
        found.extend(page_items)
        pagination = data.get("pagination") if isinstance(data.get("pagination"), dict) else {}
        try:
            total_pages = int(pagination.get("totalPages", 0) or 0)
        except (TypeError, ValueError):
            total_pages = 0
        if not page_items or (total_pages and page >= total_pages) or len(page_items) < PAGE_SIZE:
            break
    return found


def fetch_jobs() -> list[Job]:
    jobs_by_id: dict[str, Job] = {}
    max_pages = max(1, min(int(settings.european_tech_opportunities_max_pages), 10))

    for category in CATEGORIES:
        for item in _fetch_category(category, max_pages):
            job_id = str(first(item, "linkedinJobId", "linkedin_job_id", "link", default="")).strip()
            title = first(item, "title", default="")
            company = first(item, "company", default="Unknown company")
            location = first(item, "location", default="")
            url = first(item, "link", default="")
            employment_type = first(item, "employmentType", "employment_type", default="")
            industries = first(item, "industries", default="")
            start_date = first(item, "startDate", "start_date", default="")
            category_label = first(item, "category", default=category)
            metadata = [f"Category: {category_label}"]
            if industries:
                metadata.append(f"Industries: {industries}")
            if start_date:
                metadata.append(f"Expected start: {start_date}")

            remote = _is_remote(str(title), str(location))
            location = _safe_location(str(location or ""), remote)
            if remote and not location.strip():
                location = "Remote (eligibility not supplied)"

            job = normalize_job(
                source="european_tech_opportunities",
                source_id=job_id,
                title=title,
                company=company,
                location=location,
                url=url,
                # The API has no full description; expose only its actual metadata.
                description=". ".join(metadata),
                posted_at=first(item, "firstSeenAt", default=""),
                date_kind="unknown",
                remote=remote,
                employment_type=employment_type,
                eligibility="",
                description_quality="metadata",
            )
            if job:
                jobs_by_id[job.source_id] = job

    return list(jobs_by_id.values())
