from __future__ import annotations

import json
from typing import Any

from bs4 import BeautifulSoup

from app.config import settings
from app.models import Job
from app.sources.common import clean_html, get_text, normalize_job


def _job_postings(value: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if isinstance(value, list):
        for child in value:
            found.extend(_job_postings(child))
    elif isinstance(value, dict):
        kind = value.get("@type")
        if kind == "JobPosting" or (isinstance(kind, list) and "JobPosting" in kind):
            found.append(value)
        for key in ("@graph", "mainEntity", "itemListElement"):
            if key in value:
                found.extend(_job_postings(value[key]))
    return found


def _address(job: dict[str, Any]) -> str:
    location = job.get("jobLocation") or job.get("applicantLocationRequirements") or ""
    if isinstance(location, list):
        return "; ".join(_address({"jobLocation": x}) for x in location)
    if isinstance(location, dict):
        address = location.get("address", location)
        if isinstance(address, dict):
            return ", ".join(str(address.get(k, "")) for k in ("addressLocality", "addressRegion", "addressCountry") if address.get(k))
        return str(address)
    if isinstance(location, str):
        return location
    return ""


def fetch_jobs() -> list[Job]:
    jobs: list[Job] = []
    for company, url in settings.career_pages:
        html = get_text(url)
        soup = BeautifulSoup(html, "html.parser")
        for script in soup.select('script[type="application/ld+json"]'):
            try:
                payload = json.loads(script.string or script.get_text())
            except (json.JSONDecodeError, TypeError):
                continue
            for item in _job_postings(payload):
                location = _address(item)
                remote_value = item.get("jobLocationType", "")
                remote = str(remote_value).upper() == "TELECOMMUTE" or "remote" in str(remote_value).lower()
                url_value = item.get("url") or item.get("sameAs") or url
                identifier = item.get("identifier") or {}
                if isinstance(identifier, dict):
                    identifier = identifier.get("value") or identifier.get("name")
                job = normalize_job(
                    source=f"career_page:{company.lower().replace(' ', '_')}",
                    source_id=identifier or url_value,
                    title=item.get("title"), company=company, location=location or ("Remote (eligibility not supplied)" if remote else "Location not supplied"),
                    url=url_value, description=clean_html(item.get("description", "")),
                    posted_at=item.get("datePosted"), remote=remote,
                    employment_type=item.get("employmentType", ""), eligibility=_address({"jobLocation": item.get("applicantLocationRequirements")}) if item.get("applicantLocationRequirements") else "",
                    description_quality="full",
                )
                if job:
                    jobs.append(job)
    return jobs
