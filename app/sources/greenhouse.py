from __future__ import annotations

from app.config import settings
from app.models import Job
from app.sources.common import clean_html, get_json, normalize_job


def fetch_jobs() -> list[Job]:
    jobs: list[Job] = []
    from app.matching import IRRELEVANT_TITLE, SENIOR_TITLE, TARGET_ROLE, _has, _posting_age

    for company, token in settings.greenhouse_boards:
        try:
            # Query board with content=true to get full descriptions in a single request
            data = get_json(f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true")
        except Exception:
            continue
        raw_jobs = data.get("jobs", []) if isinstance(data, dict) else []
        for item in raw_jobs:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "")
            title_lower = title.lower()
            if not _has(TARGET_ROLE, title_lower):
                continue
            if _has(SENIOR_TITLE, title_lower) or _has(IRRELEVANT_TITLE, title_lower):
                continue

            office = item.get("location") or {}
            location = office.get("name", "") if isinstance(office, dict) else str(office)
            posted_at = item.get("first_published") or item.get("updated_at") or ""
            date_kind = "posted" if item.get("first_published") else "updated" if item.get("updated_at") else "unknown"

            # Only fetch full job detail if posting age is within window and location is plausible
            fresh, _ = _posting_age(posted_at)
            loc_lower = str(location).lower()
            is_remote = any(w in loc_lower for w in ("remote", "home based", "home-based", "anywhere", "worldwide", "global", "emea"))
            is_egypt = any(w in loc_lower for w in ("egypt", "cairo", "giza", "mansoura", "alexandria", "smart village"))

            description = clean_html(item.get("content", ""))
            job_id = str(item.get("id") or "")
            if not description and fresh and (is_remote or is_egypt) and job_id:
                try:
                    detail = get_json(f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs/{job_id}")
                    if isinstance(detail, dict):
                        description = clean_html(detail.get("content", ""))
                except Exception:
                    pass

            if not description:
                desc_parts = [title]
                metadata = item.get("metadata") or []
                if isinstance(metadata, list):
                    for meta in metadata:
                        if isinstance(meta, dict):
                            val = meta.get("value")
                            if val and isinstance(val, (str, list)):
                                desc_parts.append(f"{meta.get('name')}: {val}")
                description = " | ".join(desc_parts)

            job = normalize_job(
                source=f"greenhouse:{token}",
                source_id=job_id,
                title=title,
                company=company,
                location=location,
                url=item.get("absolute_url"),
                description=description,
                posted_at=posted_at,
                date_kind=date_kind,
                remote=is_remote,
                eligibility=location,
                workplace_type="remote" if is_remote else "unknown",
                description_quality="full" if len(description) >= 180 else "metadata",
            )
            if job:
                jobs.append(job)
    return jobs
