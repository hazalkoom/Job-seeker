from __future__ import annotations

from app.models import Job
from app.sources.common import get_json, normalize_job

URL = "https://remoteok.com/api"


def fetch_jobs() -> list[Job]:
    data = get_json(URL)
    jobs: list[Job] = []
    for item in data if isinstance(data, list) else []:
        if not isinstance(item, dict) or not item.get("id") or not item.get("position"):
            continue
        # RemoteOK's first object is commonly API metadata rather than a posting.
        job = normalize_job(
            source="remoteok",
            source_id=item.get("id"),
            title=item.get("position"),
            company=item.get("company"),
            location=item.get("location") or "Remote (eligibility not supplied)",
            url=item.get("url"),
            description=item.get("description"),
            posted_at=item.get("date"),
            remote=True,
            employment_type=item.get("employment_type", ""),
            description_quality="full",
        )
        if job:
            jobs.append(job)
    return jobs
