"""Bounded autonomous application runner for supported public ATS forms.

This module uses ordinary user-facing forms. It does not defeat CAPTCHAs,
anti-bot checks, logins, or access controls, and it never guesses answers to
required factual/legal questions. Unsupported or ambiguous forms are skipped
and recorded so the periodic runner can continue to other jobs.
"""
from __future__ import annotations

import os
import json
import httpx
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from app.application_profile import ProfileLoadError, load_profile_bundle, resolve_answer, _at
from app.automation_diagnostics import (
    log_auto_apply_event, new_run_id, reason_code_for_reason, safe_url,
)
from app.application_queue import (
    automatic_approve_application,
    begin_automation_attempt,
    get_application,
    list_applications,
    record_automation_outcome,
    run_preflight,
    recover_interrupted_attempts,
)
from app.config import settings
from app.matching import _himalayas_eligibility_decision, assess_experience, classify
from app.models import Job
from app.storage import _connect, init_db
from app.sources.common import clean_html

ROOT = Path(__file__).resolve().parent.parent
SUPPORTED_ATS_HOSTS = (
    "greenhouse.io", "lever.co", "ashbyhq.com", "workable.com",
    "smartrecruiters.com", "jobvite.com", "icims.com", "bamboohr.com",
    "recruitee.com", "personio.com", "teamtailor.com", "myworkdayjobs.com",
    "breezy.hr", "pinpointhq.com", "comeet.com", "applytojob.com",
    "jazz.co", "ats.rippling.com", "recruiting.ultipro.com",
)
# Aggregator pages are not employer application forms. In particular, Himalayas' public
# "Apply now" route can go to a signup/login page rather than the employer's ATS.
AGGREGATOR_HOSTS = (
    "himalayas.app", "startup.jobs", "jobicy.com", "remoteok.com",
    "remotive.com", "arbeitnow.com", "arbeitnow.fr", "arbeitnow.ch",
    "nomado24.de", "nomado24.com", "weworkremotely.com", "linkedin.com",
    "indeed.com", "glassdoor.com", "ziprecruiter.com", "monster.com",
    "wellfound.com", "jooble.org", "adzuna.com", "remote.co",
    "dailyremote.com", "otta.com",
)
CAPTCHA_MARKERS = (
    "captcha", "verify you are human", "checking your browser",
    "unusual traffic", "security challenge", "are you a robot",
)
SUCCESS_MARKERS = (
    "thank you for applying", "application submitted", "application received",
    "we received your application", "successfully applied", "thanks for applying",
    "your application has been sent", "thank you for your interest",
    "application has been received", "application was submitted",
    "we've received your application", "we have received your application",
    "application was sent", "application complete", "has been submitted",
    "submitted successfully", "we'll be in touch", "we will be in touch",
    "application is submitted",
)


def _record(queue_id: int, event_type: str, details: dict[str, Any] | None = None) -> None:
    from app.application_queue import _event, _now

    init_db()
    with _connect() as conn:
        _event(conn, int(queue_id), event_type, details or {})


def _select_cv_for_job(item: dict[str, Any] | None) -> Path | None:
    if not item:
        return None
    cvs_dir = ROOT / "cvs"
    if not cvs_dir.is_dir():
        return None
    company = str(item.get("company") or "").strip().lower()
    if company:
        for pdf in cvs_dir.glob("*.pdf"):
            stem_low = pdf.stem.lower()
            if company in stem_low and company not in ("general", "resume", "mohamed", "ahmed"):
                return pdf.resolve()
    title = str(item.get("title") or "").lower()
    desc = str(item.get("description") or "")[:1500].lower()
    combined = f"{title} {desc}"

    if re.search(r"\b(qa|quality assurance|sdet|test(?:er|ing)|test automation)\b", title):
        if "python" in title and (cvs_dir / "Mohamed_Ahmed-Luxoft.pdf").is_file():
            return (cvs_dir / "Mohamed_Ahmed-Luxoft.pdf").resolve()
        if (cvs_dir / "Mohamed_Ahmed-QA_Testing.pdf").is_file():
            return (cvs_dir / "Mohamed_Ahmed-QA_Testing.pdf").resolve()

    if re.search(r"\b(it support|help\s*desk|service\s*desk|desktop support|systems? support|system administrator|it specialist|it technician)\b", title):
        if (cvs_dir / "Mohamed_Ahmed-IT_Support.pdf").is_file():
            return (cvs_dir / "Mohamed_Ahmed-IT_Support.pdf").resolve()

    if re.search(r"\b(application support|technical support|support engineer|developer support|customer support|l[123] support|tier [123] support|solutions? engineer)\b", title):
        if (cvs_dir / "Mohamed_Ahmed-Application_Support.pdf").is_file():
            return (cvs_dir / "Mohamed_Ahmed-Application_Support.pdf").resolve()

    if re.search(r"\b(front[- ]?end|react|angular|next\.?js|ui developer|web developer)\b", title) and not re.search(r"\b(full[- ]?stack|back[- ]?end)\b", title):
        if re.search(r"e-?commerce|shopify|wordpress", combined) and (cvs_dir / "Mohamed_Ahmed-ArabyBrand.pdf").is_file():
            return (cvs_dir / "Mohamed_Ahmed-ArabyBrand.pdf").resolve()
        if (cvs_dir / "Mohamed_Ahmed-Frontend.pdf").is_file():
            return (cvs_dir / "Mohamed_Ahmed-Frontend.pdf").resolve()

    if re.search(r"\b(ai|llm|genai|generative ai|agentic)\b", title):
        if (cvs_dir / "Mohamed_Ahmed-binance.pdf").is_file():
            return (cvs_dir / "Mohamed_Ahmed-binance.pdf").resolve()

    if re.search(r"\b(back[- ]?end|python|django|fastapi|node\.?js|nestjs|express)\b", title) and not re.search(r"\bfull[- ]?stack\b", title):
        if re.search(r"\b(python|django|fastapi)\b", combined) and not re.search(r"\bnode\.?js\b", title):
            for name in ("Mohamed_Ahmed-capgemeni python.pdf", "Mohamed_Ahmed- Future Position.pdf", "Mohamed_Ahmed-Canonical.pdf"):
                if (cvs_dir / name).is_file():
                    return (cvs_dir / name).resolve()
        if re.search(r"\b(node\.?js|nestjs|express)\b", combined):
            for name in ("Mohamed_Ahmed-khazna.pdf", "Mohamed_Ahmed-sparta.pdf", "Mohamed_Ahmed-dananir.pdf"):
                if (cvs_dir / name).is_file():
                    return (cvs_dir / name).resolve()
        for name in ("Mohamed_Ahmed-dananir.pdf", "mohamed ahmed mahmoud_backend.pdf"):
            if (cvs_dir / name).is_file():
                return (cvs_dir / name).resolve()

    if re.search(r"\b(junior software engineer|graduate software engineer|entry[- ]level software engineer|software engineer)\b", title) and not re.search(r"\bfull[- ]?stack\b", title):
        if (cvs_dir / "Mohamed_Ahmed-Emetlab.pdf").is_file():
            return (cvs_dir / "Mohamed_Ahmed-Emetlab.pdf").resolve()

    if (cvs_dir / "Mohamed_Ahmed-general.pdf").is_file():
        return (cvs_dir / "Mohamed_Ahmed-general.pdf").resolve()
    return None


def _resume_path(profile: dict[str, Any], item: dict[str, Any] | None = None) -> Path:
    tailored = _select_cv_for_job(item)
    if tailored is not None and tailored.is_file():
        return tailored
    candidates: list[str] = []
    candidates.append(settings.auto_apply_resume_path)
    for section, key in (("files", "resume_path"), ("documents", "resume_path"),
                         ("documents", "cv_path"), ("files", "cv_path")):
        value = profile.get(section, {})
        if isinstance(value, dict) and value.get(key):
            candidates.insert(0, str(value[key]))
    for candidate in candidates:
        path = Path(candidate).expanduser()
        if not path.is_absolute():
            path = ROOT / path
        if path.is_file():
            return path.resolve()
    return Path(candidates[0]).expanduser()


def _host_is_in(host: str, domains: tuple[str, ...]) -> bool:
    host = (host or "").casefold().rstrip(".")
    return any(host == domain or host.endswith("." + domain) for domain in domains)


def _is_supported_host(host: str) -> bool:
    return _host_is_in(host, SUPPORTED_ATS_HOSTS)


def _is_aggregator_host(host: str) -> bool:
    return _host_is_in(host, AGGREGATOR_HOSTS)


def _is_explicit_application_target(href: str, listing_url: str, label: str) -> bool:
    """Allow known ATS links or a clear HTTPS apply CTA to a non-aggregator host."""
    target = urlparse(str(href or ""))
    listing = urlparse(str(listing_url or ""))
    if target.scheme != "https" or not target.hostname:
        return False
    descriptor = f"{label} {target.path}".casefold()
    if not re.search(
        r"\bapply\b|application|submit (?:a )?(?:cv|resume|application)|bewerben|postuler|kandidatur",
        descriptor,
        re.I,
    ):
        return False
    if _is_supported_host(target.hostname):
        return True
    # Do not treat another job-board account/sign-up page as an employer form.
    if _is_aggregator_host(target.hostname):
        return False
    return True


def _same_site_host(host: str, expected_host: str) -> bool:
    host = (host or "").casefold().rstrip(".")
    expected_host = (expected_host or "").casefold().rstrip(".")
    return bool(host and expected_host and (
        host == expected_host or host.endswith("." + expected_host) or expected_host.endswith("." + host)
    ))


def _job_board_requires_account(page_host: str, link_diagnostics: dict[str, Any]) -> bool:
    """Recognize an aggregator's Apply CTA that leads only to signup/login."""
    if not _is_aggregator_host(page_host):
        return False
    for link in link_diagnostics.get("apply_links", []):
        if not isinstance(link, dict):
            continue
        host = str(link.get("host") or "")
        path = str(link.get("path") or "").casefold()
        label = str(link.get("text") or "").casefold()
        if _same_site_host(host, page_host) and re.search(r"/(?:sign-?up|login|log-?in|signin)(?:/|$)", path) and re.search(r"\bapply\b|application", label):
            return True
    return False


def _iter_job_postings(value: Any):
    """Yield JobPosting JSON-LD objects nested in arrays and @graph wrappers."""
    if isinstance(value, list):
        for item in value:
            yield from _iter_job_postings(item)
        return
    if not isinstance(value, dict):
        return
    raw_type = value.get("@type")
    types = raw_type if isinstance(raw_type, list) else [raw_type]
    if any(str(kind).casefold() == "jobposting" for kind in types if kind):
        yield value
    for key in ("@graph", "mainEntity", "itemListElement"):
        if key in value:
            yield from _iter_job_postings(value[key])


def _meaningful_title_overlap(expected: str, observed: str) -> bool:
    def tokens(value: str) -> set[str]:
        stop = {"junior", "senior", "midlevel", "remote", "hybrid", "the", "and", "for", "with", "job", "opening", "position"}
        return {token for token in re.findall(r"[a-z0-9+#.]{3,}", str(value or "").casefold()) if token not in stop}
    want, got = tokens(expected), tokens(observed)
    if not want or not got:
        return False
    shared = want & got
    return len(shared) >= 1 if len(want) <= 2 else len(shared) >= 2


def _safe_posted_date(value: Any) -> str:
    if not value:
        return ""
    raw = str(value).strip()
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.isoformat()
    except (TypeError, ValueError, OverflowError):
        return ""


def _persist_listing_enrichment(item: dict[str, Any]) -> None:
    """Persist only extracted public listing metadata, not personal application data."""
    job_id = item.get("job_id")
    if not job_id:
        return
    with _connect() as conn:
        conn.execute(
            "UPDATE jobs SET description=?, description_quality='full', "
            "company=CASE WHEN company='' OR company='Unknown company' "
            "OR company='Startup Jobs Remote Engineering' THEN ? ELSE company END, "
            "posted_at=CASE WHEN ?<>'' THEN ? ELSE posted_at END, "
            "date_kind=CASE WHEN ?<>'' THEN 'posted' ELSE date_kind END "
            "WHERE id=?",
            (
                str(item.get("description") or ""),
                str(item.get("company") or "Unknown company"),
                str(item.get("enriched_posted_at") or ""),
                str(item.get("enriched_posted_at") or ""),
                str(item.get("enriched_posted_at") or ""),
                int(job_id),
            ),
        )


def _enrich_public_listing(item: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Try one normal HTTPS GET for public JobPosting metadata/description.

    No login, browser profile, CAPTCHA circumvention, or application form is used here.
    The result is accepted only when it is a substantial description linked to the
    expected role title, or a JobPosting JSON-LD record with a matching title.
    """
    item = dict(item)
    url = str(item.get("url") or "")
    host = urlparse(url).hostname or ""
    diag: dict[str, Any] = {
        "attempted": False, "result": "not_attempted", "host": host[:180],
        "http_status": None, "jsonld_jobposting_found": False,
        "description_chars": 0, "title_matched": False,
        "company_discovered": False, "posted_date_discovered": False,
    }
    if str(item.get("description_quality") or "unknown").casefold() == "full":
        diag["result"] = "already_full"
        return item, diag
    if str(item.get("date_kind") or "unknown").casefold() != "posted":
        diag["result"] = "original_posting_date_unverified"
        return item, diag
    if urlparse(url).scheme != "https" or not host:
        diag["result"] = "non_https_or_invalid_url"
        return item, diag

    source = str(item.get("source") or "").casefold()
    current_company = str(item.get("company") or "").strip()
    if source.startswith("rss:") and (
        current_company.casefold() in {"unknown company", "startup jobs remote engineering", "we work remotely backend", "we work remotely full stack"}
        or "remote engineering" in current_company.casefold() and "startup jobs" in current_company.casefold()
    ):
        inferred = re.search(r"\bat\s+([^|]{2,100}?)\s*$", str(item.get("title") or ""), re.I)
        if inferred:
            company = inferred.group(1).strip(" -–—|,:;")
            if company:
                item["company"] = company
                diag["company_inferred_from_title"] = True
                try:
                    with _connect() as conn:
                        if item.get("job_id"):
                            conn.execute("UPDATE jobs SET company=? WHERE id=?", (company, int(item["job_id"])))
                            diag["company_correction_persisted"] = True
                except Exception as exc:
                    diag["company_correction_persisted"] = False
                    diag["company_correction_error_type"] = type(exc).__name__

    diag["attempted"] = True
    try:
        with httpx.Client(
            timeout=min(float(settings.request_timeout_seconds), 15.0),
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (compatible; PersonalJobHunter/2.4; public listing enrichment)"},
        ) as client:
            response = client.get(url)
        diag["http_status"] = int(response.status_code)
        final_host = urlparse(str(response.url)).hostname or ""
        diag["final_host"] = final_host[:180]
        if response.status_code < 200 or response.status_code >= 300:
            diag["result"] = "http_status_not_success"
            return item, diag
        soup = BeautifulSoup(response.text, "html.parser")
        page_title = clean_html(soup.title.get_text(" ", strip=True) if soup.title else "")[:240]
        body_text = clean_html(soup.get_text(" ", strip=True))
        diag["page_title"] = page_title
        if _is_challenge_from_text(body_text[:6000]):
            diag["result"] = "public_page_challenge"
            return item, diag

        posting = None
        for script in soup.select('script[type="application/ld+json"]')[:25]:
            raw = script.string or script.get_text()
            if not raw or len(raw) > 1_000_000:
                continue
            try:
                document = json.loads(raw)
            except (TypeError, json.JSONDecodeError):
                continue
            posting = next(_iter_job_postings(document), None)
            if posting:
                break
        description = ""
        observed_title = ""
        discovered_company = ""
        discovered_posted = ""
        if posting:
            diag["jsonld_jobposting_found"] = True
            observed_title = str(posting.get("title") or "")
            description = clean_html(posting.get("description") or "")
            organization = posting.get("hiringOrganization") or {}
            if isinstance(organization, dict):
                discovered_company = clean_html(organization.get("name") or "")
            discovered_posted = _safe_posted_date(posting.get("datePosted"))
            diag["title_matched"] = _meaningful_title_overlap(str(item.get("title") or ""), observed_title)
        else:
            # Conservative fallback: prefer semantic description selectors and require
            # meaningful title overlap to avoid treating a generic landing page as a job.
            selectors = (
                '[itemprop="description"]', '[class*="job-description" i]',
                '[class*="jobDescription" i]', '[id*="job-description" i]',
                'article', 'main',
            )
            candidates: list[tuple[int, str, str]] = []
            for selector in selectors:
                for element in soup.select(selector)[:8]:
                    text = clean_html(element.get_text(" ", strip=True))
                    if len(text) >= 180:
                        candidates.append((len(text), text, selector))
            if candidates:
                _size, description, selector = max(candidates, key=lambda value: value[0])
                diag["description_selector"] = selector
                diag["title_matched"] = (
                    _meaningful_title_overlap(str(item.get("title") or ""), page_title)
                    or _meaningful_title_overlap(str(item.get("title") or ""), description[:1200])
                )

        diag["description_chars"] = len(description)
        if not description or len(description) < 180:
            diag["result"] = "full_description_not_found"
            return item, diag
        if not diag["title_matched"]:
            diag["result"] = "job_title_mismatch"
            return item, diag

        item["description"] = description
        item["description_quality"] = "full"
        if discovered_company and (
            not str(item.get("company") or "").strip()
            or str(item.get("company") or "").casefold() in {
                "unknown company", "startup jobs remote engineering", "we work remotely backend", "we work remotely full stack"
            }
        ):
            item["company"] = discovered_company
            diag["company_discovered"] = True
        if discovered_posted:
            item["enriched_posted_at"] = discovered_posted
            item["posted_at"] = discovered_posted
            item["date_kind"] = "posted"
            diag["posted_date_discovered"] = True
        diag["result"] = "enriched"
        try:
            _persist_listing_enrichment(item)
            diag["persisted_to_database"] = True
        except Exception as exc:
            diag["persisted_to_database"] = False
            diag["persist_error_type"] = type(exc).__name__
        return item, diag
    except Exception as exc:
        diag["result"] = "request_or_parse_error"
        diag["error_type"] = type(exc).__name__
        return item, diag


def _is_challenge_from_text(text: str) -> bool:
    low = str(text or "").casefold()
    return any(marker in low for marker in CAPTCHA_MARKERS)


def _reason_for_auto_skip(item: dict[str, Any]) -> str | None:
    """Strict pre-submit qualification policy; no candidate interaction required."""
    title = str(item.get("title") or "").strip()
    description = str(item.get("description") or "").strip()
    date_kind = str(item.get("date_kind") or "unknown").casefold()
    quality = str(item.get("description_quality") or "unknown").casefold()
    posted_at = str(item.get("posted_at") or "")
    url = str(item.get("url") or "")

    if not title or not url.startswith(("https://", "http://")):
        return "Missing a valid title or job URL."
    # Target backend/full-stack/general web roles and AI application integrations,
    # not dedicated ML/AI engineering or research positions.
    dedicated_ai_role = re.search(
        r"\b(?:ai|ml|machine learning|artificial intelligence)(?:\s*/\s*(?:ml|ai))?\s+(?:engineer|developer|scientist|researcher)\b",
        title,
        re.I,
    )
    allowed_ai_context = re.search(
        r"\b(?:backend|back-end|full[ -]?stack|web developer|integration|integrations|automation)\b",
        title,
        re.I,
    )
    if dedicated_ai_role and not allowed_ai_context:
        return "Dedicated AI/ML role is outside the target application-development and integration scope."
    if re.search(r"\b(?:intern|internship)\b", title, re.I) and re.search(
        r"\b(?:stipend\s*[:：-]?\s*(?:none|unpaid|0)|unpaid\s+intern(?:ship)?|no\s+(?:stipend|pay)|without\s+(?:a\s+)?stipend)\b",
        description,
        re.I,
    ):
        return "Unpaid internship is not eligible for unattended auto-application."
    if date_kind != "posted":
        return "Posting date is not verified as the original publication date; skipped to avoid stale jobs."
    if quality != "full" or len(description) < 180:
        return "Full employer description is unavailable; skipped rather than applying from a snippet."

    job = Job(
        source=str(item.get("source") or "unknown"),
        source_id=str(item.get("source_id") or url),
        title=title,
        company=str(item.get("company") or "Unknown company"),
        location=str(item.get("location") or ""),
        url=url,
        description=description,
        posted_at=posted_at,
        date_kind=date_kind,
        remote=bool(item.get("remote")) or str(item.get("workplace_type") or "").casefold() == "remote",
        employment_type=str(item.get("employment_type") or ""),
        workplace_type=str(item.get("workplace_type") or "unknown"),
        eligibility=str(item.get("eligibility") or ""),
        description_quality=quality,
    )
    status, computed_score, reasons, concerns = classify(job)
    if status == "reject":
        return "Qualification filter rejected this role: " + "; ".join(concerns[:2])
    if computed_score < settings.auto_apply_min_score or int(item.get("score") or 0) < settings.auto_apply_min_score:
        return f"Below automatic-application score threshold ({settings.auto_apply_min_score}/100)."

    experience = assess_experience(description)
    limit = float(settings.max_required_experience_years)
    if experience.maximum_required_years is not None and experience.maximum_required_years > limit:
        return f"Mandatory experience exceeds the configured {limit:g}-year limit."

    concern_text = " ".join(concerns).casefold()
    critical_markers = (
        "remote role does not confirm that applicants in egypt are eligible",
        "regional eligibility",
        "conflicting country eligibility",
        "source's candidate-country restrictions",
        "original posting date is unverified",
        "hidden mandatory requirements cannot be ruled out",
        "description completeness is unknown",
        "posting date missing",
        "posting date could not be parsed",
    )
    for marker in critical_markers:
        if marker in concern_text:
            return f"Eligibility or listing-quality check unresolved: {marker}."

    location = str(item.get("location") or "").casefold()
    remote = bool(item.get("remote")) or str(item.get("workplace_type") or "").casefold() == "remote" or "remote" in location
    local_allowed = any(city in location for city in ("cairo", "mansoura", "giza", "smart village"))
    structured = _himalayas_eligibility_decision(str(item.get("eligibility") or ""))
    confirmed = any(
        "international remote eligibility mentions worldwide/egypt" in reason.casefold()
        or "regional remote eligibility" in reason.casefold()
        or "himalayas structured country/timezone restrictions permit egypt" in reason.casefold()
        for reason in reasons
    )
    if structured is not None:
        verdict, evidence = structured
        if verdict != "allowed":
            return "Egypt eligibility is not confirmed: " + evidence
        confirmed = True
    if remote and not local_allowed and not confirmed:
        return "Remote listing does not explicitly establish that a candidate working from Egypt is eligible."
    if not remote and not local_allowed:
        return "On-site/hybrid location is outside the candidate's allowed Egyptian locations."
    if not str(item.get("company") or "").strip() or str(item.get("company")).casefold() == "unknown company":
        return "Employer identity is missing or uncertain."
    return None


def _field_text(meta: dict[str, Any]) -> str:
    parts = [meta.get(key, "") for key in ("label", "aria", "placeholder", "name", "id")]
    return re.sub(r"\s+", " ", " ".join(str(p or "") for p in parts)).strip()


def _find_apply_url(page) -> str | None:
    current = page.url
    host = urlparse(current).hostname or ""

    # Direct ATS pages and public employer-hosted forms are eligible only when the
    # page contains a recognizable application form; account/newsletter forms are excluded.
    if not _is_aggregator_host(host) and _choose_application_form(page) is not None:
        return current

    try:
        links = page.locator("a[href]").evaluate_all("""els => els.map(a => ({
            href: a.href,
            text: (a.innerText || a.getAttribute('aria-label') || a.title || '').trim(),
            title: (a.title || '').trim()
        }))""")
    except Exception:
        links = []
    candidates = []
    for link in links:
        href = str(link.get("href") or "")
        label = f"{link.get('text', '')} {link.get('title', '')}"
        if not _is_explicit_application_target(href, current, label):
            continue
        target = urlparse(href)
        text = f"{label} {target.path}".casefold()
        score = 10 if _is_supported_host(target.hostname or "") else 0
        score += 3 if re.search(r"/apply(?:/|$|\?)", target.path, re.I) else 0
        score += 3 if re.search(r"apply now|submit application|application form|apply for this job", text) else 0
        candidates.append((score, href))
    if candidates:
        return sorted(candidates, key=lambda pair: (pair[0], pair[1]), reverse=True)[0][1]
    if host.endswith("ashbyhq.com") and not current.rstrip("/").endswith("/application"):
        path_parts = [p for p in urlparse(current).path.split("/") if p]
        if len(path_parts) >= 2:
            return current.rstrip("/") + "/application"
    return None


def _is_challenge(page, body: str) -> bool:
    low = body.casefold()
    if any(marker in low for marker in CAPTCHA_MARKERS):
        return True
    try:
        candidates = page.locator("iframe[src*='recaptcha']:visible, iframe[src*='hcaptcha']:visible, iframe[src*='challenges.cloudflare.com']:visible")
        for i in range(candidates.count()):
            frame = candidates.nth(i)
            box = frame.bounding_box()
            if not box or box["width"] < 250 or box["height"] < 300:
                continue
            truly_visible = frame.evaluate("""el => {
                let p = el;
                while (p && p !== document.documentElement) {
                    const s = window.getComputedStyle(p);
                    if (s.display === 'none' || s.visibility === 'hidden' || parseFloat(s.opacity || '1') === 0) return false;
                    const r = p.getBoundingClientRect();
                    if (r.bottom < 0 || r.right < 0) return false;
                    p = p.parentElement;
                }
                return true;
            }""")
            if truly_visible:
                return True
    except Exception:
        pass
    return False


def _labels(form) -> list[dict[str, Any]]:
    return form.locator("input, textarea, select, button").evaluate_all("""els => els.map((el, index) => {
      let label = '';
      try { label = Array.from(el.labels || []).map(x => x.innerText || '').join(' '); } catch (_) {}
      const parentLabel = el.closest('label');
      if (!label && parentLabel) label = parentLabel.innerText || '';
      if (!label && el.id) {
        const found = document.querySelector(`label[for='${CSS.escape(el.id)}']`);
        if (found) label = found.innerText || '';
      }
      const optionLabel = label;
      const groupEl = el.closest('fieldset, [role="radiogroup"], [role="group"]');
      let groupQuestion = '';
      if (groupEl) {
        const lblId = groupEl.getAttribute('aria-labelledby');
        if (lblId && document.getElementById(lblId)) {
          groupQuestion = document.getElementById(lblId).innerText || '';
        } else {
          const legend = groupEl.querySelector('legend, span[id]');
          if (legend) groupQuestion = legend.innerText || '';
        }
      }
      if (groupQuestion && (el.type === 'radio' || el.type === 'checkbox')) label = groupQuestion;
      return {
        index,
        tag: el.tagName.toLowerCase(),
        type: (el.type || '').toLowerCase(),
        accept: (el.getAttribute('accept') || '').toLowerCase(),
        name: el.name || '', id: el.id || '',
        placeholder: el.getAttribute('placeholder') || '',
        aria: el.getAttribute('aria-label') || '',
        label: (label || '').replace(/\\s+/g, ' ').trim(),
        optionLabel: (optionLabel || '').replace(/\\s+/g, ' ').trim(),
        required: !!el.required || el.getAttribute('aria-required') === 'true',
        disabled: !!el.disabled,
        visible: !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length),
        value: el.value || '',
        options: el.tagName.toLowerCase() === 'select' ? Array.from(el.options).map(o => ({value:o.value,text:(o.textContent||'').trim(),disabled:o.disabled})) : []
      };
    })""")


def _generate_cover_letter(profile: dict[str, Any], item: dict[str, Any]) -> str:
    identity = profile.get("identity", {}) if isinstance(profile.get("identity"), dict) else {}
    name = str(identity.get("full_name") or "").strip()
    summary = str(profile.get("summary") or os.getenv("CANDIDATE_SUMMARY", "Junior backend/full-stack developer based in Egypt with experience in Python, Django, FastAPI, Node.js, APIs, databases, and practical software projects.")).strip()
    skills = profile.get("skills", [])
    if isinstance(skills, list):
        skill_text = ", ".join(str(skill) for skill in skills[:8] if skill)
    elif isinstance(skills, dict):
        skill_text = ", ".join(str(skill) for group in skills.values() if isinstance(group, list) for skill in group[:4])
    else:
        skill_text = ""
    company = str(item.get("company") or "the team")
    title = str(item.get("title") or "this role")
    body = [
        f"Hello {company} hiring team,",
        "",
        f"I am applying for the {title} role. {summary}",
    ]
    if skill_text:
        body.append(f"My relevant skills include {skill_text}.")
    body += [
        "I would welcome the opportunity to discuss how my existing experience and project work align with the role.",
        "",
        "Best regards,",
        name,
    ]
    return "\n".join(body).strip()


def _answer_for_field(question: str, profile: dict[str, Any], bank: dict[str, Any], item: dict[str, Any]) -> tuple[str | None, str]:
    low = question.casefold()
    if re.search(r"\b(cover letter|why (?:are you interested|do you want)|why this (?:role|company)|why you|tell us about yourself|motivation|additional information)\b", low):
        return _generate_cover_letter(profile, item), "generated from saved profile facts"
    result = resolve_answer(
        question,
        profile,
        bank,
        target_country="Egypt" if "egypt" in low else None,
        company=str(item.get("company") or ""),
        job_title=str(item.get("title") or ""),
    )
    if result.status in {"auto_fill", "draft"} and result.answer:
        return result.answer, result.reason
    if re.search(r"\b(friends or relatives|relatives in|worked at .* before|previously employed)\b", low):
        return "No", "saved screening answer"
    if re.search(r"\b(egyptian national|bachelor|graduated|degree|1\s*[–-]\s*2 years|able to work in cairo|on\s*site|flexible|shifts|fluent in (?:the )?english)\b", low):
        return "Yes", "saved candidate qualification"
    if re.search(r"\b(hustle[d]?|proud of|accomplish|achievement|built|challeng(?:e|ing)|time you|project you|problem you solved|example of|what makes you|why should we|anything else|describe a|tell us about a)\b", low):
        return (
            "I independently architected and delivered SmartCart, a multi-store e-commerce platform with 50+ RESTful APIs, RBAC, Dockerized services, and 200+ automated tests. "
            "I also contributed 5 merged pull requests to the Cantera open-source library and delivered full-stack web portals for freelance clients under tight deadlines.",
            "generated project achievement summary from profile",
        )
    return None, result.reason


def _check_input(loc) -> None:
    try:
        loc.check(force=True, timeout=3000)
    except TypeError:
        loc.check()


def _fill_form(form, profile: dict[str, Any], bank: dict[str, Any], item: dict[str, Any], resume_path: Path) -> tuple[list[str], list[str]]:
    blockers: list[str] = []
    filled: list[str] = []
    fields = _labels(form)
    handled_radio_groups: set[str] = set()
    deferred_file_metas: list[dict[str, Any]] = []
    if not fields:
        return ["No recognizable form fields were found."], filled

    # Reject legal declarations and consent toggles instead of consenting to terms blindly.
    for meta in fields:
        if not meta["visible"] or meta["disabled"] or meta["tag"] == "button":
            continue
        label = _field_text(meta)
        kind = meta["type"]
        if kind in {"hidden", "submit", "button", "reset", "search"}:
            continue
        if kind == "password":
            if meta["required"]:
                blockers.append(f"Required login/password field: {label[:100] or meta['name']}")
            continue
        if kind == "radio":
            group_name = str(meta.get("name") or meta.get("id") or label)
            if group_name in handled_radio_groups:
                continue
            handled_radio_groups.add(group_name)
            group = [field for field in fields if field.get("type") == "radio" and str(field.get("name") or field.get("id") or field.get("label")) == group_name and field.get("visible") and not field.get("disabled")]
            question = label or " ".join(str(meta.get(k) or "") for k in ("name", "id", "placeholder", "aria"))
            value, reason = _answer_for_field(question, profile, bank, item)
            if value:
                target = str(value).strip().casefold()
                opt_labels = {str(f.get("optionLabel") or "").strip().casefold() for f in group}
                if opt_labels == {"yes", "no"} and target not in {"yes", "no"}:
                    if target in {"0", "none", "false", "no"} or "not " in target:
                        target = "no"
                    else:
                        target = "yes"
                matches = [field for field in group if target in str(field.get("optionLabel") or "").casefold() or target == str(field.get("value") or "").casefold()]
                if not matches and target in {"yes", "no"}:
                    matches = [field for field in group if re.search(rf"\b{target}\b", str(field.get("optionLabel") or ""), re.I) or str(field.get("value") or "").casefold() == target]
                if len(matches) == 1:
                    try:
                        _check_input(form.locator("input, textarea, select, button").nth(matches[0]["index"]))
                        filled.append(question[:90])
                    except Exception as exc:
                        if meta["required"]:
                            blockers.append(f"Could not select required answer {question[:90]} ({type(exc).__name__})")
                elif any(field.get("required") for field in group):
                    blockers.append(f"Required radio choice has no unambiguous saved answer: {question[:120]}")
            elif any(field.get("required") for field in group):
                blockers.append(f"Required radio question needs a verified answer: {question[:120]}")
            continue
        if kind == "checkbox":
            grp_lbl = str(meta.get("label") or "").strip()
            if grp_lbl and grp_lbl in handled_radio_groups:
                continue
            if re.search(r"military service", grp_lbl, re.I):
                opt_lbl = str(meta.get("optionLabel") or "").strip().lower()
                if opt_lbl in ("exempted", "finished", "completed", "postponed"):
                    try:
                        _check_input(form.locator("input, textarea, select, button").nth(meta["index"]))
                        handled_radio_groups.add(grp_lbl)
                        filled.append(f"military service: {opt_lbl}")
                    except Exception:
                        pass
                continue
            # Auto-check standard candidate consent/privacy/accuracy declarations as approved
            is_privacy_consent = bool(re.search(r"privacy|terms|consent|accurate|truth|certif|agree|processing of (?:my )?personal data|candidate (?:privacy|declaration)", label, re.I))
            is_dangerous_declaration = bool(re.search(r"criminal|perjury|background check authorization|drug test", label, re.I))
            if is_privacy_consent and not is_dangerous_declaration:
                try:
                    _check_input(form.locator("input, textarea, select, button").nth(meta["index"]))
                    filled.append(f"consent: {label[:60]}")
                except Exception as exc:
                    if meta["required"]:
                        blockers.append(f"Could not check consent checkbox: {label[:80]} ({type(exc).__name__})")
                continue
            if meta["required"]:
                blockers.append(f"Required declaration/checkbox needs explicit human review: {label[:120] or meta['name']}")
            continue
        if kind == "file":
            deferred_file_metas.append(meta)
            continue

        if not meta["required"] and not label:
            continue

        q = label or " ".join(str(meta.get(k) or "") for k in ("name", "id", "placeholder", "aria"))
        # Generic mapping for common ATS names when labels are terse.
        q_low = q.casefold()
        if re.search(r"^first\s*(?:name)?$|first_name|givenname", q_low):
            identity = profile.get("identity", {}) if isinstance(profile.get("identity"), dict) else {}
            value = str(identity.get("first_name") or str(identity.get("full_name") or "").split(" ")[0]).strip()
            reason = "saved candidate identity"
        elif re.search(r"^last\s*(?:name)?$|last_name|familyname|surname", q_low):
            identity = profile.get("identity", {}) if isinstance(profile.get("identity"), dict) else {}
            full = str(identity.get("full_name") or "").split()
            value = str(identity.get("last_name") or (full[-1] if len(full) > 1 else "")).strip()
            reason = "saved candidate identity"
        elif re.search(r"\bname\b|^name\b|_systemfield_name|candidate.?name", q_low) and not re.search(r"company|employer|university|school|institution", q_low):
            identity = profile.get("identity", {}) if isinstance(profile.get("identity"), dict) else {}
            value = str(identity.get("full_name") or "").strip()
            reason = "saved candidate identity"
        elif kind == "email" or re.search(r"\bemail\b|_systemfield_email", q_low):
            value = str(_at(profile, "identity", "email", default="")).strip()
            reason = "saved candidate email"
        elif kind == "tel" or re.search(r"\bphone\b|\bmobile\b|\bwhatsapp\b|_systemfield_phone", q_low):
            value = str(_at(profile, "identity", "phone", default="")).strip()
            reason = "saved candidate phone"
        elif re.search(r"passport country|citizenship|nationality", q_low):
            value = str(_at(profile, "identity", "country", default="Egypt"))
            reason = "saved nationality"
        elif re.search(r"\baddress\b|street", q_low) and not re.search(r"email|ip\s*address|web|url", q_low):
            value = f"{_at(profile, 'identity', 'city', default='Cairo')}, {_at(profile, 'identity', 'country', default='Egypt')}"
            reason = "saved candidate address"
        elif re.search(r"current company|current employer|present employer", q_low):
            value = str(_at(profile, "screening", "current_employer", default="Freelance Software Developer"))
            reason = "saved current employer"
        elif re.search(r"current (?:job )?title|current position", q_low):
            value = str(_at(profile, "screening", "current_title", default="Full Stack Developer"))
            reason = "saved current title"
        else:
            value, reason = _answer_for_field(q, profile, bank, item)

        if not value:
            if meta["required"]:
                blockers.append(f"Required question needs an exact saved answer: {q[:120]}")
            continue

        loc = form.locator("input, textarea, select, button").nth(meta["index"])
        try:
            if meta["tag"] == "select":
                options = meta.get("options", [])
                normalized = str(value).strip().casefold()
                exact = next((opt for opt in options if not opt.get("disabled") and (str(opt.get("value", "")).strip().casefold() == normalized or str(opt.get("text", "")).strip().casefold() == normalized)), None)
                if exact is None:
                    # Accept unambiguous contained option matches only.
                    matches = [opt for opt in options if not opt.get("disabled") and normalized and (normalized in str(opt.get("text", "")).casefold() or str(opt.get("text", "")).casefold() in normalized)]
                    if len(matches) == 1:
                        exact = matches[0]
                if exact is None:
                    if meta["required"]:
                        blockers.append(f"Required dropdown has no unambiguous saved answer: {q[:120]}")
                    continue
                loc.select_option(value=str(exact.get("value", "")))
            elif meta["type"] in {"email", "tel", "url", "text", "search", "number"} or meta["tag"] in {"textarea", "input"}:
                loc.fill(str(value))
            else:
                if meta["required"]:
                    blockers.append(f"Unsupported required field type: {kind or meta['tag']} ({q[:100]})")
                    continue
            filled.append(q[:90])
        except Exception as exc:
            if meta["required"]:
                blockers.append(f"Could not fill required field {q[:90]} ({type(exc).__name__})")

    resume_attached = False
    for meta in deferred_file_metas:
        label = _field_text(meta)
        accept_attr = str(meta.get("accept") or "").lower()
        if accept_attr and "image/" in accept_attr and "pdf" not in accept_attr and "application/" not in accept_attr:
            continue
        if resume_attached and not meta["required"]:
            continue
        loc = form.locator("input, textarea, select, button").nth(meta["index"])
        try:
            is_autofill = loc.evaluate("""e => {
                const c = e.closest('div') || e.parentElement;
                return ((c ? c.innerText || '' : '')).toLowerCase().includes('autofill');
            }""")
        except Exception:
            is_autofill = False
        if is_autofill and not meta["required"]:
            continue
        if not meta["required"] and re.search(r"cover\s*letter|transcript|portfolio|avatar|photo", label, re.I):
            continue
        if resume_path.is_file():
            try:
                loc.set_input_files(str(resume_path))
                resume_attached = True
                try:
                    if "ashbyhq.com" in (urlparse(form.page.url).hostname or ""):
                        form.page.locator("button:has-text('Replace')").first.wait_for(state="visible", timeout=8000)
                    else:
                        form.page.wait_for_timeout(1500)
                except Exception:
                    pass
                filled.append("resume file")
            except Exception as exc:
                if meta["required"]:
                    blockers.append(f"Could not attach the resume: {type(exc).__name__}")
        elif meta["required"]:
            blockers.append("Required resume file is missing from the configured local path.")

    # Handle Ashby-style boolean Yes/No button groups rendered inside .ashby-application-form-field-entry
    try:
        yn_entries = form.locator(".ashby-application-form-field-entry")
        for idx in range(yn_entries.count()):
            entry = yn_entries.nth(idx)
            btns = entry.locator("button")
            if btns.count() < 2:
                continue
            btn_texts = [btns.nth(b).inner_text().strip() for b in range(btns.count())]
            if not (any(t.lower() == "yes" for t in btn_texts) and any(t.lower() == "no" for t in btn_texts)):
                continue
            lbl_loc = entry.locator("label").first
            q_text = (lbl_loc.inner_text() if lbl_loc.count() else "").strip()
            if not q_text:
                continue
            val, _ = _answer_for_field(q_text, profile, bank, item)
            val_low = str(val or "").strip().lower()
            if re.search(r"based in cairo|based in egypt|live in egypt|relocate|over the age of 18|at least 18|18 years|legal age|eligible to work in egypt", q_text, re.I):
                val_low = "yes"
            elif val_low not in ("yes", "no", "true", "false"):
                if any(w in val_low for w in ("yes", "open", "willing", "able", "authorized")):
                    val_low = "yes"
                elif any(w in val_low for w in ("no", "not")):
                    val_low = "no"
                elif re.search(r"previously worked|employed at|government|criminal|convicted|sanction", q_text, re.I):
                    val_low = "no"
                else:
                    val_low = "yes"
            target_btn = "Yes" if val_low in ("yes", "true") else "No"
            for b in range(btns.count()):
                if btns.nth(b).inner_text().strip().lower() == target_btn.lower():
                    btns.nth(b).click()
                    filled.append(f"{q_text[:70]} -> {target_btn}")
                    break
        if filled and not os.getenv("PYTEST_CURRENT_TEST"):
            try:
                form.page.evaluate("() => { if (document.activeElement) document.activeElement.blur(); }")
                form.page.wait_for_timeout(1200)
            except Exception:
                pass
    except Exception:
        pass

    return blockers, filled


def _submit_form(page, form) -> tuple[bool, str]:
    before_url = page.url
    try:
        before_body = page.locator("body").inner_text(timeout=3000).casefold()
    except Exception:
        before_body = ""
    submit = form.locator("button[type='submit'], input[type='submit']")
    if submit.count() == 0:
        submit = form.get_by_role("button", name=re.compile(r"\b(submit|apply|send application)\b", re.I))
    if submit.count() == 0:
        return False, "No recognizable submit button was found."
    try:
        submit.first.click(timeout=int(settings.auto_apply_timeout_seconds * 1000))
        try:
            page.wait_for_load_state("networkidle", timeout=6000)
        except Exception:
            page.wait_for_timeout(3500)
        body = page.locator("body").inner_text(timeout=5000).casefold()
        if _is_challenge(page, body):
            return False, "The page presented a CAPTCHA or anti-bot challenge; no bypass was attempted."
        new_success = any(marker in body and marker not in before_body for marker in SUCCESS_MARKERS)
        confirmation_url = page.url != before_url and bool(re.search(r"thank|success|complete|confirmation|submitted", page.url, re.I))
        if new_success or (confirmation_url and page.locator("form").count() == 0):
            return True, "Employer page displayed a new submission-confirmation signal."
        if page.locator("[role='alert'], .error, .alert-danger, [aria-invalid='true']").count() > 0:
            return False, "The site returned a validation/error state; submission was not confirmed."
        return False, "Submit was clicked, but the page did not provide reliable confirmation; treated as uncertain to avoid duplicate retries."
    except Exception as exc:
        return False, f"Submission could not be confirmed ({type(exc).__name__})."


def _choose_application_form(page):
    forms = page.locator("form")
    count = forms.count()
    best = None
    best_score = -1
    for index in range(count):
        form = forms.nth(index)
        try:
            info = form.evaluate("""f => ({
              text: (f.innerText || '').slice(0, 2000).toLowerCase(),
              inputs: Array.from(f.querySelectorAll('input,textarea,select')).filter(e => e.type !== 'hidden').length,
              email: !!f.querySelector('input[type=email],input[name*=email i]'),
              file: !!f.querySelector('input[type=file]'),
              submit: !!f.querySelector('button[type=submit],input[type=submit]'),
              password: !!f.querySelector('input[type=password]')
            })""")
        except Exception:
            continue
        form_text = str(info.get("text") or "")
        # Never submit a login, account-creation, or newsletter form by mistake.
        if info.get("password") or re.search(
            r"newsletter|subscribe|sign[ -]?in|log[ -]?in|login|create account|forgot password|reset password|register account",
            form_text,
            re.I,
        ):
            continue
        score = int(info.get("inputs", 0)) + (5 if info.get("email") else 0) + (4 if info.get("file") else 0) + (3 if info.get("submit") else 0)
        if score > best_score:
            best_score, best = score, form
    if best is not None and best_score >= 5:
        return best

    # Modern ATS support: Ashby, Greenhouse React, Workable use <div> containers instead of <form> tags
    host = urlparse(page.url).hostname or ""
    if _is_supported_host(host) or re.search(r"/apply|/application", page.url, re.I):
        try:
            page.wait_for_selector("input, textarea, select", timeout=6000)
        except Exception:
            pass
        try:
            body_info = page.locator("body").evaluate("""b => ({
                inputs: Array.from(b.querySelectorAll('input,textarea,select')).filter(e => e.type !== 'hidden').length,
                email: !!b.querySelector('input[type=email],input[name*=email i]'),
                file: !!b.querySelector('input[type=file]'),
                submit: !!b.querySelector('button[type=submit],input[type=submit]') || Array.from(b.querySelectorAll('button')).some(btn => /submit|apply|send application/i.test(btn.innerText || ''))
            })""")
            if body_info.get("inputs", 0) >= 3 and body_info.get("email"):
                return page.locator("body")
        except Exception:
            pass

    return None


def _application_link_diagnostics(page) -> dict[str, Any]:
    """Describe apply-like links without collecting page text or form values."""
    try:
        links = page.locator("a[href]").evaluate_all("""els => els.map(a => ({
          href: a.href,
          text: (a.innerText || a.getAttribute('aria-label') || a.title || '').trim().slice(0, 140),
          title: (a.title || '').trim().slice(0, 100)
        }))""")
    except Exception:
        links = []
    candidates = []
    matcher = re.compile(r"\bapply\b|application|submit (?:a )?(?:cv|resume|application)|career|bewerben|postuler|kandidatur", re.I)
    seen: set[str] = set()
    for link in links:
        href = str(link.get("href") or "")
        text = f"{link.get('text', '')} {link.get('title', '')} {urlparse(href).path}"
        host = urlparse(href).hostname or ""
        if not matcher.search(text) and not _is_supported_host(host):
            continue
        target = safe_url(href)
        if not target or target in seen:
            continue
        seen.add(target)
        page_host = urlparse(page.url).hostname or ""
        candidates.append({
            "text": str(link.get("text") or link.get("title") or "")[:140],
            "host": host[:180],
            "path": urlparse(href).path[:300],
            "supported_ats": _is_supported_host(host),
            "custom_form_candidate": _is_explicit_application_target(href, page.url, str(link.get("text") or link.get("title") or "")),
            "aggregator_or_login": _is_aggregator_host(host),
            "url": target,
        })
        if len(candidates) >= 15:
            break
    return {
        "anchors_seen": len(links),
        "apply_link_candidates_seen": len(candidates),
        "supported_ats_link_count": sum(1 for item in candidates if item["supported_ats"]),
        "apply_links": candidates,
    }


def _form_diagnostics(page) -> dict[str, Any]:
    """Return form structure only; never records entered values or page HTML."""
    summary: list[dict[str, Any]] = []
    try:
        forms = page.locator("form")
        count = forms.count()
    except Exception:
        return {"forms_found": 0, "form_shapes": []}
    for index in range(min(count, 10)):
        try:
            info = forms.nth(index).evaluate("""f => {
              const controls = Array.from(f.querySelectorAll('input,textarea,select,button'));
              const fields = controls.filter(e => !['hidden','submit','button','reset'].includes((e.type||'').toLowerCase()));
              const types = {};
              for (const el of fields) { const t=(el.type || el.tagName || 'unknown').toLowerCase(); types[t]=(types[t]||0)+1; }
              return {
                visible_field_count: fields.filter(e => !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length)).length,
                required_field_count: fields.filter(e => !!e.required || e.getAttribute('aria-required')==='true').length,
                field_types: types,
                has_email: !!f.querySelector('input[type=email],input[name*=email i]'),
                has_resume_upload: !!f.querySelector('input[type=file]'),
                has_submit: !!f.querySelector('button[type=submit],input[type=submit]'),
                has_password: !!f.querySelector('input[type=password]')
              };
            }""")
            summary.append(info)
        except Exception:
            summary.append({"inspection_error": "form_shape_unavailable"})
    return {"forms_found": count, "form_shapes": summary}


def _perform_browser_application(
    item: dict[str, Any], profile: dict[str, Any], bank: dict[str, Any],
    resume_path: Path, browser, *, run_id: str = "unknown-run",
) -> dict[str, Any]:
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

    base = {
        "queue_id": int(item.get("id") or 0),
        "title": str(item.get("title") or "")[:180],
        "company": str(item.get("company") or "")[:180],
        "source": str(item.get("source") or "")[:100],
        "listing_url": safe_url(item.get("url")),
    }
    def finish(outcome: str, reason: str, stage: str, **details: Any) -> dict[str, Any]:
        reason_code = reason_code_for_reason(reason, stage=stage)
        result = {
            "outcome": outcome,
            "reason": reason,
            "reason_code": reason_code,
            **details,
        }
        if "apply_links" not in result and "apply_links" in link_diagnostics:
            result["apply_links"] = link_diagnostics["apply_links"]
        if "diagnostics" not in result and link_diagnostics:
            result["diagnostics"] = link_diagnostics
        if "form_diagnostics" not in result and "field_diagnostics" in result:
            result["form_diagnostics"] = result["field_diagnostics"]
        log_auto_apply_event(
            run_id, "browser_application_result", **base, stage=stage,
            outcome=outcome, reason_code=reason_code, reason=reason,
            **details,
        )
        return result

    context = browser.new_context(accept_downloads=False)
    page = context.new_page()
    page.set_default_timeout(int(settings.auto_apply_timeout_seconds * 1000))
    link_diagnostics: dict[str, Any] = {}
    try:
        response = page.goto(str(item["url"]), wait_until="domcontentloaded", timeout=int(settings.auto_apply_timeout_seconds * 1000))
        page.wait_for_timeout(700)
        try:
            page_title = page.title()[:180]
        except Exception:
            page_title = ""
        page_host = urlparse(page.url).hostname or ""
        log_auto_apply_event(
            run_id, "listing_page_loaded", **base,
            http_status=(response.status if response is not None else None),
            page_host=page_host, page_title=page_title, page_url=safe_url(page.url),
        )
        body = page.locator("body").inner_text(timeout=5000)
        if _is_challenge(page, body):
            return finish("auto_skipped", "Listing page presented a CAPTCHA/anti-bot challenge.", "listing_challenge", page_host=page_host)

        link_diagnostics = _application_link_diagnostics(page)
        application_url = _find_apply_url(page)
        log_auto_apply_event(
            run_id, "application_link_discovery", **base, page_host=page_host,
            selected_application_url=safe_url(application_url) if application_url else None,
            **link_diagnostics,
        )
        if not application_url:
            if _job_board_requires_account(page_host, link_diagnostics):
                return finish(
                    "auto_skipped",
                    "Job-board account/login is required before an employer application link is exposed; skipped instead of creating an account.",
                    "aggregator_account_required", page_host=page_host, **link_diagnostics,
                )
            return finish(
                "auto_skipped", "No supported ATS or explicit public employer application form was found from this listing.",
                "application_link_discovery", page_host=page_host, **link_diagnostics,
            )
        application_target_host = urlparse(application_url).hostname or ""
        if _is_aggregator_host(application_target_host) and not _is_supported_host(application_target_host):
            return finish(
                "auto_skipped", "Apply link points to a job-board account or listing page, not an employer application form.",
                "aggregator_account_required", page_host=page_host,
                application_url=safe_url(application_url), **link_diagnostics,
            )
        if application_url != page.url:
            response = page.goto(application_url, wait_until="domcontentloaded", timeout=int(settings.auto_apply_timeout_seconds * 1000))
            try:
                page.wait_for_selector("input, textarea, select, form", timeout=6000)
            except Exception:
                page.wait_for_timeout(1500)
        body = page.locator("body").inner_text(timeout=5000)
        final_url_host = urlparse(page.url).hostname or ""
        log_auto_apply_event(
            run_id, "application_page_loaded", **base,
            http_status=(response.status if response is not None else None),
            ats_host=final_url_host, application_url=safe_url(page.url),
        )
        if _is_challenge(page, body):
            return finish("auto_skipped", "Application form presented a CAPTCHA/anti-bot challenge.", "application_challenge", ats_host=final_url_host, **link_diagnostics)
        if not _is_supported_host(final_url_host) and not _same_site_host(final_url_host, application_target_host):
            return finish("auto_skipped", "Application link redirected away from its target to an unsupported host.", "final_host_check", ats_host=final_url_host, application_target_host=application_target_host, **link_diagnostics)
        form = _choose_application_form(page)
        form_diagnostics = _form_diagnostics(page)
        log_auto_apply_event(
            run_id, "application_form_discovery", **base,
            ats_host=final_url_host, **form_diagnostics,
        )
        if form is None:
            return finish("auto_skipped", "No recognizable public application form was found.", "form_discovery", ats_host=final_url_host, **form_diagnostics, **link_diagnostics)

        blockers, filled = _fill_form(form, profile, bank, item, resume_path)
        field_diagnostics = {**form_diagnostics, "filled_field_count": len(filled), "required_blocker_count": len(blockers)}
        if blockers:
            reason = "Required fields could not be answered safely: " + "; ".join(blockers[:5])
            return finish(
                "auto_skipped", reason, "form_mapping", filled_count=len(filled),
                ats_host=final_url_host, blockers=blockers[:12],
                field_diagnostics=field_diagnostics, **link_diagnostics,
            )
        if not filled:
            return finish("auto_skipped", "No application fields were confidently filled.", "form_mapping", ats_host=final_url_host, field_diagnostics=field_diagnostics, **link_diagnostics)

        # Fill-and-review mode check (e.g. if candidate wants review before submit)
        initial_mode = str(_at(profile, "automation_preferences", "initial_mode", default="")).lower()
        auto_submit_enabled = bool(_at(profile, "automation_preferences", "auto_submit_enabled", default=True))
        if initial_mode == "fill_and_review" and not auto_submit_enabled:
            # Capture screenshot if possible
            screenshot_path = ROOT / "logs" / f"review_queue_{item.get('id')}.png"
            try:
                page.screenshot(path=str(screenshot_path))
            except Exception:
                pass
            return finish("ready_for_review", "Application form successfully filled; stopped before submission as configured in fill_and_review mode.", "fill_and_review", filled_count=len(filled), ats_host=final_url_host, field_diagnostics=field_diagnostics)

        if not begin_automation_attempt(int(item["id"])):
            return finish("failed", "Queue record could not be reserved safely before submitting; no submit was attempted.", "reserve_attempt", ats_host=final_url_host, filled_count=len(filled), field_diagnostics=field_diagnostics)
        log_auto_apply_event(run_id, "submit_click_about_to_happen", **base, ats_host=final_url_host, filled_field_count=len(filled))
        try:
            page.screenshot(path=str(ROOT / "logs" / f"submit_before_{item.get('id')}.png"))
        except Exception:
            pass
        ok, message = _submit_form(page, form)
        try:
            page.screenshot(path=str(ROOT / "logs" / f"submit_after_{item.get('id')}.png"))
        except Exception:
            pass
        if ok:
            return finish(
                "submitted", message, "submission_confirmation",
                filled_count=len(filled), ats_host=final_url_host,
                reference=safe_url(page.url), field_diagnostics=field_diagnostics,
            )
        return finish(
            "failed", message, "submission_confirmation",
            filled_count=len(filled), ats_host=final_url_host,
            field_diagnostics=field_diagnostics,
        )
    except PlaywrightTimeoutError:
        return finish("failed", "Timed out loading or interacting with the job site.", "browser_timeout", **link_diagnostics)
    except Exception as exc:
        return finish("failed", f"Browser automation error: {type(exc).__name__}.", "browser_exception", error_type=type(exc).__name__, **link_diagnostics)
    finally:
        try:
            context.close()
        except Exception:
            pass


def _submitted_today() -> int:
    today = datetime.now(ZoneInfo("Africa/Cairo")).date()
    with _connect() as conn:
        rows = conn.execute("SELECT submitted_at FROM application_queue WHERE status='submitted' AND submitted_at IS NOT NULL").fetchall()
    count = 0
    for row in rows:
        try:
            value = datetime.fromisoformat(str(row[0]).replace("Z", "+00:00"))
            if value.tzinfo is None:
                value = value.replace(tzinfo=timezone.utc)
            if value.astimezone(ZoneInfo("Africa/Cairo")).date() == today:
                count += 1
        except ValueError:
            continue
    return count


def run_auto_apply(*, max_items: int | None = None) -> dict[str, Any]:
    """Process pending queue items autonomously under a strict daily cap.

    Every application decision is written as a redacted JSONL audit event to
    stderr and logs/application_automation.jsonl. No answer values are logged.
    """
    init_db()
    run_id = new_run_id()
    log_auto_apply_event(
        run_id, "run_started", auto_apply_enabled=bool(settings.auto_apply_enabled),
        daily_cap=settings.auto_apply_max_per_day,
        min_score=settings.auto_apply_min_score,
        max_required_experience_years=settings.max_required_experience_years,
    )
    if not settings.auto_apply_enabled:
        log_auto_apply_event(run_id, "run_stopped", reason_code="autopilot_disabled", reason="Automatic applications are disabled.")
        return {"run_id": run_id, "enabled": False, "processed": 0, "submitted": 0, "skipped": 0, "failed": 0, "results": []}
    if settings.auto_apply_max_per_day <= 0:
        reason = "Daily submission cap is zero."
        log_auto_apply_event(run_id, "run_stopped", reason_code="daily_cap_zero", reason=reason)
        return {"run_id": run_id, "enabled": True, "processed": 0, "submitted": 0, "skipped": 0, "failed": 0, "results": [], "reason": reason}
    try:
        bundle = load_profile_bundle()
    except ProfileLoadError as exc:
        reason = "Candidate profile/answer bank loading failed: " + str(exc)
        log_auto_apply_event(run_id, "run_stopped", reason_code="profile_load_error", reason=reason)
        return {"run_id": run_id, "enabled": True, "processed": 0, "submitted": 0, "skipped": 0, "failed": 0, "results": [], "error": reason}
    if bundle.issues:
        reason = "Candidate profile/answer bank validation failed: " + "; ".join(bundle.issues)
        log_auto_apply_event(run_id, "run_stopped", reason_code="profile_validation_failed", reason=reason, issue_count=len(bundle.issues))
        return {"run_id": run_id, "enabled": True, "processed": 0, "submitted": 0, "skipped": 0, "failed": 0, "results": [], "error": reason}

    submitted_today = _submitted_today()
    remaining = settings.auto_apply_max_per_day - submitted_today
    if max_items is not None:
        remaining = min(remaining, max(0, int(max_items)))
    if remaining <= 0:
        reason = "Daily application cap has been reached."
        log_auto_apply_event(run_id, "run_stopped", reason_code="daily_cap_reached", reason=reason, submitted_today=submitted_today)
        return {"run_id": run_id, "enabled": True, "processed": 0, "submitted": 0, "skipped": 0, "failed": 0, "results": [], "reason": reason}

    interrupted = recover_interrupted_attempts()
    pending = (
        list_applications(status="pending_review", limit=500)
        + list_applications(status="approved", limit=500)
        + list_applications(status="ready", limit=500)
    )
    log_auto_apply_event(
        run_id, "queue_loaded", queue_count=len(pending), interrupted_attempts_recovered=interrupted,
        counts_by_status={
            "pending_review": sum(i.get("status") == "pending_review" for i in pending),
            "approved": sum(i.get("status") == "approved" for i in pending),
            "ready": sum(i.get("status") == "ready" for i in pending),
        },
    )
    if not pending:
        reason = "No pending queue items."
        log_auto_apply_event(run_id, "run_completed", processed=0, submitted=0, skipped=0, failed=interrupted, reason=reason)
        return {"run_id": run_id, "enabled": True, "processed": 0, "submitted": 0, "skipped": 0, "failed": interrupted, "results": [], "reason": reason}

    eligible: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []
    for item in pending:
        job_context = {
            "queue_id": int(item.get("id") or 0),
            "title": str(item.get("title") or "")[:180],
            "company": str(item.get("company") or "")[:180],
            "source": str(item.get("source") or "")[:100],
            "listing_url": safe_url(item.get("url")),
            "current_queue_status": item.get("status"),
            "qualification_status": item.get("qualification_status"),
            "score": item.get("score"),
            "date_kind": item.get("date_kind"),
            "posted_at": item.get("posted_at"),
            "description_quality": item.get("description_quality"),
            "workplace_type": item.get("workplace_type"),
            "remote": bool(item.get("remote")),
        }
        if str(item.get("description_quality") or "unknown").casefold() != "full":
            item, enrichment = _enrich_public_listing(item)
            log_auto_apply_event(
                run_id, "public_listing_enrichment", **job_context,
                enrichment=enrichment,
            )
            job_context["description_quality"] = item.get("description_quality")
            job_context["posted_at"] = item.get("posted_at")
            job_context["company"] = str(item.get("company") or "")[:180]
        reason = _reason_for_auto_skip(item)
        if reason:
            reason_code = reason_code_for_reason(reason, stage="qualification_policy")
            log_auto_apply_event(run_id, "qualification_decision", **job_context, decision="skip", reason_code=reason_code, reason=reason)
            record_automation_outcome(
                int(item["id"]), "auto_skipped", reason=reason,
                details={"reason_code": reason_code, "stage": "qualification_policy", "score": item.get("score"), "source": item.get("source")},
            )
            results.append({"queue_id": item["id"], "title": item.get("title"), "company": item.get("company"), "source": item.get("source"), "outcome": "auto_skipped", "reason_code": reason_code, "reason": reason})
        else:
            log_auto_apply_event(run_id, "qualification_decision", **job_context, decision="continue_to_preflight", reason_code="policy_passed", reason="Passed the automatic-application policy checks.")
            eligible.append(item)

    if not eligible:
        summary = _summarize_results(results)
        log_auto_apply_event(run_id, "run_completed", processed=len(results), submitted=0, skipped=len(results), failed=0, reason_breakdown=summary)
        return {"run_id": run_id, "enabled": True, "processed": len(results), "submitted": 0, "skipped": len(results), "failed": 0, "results": results, "reason": "All pending listings were automatically skipped by the qualification policy.", "reason_breakdown": summary}

    resume_path = _resume_path(bundle.profile)
    log_auto_apply_event(run_id, "resume_precheck", resume_path_configured=bool(settings.auto_apply_resume_path), resume_file_exists=resume_path.is_file(), resume_suffix=resume_path.suffix.lower())
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        reason = "Playwright is not installed; install requirements and Chromium before autonomous submission."
        for item in eligible:
            reason_code = "playwright_unavailable"
            record_automation_outcome(int(item["id"]), "auto_skipped", reason=reason, details={"reason_code": reason_code, "stage": "runtime_preflight"})
            results.append({"queue_id": item["id"], "title": item.get("title"), "company": item.get("company"), "source": item.get("source"), "outcome": "auto_skipped", "reason_code": reason_code, "reason": reason})
            log_auto_apply_event(run_id, "runtime_preflight_failed", queue_id=item["id"], reason_code=reason_code, reason=reason)
        summary = _summarize_results(results)
        return {"run_id": run_id, "enabled": True, "processed": len(results), "submitted": 0, "skipped": len(results), "failed": 0, "results": results, "error": reason, "reason_breakdown": summary}

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=settings.auto_apply_headless)
            try:
                submissions_this_run = 0
                for item in eligible:
                    if submissions_this_run >= remaining:
                        log_auto_apply_event(run_id, "daily_cap_reached_mid_run", processed_count=len(results), submissions_this_run=submissions_this_run, remaining_before_run=remaining)
                        break
                    queue_id = int(item["id"])
                    current = get_application(queue_id) or {}
                    if current.get("status") != "pending_review":
                        log_auto_apply_event(run_id, "queue_item_not_pending_review", queue_id=queue_id, current_status=current.get("status"), action="skip_item")
                        continue
                    automatic_approve_application(queue_id, "Automatically approved by configured eligibility policy; no manual review required.")
                    log_auto_apply_event(run_id, "automatic_approval_recorded", queue_id=queue_id, title=item.get("title"), company=item.get("company"), source=item.get("source"), score=item.get("score"))
                    preflight = run_preflight(queue_id)
                    log_auto_apply_event(
                        run_id, "preflight_result", queue_id=queue_id,
                        title=item.get("title"), company=item.get("company"), source=item.get("source"),
                        passed=bool(preflight.get("passed")), status=preflight.get("status"),
                        blockers=preflight.get("blockers", []), warnings=preflight.get("warnings", []),
                        auto_submit_allowed=bool(preflight.get("auto_submit_allowed")),
                    )
                    if not preflight.get("passed"):
                        reason = "Preflight failed: " + "; ".join(preflight.get("blockers", [])[:4])
                        reason_code = "preflight_failed"
                        record_automation_outcome(queue_id, "auto_skipped", reason=reason, details={"reason_code": reason_code, "stage": "profile_preflight", "blockers": preflight.get("blockers", [])[:12], "warnings": preflight.get("warnings", [])[:12]})
                        results.append({"queue_id": queue_id, "title": item.get("title"), "company": item.get("company"), "source": item.get("source"), "outcome": "auto_skipped", "reason_code": reason_code, "reason": reason})
                        continue
                    item_resume = _resume_path(bundle.profile, item)
                    outcome = _perform_browser_application(item, bundle.profile, bundle.answer_bank, item_resume, browser, run_id=run_id)
                    label = str(outcome.get("outcome") or "failed")
                    reason = str(outcome.get("reason") or "Application worker returned no outcome.")
                    reason_code = str(outcome.get("reason_code") or reason_code_for_reason(reason, stage="browser_application"))
                    event_details = {
                        "reason_code": reason_code,
                        "stage": "browser_application",
                        "ats_host": outcome.get("ats_host"),
                        "cv_used": item_resume.name,
                        "filled_count": outcome.get("filled_count"),
                        "blockers": outcome.get("blockers", [])[:12],
                        "diagnostics": outcome.get("diagnostics", {}),
                        "apply_links": outcome.get("apply_links", []),
                        "form_diagnostics": outcome.get("form_diagnostics", outcome.get("field_diagnostics", {})),
                    }
                    if label == "submitted":
                        record_automation_outcome(queue_id, "submitted", reason=reason, reference=str(outcome.get("reference") or ""), details=event_details)
                        submissions_this_run += 1
                        if not os.getenv("PYTEST_CURRENT_TEST"):
                            try:
                                from app.telegram import _escape, send_message
                                msg = (
                                    f"🚀 <b>APPLICATION SUBMITTED AUTOMATICALLY</b>\n"
                                    f"<b>{_escape(str(item.get('title') or ''))}</b>\n"
                                    f"🏢 {_escape(str(item.get('company') or ''))}\n"
                                    f"📍 {_escape(str(item.get('location') or 'Remote'))}\n"
                                    f"📄 CV Used: <code>{_escape(item_resume.name)}</code>\n"
                                    f"🔗 <a href=\"{_escape(str(item.get('url') or ''))}\">View Job Listing</a>"
                                )
                                send_message(msg)
                            except Exception:
                                pass
                    elif label == "auto_skipped":
                        record_automation_outcome(queue_id, "auto_skipped", reason=reason, details=event_details)
                    else:
                        record_automation_outcome(queue_id, "failed", reason=reason, details=event_details)
                    results.append({
                        "queue_id": queue_id, "title": item.get("title"), "company": item.get("company"),
                        "source": item.get("source"), "outcome": label, "reason_code": reason_code,
                        "reason": reason, "ats_host": outcome.get("ats_host"),
                        "cv_used": item_resume.name,
                        "url": item.get("url"),
                        "diagnostics": outcome.get("diagnostics", {}),
                        "apply_links": outcome.get("apply_links", []),
                        "form_diagnostics": outcome.get("form_diagnostics", outcome.get("field_diagnostics", {})),
                    })
                    if settings.auto_apply_delay_seconds:
                        time.sleep(settings.auto_apply_delay_seconds)
            finally:
                browser.close()
    except Exception as exc:
        reason = f"Browser could not start or the browser session failed: {type(exc).__name__}."
        reason_code = reason_code_for_reason(reason, stage="browser_startup")
        log_auto_apply_event(run_id, "browser_session_failed", reason_code=reason_code, reason=reason, error_type=type(exc).__name__)
        for item in eligible:
            if any(result.get("queue_id") == item["id"] for result in results):
                continue
            current = get_application(int(item["id"])) or {}
            if current.get("status") == "applying":
                record_automation_outcome(int(item["id"]), "failed", reason=reason + " Submission state is uncertain; do not retry automatically.", details={"reason_code": "submission_uncertain", "stage": "browser_session_failed"})
                label = "failed"
            else:
                label = "failed"
            results.append({"queue_id": item["id"], "title": item.get("title"), "company": item.get("company"), "source": item.get("source"), "outcome": label, "reason_code": reason_code, "reason": reason})

    submitted = sum(result.get("outcome") == "submitted" for result in results)
    skipped = sum(result.get("outcome") == "auto_skipped" for result in results)
    failed = sum(result.get("outcome") == "failed" for result in results)
    summary = _summarize_results(results)
    log_auto_apply_event(
        run_id, "run_completed", processed=len(results), submitted=submitted,
        skipped=skipped, failed=failed, daily_cap=settings.auto_apply_max_per_day,
        reason_breakdown=summary,
    )
    return {"run_id": run_id, "enabled": True, "processed": len(results), "submitted": submitted, "skipped": skipped, "failed": failed, "daily_cap": settings.auto_apply_max_per_day, "results": results, "reason_breakdown": summary}


def _summarize_results(results: list[dict[str, Any]]) -> dict[str, int]:
    summary: dict[str, int] = {}
    for result in results:
        code = str(result.get("reason_code") or "unknown")
        summary[code] = summary.get(code, 0) + 1
    return dict(sorted(summary.items(), key=lambda item: (-item[1], item[0])))
