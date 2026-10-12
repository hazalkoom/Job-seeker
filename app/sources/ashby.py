from __future__ import annotations

from app.config import settings
from app.models import Job
from app.sources.common import get_json, first, normalize_job


def fetch_jobs() -> list[Job]:
    jobs: list[Job] = []
    for company, board in settings.ashby_boards:
        data = get_json(f"https://api.ashbyhq.com/posting-api/job-board/{board}")
        for item in data.get("jobs", []) if isinstance(data, dict) else []:
            if not isinstance(item, dict):
                continue
            location = first(item, "location", "locationName", default="")
            if item.get("isRemote") and not location:
                location = "Remote (eligibility not supplied)"
            job = normalize_job(
                source=f"ashby:{board}", source_id=first(item, "id", "jobId", "jobUrl"),
                title=item.get("title"), company=company, location=location,
                url=first(item, "jobUrl", "applyUrl", "url"),
                description=first(item, "descriptionHtml", "description", default=""),
                posted_at=first(item, "publishedAt", "publishedDate", "updatedAt"),
                remote=bool(item.get("isRemote", False)) or "remote" in str(location).lower(),
                eligibility=location,
            )
            if job:
                jobs.append(job)
    return jobs
