from __future__ import annotations

from app.config import settings
from app.models import Job
from app.sources.common import first, get_json, normalize_job


def fetch_jobs() -> list[Job]:
    jobs: list[Job] = []
    for company, slug in getattr(settings, "recruitee_companies", ()):
        try:
            data = get_json(f"https://{slug}.recruitee.com/api/offers")
        except Exception:
            continue
        offers = data.get("offers", []) if isinstance(data, dict) else []
        for item in offers:
            if not isinstance(item, dict):
                continue
            location = str(
                first(item, "location", "city", "country", default="")
            )
            remote = bool(item.get("remote")) or "remote" in location.lower()
            if remote and not location:
                location = "Remote"
            pub_date = str(
                first(item, "published_at", "created_at", default="")
            )
            url = str(
                first(
                    item,
                    "careers_url",
                    "careers_apply_url",
                    "url",
                    default=f"https://{slug}.recruitee.com/o/{item.get('slug', '')}",
                )
            )
            desc = str(
                first(item, "description", "requirements", default="")
            )
            req = str(item.get("requirements") or "")
            if req and req not in desc:
                desc = f"{desc}\n\n{req}".strip()
            job = normalize_job(
                source=f"recruitee:{slug}",
                source_id=str(first(item, "id", "slug", default=url)),
                title=str(item.get("title") or ""),
                company=company,
                location=location,
                url=url,
                description=desc,
                posted_at=pub_date,
                date_kind="posted" if pub_date else "unknown",
                remote=remote,
                eligibility=location,
                description_quality="full" if len(desc) >= 180 else "snippet",
            )
            if job:
                jobs.append(job)
    return jobs
