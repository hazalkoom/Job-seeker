from __future__ import annotations

from app.config import settings
from app.models import Job
from app.sources.common import get_json, first, normalize_job


def fetch_jobs() -> list[Job]:
    jobs: list[Job] = []
    for company, site in settings.lever_sites:
        data = get_json(f"https://api.lever.co/v0/postings/{site}", params={"mode": "json"})
        for item in data if isinstance(data, list) else []:
            if not isinstance(item, dict):
                continue
            categories = item.get("categories") or {}
            location = first(categories, "location", default="") if isinstance(categories, dict) else ""
            description = " ".join(str(first(item, key, default="")) for key in ("description", "lists", "additional", "opening"))
            if isinstance(description, list):
                description = " ".join(str(x) for x in description)
            job = normalize_job(
                source=f"lever:{site}", source_id=item.get("id"), title=item.get("text"),
                company=company, location=location, url=item.get("hostedUrl") or item.get("applyUrl"),
                description=description, posted_at=first(item, "createdAt", "updatedAt"),
                remote="remote" in str(location).lower(), eligibility=location,
                description_quality="full",
            )
            if job:
                jobs.append(job)
    return jobs
