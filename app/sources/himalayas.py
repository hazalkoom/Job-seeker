from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

import httpx

from app.models import Job
from app.sources.common import get_json, first, normalize_job

URL = "https://himalayas.app/jobs/api/search"
SEARCHES = [
    "node.js developer", "express developer", "django developer", "fastapi developer",
    "angular developer", "react developer", "junior backend developer",
    "junior software engineer", "python developer", "java developer", "software internship",
]
LOG = logging.getLogger(__name__)


def _location(item: dict) -> str:
    value = first(item, "location", "locationRestrictions", "locations", "locationRestriction", default="Remote")
    if isinstance(value, list):
        return ", ".join(str(v.get("name", v) if isinstance(v, dict) else v) for v in value)
    if isinstance(value, dict):
        return str(first(value, "name", "label", "country", default="Remote"))
    return str(value)


def _search(term: str) -> list[dict]:
    data = get_json(URL, params={"q": term, "limit": 20, "sort": "recent"})
    items = data.get("jobs", []) if isinstance(data, dict) else []
    return [item for item in items if isinstance(item, dict)]


def fetch_jobs() -> list[Job]:
    found: dict[str, Job] = {}
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {pool.submit(_search, term): term for term in SEARCHES}
        for future in as_completed(futures):
            term = futures[future]
            try:
                items = future.result()
            except (httpx.HTTPError, ValueError) as exc:
                LOG.warning("Himalayas search %r failed: %s", term, exc)
                continue
            for item in items:
                location = _location(item)
                job = normalize_job(
                    source="himalayas",
                    source_id=first(item, "id", "slug", "url"),
                    title=first(item, "title", "jobTitle"),
                    company=first(item, "companyName", "company", default="Unknown company"),
                    location=location,
                    url=first(item, "applicationLink", "applicationUrl", "url"),
                    description=first(item, "description", "descriptionText"),
                    posted_at=first(item, "pubDate", "publishedAt", "createdAt", "datePosted"),
                    remote=True,
                    employment_type=first(item, "employmentType", "employment_type"),
                    eligibility=location,
                )
                if job:
                    found[job.source_id] = job
    return list(found.values())
