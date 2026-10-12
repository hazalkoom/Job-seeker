from __future__ import annotations

import logging

import httpx

from app.models import Job
from app.sources.common import get_json, normalize_job

URL = "https://jobicy.com/api/v2/remote-jobs"
LOG = logging.getLogger(__name__)
MAX_PAGES = 3  # up to 600 recent listings; the API feed is already limited to the last 7 days


def fetch_jobs() -> list[Job]:
    jobs: dict[str, Job] = {}
    cursor: str | None = None
    for _ in range(MAX_PAGES):
        params: dict[str, str | int] = {"count": 200}
        if cursor:
            params["cursor"] = cursor
        data = get_json(URL, params=params)
        if not isinstance(data, dict):
            break
        if data.get("success") is False:
            raise RuntimeError(str(data.get("error", "Jobicy API reported failure")))
        for item in data.get("jobs", []):
            if not isinstance(item, dict):
                continue
            job = normalize_job(
                source="jobicy",
                source_id=item.get("id") or item.get("jobSlug"),
                title=item.get("jobTitle"),
                company=item.get("companyName"),
                location=item.get("jobGeo") or "Remote (eligibility not supplied)",
                url=item.get("url"),
                description=item.get("jobDescription") or item.get("jobExcerpt", ""),
                posted_at=item.get("pubDate"),
                remote=True,
                employment_type=" / ".join(item.get("jobType", [])) if isinstance(item.get("jobType"), list) else item.get("jobType", ""),
                eligibility=item.get("jobGeo", ""),
            )
            if job:
                # Jobicy publishes only the recent feed; preserve the canonical Jobicy URL.
                jobs[job.source_id] = job
        cursor = data.get("nextCursor")
        if not cursor:
            break
    return list(jobs.values())
