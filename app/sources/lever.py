from __future__ import annotations

from app.config import settings
from app.models import Job
from app.sources.common import get_json, first, normalize_job


def fetch_jobs() -> list[Job]:
    jobs: list[Job] = []
    for company, site in settings.lever_sites:
        try:
            data = get_json(f"https://api.lever.co/v0/postings/{site}", params={"mode": "json"})
        except Exception:
            continue
        for item in data if isinstance(data, list) else []:
            if not isinstance(item, dict):
                continue
            categories = item.get("categories") or {}
            location = first(categories, "location", default="") if isinstance(categories, dict) else ""
            description = " ".join(str(first(item, key, default="")) for key in ("description", "lists", "additional", "opening"))
            if isinstance(description, list):
                description = " ".join(str(x) for x in description)
            created_at = item.get("createdAt")
            updated_at = item.get("updatedAt")
            posted_at = created_at or updated_at or ""
            date_kind = "posted" if created_at else "updated" if updated_at else "unknown"
            workplace_type = str(item.get("workplaceType") or "").lower()
            is_remote = workplace_type == "remote" or "remote" in str(location).lower()
            job = normalize_job(
                source=f"lever:{site}", source_id=item.get("id"), title=item.get("text"),
                company=company, location=location, url=item.get("hostedUrl") or item.get("applyUrl"),
                description=description, posted_at=posted_at, date_kind=date_kind,
                remote=is_remote, eligibility=location, workplace_type=workplace_type or ("remote" if is_remote else "unknown"),
                description_quality="full",
            )
            if job:
                jobs.append(job)
    return jobs
