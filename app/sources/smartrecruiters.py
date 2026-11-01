from __future__ import annotations

from app.config import settings
from app.models import Job
from app.sources.common import clean_html, get_json, normalize_job


def fetch_jobs() -> list[Job]:
    jobs: list[Job] = []
    for company, comp_id in settings.smartrecruiters_companies:
        try:
            # Query SmartRecruiters postings for this company
            data = get_json(f"https://api.smartrecruiters.com/v1/companies/{comp_id}/postings", params={"limit": 50})
        except Exception:
            continue
        content = data.get("content", []) if isinstance(data, dict) else []
        for item in content:
            if not isinstance(item, dict):
                continue
            loc_data = item.get("location") or {}
            city = loc_data.get("city", "")
            country = loc_data.get("country", "")
            remote = bool(loc_data.get("remote", False))
            location = ", ".join(p for p in (city, country) if p) or ("Remote" if remote else "Location not supplied")
            url = f"https://jobs.smartrecruiters.com/{comp_id}/{item.get('id')}"
            posted_at = item.get("releasedDate") or item.get("createdOn") or ""
            job = normalize_job(
                source=f"smartrecruiters:{comp_id}",
                source_id=item.get("id") or url,
                title=item.get("name"),
                company=company,
                location=location,
                url=url,
                description="",  # SmartRecruiters postings list doesn't include full body, full body enriched on need
                posted_at=posted_at,
                date_kind="posted" if item.get("releasedDate") else "unknown",
                remote=remote,
                workplace_type="remote" if remote else "unknown",
                eligibility=location,
                description_quality="summary",
            )
            if job:
                jobs.append(job)
    return jobs
