from __future__ import annotations

from app.config import settings
from app.models import Job
from app.sources.common import clean_html, get_json, normalize_job


def fetch_jobs() -> list[Job]:
    jobs: list[Job] = []
    from app.matching import IRRELEVANT_TITLE, SENIOR_TITLE, TARGET_ROLE, _has, _posting_age

    for company, account in settings.workable_accounts:
        try:
            data = get_json(f"https://apply.workable.com/api/v1/widget/accounts/{account}")
        except Exception:
            continue
        for item in data.get("jobs", []) if isinstance(data, dict) else []:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "")
            title_lower = title.lower()
            city = item.get("city", "")
            country = item.get("country", "")
            location = ", ".join(p for p in (city, country) if p) or "Location not supplied"
            telecommute = item.get("telecommute", False)
            remote = bool(telecommute) or "remote" in location.lower() or "remote" in title_lower
            if remote and not location:
                location = "Remote (eligibility not supplied)"
            url = item.get("url") or item.get("shortlink") or ""
            shortcode = item.get("shortcode") or item.get("id") or ""
            posted_at = item.get("published_on") or item.get("created_at") or ""

            description = clean_html(item.get("description", ""))
            fresh, _ = _posting_age(posted_at)
            loc_lower = location.lower()
            is_egypt = any(w in loc_lower for w in ("egypt", "cairo", "giza", "mansoura", "alexandria"))

            if (
                not description
                and shortcode
                and fresh
                and (remote or is_egypt)
                and _has(TARGET_ROLE, title_lower)
                and not _has(SENIOR_TITLE, title_lower)
                and not _has(IRRELEVANT_TITLE, title_lower)
            ):
                try:
                    detail = get_json(f"https://apply.workable.com/api/v2/accounts/{account}/jobs/{shortcode}")
                    if isinstance(detail, dict):
                        desc_html = (detail.get("description") or "") + " " + (detail.get("requirements") or "") + " " + (detail.get("benefits") or "")
                        description = clean_html(desc_html)
                except Exception:
                    pass

            job = normalize_job(
                source=f"workable:{account}",
                source_id=shortcode or url,
                title=title,
                company=company,
                location=location,
                url=url,
                description=description,
                posted_at=posted_at,
                date_kind="posted" if item.get("published_on") else "unknown",
                remote=remote,
                workplace_type="remote" if remote else "unknown",
                eligibility=location,
                description_quality="full" if len(description) >= 180 else "metadata",
            )
            if job:
                jobs.append(job)
    return jobs
