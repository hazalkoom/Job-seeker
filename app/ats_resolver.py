"""Resolve aggregator/alert jobs to direct public ATS postings or enrich public job pages."""
from __future__ import annotations

import csv
import json
import logging
import re
from dataclasses import replace
from pathlib import Path
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from app.models import Job
from app.sources.common import HEADERS, clean_html

logger = logging.getLogger(__name__)
USER_AGENT = HEADERS.get("User-Agent", "PersonalJobHunter/2.0")

ATS_CSV_PATH = Path("data/ats_companies.csv")

_COMPANY_SUFFIXES = re.compile(
    r"\b(?:inc|incorporated|llc|ltd|limited|corp|corporation|co|company|gmbh|ag|plc|"
    r"group|holdings|technologies|technology|tech|software|solutions|systems|labs|studio|studios|"
    r"egypt|mena|emea|global|international|hq)\b",
    re.I,
)

# Cache of (ats, slug) -> list of normalized posting dicts within a process run
_BOARD_CACHE: dict[tuple[str, str], list[dict]] = {}
# Negative cache of company names that already missed all probes in this process
_NEGATIVE_COMPANY_CACHE: set[str] = set()


def clear_resolver_cache() -> None:
    """Clear in-memory board and negative caches (useful in tests)."""
    _BOARD_CACHE.clear()
    _NEGATIVE_COMPANY_CACHE.clear()


def _normalize_text(value: str) -> str:
    text = (value or "").lower()
    text = re.sub(r"\bback[- ]+end\b", "backend", text)
    text = re.sub(r"\bfront[- ]+end\b", "frontend", text)
    text = re.sub(r"\bfull[- ]+stack\b", "fullstack", text)
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _title_tokens(title: str) -> set[str]:
    stop = {"the", "and", "for", "with", "at", "in", "of", "to", "a", "an", "remote", "hybrid", "onsite", "egypt", "cairo"}
    return {tok for tok in _normalize_text(title).split() if len(tok) >= 2 and tok not in stop}


def titles_match(target_title: str, candidate_title: str) -> bool:
    """Return True when target_title and candidate_title refer to the same role."""
    norm_a = _normalize_text(target_title)
    norm_b = _normalize_text(candidate_title)
    if not norm_a or not norm_b:
        return False
    if norm_a == norm_b or norm_a in norm_b or norm_b in norm_a:
        return True
    tokens_a = _title_tokens(target_title)
    tokens_b = _title_tokens(candidate_title)
    if not tokens_a or not tokens_b:
        return False
    overlap = len(tokens_a & tokens_b)
    min_len = min(len(tokens_a), len(tokens_b))
    max_len = max(len(tokens_a), len(tokens_b))
    if min_len >= 2 and overlap == min_len and (overlap / max_len) >= 0.6:
        return True
    return (overlap / max_len) >= 0.75


def derive_company_slugs(company: str) -> list[str]:
    """Generate ordered ATS slug candidates for a company name."""
    raw = (company or "").strip()
    if not raw or raw.lower() in {"unknown", "unknown company", "confidential"}:
        return []
    # Strip parentheticals and region suffixes after dashes
    cleaned = re.sub(r"\([^)]*\)", " ", raw)
    cleaned = re.split(r"\s+[–—|]\s+", cleaned)[0].strip()

    stripped = _COMPANY_SUFFIXES.sub(" ", cleaned)
    candidates: list[str] = []
    for variant in (cleaned, stripped):
        compact = re.sub(r"[^a-z0-9]+", "", variant.lower())
        dashed = re.sub(r"[^a-z0-9]+", "-", variant.lower()).strip("-")
        for slug in (compact, dashed):
            if slug and len(slug) >= 2 and slug not in candidates:
                candidates.append(slug)
    return candidates[:4]


def _load_known_ats_entries(csv_path: Path = ATS_CSV_PATH) -> list[tuple[str, str, str]]:
    if not csv_path.exists():
        return []
    entries: list[tuple[str, str, str]] = []
    try:
        with csv_path.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                ats = (row.get("ats") or "").strip().lower()
                slug = (row.get("slug") or "").strip()
                company = (row.get("company") or slug).strip()
                if ats and slug:
                    entries.append((ats, slug, company))
    except Exception as exc:
        logger.debug("Could not read ATS CSV %s: %s", csv_path, exc)
    return entries


def _persist_ats_entry(ats: str, slug: str, company: str, csv_path: Path = ATS_CSV_PATH) -> None:
    existing = _load_known_ats_entries(csv_path)
    for ex_ats, ex_slug, _ in existing:
        if ex_ats == ats.lower() and ex_slug.lower() == slug.lower():
            return
    try:
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        write_header = not csv_path.exists() or csv_path.stat().st_size == 0
        with csv_path.open("a", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            if write_header:
                writer.writerow(["ats", "slug", "company", "remote_friendly", "egypt_presence"])
            writer.writerow([ats.lower(), slug, company, "true", "true"])
    except Exception as exc:
        logger.debug("Could not persist discovered ATS entry (%s, %s): %s", ats, slug, exc)


def _http_get(url: str, *, headers: dict[str, str], timeout: float):
    return httpx.get(url, headers=headers, timeout=timeout, follow_redirects=True)


def _fetch_board_postings(ats: str, slug: str, timeout: float = 4.0) -> list[dict]:
    cache_key = (ats.lower(), slug.lower())
    if cache_key in _BOARD_CACHE:
        return _BOARD_CACHE[cache_key]

    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    postings: list[dict] = []
    try:
        if ats == "greenhouse":
            resp = _http_get(
                f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true",
                headers=headers,
                timeout=timeout,
            )
            if resp.status_code == 200:
                for item in resp.json().get("jobs", []):
                    postings.append({
                        "source": "greenhouse",
                        "source_id": str(item.get("id") or item.get("absolute_url") or ""),
                        "title": item.get("title") or "",
                        "url": item.get("absolute_url") or "",
                        "location": (item.get("location") or {}).get("name") or "",
                        "description": clean_html(item.get("content") or ""),
                    })
        elif ats == "ashby":
            resp = _http_get(
                f"https://api.ashbyhq.com/posting-api/job-board/{slug}",
                headers=headers,
                timeout=timeout,
            )
            if resp.status_code == 200:
                for item in resp.json().get("jobs", []):
                    if item.get("isListed") is False:
                        continue
                    postings.append({
                        "source": "ashby",
                        "source_id": str(item.get("id") or item.get("jobUrl") or ""),
                        "title": item.get("title") or "",
                        "url": item.get("jobUrl") or item.get("applyUrl") or "",
                        "location": item.get("location") or "",
                        "description": clean_html(item.get("descriptionHtml") or item.get("descriptionPlain") or ""),
                    })
        elif ats == "lever":
            resp = _http_get(
                f"https://api.lever.co/v0/postings/{slug}?mode=json",
                headers=headers,
                timeout=timeout,
            )
            if resp.status_code == 200 and isinstance(resp.json(), list):
                for item in resp.json():
                    postings.append({
                        "source": "lever",
                        "source_id": str(item.get("id") or item.get("hostedUrl") or ""),
                        "title": item.get("text") or "",
                        "url": item.get("hostedUrl") or item.get("applyUrl") or "",
                        "location": (item.get("categories") or {}).get("location") or "",
                        "description": clean_html(
                            f"{item.get('descriptionPlain') or item.get('description') or ''} "
                            f"{item.get('additionalPlain') or ''}"
                        ),
                    })
        elif ats == "workable":
            resp = _http_get(
                f"https://apply.workable.com/api/v1/widget/accounts/{slug}",
                headers=headers,
                timeout=timeout,
            )
            if resp.status_code == 200:
                for item in resp.json().get("jobs", []):
                    shortcode = item.get("shortcode") or ""
                    url = item.get("url") or (f"https://apply.workable.com/{slug}/j/{shortcode}/" if shortcode else "")
                    locs = [
                        part
                        for part in (item.get("city"), item.get("country"))
                        if part
                    ]
                    postings.append({
                        "source": "workable",
                        "source_id": str(shortcode or url),
                        "title": item.get("title") or "",
                        "url": url,
                        "location": ", ".join(locs) or item.get("location") or "",
                        "description": clean_html(item.get("description") or ""),
                    })
        elif ats == "smartrecruiters":
            resp = _http_get(
                f"https://api.smartrecruiters.com/v1/companies/{slug}/postings",
                headers=headers,
                timeout=timeout,
            )
            if resp.status_code == 200:
                for item in resp.json().get("content", []):
                    pid = item.get("id") or ""
                    loc_obj = item.get("location") or {}
                    locs = [part for part in (loc_obj.get("city"), loc_obj.get("country")) if part]
                    postings.append({
                        "source": "smartrecruiters",
                        "source_id": str(pid),
                        "title": item.get("name") or "",
                        "url": f"https://jobs.smartrecruiters.com/{slug}/{pid}" if pid else "",
                        "location": ", ".join(locs),
                        "description": clean_html(item.get("jobAd", {}).get("sections", {}).get("jobDescription", {}).get("text") or ""),
                    })
        elif ats == "recruitee":
            resp = _http_get(
                f"https://{slug}.recruitee.com/api/offers",
                headers=headers,
                timeout=timeout,
            )
            if resp.status_code == 200:
                for item in resp.json().get("offers", []):
                    postings.append({
                        "source": "recruitee",
                        "source_id": str(item.get("id") or item.get("careers_url") or ""),
                        "title": item.get("title") or "",
                        "url": item.get("careers_url") or "",
                        "location": item.get("location") or item.get("city") or "",
                        "description": clean_html(f"{item.get('description') or ''} {item.get('requirements') or ''}"),
                    })
    except Exception as exc:
        logger.debug("ATS probe failed for %s/%s: %s", ats, slug, exc)

    _BOARD_CACHE[cache_key] = postings
    return postings


def enrich_wuzzuf_public_job(job: Job, timeout: float = 5.0) -> Job:
    """Fetch public Wuzzuf job page JSON-LD / HTML to populate full description and company."""
    host = (urlparse(job.url).hostname or "").lower()
    if "wuzzuf.net" not in host:
        return job
    try:
        resp = _http_get(
            job.url,
            headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"},
            timeout=timeout,
        )
        if resp.status_code != 200 or not resp.text:
            return job
        soup = BeautifulSoup(resp.text, "html.parser")
        description = ""
        company = job.company
        location = job.location
        for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
            raw_json = (script.string or script.get_text() or "").strip()
            if not raw_json:
                continue
            try:
                data = json.loads(raw_json)
            except Exception:
                continue
            items = data if isinstance(data, list) else [data]
            for item in items:
                if not isinstance(item, dict) or item.get("@type") != "JobPosting":
                    continue
                desc_html = item.get("description") or ""
                if desc_html:
                    description = clean_html(desc_html)
                org = item.get("hiringOrganization")
                if isinstance(org, dict) and org.get("name") and company in {"", "Unknown company"}:
                    company = clean_html(str(org["name"]))
                job_loc = item.get("jobLocation")
                if isinstance(job_loc, dict):
                    addr = job_loc.get("address") or {}
                    if isinstance(addr, dict):
                        parts = [addr.get("addressLocality"), addr.get("addressRegion"), addr.get("addressCountry")]
                        loc_str = ", ".join(str(p) for p in parts if p)
                        if loc_str and location in {"", "Location not supplied"}:
                            location = loc_str
        if not description:
            meta_desc = soup.find("meta", attrs={"name": "description"}) or soup.find("meta", attrs={"property": "og:description"})
            if meta_desc and meta_desc.get("content"):
                description = clean_html(str(meta_desc.get("content")))
        if description and len(description) > len(job.description or ""):
            return replace(
                job,
                company=company,
                location=location,
                description=description,
                description_quality="full" if len(description) >= 240 else "summary",
            )
    except Exception as exc:
        logger.debug("Wuzzuf public page enrichment failed for %s: %s", job.url, exc)
    return job


def resolve_job_to_ats(
    job: Job,
    *,
    probe_unknown_companies: bool = True,
    persist_discovered: bool = True,
    csv_path: Path = ATS_CSV_PATH,
    timeout: float = 4.0,
) -> Job:
    """Resolve an alert/aggregator job to its direct public ATS URL when available."""
    if not job.source.endswith("_alert") and job.description_quality == "full":
        return job

    # Enrich Wuzzuf jobs first so "Unknown company" or snippet descriptions get populated
    if job.source == "wuzzuf_alert" and (job.company in {"", "Unknown company"} or job.description_quality != "full"):
        job = enrich_wuzzuf_public_job(job, timeout=timeout)

    company_norm = _normalize_text(job.company)
    if not company_norm or company_norm in {"unknown company", "unknown", "confidential"}:
        return job

    known_entries = _load_known_ats_entries(csv_path)
    candidate_probes: list[tuple[str, str, bool]] = []

    # 1. Check known ATS companies CSV first
    for ats, slug, known_co in known_entries:
        known_norm = _normalize_text(known_co)
        if known_norm == company_norm or slug.lower() == company_norm.replace(" ", ""):
            candidate_probes.append((ats, slug, False))

    # 2. Optionally probe derived slugs on major ATS platforms
    if not candidate_probes and probe_unknown_companies and company_norm not in _NEGATIVE_COMPANY_CACHE:
        slugs = derive_company_slugs(job.company)
        for slug in slugs[:2]:
            for ats in ("greenhouse", "ashby", "lever", "workable", "smartrecruiters", "recruitee"):
                candidate_probes.append((ats, slug, True))

    for ats, slug, is_new in candidate_probes:
        postings = _fetch_board_postings(ats, slug, timeout=timeout)
        if not postings:
            continue
        if is_new and persist_discovered:
            _persist_ats_entry(ats, slug, job.company, csv_path=csv_path)
        for post in postings:
            if titles_match(job.title, post.get("title") or "") and post.get("url"):
                resolved_desc = post.get("description") or job.description
                resolved_loc = post.get("location") or job.location
                return replace(
                    job,
                    source=post["source"],
                    source_id=post["source_id"] or post["url"],
                    url=post["url"],
                    location=resolved_loc,
                    description=resolved_desc,
                    description_quality="full" if len(resolved_desc or "") >= 200 else job.description_quality,
                )

    if probe_unknown_companies and not any( not is_new for _, _, is_new in candidate_probes ):
        _NEGATIVE_COMPANY_CACHE.add(company_norm)

    return job
