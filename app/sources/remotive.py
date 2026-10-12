from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

import httpx

from app.models import Job
from app.sources.common import get_json, normalize_job

URL = "https://remotive.com/api/remote-jobs"
SEARCHES = [
    "node.js", "express", "django", "fastapi", "angular", "react",
    "backend developer", "full stack developer", "junior developer",
    "software engineer", "python developer", "java developer", "devops",
    "internship", "graduate", "entry level", "QA automation",
]
LOG = logging.getLogger(__name__)


def _search(term: str) -> list[dict]:
    data = get_json(URL, params={"search": term})
    items = data.get("jobs", []) if isinstance(data, dict) else []
    return [item for item in items if isinstance(item, dict)]


def fetch_jobs() -> list[Job]:
    found: dict[str, Job] = {}
    # Bounded concurrency keeps runs faster without launching dozens of simultaneous requests.
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {pool.submit(_search, term): term for term in SEARCHES}
        for future in as_completed(futures):
            term = futures[future]
            try:
                items = future.result()
            except (httpx.HTTPError, ValueError) as exc:
                LOG.warning("Remotive search %r failed: %s", term, exc)
                continue
            for item in items:
                job = normalize_job(
                    source="remotive",
                    source_id=item.get("id"),
                    title=item.get("title"),
                    company=item.get("company_name"),
                    location=item.get("candidate_required_location") or "Remote (eligibility not supplied)",
                    url=item.get("url"),
                    description=item.get("description"),
                    posted_at=item.get("publication_date"),
                    remote=True,
                    employment_type=item.get("job_type", ""),
                    eligibility=item.get("candidate_required_location", ""),
                )
                if job:
                    found[job.source_id] = job
    return list(found.values())
