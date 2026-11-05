from __future__ import annotations

from collections.abc import Callable

from app.config import settings
from app.models import Job
from app.sources.arbeitnow import fetch_jobs as fetch_arbeitnow
from app.sources.ashby import fetch_jobs as fetch_ashby
from app.sources.career_pages import fetch_jobs as fetch_career_pages
from app.sources.email_alerts import fetch_jobs as fetch_email_alerts
from app.sources.european_tech_opportunities import (
    fetch_jobs as fetch_european_tech_opportunities,
)
from app.sources.google_jobs import fetch_jobs as fetch_google_jobs
from app.sources.greenhouse import fetch_jobs as fetch_greenhouse
from app.sources.himalayas import fetch_jobs as fetch_himalayas
from app.sources.jobicy import fetch_jobs as fetch_jobicy
from app.sources.lever import fetch_jobs as fetch_lever
from app.sources.nomado24 import fetch_jobs as fetch_nomado24
from app.sources.remotive import fetch_jobs as fetch_remotive
from app.sources.remoteok import fetch_jobs as fetch_remoteok
from app.sources.rss_feeds import fetch_jobs as fetch_rss_feeds
from app.sources.workable import fetch_jobs as fetch_workable
from app.sources.smartrecruiters import fetch_jobs as fetch_smartrecruiters
from app.sources.recruitee import fetch_jobs as fetch_recruitee
from app.sources.bamboohr import fetch_jobs as fetch_bamboohr
from app.sources.breezy import fetch_jobs as fetch_breezy
from app.sources.hn_jobs import fetch_jobs as fetch_hn_jobs

Source = tuple[str, Callable[[], list[Job]]]


def enabled_sources() -> list[Source]:
    sources: list[Source] = []

    candidates = [
        (
            getattr(settings, "enable_google_jobs", True)
            and bool(getattr(settings, "serpapi_api_key", "")),
            "google_jobs",
            fetch_google_jobs,
        ),
        (settings.enable_remoteok, "remoteok", fetch_remoteok),
        (settings.enable_remotive, "remotive", fetch_remotive),
        (settings.enable_himalayas, "himalayas", fetch_himalayas),
        (settings.enable_jobicy, "jobicy", fetch_jobicy),
        (settings.enable_arbeitnow, "arbeitnow", fetch_arbeitnow),
        (
            settings.enable_european_tech_opportunities,
            "european_tech_opportunities",
            fetch_european_tech_opportunities,
        ),
        (settings.enable_nomado24, "nomado24", fetch_nomado24),
        (
            settings.enable_greenhouse and bool(settings.greenhouse_boards),
            "greenhouse",
            fetch_greenhouse,
        ),
        (
            settings.enable_lever and bool(settings.lever_sites),
            "lever",
            fetch_lever,
        ),
        (
            settings.enable_ashby and bool(settings.ashby_boards),
            "ashby",
            fetch_ashby,
        ),
        (
            getattr(settings, "enable_workable", True) and bool(getattr(settings, "workable_accounts", ())),
            "workable",
            fetch_workable,
        ),
        (
            getattr(settings, "enable_smartrecruiters", True) and bool(getattr(settings, "smartrecruiters_companies", ())),
            "smartrecruiters",
            fetch_smartrecruiters,
        ),
        (
            getattr(settings, "enable_recruitee", True) and bool(getattr(settings, "recruitee_companies", ())),
            "recruitee",
            fetch_recruitee,
        ),
        (
            getattr(settings, "enable_bamboohr", True) and bool(getattr(settings, "bamboohr_companies", ())),
            "bamboohr",
            fetch_bamboohr,
        ),
        (
            getattr(settings, "enable_breezy", True) and bool(getattr(settings, "breezy_companies", ())),
            "breezy",
            fetch_breezy,
        ),
        (
            getattr(settings, "enable_hn_jobs", True),
            "hn_jobs",
            fetch_hn_jobs,
        ),
        (
            settings.enable_career_pages and bool(settings.career_pages),
            "career_pages",
            fetch_career_pages,
        ),
        (
            settings.enable_email_alerts
            and bool(settings.email_alerts_username and settings.email_alerts_password),
            "email_alerts",
            fetch_email_alerts,
        ),
        (
            settings.enable_rss_feeds and bool(settings.rss_feeds),
            "rss_feeds",
            fetch_rss_feeds,
        ),
    ]

    for enabled, name, function in candidates:
        if enabled:
            sources.append((name, function))

    return sources


__all__ = [
    "fetch_arbeitnow",
    "fetch_remoteok",
    "fetch_remotive",
    "fetch_himalayas",
    "fetch_google_jobs",
    "fetch_greenhouse",
    "fetch_lever",
    "fetch_ashby",
    "fetch_career_pages",
    "fetch_jobicy",
    "fetch_email_alerts",
    "fetch_rss_feeds",
    "fetch_recruitee",
    "fetch_bamboohr",
    "fetch_breezy",
    "fetch_hn_jobs",
    "enabled_sources",
]