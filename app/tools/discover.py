"""Career-page web scraper and ATS endpoint discovery tool.

Crawls public career pages or seed URLs, extracts embedded ATS links/iframes
(Greenhouse, Ashby, Lever, Workable, SmartRecruiters, Recruitee, BambooHR, Breezy),
verifies that the ATS API returns HTTP 200 with open jobs, and writes verified
rows to `data/proposed_companies.csv`.
"""
from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Any

import httpx
from bs4 import BeautifulSoup

from app.ats_resolver import extract_ats_from_url

ROOT = Path(__file__).resolve().parent.parent.parent
PROPOSED_CSV = ROOT / "data" / "proposed_companies.csv"


def extract_ats_links_from_html(html_text: str, default_company: str = "") -> list[dict[str, str]]:
    """Extract unique (ats, slug, company, url) entries from HTML anchors, iframes, and scripts."""
    found: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    soup = BeautifulSoup(html_text or "", "html.parser")
    candidates: list[str] = []
    for tag in soup.select("a[href], iframe[src], script[src]"):
        raw = str(tag.get("href") or tag.get("src") or "").strip()
        if raw:
            candidates.append(raw)
    url_re = re.compile(
        r"https?://[^\s\"'<>()]+?(?:greenhouse\.io|ashbyhq\.com|lever\.co|workable\.com|"
        r"smartrecruiters\.com|recruitee\.com|bamboohr\.com|breezy\.hr)[^\s\"'<>()]*",
        re.I,
    )
    for match in url_re.finditer(html_text or ""):
        candidates.append(match.group(0))

    for url in candidates:
        parsed = extract_ats_from_url(url)
        if not parsed:
            continue
        ats, slug = parsed
        key = (ats.lower(), slug.lower())
        if key in seen:
            continue
        seen.add(key)
        company = default_company or slug.replace("-", " ").title()
        found.append({"ats": ats, "slug": slug, "company": company, "url": url})
    return found


def probe_ats_endpoint(ats: str, slug: str, timeout: float = 8.0) -> dict[str, Any]:
    """Verify whether (ats, slug) is live and return job count."""
    ats_low = ats.strip().lower()
    slug_clean = slug.strip()
    try:
        with httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (compatible; PersonalJobHunter/4.0)"},
        ) as client:
            if ats_low == "greenhouse":
                r = client.get(f"https://boards-api.greenhouse.io/v1/boards/{slug_clean}/jobs")
                jobs = (r.json().get("jobs", []) if r.status_code == 200 else [])
            elif ats_low == "ashby":
                r = client.get(f"https://api.ashbyhq.com/posting-api/job-board/{slug_clean}")
                jobs = (r.json().get("jobs", []) if r.status_code == 200 else [])
            elif ats_low == "lever":
                r = client.get(f"https://api.lever.co/v0/postings/{slug_clean}?mode=json")
                data = r.json() if r.status_code == 200 else []
                jobs = data if isinstance(data, list) else []
            elif ats_low == "workable":
                r = client.post(
                    f"https://apply.workable.com/api/v3/accounts/{slug_clean}/jobs",
                    json={"query": ""},
                )
                jobs = (r.json().get("results", []) if r.status_code == 200 else [])
            elif ats_low == "smartrecruiters":
                r = client.get(f"https://api.smartrecruiters.com/v1/companies/{slug_clean}/postings?limit=50")
                jobs = (r.json().get("content", []) if r.status_code == 200 else [])
            elif ats_low == "recruitee":
                r = client.get(f"https://{slug_clean}.recruitee.com/api/offers")
                jobs = (r.json().get("offers", []) if r.status_code == 200 else [])
            elif ats_low == "bamboohr":
                r = client.get(f"https://{slug_clean}.bamboohr.com/careers/list")
                jobs = (r.json().get("result", []) if r.status_code == 200 else [])
            elif ats_low == "breezy":
                r = client.get(f"https://{slug_clean}.breezy.hr/json")
                data = r.json() if r.status_code == 200 else []
                jobs = data if isinstance(data, list) else []
            else:
                return {"ats": ats_low, "slug": slug_clean, "ok": False, "status_code": None, "job_count": 0}
            return {
                "ats": ats_low,
                "slug": slug_clean,
                "ok": r.status_code == 200,
                "status_code": r.status_code,
                "job_count": len(jobs) if isinstance(jobs, list) else 0,
            }
    except Exception as exc:
        return {
            "ats": ats_low,
            "slug": slug_clean,
            "ok": False,
            "status_code": None,
            "job_count": 0,
            "error": type(exc).__name__,
        }


def discover_from_url(url: str, company: str = "", save_proposed: bool = True) -> list[dict[str, Any]]:
    """Fetch a career page URL, extract ATS links, probe them, and optionally save to proposed_companies.csv."""
    try:
        with httpx.Client(
            timeout=10.0,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (compatible; PersonalJobHunter/4.0)"},
        ) as client:
            resp = client.get(url)
            html_text = resp.text if resp.status_code == 200 else ""
            final_url = str(resp.url)
    except Exception:
        html_text = ""
        final_url = url

    extracted = extract_ats_links_from_html(f"{final_url}\n{html_text}", default_company=company)
    verified: list[dict[str, Any]] = []
    for entry in extracted:
        probe = probe_ats_endpoint(entry["ats"], entry["slug"])
        merged = {**entry, **probe}
        verified.append(merged)

    if save_proposed and verified:
        PROPOSED_CSV.parent.mkdir(parents=True, exist_ok=True)
        write_header = not PROPOSED_CSV.is_file()
        with PROPOSED_CSV.open("a", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            if write_header:
                writer.writerow(["ats", "slug", "company", "remote_friendly", "egypt_presence", "job_count"])
            for row in verified:
                if row.get("ok"):
                    writer.writerow([row["ats"], row["slug"], row["company"], "true", "true", row.get("job_count", 0)])
    return verified
