from __future__ import annotations

from app.config import settings
from app.models import Job
from app.sources.common import get_json, normalize_job

URL = "https://www.arbeitnow.com/api/job-board-api"


def fetch_jobs() -> list[Job]:
    jobs: list[Job] = []
    # The API supports page pagination; cap requests to keep a scheduled run polite.
    for page in range(1, 4):
        data = get_json(URL, params={"page": page})
        items = data.get("data", []) if isinstance(data, dict) else []
        if not items:
            break
        for item in items:
            if not isinstance(item, dict):
                continue
            job = normalize_job(
                source="arbeitnow",
                source_id=item.get("slug") or item.get("url"),
                title=item.get("title"),
                company=item.get("company_name"),
                location=item.get("location"),
                url=item.get("url"),
                description=item.get("description"),
                posted_at=item.get("created_at"),
                remote=bool(item.get("remote", False)),
                employment_type=item.get("job_types", ""),
                description_quality="full",
            )
            if job:
                jobs.append(job)
        # Some API implementations don't expose pagination metadata; empty page ends loop.
        if len(items) < 1:
            break
    return jobs
