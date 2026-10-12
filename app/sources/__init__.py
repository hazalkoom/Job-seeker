from __future__ import annotations

from collections.abc import Callable

from app.config import settings
from app.models import Job
from app.sources.arbeitnow import fetch_jobs as fetch_arbeitnow
from app.sources.ashby import fetch_jobs as fetch_ashby
from app.sources.career_pages import fetch_jobs as fetch_career_pages
from app.sources.greenhouse import fetch_jobs as fetch_greenhouse
from app.sources.himalayas import fetch_jobs as fetch_himalayas
from app.sources.email_alerts import fetch_jobs as fetch_email_alerts
from app.sources.rss_feeds import fetch_jobs as fetch_rss_feeds
from app.sources.jobicy import fetch_jobs as fetch_jobicy
from app.sources.lever import fetch_jobs as fetch_lever
from app.sources.remotive import fetch_jobs as fetch_remotive
from app.sources.remoteok import fetch_jobs as fetch_remoteok

Source = tuple[str, Callable[[], list[Job]]]


def enabled_sources() -> list[Source]:
    sources: list[Source] = []
    for enabled, name, function in [
        (settings.enable_remoteok, "remoteok", fetch_remoteok),
        (settings.enable_remotive, "remotive", fetch_remotive),
        (settings.enable_himalayas, "himalayas", fetch_himalayas),
        (settings.enable_jobicy, "jobicy", fetch_jobicy),
        (settings.enable_arbeitnow, "arbeitnow", fetch_arbeitnow),
        (settings.enable_greenhouse and bool(settings.greenhouse_boards), "greenhouse", fetch_greenhouse),
        (settings.enable_lever and bool(settings.lever_sites), "lever", fetch_lever),
        (settings.enable_ashby and bool(settings.ashby_boards), "ashby", fetch_ashby),
        (settings.enable_career_pages and bool(settings.career_pages), "career_pages", fetch_career_pages),
        (settings.enable_email_alerts and bool(settings.email_alerts_username and settings.email_alerts_password), "email_alerts", fetch_email_alerts),
        (settings.enable_rss_feeds and bool(settings.rss_feeds), "rss_feeds", fetch_rss_feeds),
    ]:
        if enabled:
            sources.append((name, function))
    return sources


__all__ = [
    "fetch_arbeitnow", "fetch_remoteok", "fetch_remotive", "fetch_himalayas",
    "fetch_greenhouse", "fetch_lever", "fetch_ashby", "fetch_career_pages", "fetch_jobicy",
    "fetch_email_alerts", "fetch_rss_feeds", "enabled_sources",
]
