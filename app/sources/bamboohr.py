from __future__ import annotations

from app.config import settings
from app.models import Job
from app.sources.common import first, get_json, normalize_job


def fetch_jobs() -> list[Job]:
    jobs: list[Job] = []
    for company, slug in getattr(settings, "bamboohr_companies", ()):
        try:
            data = get_json(f"https://{slug}.bamboohr.com/careers/list")
        except Exception:
            continue
        items = data.get("result", []) if isinstance(data, dict) else []
        for item in items:
            if not isinstance(item, dict):
                continue
            job_id = str(first(item, "id", default=""))
            if not job_id:
                continue
            loc_obj = item.get("location") if isinstance(item.get("location"), dict) else {}
            city = str(loc_obj.get("city") or "")
            state = str(loc_obj.get("state") or "")
            country = str(loc_obj.get("country") or "")
            location = ", ".join(p for p in (city, state, country) if p)
            is_remote = bool(item.get("isRemote")) or str(item.get("atsLocation", "")).lower() == "remote" or "remote" in location.lower()
            if is_remote and not location:
                location = "Remote"
            url = f"https://{slug}.bamboohr.com/careers/{job_id}"
            desc = str(first(item, "description", "departmentLabel", default=""))
            pub_date = str(first(item, "datePosted", "createdDate", default=""))
            job = normalize_job(
                source=f"bamboohr:{slug}",
                source_id=job_id,
                title=str(first(item, "jobOpeningName", "title", default="")),
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
