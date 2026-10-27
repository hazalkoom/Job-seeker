from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

DEFAULT_GOOGLE_JOBS_FIXED_QUERY = (
    '("junior backend developer" OR "junior backend engineer" '
    'OR "junior full stack developer" OR "junior full-stack developer") Egypt'
)

DEFAULT_GOOGLE_JOBS_ROTATING_QUERIES = (
    '("junior Node.js developer" OR "junior Node.js engineer") Egypt',
    '("junior Python developer" OR "junior Python engineer") Egypt',
    '("junior Django developer" OR "junior FastAPI developer") Egypt',
    '("junior Angular developer" OR "junior React developer") Egypt',
    '("entry level software engineer" OR "graduate software engineer") Egypt',
    '("software engineering intern" OR "backend developer intern") Egypt',
    '("associate software engineer" OR "trainee software developer") Egypt',
    '("junior Java developer" OR "junior Java engineer") Egypt',
    '("junior AI application engineer" OR "junior AI engineer" OR "junior LLM engineer") Egypt',
    '("junior backend developer" OR "junior backend engineer") Cairo',
    '("junior backend developer" OR "junior backend engineer") remote worldwide',
    '("junior Python developer" OR "junior Python engineer") remote worldwide',
    '("junior Node.js developer" OR "junior Node.js engineer") remote worldwide',
    '("junior full stack developer" OR "junior full-stack developer") remote worldwide',
    '("graduate software engineer" OR "entry level software engineer") remote worldwide',
    '("software engineer intern" OR "backend developer intern") remote worldwide',
    '("junior AI application engineer" OR "junior LLM engineer") remote worldwide',
    '"work from anywhere" junior software developer',
    '("junior backend developer" OR "junior full stack developer") remote Europe',
    '("junior software developer" OR "entry level software engineer") remote EMEA',
    '"AI coding tasks" software engineer remote',
    '("junior developer" OR "software engineer intern") remote Poland',
    '("junior developer" OR "software engineer intern") remote Germany',
    '("junior developer" OR "software engineer intern") remote Netherlands',
    '("junior developer" OR "software engineer intern") remote France',
    '("junior developer" OR "software engineer intern") remote Greece',
    '("junior backend developer" OR "junior software engineer") remote Egypt',
    '("junior backend developer" OR "junior software engineer") Mansoura',
)


def _bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _pairs(name: str) -> list[tuple[str, str]]:
    """Parse NAME:slug;NAME:slug values without requiring JSON in .env."""
    result: list[tuple[str, str]] = []
    for item in os.getenv(name, "").split(";"):
        item = item.strip()
        if not item or ":" not in item:
            continue
        company, slug = item.split(":", 1)
        company, slug = company.strip(), slug.strip()
        if company and slug:
            result.append((company, slug))
    return result


def _career_pages() -> list[tuple[str, str]]:
    """Parse COMPANY|URL;COMPANY|URL values for schema.org career pages."""
    result: list[tuple[str, str]] = []
    for item in os.getenv("CAREER_PAGES", "").split(";"):
        item = item.strip()
        if "|" not in item:
            continue
        company, url = item.split("|", 1)
        company, url = company.strip(), url.strip()
        if company and url.startswith("https://"):
            result.append((company, url))
    return result


def _named_urls(name: str) -> list[tuple[str, str]]:
    """Parse NAME|URL;NAME|URL entries for public RSS/Atom feeds."""
    result: list[tuple[str, str]] = []
    for item in os.getenv(name, "").split(";"):
        item = item.strip()
        if "|" not in item:
            continue
        label, url = item.split("|", 1)
        label, url = label.strip(), url.strip()
        if label and url.startswith(("https://", "http://")):
            result.append((label, url))
    return result


def _query_list(name: str, defaults: tuple[str, ...]) -> tuple[str, ...]:
    """Read semicolon-separated search queries, preserving safe defaults when empty."""
    raw = os.getenv(name, "").strip()
    if not raw:
        return defaults
    return tuple(item.strip() for item in raw.split(";") if item.strip())


@dataclass(frozen=True, slots=True)
class Settings:
    telegram_bot_token: str = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    telegram_chat_id: str = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    min_match_score: int = int(os.getenv("MIN_MATCH_SCORE", "70"))
    max_posting_age_days: int = int(os.getenv("MAX_POSTING_AGE_DAYS", "7"))
    request_timeout_seconds: float = float(os.getenv("REQUEST_TIMEOUT_SECONDS", "18"))
    notify_review_candidates: bool = _bool("NOTIFY_REVIEW_CANDIDATES", False)
    review_digest_size: int = max(1, min(15, int(os.getenv("REVIEW_DIGEST_SIZE", "5"))))
    max_required_experience_years: float = max(0.0, float(os.getenv("MAX_REQUIRED_EXPERIENCE_YEARS", "2")))
    require_full_description_for_match: bool = _bool("REQUIRE_FULL_DESCRIPTION_FOR_MATCH", True)
    candidate_display_name: str = os.getenv("CANDIDATE_DISPLAY_NAME", "").strip()
    candidate_summary: str = os.getenv("CANDIDATE_SUMMARY", "Junior backend/full-stack developer based in Egypt, focused on Python, Django, FastAPI, Node.js, APIs, databases, and practical software projects.").strip()
    candidate_linkedin_url: str = os.getenv("CANDIDATE_LINKEDIN_URL", "").strip()
    candidate_portfolio_url: str = os.getenv("CANDIDATE_PORTFOLIO_URL", "").strip()
    candidate_cv_url: str = os.getenv("CANDIDATE_CV_URL", "").strip()

    # Autonomous application submission is opt-in and bounded. The runner only
    # submits when its strict eligibility/form-completeness policy passes.
    auto_apply_enabled: bool = _bool("AUTO_APPLY_ENABLED", False)
    auto_apply_max_per_day: int = max(0, min(10, int(os.getenv("AUTO_APPLY_MAX_PER_DAY", "10"))))
    auto_apply_min_score: int = max(0, min(100, int(os.getenv("AUTO_APPLY_MIN_SCORE", "60"))))
    auto_apply_delay_seconds: float = max(0.0, float(os.getenv("AUTO_APPLY_DELAY_SECONDS", "8")))
    auto_apply_headless: bool = _bool("AUTO_APPLY_HEADLESS", True)
    auto_apply_resume_path: str = os.getenv("AUTO_APPLY_RESUME_PATH", "private/Mohamed_Ahmed_CV.pdf").strip()
    auto_apply_timeout_seconds: int = max(10, min(90, int(os.getenv("AUTO_APPLY_TIMEOUT_SECONDS", "30"))))

    enable_arbeitnow: bool = _bool("ENABLE_ARBEITNOW", True)
    enable_remoteok: bool = _bool("ENABLE_REMOTEOK", True)
    enable_remotive: bool = _bool("ENABLE_REMOTIVE", True)
    enable_himalayas: bool = _bool("ENABLE_HIMALAYAS", True)
    enable_jobicy: bool = _bool("ENABLE_JOBICY", True)

    # International job APIs that don't require API keys.
    enable_european_tech_opportunities: bool = _bool(
        "ENABLE_EUROPEAN_TECH_OPPORTUNITIES", True
    )
    enable_nomado24: bool = _bool("ENABLE_NOMADO24", True)
    european_tech_opportunities_max_pages: int = int(
        os.getenv("EUROPEAN_TECH_OPPORTUNITIES_MAX_PAGES", "3")
    )
    nomado24_language: str = os.getenv("NOMADO24_LANGUAGE", "en").strip() or "en"
    nomado24_max_pages: int = int(os.getenv("NOMADO24_MAX_PAGES", "1"))
    nomado24_search_terms: tuple[str, ...] = _query_list(
        "NOMADO24_SEARCH_TERMS",
        ("junior", "entry level", "graduate", "internship", "trainee", "no experience", "junior backend", "junior python"),
    )

    enable_greenhouse: bool = _bool("ENABLE_GREENHOUSE", True)
    enable_lever: bool = _bool("ENABLE_LEVER", True)
    enable_ashby: bool = _bool("ENABLE_ASHBY", True)
    enable_career_pages: bool = _bool("ENABLE_CAREER_PAGES", True)
    enable_email_alerts: bool = _bool("ENABLE_EMAIL_ALERTS", False)
    enable_rss_feeds: bool = _bool("ENABLE_RSS_FEEDS", True)

    enable_google_jobs: bool = _bool("ENABLE_GOOGLE_JOBS", True)
    serpapi_api_key: str = os.getenv("SERPAPI_API_KEY", "").strip()
    google_jobs_fixed_query: str = os.getenv(
        "GOOGLE_JOBS_FIXED_QUERY", DEFAULT_GOOGLE_JOBS_FIXED_QUERY
    ).strip()
    google_jobs_rotating_queries: tuple[str, ...] = _query_list(
        "GOOGLE_JOBS_ROTATING_QUERIES", DEFAULT_GOOGLE_JOBS_ROTATING_QUERIES
    )

    email_alerts_imap_host: str = os.getenv(
        "EMAIL_ALERTS_IMAP_HOST", "imap.gmail.com"
    ).strip()
    email_alerts_imap_port: int = int(os.getenv("EMAIL_ALERTS_IMAP_PORT", "993"))
    email_alerts_username: str = os.getenv("EMAIL_ALERTS_USERNAME", "").strip()
    email_alerts_password: str = os.getenv("EMAIL_ALERTS_PASSWORD", "").strip()
    email_alerts_mailbox: str = os.getenv("EMAIL_ALERTS_MAILBOX", "INBOX").strip()
    email_alerts_lookback_days: int = int(os.getenv("EMAIL_ALERTS_LOOKBACK_DAYS", "14"))
    email_alerts_max_messages: int = int(os.getenv("EMAIL_ALERTS_MAX_MESSAGES", "300"))

    greenhouse_boards: tuple[tuple[str, str], ...] = tuple(_pairs("GREENHOUSE_BOARDS"))
    lever_sites: tuple[tuple[str, str], ...] = tuple(_pairs("LEVER_SITES"))
    ashby_boards: tuple[tuple[str, str], ...] = tuple(_pairs("ASHBY_BOARDS"))
    career_pages: tuple[tuple[str, str], ...] = tuple(_career_pages())
    rss_feeds: tuple[tuple[str, str], ...] = tuple(_named_urls("RSS_FEEDS"))

    database_path: str = os.getenv("DATABASE_PATH", str(ROOT / "jobs.sqlite3"))


settings = Settings()
