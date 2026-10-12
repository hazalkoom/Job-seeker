from __future__ import annotations

from app.config import settings
from app.models import Job
from app.sources.common import get_json, first, normalize_job


def fetch_jobs() -> list[Job]:
    jobs: list[Job] = []
    for company, token in settings.greenhouse_boards:
        data = get_json(f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs", params={"content": "true"})
        for item in data.get("jobs", []) if isinstance(data, dict) else []:
            if not isinstance(item, dict):
                continue
            office = item.get("location") or {}
            location = office.get("name", "") if isinstance(office, dict) else str(office)
            job = normalize_job(
                source=f"greenhouse:{token}", source_id=item.get("id"), title=item.get("title"),
                company=company, location=location, url=item.get("absolute_url"),
                description=item.get("content", ""), posted_at=item.get("updated_at", ""), date_kind="updated",
                remote="remote" in str(location).lower(), eligibility=location,
                workplace_type="remote" if "remote" in str(location).lower() else "unknown",
            )
            if job:
                jobs.append(job)
    return jobs
