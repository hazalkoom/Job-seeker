"""URL normalization helpers shared by discovery and application tracking."""
from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


def canonical_job_url(value: str) -> str:
    """Remove common tracking parameters without discarding job identifiers."""
    try:
        raw = str(value or "").strip()
        parsed = urlsplit(raw)
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
            return raw.lower()
        tracking = {"fbclid", "gclid", "mc_cid", "mc_eid", "ref", "source"}
        query = [
            (key, item)
            for key, item in parse_qsl(parsed.query, keep_blank_values=True)
            if not key.lower().startswith("utm_") and key.lower() not in tracking
        ]
        return urlunsplit(
            (
                parsed.scheme.lower(),
                parsed.netloc.lower(),
                parsed.path.rstrip("/"),
                urlencode(query, doseq=True),
                "",
            )
        )
    except (ValueError, TypeError):
        return str(value or "").strip().lower()

def ats_posting_key(url: str) -> str:
    """Recognize posting URLs and their form variants on known ATS hosts."""
    parsed = urlsplit(canonical_job_url(url))
    host = parsed.hostname or ""
    path = parsed.path.strip("/")
    patterns = {
        "boards.greenhouse.io": ("greenhouse", r"([\w.-]+)/jobs/(\d+)"),
        "job-boards.greenhouse.io": ("greenhouse", r"([\w.-]+)/jobs/(\d+)"),
        "jobs.lever.co": ("lever", r"([\w.-]+)/([\w-]+)(?:/apply)?"),
        "jobs.eu.lever.co": ("lever", r"([\w.-]+)/([\w-]+)(?:/apply)?"),
        "jobs.ashbyhq.com": ("ashby", r"([\w.-]+)/([\w-]+)(?:/application)?"),
        "apply.workable.com": ("workable", r"([\w.-]+)/j/([\w-]+)(?:/apply)?"),
        "jobs.smartrecruiters.com": ("smartrecruiters", r"([\w.-]+)/(\d+)(?:-[^/]+)?"),
    }
    if host in patterns:
        provider, pattern = patterns[host]
        match = re.fullmatch(pattern, path, re.I)
        if match:
            board, posting_id = match.groups()
            return f"{provider}:{board.casefold()}:{posting_id.casefold()}"
    return ""
