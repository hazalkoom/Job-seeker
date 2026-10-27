from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

import httpx

from app.models import Job
from app.sources.common import get_json, first, normalize_job

URL = "https://himalayas.app/jobs/api/search"
ELIGIBILITY_PREFIX = "himalayas:v1:"

SEARCHES = [
    "node.js developer",
    "express developer",
    "django developer",
    "fastapi developer",
    "angular developer",
    "react developer",
    "junior backend developer",
    "junior software engineer",
    "python developer",
    "java developer",
    "software internship",
]

LOG = logging.getLogger(__name__)


def _country_records(value):
    """Normalize candidate-country restrictions without losing their meaning."""
    if not isinstance(value, list):
        return None

    records = []

    for country in value:
        if isinstance(country, dict):
            records.append({
                "alpha2": str(country.get("alpha2") or "").strip().upper(),
                "name": str(country.get("name") or "").strip(),
                "slug": str(country.get("slug") or "").strip(),
            })
        elif isinstance(country, str):
            country = country.strip()
            records.append({
                "alpha2": country.upper() if len(country) == 2 else "",
                "name": country if len(country) != 2 else "",
                "slug": "",
            })
        else:
            return None

    return records


def _eligibility_metadata(item):
    """Preserve the API's structured candidate restrictions for the matcher."""
    countries = _country_records(item.get("locationRestrictions"))
    timezones = item.get("timezoneRestrictions")

    timezone_records = (
        [str(value).strip() for value in timezones]
        if isinstance(timezones, list)
        else None
    )

    metadata = {
        "provider": "himalayas",
        "locationRestrictionsPresent": countries is not None,
        "locationRestrictions": countries,
        "timezoneRestrictionsPresent": timezone_records is not None,
        "timezoneRestrictions": timezone_records,
    }

    return ELIGIBILITY_PREFIX + json.dumps(
        metadata, separators=(",", ":"), sort_keys=True
    )


def _location(item):
    """Do not mistake candidate-location restrictions for the job's worksite."""
    explicit = first(
        item, "workLocation", "officeLocation", "location", default=""
    )

    if explicit:
        if isinstance(explicit, list):
            return ", ".join(
                str(value.get("name", value)
                    if isinstance(value, dict) else value)
                for value in explicit
            )

        if isinstance(explicit, dict):
            return str(
                first(explicit, "name", "label", "country", default="Remote")
            )

        return str(explicit)

    countries = _country_records(item.get("locationRestrictions"))

    if countries is None:
        return "Remote (candidate eligibility not supplied)"

    names = [
        country["name"] or country["slug"] or country["alpha2"]
        for country in countries
    ]
    names = [name for name in names if name]

    if not names:
        return "Remote (no candidate-country restriction)"

    return "Remote (candidate must be located in: " + ", ".join(names) + ")"


def _search(term):
    # Ask Himalayas for jobs open to candidates in Egypt, then independently
    # validate the returned restrictions before classifying each job.
    data = get_json(
        URL,
        params={
            "q": term,
            "country": "EG",
            "page": 1,
            "sort": "recent",
        },
    )

    items = data.get("jobs", []) if isinstance(data, dict) else []
    return [item for item in items if isinstance(item, dict)]


def fetch_jobs() -> list[Job]:
    found = {}

    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {
            pool.submit(_search, term): term
            for term in SEARCHES
        }

        for future in as_completed(futures):
            term = futures[future]

            try:
                items = future.result()
            except (httpx.HTTPError, ValueError, RuntimeError) as exc:
                LOG.warning("Himalayas search %r failed: %s", term, exc)
                continue

            for item in items:
                # Distinguish an original publication timestamp from a last-updated
                # timestamp. The API's ``updatedAt`` is not a safe substitute for
                # a posting date when enforcing the freshness window.
                publication_date = first(
                    item, "pubDate", "publishedAt", "createdAt", "datePosted"
                )
                updated_date = first(
                    item, "updatedAt", "updated_at", "modifiedAt", "updated"
                )
                posted_at = publication_date or updated_date or ""
                date_kind = (
                    "posted" if publication_date
                    else "updated" if updated_date
                    else "unknown"
                )
                job = normalize_job(
                    source="himalayas",
                    source_id=first(item, "guid", "id", "slug", "url"),
                    title=first(item, "title", "jobTitle"),
                    company=first(
                        item, "companyName", "company",
                        default="Unknown company",
                    ),
                    location=_location(item),
                    url=first(item, "applicationLink", "applicationUrl", "url"),
                    description=first(
                        item, "description", "excerpt", "descriptionText"
                    ),
                    posted_at=posted_at,
                    date_kind=date_kind,
                    remote=True,
                    employment_type=first(
                        item, "employmentType", "employment_type"
                    ),
                    eligibility=_eligibility_metadata(item),
                    description_quality=(
                        "full"
                        if first(item, "description", "descriptionText")
                        else "summary"
                    ),
                )

                if job:
                    found[job.source_id] = job

    return list(found.values())