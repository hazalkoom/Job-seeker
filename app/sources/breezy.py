from __future__ import annotations

from app.config import settings
from app.models import Job
from app.sources.common import first, get_json, normalize_job


def fetch_jobs() -> list[Job]:
    jobs: list[Job] = []
    for company, slug in getattr(settings, "breezy_companies", ()):
        try:
            data = get_json(f"https://{slug}.breezy.hr/json")
        except Exception:
            continue
        items = data if isinstance(data, list) else data.get("positions", []) if isinstance(data, dict) else []
        for item in items:
            if not isinstance(item, dict):
                continue
            loc_obj = item.get("location") if isinstance(item.get("location"), dict) else {}
            location = str(
                loc_obj.get("name")
                or loc_obj.get("city")
                or item.get("location")
                or ""
            )
            is_remote = bool(loc_obj.get("is_remote")) or "remote" in location.lower()
            if is_remote and not location:
                location = "Remote"
            url = str(first(item, "url", default=f"https://{slug}.breezy.hr/p/{item.get('friendly_id', '')}"))
            pub_date = str(first(item, "published_date", "creation_date", default=""))
            desc = str(first(item, "description", default=""))
            job = normalize_job(
                source=f"breezy:{slug}",
                source_id=str(first(item, "id", "friendly_id", default=url)),
                title=str(first(item, "name", "title", default="")),
                company=company,
                location=location,
                url=url,
                description=desc,
                posted_at=pub_date,
                date_kind="posted" if pub_date else "unknown",
                remote=is_remote,
                eligibility=location,
                description_quality="full" if len(desc) >= 180 else "snippet",
            )
            if job:
                jobs.append(job)
    return jobs
