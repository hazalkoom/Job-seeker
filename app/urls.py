"""URL normalization helpers shared by discovery and application tracking."""
from __future__ import annotations

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
