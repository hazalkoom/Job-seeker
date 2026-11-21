"""Hacker News 'Who is hiring?' monthly thread parser via Algolia HN API.

Extracts comments that link directly to supported public ATS job pages
(Greenhouse, Ashby, Lever, Workable, SmartRecruiters, Recruitee, BambooHR, Breezy).
"""
from __future__ import annotations

import html
import re

from app.models import Job
from app.sources.common import clean_html, get_json, normalize_job

_ATS_URL_RE = re.compile(
    r"https?://[^\s\"'<>()]+?(?:greenhouse\.io|ashbyhq\.com|lever\.co|workable\.com|"
    r"smartrecruiters\.com|recruitee\.com|bamboohr\.com|breezy\.hr)[^\s\"'<>()]*",
    re.I,
)


def parse_hn_comment(comment: dict) -> Job | None:
    raw_html = str(comment.get("comment_text") or comment.get("text") or "")
    if not raw_html:
        return None
    unescaped = html.unescape(raw_html)
    match = _ATS_URL_RE.search(unescaped)
    if not match:
        return None
    url = match.group(0).rstrip(".,;)")
    text = clean_html(unescaped)
    first_line = raw_html.split("<p>")[0]
    first_line_clean = clean_html(first_line)
    parts = [p.strip() for p in first_line_clean.split("|") if p.strip()]
    company = parts[0][:80] if parts else "Unknown company"
    title = parts[1][:120] if len(parts) >= 2 else "Software Engineer"
    location = parts[2][:120] if len(parts) >= 3 else ("Remote" if "remote" in first_line_clean.lower() else "")
    if not any(
        kw in title.lower()
        for kw in ("engineer", "developer", "backend", "full stack", "fullstack", "python", "node", "software", "qa", "support")
    ):
        for part in parts[1:]:
            if any(kw in part.lower() for kw in ("engineer", "developer", "backend", "full stack", "fullstack", "python", "software")):
                title = part[:120]
                break
    created_at = str(comment.get("created_at") or "")
    comment_id = str(comment.get("objectID") or comment.get("id") or url)
    remote = "remote" in first_line_clean.lower() or "remote" in location.lower()
    return normalize_job(
        source="hn_jobs",
        source_id=f"hn:{comment_id}",
        title=title,
        company=company,
        location=location or ("Remote" if remote else ""),
        url=url,
        description=text,
        posted_at=created_at,
        date_kind="posted" if created_at else "unknown",
        remote=remote,
        eligibility=first_line_clean[:240],
        description_quality="full" if len(text) >= 180 else "snippet",
    )


def fetch_jobs() -> list[Job]:
    jobs: list[Job] = []
    try:
        stories = get_json(
            "https://hn.algolia.com/api/v1/search_by_date",
            params={
                "query": '"Ask HN: Who is hiring?"',
                "tags": "story,author_whoishiring",
                "hitsPerPage": 1,
            },
        )
        hits = stories.get("hits", []) if isinstance(stories, dict) else []
        if not hits:
            return []
        story_id = hits[0].get("objectID")
        if not story_id:
            return []
        comments_resp = get_json(
            "https://hn.algolia.com/api/v1/search_by_date",
            params={
                "tags": f"comment,story_{story_id}",
                "hitsPerPage": 200,
            },
        )
        comment_hits = comments_resp.get("hits", []) if isinstance(comments_resp, dict) else []
        for comment in comment_hits:
            if not isinstance(comment, dict):
                continue
            job = parse_hn_comment(comment)
            if job:
                jobs.append(job)
    except Exception:
        return jobs
    return jobs
