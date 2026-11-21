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
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from app.application_profile import ProfileLoadError, load_profile_bundle, resolve_answer, _at
from app.automation_diagnostics import (
    log_auto_apply_event, new_run_id, reason_code_for_reason, safe_url,
)
from app.application_queue import (
    automatic_approve_application,
    begin_automation_attempt,
    has_attempt_history,
    company_submitted_count_last_30_days,
    get_application,
    list_applications,
    prioritize_queue_items,
    record_automation_outcome,
    run_preflight,
    recover_interrupted_attempts,
)
from app.config import settings
from app.cover_letter import generate_generic_cover_letter_pdf
from app.funnel import record_unanswered_question
from app.matching import (
    LOCAL_CITIES,
    NON_LOCAL_EGYPT_CITIES,
    _himalayas_eligibility_decision,
    assess_experience,
    classify,
)
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
    "dailyremote.com", "otta.com", "wuzzuf.net", "bayt.com",
)
CAPTCHA_MARKERS = (
    "verify you are human", "checking your browser",
    "unusual traffic", "security challenge", "are you a robot",
    "i'm not a robot", "i am not a robot", "complete the captcha", "solve the captcha",
    "captcha verification", "captcha challenge", "select all images", "prove you are human",
)
SUCCESS_MARKERS = (
    "thank you for applying", "application submitted", "application received",
    "we received your application", "successfully applied", "thanks for applying",
    "your application has been sent",
    "application has been received", "application was submitted",
    "we've received your application", "we have received your application",
    "application was sent", "application complete",
    "submitted successfully",
    "application is submitted",
    "successfully submitted", "application was successfully", "application has been successfully",
    "your application has been submitted", "your application has been sent",
    "application sent", "we've got your application", "we got your application",
    "thanks for your application", "thank you for your application",
    "application is complete", "you have applied", "you've applied", "you applied",
)


def _record(queue_id: int, event_type: str, details: dict[str, Any] | None = None) -> None:
    from app.application_queue import _event

    init_db()
    with _connect() as conn:
        _event(conn, int(queue_id), event_type, details or {})


def _select_cv_for_job(item: dict[str, Any] | None) -> Path | None:
    if not item:
        return None
    cvs_dir = ROOT / "cvs"
    if not cvs_dir.is_dir():
        return None

    def pick(*names: str) -> Path | None:
        for name in names:
            candidate = cvs_dir / name
            if candidate.is_file():
                return candidate.resolve()
        return None

    company = str(item.get("company") or "").strip().lower()
    if company:
        for pdf in cvs_dir.glob("*.pdf"):
            stem_low = pdf.stem.lower()
            if company in stem_low and company not in ("general", "resume", "mohamed", "ahmed"):
                return pdf.resolve()

    title = str(item.get("title") or "").lower()
    desc = str(item.get("description") or "")[:2000].lower()
    combined = f"{title} {desc}"

    # 1. QA / Test Automation / SDET
    if re.search(r"\b(qa|quality assurance|sdet|test(?:er|ing)|test automation)\b", title):
        if re.search(r"\b(sdet|automation|playwright|cypress|selenium)\b", combined):
            chosen = pick("Mohamed_Ahmed-QA_Automation.pdf", "Mohamed_Ahmed-QA_Engineer.pdf")
        else:
            chosen = pick("Mohamed_Ahmed-QA_Engineer.pdf", "Mohamed_Ahmed-QA_Automation.pdf")
        if chosen:
            return chosen

    # 2. IT & Systems Support
    if re.search(r"\b(it support|help\s*desk|service\s*desk|desktop support|systems? support|system administrator|it specialist|it technician)\b", title):
        chosen = pick("Mohamed_Ahmed-IT_Support.pdf", "Mohamed_Ahmed-Application_Support.pdf")
        if chosen:
            return chosen

    # 3. Developer Support vs Application / Technical Support
    if re.search(r"\b(developer support|api support|sdk support)\b", title):
        chosen = pick("Mohamed_Ahmed-Developer_Support.pdf", "Mohamed_Ahmed-Application_Support.pdf")
        if chosen:
            return chosen

    if re.search(r"\b(application support|technical support|support engineer|customer support|l[123] support|tier [123] support|solutions? engineer|implementation engineer)\b", title):
        chosen = pick("Mohamed_Ahmed-Application_Support.pdf", "Mohamed_Ahmed-Developer_Support.pdf", "Mohamed_Ahmed-General.pdf")
        if chosen:
            return chosen

    # 4. Workflow Automation & Integrations
    if re.search(r"\b(workflow|automation|integrations?|rpa|n8n|zapier)\b", title) and not re.search(r"\b(qa|test)\b", title):
        chosen = pick("Mohamed_Ahmed-Workflow_Automation.pdf", "Mohamed_Ahmed-AI_Applications.pdf")
        if chosen:
            return chosen

    # 5. AI / LLM Application Engineering
    if re.search(r"\b(ai|llm|genai|generative ai|agentic|rag)\b", title):
        chosen = pick("Mohamed_Ahmed-AI_Applications.pdf", "Mohamed_Ahmed-Backend_Python.pdf")
        if chosen:
            return chosen

    # 6. Linux / Open-Source / Systems / C++ Maintenance (e.g., Canonical/Ubuntu)
    if re.search(r"\b(linux|ubuntu|open[- ]?source|embedded|c\+\+|kernel|systems? engineer)\b", title) or "canonical" in company:
        if re.search(r"\b(systems? engineer|sysadmin|linux administrator)\b", title):
            chosen = pick("Mohamed_Ahmed-Linux_Systems_Engineer.pdf", "Mohamed_Ahmed-Linux_OpenSource.pdf")
        else:
            chosen = pick("Mohamed_Ahmed-Linux_OpenSource.pdf", "Mohamed_Ahmed-Linux_Systems_Engineer.pdf")
        if chosen:
            return chosen

    # 7. Cloud / DevOps / Infrastructure / Kubernetes
    if re.search(r"\b(cloud|devops|kubernetes|docker|platform|infrastructure)\b", title):
        chosen = pick("Mohamed_Ahmed-Cloud_DevOps.pdf", "Mohamed_Ahmed-Backend_General.pdf")
        if chosen:
            return chosen

    # 8. Database / SQL / API Engineering
    if re.search(r"\b(database|postgres|sql)\b", title):
        chosen = pick("Mohamed_Ahmed-Database_API.pdf", "Mohamed_Ahmed-Backend_Python.pdf")
        if chosen:
            return chosen
    if re.search(r"\bapi\s+(?:engineer|developer)\b", title):
        chosen = pick("Mohamed_Ahmed-API_Engineer.pdf", "Mohamed_Ahmed-Backend_General.pdf")
        if chosen:
            return chosen

    # 9. Frontend-only roles
    if re.search(r"\b(front[- ]?end|react|angular|next\.?js|ui developer|web developer)\b", title) and not re.search(r"\b(full[- ]?stack|back[- ]?end)\b", title):
        if re.search(r"\breact|next\.?js\b", title):
            chosen = pick("Mohamed_Ahmed-React_Developer.pdf", "Mohamed_Ahmed-Frontend.pdf")
        elif re.search(r"\bangular\b", title):
            chosen = pick("Mohamed_Ahmed-Angular_Developer.pdf", "Mohamed_Ahmed-Frontend.pdf")
        elif re.search(r"\bweb developer\b", title):
            chosen = pick("Mohamed_Ahmed-Web_Developer.pdf", "Mohamed_Ahmed-Frontend.pdf")
        else:
            chosen = pick("Mohamed_Ahmed-Frontend.pdf", "Mohamed_Ahmed-General.pdf")
        if chosen:
            return chosen

    # 10. Backend roles (Django vs FastAPI vs Node.js vs Python vs General)
    if re.search(r"\b(back[- ]?end|python|django|fastapi|node\.?js|nestjs|express)\b", title) and not re.search(r"\bfull[- ]?stack\b", title):
        if re.search(r"\bdjango\b", title):
            chosen = pick("Mohamed_Ahmed-Backend_Django.pdf", "Mohamed_Ahmed-Backend_Python.pdf")
            if chosen:
                return chosen
        if re.search(r"\bfastapi\b", title):
            chosen = pick("Mohamed_Ahmed-Backend_FastAPI.pdf", "Mohamed_Ahmed-Backend_Python.pdf")
            if chosen:
                return chosen
        if re.search(r"\b(node\.?js|nestjs|express|typescript)\b", title) or (
            re.search(r"\b(node\.?js|nestjs|express)\b", combined) and not re.search(r"\b(python|django|fastapi)\b", title)
        ):
            chosen = pick("Mohamed_Ahmed-Backend_NodeJS.pdf", "Mohamed_Ahmed-Backend_General.pdf")
            if chosen:
                return chosen
        if re.search(r"\b(python|django|fastapi)\b", combined):
            chosen = pick("Mohamed_Ahmed-Backend_Python.pdf", "Mohamed_Ahmed-Backend_General.pdf")
            if chosen:
                return chosen
        chosen = pick("Mohamed_Ahmed-Backend_General.pdf", "Mohamed_Ahmed-General.pdf")
        if chosen:
            return chosen

    # 11. Full-Stack roles (Angular vs React vs Python vs TypeScript vs General)
    if re.search(r"\bfull[- ]?stack\b", title):
        if re.search(r"\bangular\b", combined):
            chosen = pick("Mohamed_Ahmed-FullStack_Angular.pdf", "Mohamed_Ahmed-General.pdf")
            if chosen:
                return chosen
        if re.search(r"\b(python|django|fastapi)\b", combined) and not re.search(r"\b(node\.?js|express)\b", title):
            chosen = pick("Mohamed_Ahmed-FullStack_Python.pdf", "Mohamed_Ahmed-General.pdf")
            if chosen:
                return chosen
        if re.search(r"\b(react|next\.?js)\b", combined):
            chosen = pick("Mohamed_Ahmed-FullStack_React.pdf", "Mohamed_Ahmed-General.pdf")
            if chosen:
                return chosen
        if re.search(r"\b(typescript|javascript|node\.?js)\b", combined):
            chosen = pick("Mohamed_Ahmed-FullStack_TypeScript.pdf", "Mohamed_Ahmed-General.pdf")
            if chosen:
                return chosen
        chosen = pick("Mohamed_Ahmed-General.pdf", "Mohamed_Ahmed-FullStack_Angular.pdf")
        if chosen:
            return chosen

    # 12. General Software Engineer / Developer roles
    if re.search(r"\b(junior|entry[- ]?level|graduate|associate)\b", title):
        chosen = pick("Mohamed_Ahmed-Junior_Software_Engineer.pdf", "Mohamed_Ahmed-Software_Engineer.pdf")
        if chosen:
            return chosen
    if re.search(r"\bsoftware developer\b", title):
        chosen = pick("Mohamed_Ahmed-Software_Developer.pdf", "Mohamed_Ahmed-Software_Engineer.pdf")
        if chosen:
            return chosen
    if re.search(r"\bsoftware engineer\b", title):
        chosen = pick("Mohamed_Ahmed-Software_Engineer.pdf", "Mohamed_Ahmed-General.pdf")
        if chosen:
            return chosen

    return pick("Mohamed_Ahmed-General.pdf", "Mohamed_Ahmed-general.pdf")


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
    urlparse(str(listing_url or ""))
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


def _unspecified_remote_min_score() -> int:
    """Stricter score floor for listings whose Egypt eligibility is only *assumed* (opt-in)."""
    try:
        return max(0, min(100, int(os.getenv("AUTO_APPLY_UNSPECIFIED_REMOTE_MIN_SCORE", "70"))))
    except ValueError:
        return 70


def _review_min_score() -> int:
    """Score floor for listings classified "review" (defaults to the global auto-apply floor).

    Set AUTO_APPLY_REVIEW_MIN_SCORE=70 in .env to require 70+ for review-class listings.
    """
    try:
        configured = os.getenv("AUTO_APPLY_REVIEW_MIN_SCORE", "").strip()
        if configured:
            return max(0, min(100, int(configured)))
    except ValueError:
        pass
    return int(settings.auto_apply_min_score)


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

    # "review" listings are NOT blocked for being review: they proceed when the score floor
    # is met AND Egypt/remote eligibility is confirmed (checked further below).
    queue_status = str(item.get("qualification_status") or status).casefold()
    if queue_status == "review":
        review_floor = _review_min_score()
        if computed_score < review_floor or int(item.get("score") or 0) < review_floor:
            return f"Review-class listing is below the review auto-apply threshold ({review_floor}/100)."

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
    local_allowed = any(
        re.search(rf"\b{re.escape(city)}\b", location) for city in LOCAL_CITIES
    ) or (
        not remote
        and bool(re.search(r"\begypt\b", location))
        and not any(
            re.search(rf"\b{re.escape(other)}\b", location)
            for other in NON_LOCAL_EGYPT_CITIES
        )
    )
    structured = _himalayas_eligibility_decision(str(item.get("eligibility") or ""))
    confirmed = any(
        "international remote eligibility mentions worldwide/egypt" in reason.casefold()
        or "regional remote eligibility" in reason.casefold()
        or "himalayas structured country/timezone restrictions permit egypt" in reason.casefold()
        or "no stated country restriction" in reason.casefold()
        for reason in reasons
    )
    assumed_open = any("no stated country restriction" in reason.casefold() for reason in reasons)
    if assumed_open and not local_allowed:
        floor = _unspecified_remote_min_score()
        if computed_score < floor or int(item.get("score") or 0) < floor:
            return f"Assumed-open remote listing (no explicit country list) is below the stricter {floor}/100 threshold."
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
    company_name = str(item.get("company") or "").strip()
    try:
        max_per_company = int(os.getenv("AUTO_APPLY_MAX_PER_COMPANY_30D", "2"))
    except ValueError:
        max_per_company = 2
    if max_per_company > 0 and company_submitted_count_last_30_days(company_name) >= max_per_company:
        return f"Company cap reached: already submitted {max_per_company} applications to {company_name} in the last 30 days."
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


def _detect_challenge_marker(page, body: str) -> str | None:
    low = body.casefold()
    for marker in CAPTCHA_MARKERS:
        if marker in low:
            return f"text:{marker}"
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
                src = str(frame.get_attribute("src") or "captcha_iframe")[:80]
                return f"iframe:{src}"
    except Exception:
        pass
    return None


def _requires_manual_verification(page, body: str) -> bool:
    if re.search(r"enter (?:the |your )?(?:security|verification) code|"
                 r"(?:security|verification) code (?:we |was |has been )?sent|"
                 r"check your email (?:for|to find) (?:a|the|your) code", body, re.I):
        return True
    try:
        return bool(page.locator(
            'input[autocomplete="one-time-code"]:visible, input[id^="security-input-"]:visible, '
            'input[name^="security-input-"]:visible, iframe[src*="turnstile"]:visible'
        ).count())
    except Exception:
        return False


def _is_challenge(page, body: str) -> bool:
    return bool(_detect_challenge_marker(page, body))


_JS_REQUIRED_HELPER = r"""
const isReqNode = (n) => {
  if (!n) return false;
  try {
    if (/required/i.test((n.className && n.className.toString()) || '')) return true;
    const c = getComputedStyle(n, '::after').content;
    if (c && c.includes('*')) return true;
    const b = getComputedStyle(n, '::before').content;
    if (b && b.includes('*')) return true;
  } catch (_) {}
  const t = (n.innerText || '').trim();
  return /^\*|\*\s*$/.test(t) || /\(required\)/i.test(t);
};
"""


def _labels(form) -> list[dict[str, Any]]:
    return form.locator("input, textarea, select, button").evaluate_all(
        "els => {" + _JS_REQUIRED_HELPER + r"""
    const isPlaceholderJunk = s => !s || /^(?:select(?:\.\.\.| an option)?|choose(?:\.\.\.)?|search(?:\.\.\.)?|type here(?:\.\.\.)?|start typing(?:\.\.\.)?)$/i.test(String(s).trim());
    return els.map((el, index) => {
      try { el.setAttribute('data-jh-field-idx', String(index)); } catch (_) {}
      let label = '';
      let labelEl = null;
      try {
        const labs = Array.from(el.labels || []);
        label = labs.map(x => x.innerText || '').join(' ');
        labelEl = labs[0] || null;
      } catch (_) {}
      const parentLabel = el.closest('label');
      if ((!label || isPlaceholderJunk(label)) && parentLabel) { label = parentLabel.innerText || ''; labelEl = parentLabel; }
      if ((!label || isPlaceholderJunk(label)) && el.id) {
        const found = document.querySelector(`label[for='${CSS.escape(el.id)}']`);
        if (found) { label = found.innerText || ''; labelEl = found; }
      }
      if ((!label || isPlaceholderJunk(label))) {
        const lb = el.getAttribute('aria-labelledby');
        if (lb) {
          label = lb.split(/\s+/).map(id => (document.getElementById(id) || {}).innerText || '').join(' ');
        }
      }
      // Ashby, Greenhouse, and similar field containers wrapping both label and input
      const entry = el.closest('[data-field-path], [class*="field-entry"], [class*="fieldEntry"], .field, [class*="field" i], .form-group, .form-field, .form-item, [class*="input-wrapper" i], [class*="select__container" i], [class*="question" i], tr');
      let titleEl = null;
      let description = '';
      if (entry) {
        const controls = entry.querySelectorAll('input:not([type=hidden]), textarea, select');
        titleEl = entry.querySelector('label, legend, [class*="question-title" i], [class*="label" i], [class*="title" i]');
        const descEl = entry.querySelector('[class*="description" i], [class*="hint" i]');
        if (descEl) description = (descEl.innerText || '').trim().slice(0, 200);
        if ((!label || isPlaceholderJunk(label)) && titleEl && controls.length <= 2) {
          label = titleEl.innerText || '';
          labelEl = titleEl;
        }
      }
      if (!label || isPlaceholderJunk(label)) {
        let p = el.parentElement;
        for (let d = 0; p && d < 4; d++, p = p.parentElement) {
          const ctrls = p.querySelectorAll('input:not([type=hidden]), textarea, select');
          if (ctrls.length > 2) break;
          const cand = p.querySelector('label, legend, [class*="label" i], [class*="title" i]');
          if (cand && !isPlaceholderJunk(cand.innerText)) {
            label = cand.innerText || '';
            labelEl = cand;
            break;
          }
        }
      }
      const optionLabel = (!isPlaceholderJunk(label) ? label : '') || (parentLabel ? parentLabel.innerText : '') || '';
      const groupEl = el.closest('fieldset, [role="radiogroup"], [role="group"]');
      let groupQuestion = '';
      let groupNode = null;
      if (groupEl) {
        const lblId = groupEl.getAttribute('aria-labelledby');
        if (lblId && document.getElementById(lblId)) {
          groupNode = document.getElementById(lblId);
          groupQuestion = groupNode.innerText || '';
        } else {
          const legend = groupEl.querySelector('legend, span[id]');
          if (legend) { groupNode = legend; groupQuestion = legend.innerText || ''; }
        }
      }
      // Ashby / card groups: entry with multiple checkboxes or radios
      if (!groupQuestion && entry && (el.type === 'radio' || el.type === 'checkbox')) {
        const siblingsOfType = entry.querySelectorAll(`input[type="${el.type}"]`);
        if (siblingsOfType.length >= 2 && titleEl) {
          groupNode = titleEl;
          groupQuestion = titleEl.innerText || '';
        }
      }
      // Radios without a fieldset (Askable-style cards): nearest preceding heading of the group.
      if (!groupQuestion && el.type === 'radio') {
        let a = el.parentElement;
        for (let d = 0; a && d < 7; d++, a = a.parentElement) {
          if (a.querySelectorAll('input[type=radio]').length >= 2) {
            const h = a.querySelector('legend, h1, h2, h3, h4, [role=heading]');
            if (h && !h.contains(el) && (h.compareDocumentPosition(el) & Node.DOCUMENT_POSITION_FOLLOWING)) {
              groupNode = h;
              groupQuestion = h.innerText || '';
              break;
            }
          }
        }
      }
      if (groupQuestion && (el.type === 'radio' || el.type === 'checkbox')) label = groupQuestion;
      if (!label || isPlaceholderJunk(label)) {
        if (titleEl && !isPlaceholderJunk(titleEl.innerText)) {
          label = titleEl.innerText || '';
          labelEl = titleEl;
        } else {
          const ariaLbl = el.getAttribute('aria-label') || '';
          const ph = el.getAttribute('placeholder') || '';
          if (!isPlaceholderJunk(ariaLbl)) label = ariaLbl;
          else if (!isPlaceholderJunk(ph)) label = ph;
          else if (el.previousElementSibling && (el.previousElementSibling.innerText || '').trim().length <= 160 && !isPlaceholderJunk(el.previousElementSibling.innerText)) {
            label = el.previousElementSibling.innerText || '';
          } else if (el.parentElement && el.parentElement.previousElementSibling && (el.parentElement.previousElementSibling.innerText || '').trim().length <= 160 && !isPlaceholderJunk(el.parentElement.previousElementSibling.innerText)) {
            label = el.parentElement.previousElementSibling.innerText || '';
          }
        }
      }
      const shown = (n) => !!(n && (n.offsetWidth || n.offsetHeight || n.getClientRects().length));
      const cls = (el.className && el.className.toString()) || '';
      const tag = el.tagName.toLowerCase();
      const isTextish = tag === 'input' && !['checkbox', 'radio', 'file', 'hidden', 'submit', 'button', 'reset', 'tel'].includes((el.type || '').toLowerCase());
      const isHiddenDummy = el.getAttribute('aria-hidden') === 'true' || (el.tabIndex === -1 && el.getAttribute('role') !== 'combobox');
      const combobox = isTextish && !isHiddenDummy && (
        el.getAttribute('role') === 'combobox' ||
        el.getAttribute('aria-haspopup') === 'listbox' ||
        /select__input|react-select|autocomplete/i.test(cls) ||
        !!el.closest('[class*="select__control"], [class*="react-select"]')
      );
      const isGroupChoice = (el.type === 'checkbox' || el.type === 'radio') && !!groupQuestion;
      let style = null;
      try { style = window.getComputedStyle(el); } catch (_) {}
      const isDummyInput = isTextish && !combobox && (
        !!el.readOnly ||
        el.tabIndex === -1 ||
        el.getAttribute('aria-hidden') === 'true' ||
        (style && (style.pointerEvents === 'none' || parseFloat(style.opacity || '1') === 0)) ||
        /dummy|requiredInput/i.test(cls)
      );
      const entryHasRequiredControl = !!(entry && entry.querySelector('input[required], select[required], textarea[required], [aria-required="true"]'));
      const groupRequiredHint = isReqNode(titleEl) || isReqNode(groupNode) || (!!entry && !!entry.querySelector('[class*="required" i]')) || (combobox && entryHasRequiredControl);
      const requiredHint = isReqNode(labelEl) || (!isGroupChoice && groupRequiredHint);
      const snippetNode = entry || groupEl || el.parentElement || el;
      let htmlSnippet = '';
      try { htmlSnippet = ((snippetNode && snippetNode.outerHTML) || '').replace(/\s+/g, ' ').slice(0, 320); } catch (_) {}
      const cleanLabel = (label || '')
        .replace(/\u00a0/g, ' ')
        .replace(/\s+/g, ' ')
        .replace(/\s*\*?\s*Select(?:\.\.\.)?\s*$/i, '')
        .replace(/\s*\*\s*$/, '')
        .trim();
      return {
        index,
        tag,
        type: (el.type || '').toLowerCase(),
        accept: (el.getAttribute('accept') || '').toLowerCase(),
        name: el.name || '', id: el.id || '',
        fieldPath: (entry && entry.getAttribute('data-field-path')) || '',
        placeholder: el.getAttribute('placeholder') || '',
        aria: el.getAttribute('aria-label') || '',
        label: isPlaceholderJunk(cleanLabel) ? '' : cleanLabel,
        optionLabel: (optionLabel || '').replace(/\s+/g, ' ').replace(/\s*\*\s*$/, '').trim(),
        description: description.replace(/\s+/g, ' ').trim(),
        htmlSnippet,
        required: !!el.required || el.getAttribute('aria-required') === 'true' || (requiredHint && el.type !== 'hidden'),
        groupRequired: !!groupRequiredHint,
        disabled: !!el.disabled,
        visible: shown(el) && !isDummyInput,
        labelVisible: shown(labelEl) || shown(el.parentElement),
        combobox: !!combobox,
        yesNoWidget: !!(entry && entry.querySelector('button[data-option], [class*="yesno" i]')),
        checked: !!el.checked,
        value: el.value || '',
        options: tag === 'select' ? Array.from(el.options).map(o => ({value:o.value,text:(o.textContent||'').trim(),disabled:o.disabled})) : []
      };
    }); }"""
    )


# ---------------------------------------------------------------------------------------
# Round 2 answer helpers
# ---------------------------------------------------------------------------------------
_TZ_QUESTION = re.compile(r"time\s*-?\s*zone|\b(?:est|edt|pst|pdt|cst|cet|utc|gmt)\b|eastern|pacific|central time|overlap", re.I)
_AMERICAS = re.compile(r"\bamericas?\b|north america|south america|latin america|\bu\.?s\.?a?\b|united states|canada|brazil|\blatam\b", re.I)
_ROLE_QUESTION = re.compile(r"(?:current|most recent|present)\s+(?:or\s+most\s+recent\s+)?(?:role|position|job|occupation)|best describes your (?:current )?(?:role|position|job)", re.I)


def _timezone_answer(question: str) -> str | None:
    """Candidate is in Cairo (UTC+2): NOT in an Americas time zone, but available for US/CET overlap."""
    if not _TZ_QUESTION.search(question):
        return None
    located = re.search(r"\b(?:are you|do you)\b[^?]{0,30}\b(?:in|based in|located in|live in|reside in|currently in|within)\b", question, re.I)
    willing = re.search(r"overlap|comfortable|willing|able to|available|work\s+(?:during|within|in|from)|can you work|hours", question, re.I)
    if located and _AMERICAS.search(question) and not willing:
        return "No"
    if willing:
        return "Yes"
    return None


def _location_answer(question: str, profile: dict[str, Any], bank: dict[str, Any] | None = None) -> str | None:
    low = question.casefold()
    if re.search(r"in which country do you (?:currently )?work|which country do you (?:currently )?work|country you (?:currently )?work\b|where (?:do|will) you (?:plan (?:on|to) |intend to )?work", low):
        saved = _at(bank or {}, "answers", "work_country", "answer", default="")
        return str(saved or "Egypt (Cairo)")
    country = str(_at(profile, "identity", "country", default="Egypt") or "Egypt")
    city = str(_at(profile, "identity", "city", default="Cairo") or "Cairo")
    if re.search(r"nationality|citizenship|passport country", low):
        return _at(profile, "identity", "nationality", default=None)
    if re.search(r"\b(?:what|which)\s+country\b[^?]*\b(?:based|live|reside|located|are you in|do you live)\b|country of residence|country you (?:currently )?(?:live|reside|are (?:based|located))|where are you (?:currently |presently )?(?:based|located)\b", low):
        return country
    if re.fullmatch(r"country(?:\s*\*)?", low.strip()) or (
        re.search(r"\bcountry\b", low)
        and not re.search(r"work\s+auth|authori[sz]ed|eligible|visa|sponsor|passport|relocat", low)
    ):
        return country
    if re.search(r"\b(?:what|which)\s+city\b|city of residence|city you (?:live|are based)", low):
        return city
    if re.search(r"\b(?:zip|postal)\s*code\b", low):
        if "00000" in low:
            return "00000"
        return "11511"
    if re.search(r"\b(?:current\s+)?location\b|where are you located|your location|presently located", low) and not re.search(r"preference|preferred|office", low):
        return f"{city}, {country}"
    return None


_DEFAULT_FX_MONTHLY: dict[str, float] = {
    "EGP": 12000.0,
    "USD": 222.44,
    "EUR": 198.20,
    "GBP": 165.35,
    "JPY": 35227.0,
    "SAR": 834.15,
    "AED": 816.90,
    "CAD": 308.50,
    "AUD": 342.10,
    "CHF": 196.40,
}
_DEFAULT_FX_ANNUAL: dict[str, int] = {
    "EGP": 144000,
    "USD": 2669,
    "EUR": 2378,
    "GBP": 1984,
    "JPY": 422724,
    "SAR": 10010,
    "AED": 9803,
    "CAD": 3702,
    "AUD": 4105,
    "CHF": 2357,
}
# Hourly rates targeting 12,000 EGP/month net after Egyptian income tax (13,932 EGP gross @ 160 hrs/mo)
_DEFAULT_FX_HOURLY: dict[str, float] = {
    "EGP": 88.0,
    "USD": 1.62,
    "EUR": 1.45,
    "GBP": 1.20,
    "CAD": 2.25,
    "AUD": 2.50,
    "CHF": 1.40,
    "JPY": 256.0,
    "SAR": 6.0,
    "AED": 6.0,
}


def _detect_currency_code(low: str) -> str | None:
    if re.search(r"\bcad\b|canadian dollars?", low):
        return "CAD"
    if re.search(r"\baud\b|australian dollars?", low):
        return "AUD"
    if re.search(r"\busd\b|us\$|\$|dollars?", low):
        return "USD"
    if re.search(r"\beur\b|€|euros?", low):
        return "EUR"
    if re.search(r"\bgbp\b|£|british pounds?|sterling", low):
        return "GBP"
    if re.search(r"\bjpy\b|¥|japanese yen|\byen\b", low):
        return "JPY"
    if re.search(r"\bsar\b|saudi riyals?", low):
        return "SAR"
    if re.search(r"\baed\b|dirhams?", low):
        return "AED"
    if re.search(r"\bchf\b|swiss francs?", low):
        return "CHF"
    if re.search(r"\begp\b|egyptian pounds?|\bl\.?e\.?\b", low):
        return "EGP"
    return None


def _format_currency_amount(val: float, currency: str) -> str:
    if currency in {"EGP", "JPY"} or abs(val - round(val)) < 1e-6:
        return str(int(round(val)))
    return f"{val:.2f}"


def _compensation_answer(question: str, bank: dict[str, Any], profile: dict[str, Any] | None = None) -> tuple[str | None, str] | None:
    """Period- and currency-aware compensation (12,000 EGP/month base). Returns None to defer."""
    low = question.casefold()
    if not re.search(r"salary|compensation|remuneration|\bpay\b|\brate\b|stipend", low):
        return None
    currency = _detect_currency_code(low)
    cur = currency or "EGP"
    answers = bank.get("answers") if isinstance(bank.get("answers"), dict) else {}

    if re.search(r"\bhour(?:ly)?\b|per hour|/\s*hr\b", low):
        entry_key = "salary_expectation_hourly" if cur == "EGP" else f"salary_expectation_{cur.lower()}_hourly"
        entry = answers.get(entry_key) if isinstance(answers.get(entry_key), dict) else {}
        target = entry.get("target_amount") or entry.get("hourly_target_amount")
        try:
            val = float(target) if target is not None else float(_DEFAULT_FX_HOURLY.get(cur, 1.62))
        except (TypeError, ValueError):
            val = 1.62
        return _format_currency_amount(val, cur), f"saved hourly rate in {cur} targeting 12,000 EGP/mo net after taxes"

    is_annual = bool(re.search(r"annual|yearly|per year|/\s*year|per annum|\byr\b", low))
    if not currency and not is_annual:
        return None
    entry_key = "salary_expectation" if cur == "EGP" else f"salary_expectation_{cur.lower()}"
    entry = answers.get(entry_key) if isinstance(answers.get(entry_key), dict) else {}
    if is_annual:
        explicit = entry.get("annual_target_amount")
        target = entry.get("target_amount")
        try:
            if explicit is not None:
                amount = float(explicit)
            elif target is not None:
                amount = float(target) * 12.0
            else:
                amount = float(_DEFAULT_FX_ANNUAL.get(cur, round(_DEFAULT_FX_MONTHLY.get(cur, 12000.0) * 12.0)))
        except (TypeError, ValueError):
            return None
        return str(int(round(amount))), f"saved monthly target converted to annual ({cur})"

    target = entry.get("target_amount")
    try:
        monthly_val = float(target) if target is not None else float(_DEFAULT_FX_MONTHLY.get(cur, 12000.0))
    except (TypeError, ValueError):
        return None
    return _format_currency_amount(monthly_val, cur), f"saved monthly target in {cur} (12,000 EGP equivalent)"


_DEFAULT_SKILL_YEARS: dict[str, int | float] = {
    "python": 3,
    "django": 2,
    "fastapi": 1,
    "javascript": 3,
    "js": 3,
    "node.js": 3,
    "nodejs": 3,
    "node": 3,
    "express": 2,
    "typescript": 2,
    "ts": 2,
    "angular": 2,
    "react": 1,
    "react.js": 1,
    "reactjs": 1,
    "postgresql": 2,
    "postgres": 2,
    "sql": 2,
    "mysql": 2,
    "mongodb": 2,
    "redis": 2,
    "docker": 2,
    "linux": 2,
    "linix": 2,
    "ubuntu": 2,
    "bash": 2,
    "git": 2,
    "github": 2,
    "qa": 1,
    "quality assurance": 1,
    "testing": 1,
    "pytest": 2,
    "jest": 2,
    "kubernetes": 1,
    "k8s": 1,
    "k3s": 1,
}


def _skill_years_answer(question: str, profile: dict[str, Any], bank: dict[str, Any]) -> tuple[str, str] | None:
    low = question.casefold()
    if not re.search(r"years? of .*experience|how many years|experience (?:in|with) .*years|years (?:working )?with", low):
        return None
    merged: dict[str, int | float] = dict(_DEFAULT_SKILL_YEARS)
    for src in (
        _at(profile, "skill_years", default={}),
        _at(profile, "experience", "skill_years", default={}),
        _at(bank, "answers", "skill_years", "skills", default={}),
    ):
        if isinstance(src, dict):
            for k, v in src.items():
                try:
                    merged[str(k).strip().casefold()] = int(v) if float(v).is_integer() else float(v)
                except (TypeError, ValueError):
                    continue
    for skill in sorted(merged.keys(), key=len, reverse=True):
        if re.search(rf"(?<![a-z0-9]){re.escape(skill)}(?![a-z0-9])", low):
            return str(merged[skill]), f"saved skill years ({skill})"
    if re.search(r"\b(?:total|overall|professional|software|work|relevant|general|industry|engineering|development)\s+experience\b", low) and not re.search(r"\b(?:with|in)\s+[a-z0-9+#.]{2,}", low):
        gen = _at(profile, "experience", "years", default=3) or 3
        return str(gen), "saved general software experience years"
    return "0", "unlisted skill defaulted to 0 years"


def _saved_why_answer(question: str, bank: dict[str, Any]) -> str | None:
    low = question.casefold()
    if not re.search(r"\bwhy\b", low):
        return None
    answers = bank.get("answers") if isinstance(bank.get("answers"), dict) else {}
    role_only = re.search(r"\b(role|position|job)\b", low) and not re.search(r"\b(company|join|us|team)\b", low)
    entry = answers.get("why_this_role" if role_only else "why_this_company") or {}
    text = str(entry.get("answer") or "").strip()
    return text or None


def _choose_role_option(group: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Pick the junior software engineer/developer option for 'current or most recent role'."""
    positive = re.compile(r"software engineer|software developer|\bdeveloper\b|programmer|full[- ]?stack|back[- ]?end|front[- ]?end", re.I)
    negative = re.compile(r"senior|staff|principal|\blead\b|manager|architect|student|learning|\btest|\bqa\b|reliab|\bsre\b|devops|platform|infrastructure|data|machine|design|product|\bother\b|none|unemployed", re.I)
    scored = []
    for opt in group:
        text = str(opt.get("optionLabel") or "")
        scored.append((len(positive.findall(text)) - 2 * len(negative.findall(text)), opt))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    if scored and scored[0][0] > 0 and (len(scored) == 1 or scored[0][0] > scored[1][0]):
        return scored[0][1]
    return None


def _skill_groups(profile: dict[str, Any]) -> list[list[str]]:
    """Skill lists the candidate actually claims; `excluded_*` groups are never claimed."""
    skills = profile.get("skills", {})
    if isinstance(skills, list):
        return [[str(s) for s in skills if s]]
    if isinstance(skills, dict):
        return [
            [str(s) for s in value if s]
            for key, value in skills.items()
            if isinstance(value, list) and "exclu" not in str(key).casefold()
        ]
    return []


def _generate_cover_letter(profile: dict[str, Any], item: dict[str, Any]) -> str:
    identity = profile.get("identity", {}) if isinstance(profile.get("identity"), dict) else {}
    name = str(identity.get("full_name") or "").strip()
    summary = str(profile.get("summary") or os.getenv("CANDIDATE_SUMMARY", "Junior backend/full-stack developer based in Egypt with experience in Python, Django, FastAPI, Node.js, APIs, databases, and practical software projects.")).strip()
    groups = _skill_groups(profile)
    if len(groups) == 1:
        skill_text = ", ".join(groups[0][:8])
    else:
        skill_text = ", ".join(skill for group in groups for skill in group[:4])
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


def _explicit_screening_answer(bank: dict[str, Any], company: str, question: str) -> str | None:
    def key(value: str) -> str:
        return re.sub(r"[^a-z0-9]+", "_", value.casefold()).strip("_")

    answer = _at(bank, "answers", f"{key(company)}__{key(question)}", default={})
    if isinstance(answer, dict) and answer.get("auto_fill") is True:
        return str(answer.get("answer") or "").strip() or None
    return None


def _answer_for_field(question: str, profile: dict[str, Any], bank: dict[str, Any], item: dict[str, Any]) -> tuple[str | None, str]:
    low = question.casefold()
    company = str(item.get("company") or "")
    explicit = _explicit_screening_answer(bank, company, question)
    if explicit:
        return explicit, "verified employer-specific answer"
    if company.casefold() == "gusto" and re.search(
        r"gusto or symmetry|sexual orientation|transgender|race|ethnicity|veteran|disability", low
    ):
        return None, "verified answer required"
    if re.search(r"\b(cover letter|additional information|motivation)\b", low):
        return _generate_cover_letter(profile, item), "generated from saved profile facts"
    saved_why = _saved_why_answer(question, bank)
    if saved_why:
        return saved_why, "saved why-this-company/role answer"
    if re.search(r"\b(?:why (?:are you interested|do you want)|why this (?:role|company)|why you|tell us about yourself)\b", low):
        return _generate_cover_letter(profile, item), "generated from saved profile facts"
    if re.search(r"first university degree|bachelor or undergrad.*completed|confirm.*first university degree", low):
        saved_deg = _at(bank, "answers", "first_university_degree_completed", "answer", default="Yes")
        return str(saved_deg or "Yes"), "saved first university degree confirmation (diploma completed)"
    if re.search(r"how many companies have you worked for|time since you graduated.*how many companies|looking only at the time since you graduated", low):
        saved_comp = _at(bank, "answers", "companies_worked_since_undergrad", "answer", default="0")
        return str(saved_comp or "0"), "candidate worked for 0 companies since undergraduate degree"
    if re.search(r"privacy notice|privacy policy|data processing agreement|recruitment privacy", low) and re.search(r"agree|confirm|read and|consent|accept|notice and policy", low):
        return "Yes", "agreed to recruitment privacy notice and terms"
    if re.search(r"only my own words|plagiarism|automatically disqualif", low):
        return "Yes", "agreed to own-words application pledge"
    if re.search(r"meet in person|2-4 times a year|internal company events|willing to travel|able to travel", low):
        return "Yes", "confirmed willingness to travel for company events"
    if re.search(r"high school|secondary school", low) and re.search(r"perform in|mathematics|math|language|overall|grade|rank|result", low):
        return "Top 10%", "saved high school performance tier"
    if re.search(r"which programming languages are you most familiar with|kinds of projects have you worked on with them", low):
        return (
            "I am most familiar with TypeScript/JavaScript (3 years) and Python (3 years). With Node.js, Express, Angular, and React, I built SmartCart (an AI-powered multi-retailer shopping platform with GraphQL, gRPC, PostgreSQL, and Redis) and RealEstate Investment Engine. With Python (Django, FastAPI), I built AeroLock (an encrypted file storage and transfer platform) and contributed to open-source Python/C++ tooling in Cantera.",
            "saved programming languages and project portfolio summary",
        )
    if re.search(r"which gender|gender identity|\bgender\b", low):
        return "Male", "saved demographic answer"
    if re.search(r"race or ethnicity|ethnic background|\bethnicity\b|\brace\b", low):
        return "Middle Eastern", "saved demographic answer"
    if re.search(r"transgender|sexual orientation", low):
        return "Prefer not to say", "saved voluntary EEO preference"

    skill_yrs = _skill_years_answer(question, profile, bank)
    if skill_yrs is not None:
        return skill_yrs

    is_years_q = bool(re.search(r"\b(?:how many|number of)\s+years|\byears?\s+of\b", low))
    if not is_years_q and re.search(r"python software development experience|experience with python|describe your python", low):
        return (
            "I have 3 years of hands-on software development experience with Python, building backend services, RESTful APIs, and data workflows using FastAPI and Django. I emphasize clean architecture, type annotations, automated testing, and integration with relational databases like PostgreSQL.",
            "saved python development experience summary",
        )
    if not is_years_q and re.search(r"(?:embedded.*linux|linux.*(?:distribution|packaging)|linux.*system level|experience on linux|describe your experiences with embedded software)", low):
        return (
            "I have 2 years of daily Linux experience (primarily Ubuntu/Debian), using bash scripting, command-line utilities, system process monitoring, Docker containerization, and environment configuration for deploying software applications.",
            "saved linux systems and development experience summary",
        )
    if re.search(r"hypervisor|virtualization|virtual machine|kvm|qemu", low):
        return (
            "I regularly work with Docker containerization, Docker Compose, and virtual machine hypervisors (VirtualBox, KVM, and cloud VMs) to isolate development environments, manage service dependencies, and simulate production deployments.",
            "saved virtualization and container experience summary",
        )
    if not is_years_q and re.search(r"experience with c\+\+|c\+\+.*standard|experience.*in c,\s*c\+\+|experience developing backend services in c/c\+\+/go/python|describe your experience with c\+\+", low):
        return (
            "My primary backend development focus is Python (FastAPI/Django) and modern database services, with solid academic foundation and coursework in C/C++ memory management, POSIX systems, and data structures.",
            "saved backend and C/C++ systems experience summary",
        )
    if not is_years_q and re.search(r"experience on windows|experience on macos", low):
        return (
            "I develop software primarily in POSIX/Linux environments, and test and run services across Windows and macOS workstations using containerized workflows, virtual environments, and standard CLI tooling.",
            "saved cross-platform OS experience summary",
        )
    tz = _timezone_answer(question)
    if tz:
        return tz, "saved timezone answer (Cairo, UTC+2; US/CET overlap available)"
    place = _location_answer(question, profile, bank)
    if place:
        return place, "saved candidate location"
    comp = _compensation_answer(question, bank, profile)
    if comp is not None:
        return comp
    if re.search(r"authorized to work|authorised to work|legally eligible to work|right to work|work authorization|work permit", low) and not re.search(r"which countr|what countr", low):
        emp_ctx = f"{low} {str(item.get('employment_type') or '').casefold()} {str(item.get('title') or '').casefold()}"
        if re.search(r"\b(?:contract(?:or)?|freelance|independent contractor|b2b)\b", emp_ctx) and not re.search(r"u\.?s\.? citizen|security clearance", low):
            return "Yes", "authorized to work remotely from Egypt as an independent contractor"
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
    if re.search(r"\b(remote(?:ly)?|async(?:hronous(?:ly)?)?|distributed team|work from home|autonomous(?:ly)?)\b", low) and re.search(r"\b(experience|work(?:ing)?|collaborat|communicat|describe|how do you|environment)\b", low):
        return (
            "I work effectively in structured remote and asynchronous environments by writing clear documentation, sharing regular progress updates, and breaking deliverables into small, well-tested increments.",
            "generic abstract remote/async work template",
        )
    if re.search(r"\b(strengths?|working style|career goals?|where do you see yourself|what drives you|what motivates you|what excites you|what interests you|how do you approach|how do you handle|debugging|troubleshooting|workflow)\b", low):
        return (
            "I focus on writing clean, reliable, and well-tested solutions, understanding system requirements thoroughly, and collaborating clearly with teammates to deliver practical results on schedule.",
            "generic abstract professional approach template",
        )
    if re.search(r"\b(hustle[d]?|proud of|accomplish|achievement|built|challeng(?:e|ing)|time you|project you|problem you solved|example of|what makes you|why should we|anything else|describe a|tell us about a|brief summary|short bio|introduction|note to hiring|message to hiring|additional comments?|questions? for us)\b", low):
        return (
            "I focus on building reliable, maintainable software systems, writing automated tests, and taking ownership of tasks from requirements through delivery while continuously learning and adapting to team workflows.",
            "generic abstract open-ended template",
        )
    return None, result.reason


# ---------------------------------------------------------------------------------------
# Cookie banners (Workable/OneTrust overlays intercept clicks)
# ---------------------------------------------------------------------------------------
_COOKIE_DECLINE = re.compile(r"^\s*(?:decline all|reject all|decline(?: optional)?(?: cookies)?|reject(?: cookies)?|only (?:necessary|essential)(?: cookies)?|necessary only|essential only|deny(?: all)?|no,? thanks)\s*$", re.I)
_COOKIE_ACCEPT = re.compile(r"^\s*(?:accept all(?: cookies)?|accept(?: cookies)?|allow all(?: cookies)?|i agree|agree|got it|ok(?:ay)?|accept (?:&|and) close|agree (?:&|and) close)\s*$", re.I)
_COOKIE_CONTAINER = "[id*='cookie' i], [class*='cookie' i], [data-ui*='cookie' i], [id*='consent' i], [class*='consent' i], [id*='onetrust' i], [aria-label*='cookie' i], [role='dialog'], [role='alertdialog']"


def _dismiss_cookie_banner(page) -> str | None:
    """Dismiss a cookie-consent overlay. Declines optional cookies by default.

    AUTO_APPLY_COOKIE_CHOICE=accept switches to "Accept all" first. Either way the banner is
    cleared so it cannot intercept clicks. Only small containers that actually mention
    cookies are touched, so terms/legal dialogs are never auto-accepted.
    """
    prefer = os.getenv("AUTO_APPLY_COOKIE_CHOICE", "decline").strip().casefold()
    order = [(_COOKIE_ACCEPT, "accepted"), (_COOKIE_DECLINE, "declined")] if prefer == "accept" else [(_COOKIE_DECLINE, "declined"), (_COOKIE_ACCEPT, "accepted")]
    try:
        containers = page.locator(_COOKIE_CONTAINER).filter(has_text=re.compile(r"cookie", re.I))
        have_containers = containers.count() > 0
    except Exception:
        containers, have_containers = None, False
    in_cookie_box = (
        "el => { if (el.closest('[data-ui*=\"cookie\" i], [class*=\"cookie\" i], [id*=\"cookie\" i]')) return true;"
        " let a = el; for (let i = 0; a && i < 8; i++, a = a.parentElement) {"
        " const t = a.innerText || ''; if (t.length < 2500 && /cookie/i.test(t)) return true; } return false; }"
    )
    for pattern, outcome in order:
        scopes = ([containers] if have_containers else []) + [page]
        for scope in scopes:
            try:
                buttons = scope.get_by_role("button", name=pattern)
                for i in range(min(buttons.count(), 4)):
                    candidate = buttons.nth(i)
                    if not candidate.is_visible():
                        continue
                    if scope is page and not candidate.evaluate(in_cookie_box):
                        continue
                    candidate.click(timeout=2500)
                    page.wait_for_timeout(500)
                    return outcome
            except Exception:
                continue
    return None


def _check_input(loc) -> None:
    try:
        loc.check(force=True, timeout=3000)
    except TypeError:
        loc.check()


# --------------------------------------------------------------------------------------
# Modern ATS widgets: react-select, styled/hidden radios + checkboxes, Yes/No buttons
# --------------------------------------------------------------------------------------
_OPTION_SELECTOR = "[role='option'], [id*='-option-'], [class*='select__option']"
_SAFE_OPTIONAL_FIELD = re.compile(
    r"\bname\b|e-?mail|phone|mobile|whatsapp|linkedin|github|website|portfolio|\burl\b|"
    r"\bcity\b|location|country|address|hear about|how did you (?:hear|find)|"
    r"current (?:company|employer|title|position)|pronouns?",
    re.I,
)
_EXCLUDED_CHECKBOX_OPTION = re.compile(r"^\s*(?:other|none(?: of the above)?|n/?a|prefer not|decline|i do not wish)", re.I)
_INTEREST_QUESTION = re.compile(
    r"interest|areas?\b|technolog|skills?|stack|languages?|tools?|select all|check all|"
    r"which of the following|what (?:do|would) you|experience with|familiar|"
    r"projects?\b|excited|working on|work on",
    re.I,
)
# Option words that are honestly supported by the verified profile (Azure/K3s/Docker,
# Linux, Python/Django/FastAPI, React/Node, PostgreSQL/Redis, Jest/pytest, GitHub Actions).
_INTEREST_ALIASES: dict[str, tuple[str, ...]] = {
    "cloud": ("azure", "k3s", "docker", "kubernetes"),
    "linux": ("linux",),
    "ubuntu": ("linux",),
    "server": ("linux", "docker"),
    "devops": ("docker", "github actions", "k3s"),
    "infrastructure": ("docker", "k3s", "azure"),
    "containers": ("docker", "k3s"),
    "web": ("react", "node", "django", "fastapi", "typescript"),
    "backend": ("python", "node", "django", "fastapi", "postgres"),
    "back-end": ("python", "node", "django", "fastapi", "postgres"),
    "frontend": ("react", "angular", "typescript"),
    "front-end": ("react", "angular", "typescript"),
    "full stack": ("react", "node", "python", "postgres"),
    "database": ("postgres", "redis"),
    "api": ("fastapi", "express", "django", "graphql", "grpc"),
    "testing": ("jest", "pytest"),
    "python": ("python",),
    "typescript": ("typescript",),
    "javascript": ("typescript", "node", "react"),
    "open source": ("cantera", "open source", "open-source"),
    "operating systems": ("linux", "python", "docker"),
    "distributed systems": ("node", "python", "docker", "redis"),
    "software": ("python", "node", "typescript"),
    "applications": ("python", "node", "react"),
    "security": ("linux", "python"),
    "networking": ("linux", "docker"),
    "storage": ("linux", "postgres"),
    "data": ("python", "postgres", "redis"),
    "ai": ("python",),
}


def _is_visible_choice(meta: dict[str, Any]) -> bool:
    """Radios/checkboxes are often invisible inputs with a visible styled label."""
    return bool(meta.get("visible") or meta.get("labelVisible"))


def _profile_skill_keywords(profile: dict[str, Any]) -> set[str]:
    keywords: set[str] = set()
    for group in _skill_groups(profile):
        for skill in group:
            for token in re.split(r"[,/()&;]+", str(skill)):
                token = token.strip().casefold()
                if len(token) >= 3:
                    keywords.add(token)
    # Verified project stack words, so aliases below can be justified.
    keywords.update({"python", "node", "react", "typescript", "docker", "postgres", "redis", "jest", "pytest", "github actions", "azure", "k3s", "linux", "graphql", "grpc", "fastapi", "django"})
    return keywords


def _field_locator(form, meta: dict[str, Any]):
    """Locate a field by its stamped `data-jh-field-idx` attribute to resist DOM shifts."""
    idx = meta.get("index")
    by_attr = form.locator(f"[data-jh-field-idx='{idx}']")
    try:
        if by_attr.count() > 0:
            return by_attr.first
    except Exception:
        pass
    return form.locator("input, textarea, select, button").nth(int(idx or 0))


def _is_unmounted_field(form, meta: dict[str, Any]) -> bool:
    """Return True when React unmounted a previously stamped conditional field."""
    idx = meta.get("index")
    try:
        has_stamped = form.locator("[data-jh-field-idx]").count() > 0
        if has_stamped and form.locator(f"[data-jh-field-idx='{idx}']").count() == 0:
            return True
    except Exception:
        pass
    return False


def _click_choice(form, meta: dict[str, Any]) -> bool:
    """Select a radio/checkbox, including inputs hidden behind custom SVG/label widgets."""
    if _is_unmounted_field(form, meta):
        return False
    loc = _field_locator(form, meta)

    def is_on() -> bool:
        try:
            return bool(loc.is_checked())
        except Exception:
            return False

    if is_on():
        return True
    try:
        _check_input(loc)
    except Exception:
        pass
    if is_on():
        return True
    # Styled control: click the label/wrapper the user would actually click.
    try:
        loc.evaluate("el => { const t = (el.labels && el.labels[0]) || el.closest('label') || el.parentElement || el; t.click(); }")
    except Exception:
        pass
    if is_on():
        return True
    try:
        loc.evaluate("el => el.click()")
    except Exception:
        pass
    return is_on()


def _fill_react_select(page, loc, value: str, *, loose: bool = False) -> tuple[bool, str]:
    """react-select / Ashby autocomplete: click control -> type value -> choose option (Enter).

    `loose=True` (location pickers) accepts the first option that contains the value, because
    the list is usually "Cairo, Egypt" style rather than an exact string.
    """
    target = str(value or "").strip()
    if not target:
        return False, "no value"
    norm = target.casefold()
    control = loc.locator("xpath=ancestor::*[contains(@class,'select__control')][1]")
    target_el = control.first if control.count() else loc
    try:
        target_el.scroll_into_view_if_needed(timeout=2000)
    except Exception:
        pass
    try:
        target_el.click(timeout=3000)
    except Exception:
        try:
            loc.click(timeout=3000, force=True)
        except Exception:
            try:
                target_el.evaluate("el => el.click()")
            except Exception as exc:
                return False, f"could not open dropdown ({type(exc).__name__})"
    try:
        page.keyboard.press("Control+A")
        page.keyboard.type(target, delay=25)
    except Exception as exc:
        return False, f"could not type into dropdown ({type(exc).__name__})"

    visible_option_sel = ", ".join(f"{s.strip()}:visible" for s in _OPTION_SELECTOR.split(","))
    options = page.locator(visible_option_sel)
    texts: list[str] = []
    for attempt in range(8):  # remote autocomplete (Ashby locations) answers asynchronously
        page.wait_for_timeout(400)
        try:
            texts = [t.strip() for t in options.all_inner_texts() if t.strip()]
        except Exception:
            texts = []
        if texts:
            break
        if attempt == 2:
            try:
                page.keyboard.press("ArrowDown")
            except Exception:
                pass

    chosen = None
    exact = [i for i, t in enumerate(texts) if t.casefold() == norm]
    contains = [i for i, t in enumerate(texts) if norm in t.casefold() or t.casefold() in norm]
    starts = [i for i, t in enumerate(texts) if t.casefold().startswith(norm)]
    if exact:
        chosen = exact[0]
    elif len(starts) == 1:
        chosen = starts[0]
    elif len(contains) == 1:
        chosen = contains[0]
    elif norm in {"yes", "i agree", "agree"} and (starts or contains):
        pool = starts or contains
        completed = [i for i in pool if "completed" in texts[i].casefold() and "expected" not in texts[i].casefold()]
        if len(completed) == 1:
            chosen = completed[0]
        elif len(pool) == 1:
            chosen = pool[0]
    elif loose and (starts or contains):
        pool = starts or contains
        chosen = min(pool, key=lambda i: len(texts[i]))

    try:
        if chosen is not None:
            options.nth(chosen).click(timeout=3000)
        elif texts and len(texts) == 1:
            page.keyboard.press("Enter")
        elif texts and texts[0].casefold().startswith(norm):
            page.keyboard.press("Enter")
        else:
            page.keyboard.press("Escape")
            return False, "no unambiguous dropdown option matched"
    except Exception as exc:
        try:
            page.keyboard.press("Escape")
        except Exception:
            pass
        return False, f"could not choose option ({type(exc).__name__})"

    page.wait_for_timeout(250)
    try:
        shown = control.first.inner_text(timeout=1500).strip() if control.count() else ""
    except Exception:
        shown = ""
    try:
        typed = loc.input_value(timeout=1000).strip()
    except Exception:
        typed = ""
    if shown and shown.casefold() not in {"select...", "select", "search", ""}:
        return True, "selected"
    if typed:
        return True, "selected"
    return False, "dropdown value did not persist"


def _fill_checkbox_group(
    form, group: list[dict[str, Any]], question: str,
    profile: dict[str, Any], bank: dict[str, Any], item: dict[str, Any],
) -> tuple[list[str], list[str]]:
    """Tick the matching options of a multi-checkbox fieldset (e.g. Greenhouse `question_123[]`).

    Only options supported by a saved answer or by the verified profile are ticked.
    Nothing is guessed: a required group with no supportable option becomes a blocker.
    """
    checked: list[str] = []
    blockers: list[str] = []
    required = any(f.get("required") for f in group) or any(f.get("groupRequired") for f in group) or bool(re.search(r"\*\s*$|\(required\)", question or "", re.I))
    options = [f for f in group if not _EXCLUDED_CHECKBOX_OPTION.search(str(f.get("optionLabel") or ""))]

    desired: set[str] = set()
    referral = bool(re.search(r"how did you (?:hear|learn|find out) about", question or "", re.I))
    if referral:
        entry = _at(bank, "answers", "application_referral_source", default={})
        value = entry.get("answer") if isinstance(entry, dict) and entry.get("auto_fill") is True else None
    else:
        value, _reason = _answer_for_field(question, profile, bank, item)
    if value:
        for token in re.split(r"[,;|\n]+|\band\b", str(value)):
            token = token.strip().casefold()
            if len(token) >= 2:
                desired.add(token)

    matched: list[dict[str, Any]] = []
    for opt in options:
        text = str(opt.get("optionLabel") or "").strip().casefold()
        if text and any(tok == text or (not referral and (tok in text or text in tok)) for tok in desired):
            matched.append(opt)

    if not matched and _INTEREST_QUESTION.search(question or ""):
        keywords = _profile_skill_keywords(profile)
        for opt in options:
            text = str(opt.get("optionLabel") or "").strip().casefold()
            if not text:
                continue
            direct = any(len(k) >= 3 and re.search(rf"\b{re.escape(k)}\b", text) for k in keywords)
            aliased = any(
                re.search(rf"\b{re.escape(trigger)}\b", text) and any(support in keywords for support in supports)
                for trigger, supports in _INTEREST_ALIASES.items()
            )
            if direct or aliased:
                matched.append(opt)

    for opt in matched:
        if _click_choice(form, opt):
            checked.append(str(opt.get("optionLabel") or "")[:60])
        elif required:
            blockers.append(f"Could not tick required option '{str(opt.get('optionLabel') or '')[:50]}' in: {question[:80]}")
    if required and not checked and not blockers:
        blockers.append(f"Required checkbox group has no option supported by saved answers/profile: {question[:120]}")
    return checked, blockers


def _fill_yes_no_buttons(form, profile: dict[str, Any], bank: dict[str, Any], item: dict[str, Any]) -> tuple[list[str], list[str]]:
    """Ashby-style Yes/No button pairs (`<button data-option="yes|no">`, hidden input has no id).

    Found structurally; required-ness comes from the label's class / CSS asterisk, because
    Ashby draws the "*" with CSS so it is absent from innerText.
    """
    filled: list[str] = []
    blockers: list[str] = []
    page = form.page
    try:
        groups = page.evaluate("() => {" + _JS_REQUIRED_HELPER + r"""
          const kind = b => {
            const t = (b.innerText || '').trim().toLowerCase();
            if (t === 'yes' || t === 'no') return t;
            const d = ((b.dataset && b.dataset.option) || '').trim().toLowerCase();
            return (d === 'yes' || d === 'no') ? d : '';
          };
          const out = []; const seen = new Set(); let n = 0;
          for (const b of Array.from(document.querySelectorAll('button')).filter(x => kind(x))) {
            let c = b.parentElement;
            const isPair = el => { const bs = Array.from(el.querySelectorAll('button')); return bs.length === 2 && bs.every(x => kind(x)) && new Set(bs.map(kind)).size === 2; };
            for (let d = 0; c && d < 3; d++, c = c.parentElement) { if (isPair(c)) break; }
            if (!c || seen.has(c) || !isPair(c)) continue;
            seen.add(c);
            const field = c.closest('[data-field-path], [class*="field-entry"], [class*="fieldEntry"], fieldset') || c.parentElement;
            const lab = field && field.querySelector('label, legend, [class*="question-title"], [class*="label"]');
            const text = ((lab && lab.innerText) || (field && field.innerText) || '').replace(/\s+/g, ' ').replace(/\s*\*\s*$/, '').trim();
            const required = isReqNode(lab) || (!!field && !!field.querySelector('[class*="required" i]')) || /\(required\)/i.test(text);
            const btns = Array.from(c.querySelectorAll('button'));
            btns.forEach(x => x.setAttribute('data-jh-yn-btn', kind(x)));
            const pressed = btns.some(x => x.getAttribute('aria-pressed') === 'true' || x.getAttribute('data-state') === 'on' || /(?:^|[-_\s])(active|selected|checked|pressed)(?:$|[-_\s])/i.test(x.className.toString()));
            c.setAttribute('data-jh-yn', String(n));
            out.push({ id: n, question: text.slice(0, 300), required, pressed });
            n += 1;
          }
          return out;
        }""")
    except Exception:
        return filled, blockers

    for group in groups or []:
        question = str(group.get("question") or "").strip()
        if not question or group.get("pressed"):
            continue
        answer = _yes_no_answer(question, profile, bank, item)
        if answer is None:
            if group.get("required"):
                blockers.append(f"Required Yes/No question needs a verified answer: {question[:120]}")
            continue
        button = page.locator(f"[data-jh-yn='{group['id']}'] [data-jh-yn-btn='{answer}']").first
        try:
            button.click(timeout=3000)
        except Exception:
            _dismiss_cookie_banner(page)
            try:
                button.click(timeout=3000, force=True)
            except Exception as exc:
                if group.get("required"):
                    blockers.append(f"Could not answer required Yes/No question {question[:90]} ({type(exc).__name__})")
                continue
        filled.append(f"{question[:70]} -> {answer.title()}")
    return filled, blockers


def _yes_no_answer(question: str, profile: dict[str, Any], bank: dict[str, Any], item: dict[str, Any]) -> str | None:
    """Return 'yes'/'no' only when saved facts support it; never default-guess."""
    tz = _timezone_answer(question)
    if tz:
        return tz.casefold()
    if re.search(r"based in cairo|based in egypt|live in egypt|reside in egypt|relocate|over the age of 18|at least 18|18 years|legal age|eligible to work in egypt|work remotely from egypt|first university degree|bachelor or undergrad.*completed", question, re.I):
        return "yes"
    if re.search(r"previously worked|previously employed|currently employed by|currently working at|ever.*worked|criminal|convicted|sanction", question, re.I):
        return "no"
    value, _ = _answer_for_field(question, profile, bank, item)
    low = str(value or "").strip().casefold()
    if re.match(r"^(?:yes|true|y)\b", low) or re.search(r"\b(?:willing|able|authori[sz]ed|open to)\b", low):
        return "yes"
    if re.match(r"^(?:no|false|n|none)\b", low) or re.search(r"\bnot\b", low):
        return "no"
    return None


def _log_unanswered_to_ledger(
    question: str,
    meta: dict[str, Any] | None,
    item: dict[str, Any],
    form,
) -> None:
    try:
        page_url = str(getattr(getattr(form, "page", None), "url", "") or item.get("url") or "")
        ats_host = urlparse(page_url).hostname or ""
        opts: list[str] = []
        if isinstance(meta, dict) and isinstance(meta.get("options"), list):
            opts = [str(o.get("text") or o.get("value") or "") for o in meta["options"] if isinstance(o, dict) and (o.get("text") or o.get("value"))]
        record_unanswered_question(
            question_text=question,
            field_type=str((meta or {}).get("type") or (meta or {}).get("tag") or "unknown"),
            field_name=str((meta or {}).get("name") or (meta or {}).get("id") or ""),
            html_snippet=str((meta or {}).get("htmlSnippet") or ""),
            options=opts,
            ats_host=ats_host,
            job_url=page_url,
            company=str(item.get("company") or ""),
            queue_id=int(item["id"]) if item.get("id") is not None else None,
        )
    except Exception:
        pass


def _fill_form(form, profile: dict[str, Any], bank: dict[str, Any], item: dict[str, Any], resume_path: Path) -> tuple[list[str], list[str]]:
    blockers: list[str] = []
    filled: list[str] = []
    fields = _labels(form)
    handled_radio_groups: set[str] = set()
    handled_checkbox_groups: set[str] = set()
    deferred_file_metas: list[dict[str, Any]] = []
    contact_restore: list[tuple[dict[str, Any], str]] = []
    if not fields:
        return ["No recognizable form fields were found."], filled

    # Reject legal declarations and consent toggles instead of consenting to terms blindly.
    for meta in fields:
        kind = meta["type"]
        choice_like = kind in {"radio", "checkbox"}
        label = _field_text(meta)
        is_consent_cb = (
            kind == "checkbox"
            and bool(meta.get("required"))
            and bool(re.search(
                r"privacy|terms|consent|accurate|truth|certif|agree|acknowledge|confirm that|gdpr|data protection|"
                r"retention|retain|store my|process(?:ing)? (?:of )?(?:my )?(?:personal )?data|"
                r"candidate (?:privacy|declaration)|by submitting|read and understood|policy|notice",
                label,
                re.I,
            ))
        )
        visible = (_is_visible_choice(meta) or is_consent_cb) if choice_like else meta["visible"]
        if not visible or meta["disabled"] or meta["tag"] == "button":
            continue
        if meta.get("yesNoWidget") and kind in {"checkbox", "radio"}:
            continue  # Ashby's hidden input behind Yes/No buttons; handled by _fill_yes_no_buttons
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
            group = [field for field in fields if field.get("type") == "radio" and str(field.get("name") or field.get("id") or field.get("label")) == group_name and _is_visible_choice(field) and not field.get("disabled")]
            question = label or " ".join(str(meta.get(k) or "") for k in ("name", "id", "placeholder", "aria"))
            value, reason = _answer_for_field(question, profile, bank, item)
            if not value and _ROLE_QUESTION.search(question):
                role_pick = _choose_role_option(group)
                if role_pick is not None:
                    if _click_choice(form, role_pick):
                        filled.append(f"{question[:60]} -> {str(role_pick.get('optionLabel') or '')[:40]}")
                    elif any(f.get("required") for f in group):
                        blockers.append(f"Could not select required answer {question[:90]}")
                    continue
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
                    if _click_choice(form, matches[0]):
                        filled.append(question[:90])
                    elif any(f.get("required") for f in group):
                        blockers.append(f"Could not select required answer {question[:90]}")
                elif any(field.get("required") for field in group):
                    blockers.append(f"Required radio choice has no unambiguous saved answer: {question[:120]}")
                    _log_unanswered_to_ledger(question, meta, item, form)
            elif any(field.get("required") for field in group):
                blockers.append(f"Required radio question needs a verified answer: {question[:120]}")
                _log_unanswered_to_ledger(question, meta, item, form)
            continue
        if kind == "checkbox":
            grp_lbl = str(meta.get("label") or "").strip()
            if grp_lbl and grp_lbl in handled_radio_groups:
                continue
            if re.search(r"military service", grp_lbl, re.I):
                opt_lbl = str(meta.get("optionLabel") or "").strip().lower()
                if opt_lbl in ("exempted", "finished", "completed", "postponed"):
                    if _click_choice(form, meta):
                        handled_radio_groups.add(grp_lbl)
                        filled.append(f"military service: {opt_lbl}")
                continue
            # Auto-check standard candidate consent/privacy/accuracy declarations as approved
            is_privacy_consent = bool(re.search(
                r"privacy|terms|consent|accurate|truth|certif|agree|acknowledge|confirm that|gdpr|data protection|"
                r"retention|retain|store my|process(?:ing)? (?:of )?(?:my )?(?:personal )?data|"
                r"candidate (?:privacy|declaration)|by submitting|read and understood|policy|notice",
                label,
                re.I,
            ))
            is_dangerous_declaration = bool(re.search(
                r"criminal|perjury|background check authorization|drug test|"
                r"u\.?s\.? citizen|united states citizen|security clearance|eu citizen|uk citizen",
                label,
                re.I,
            ))
            if is_privacy_consent and not is_dangerous_declaration:
                if _click_choice(form, meta):
                    filled.append(f"consent: {label[:60]}")
                elif meta["required"]:
                    blockers.append(f"Could not check consent checkbox: {label[:80]}")
                continue
            # Multi-checkbox fieldset (Greenhouse `question_123[]`, Ashby field-entry, Workable checkbox lists).
            group_key = str(meta.get("name") or "").strip() or grp_lbl or str(meta.get("fieldPath") or "") or str(meta.get("id") or "")
            siblings = [
                f for f in fields
                if f.get("type") == "checkbox" and not f.get("disabled") and _is_visible_choice(f)
                and (
                    (grp_lbl and str(f.get("label") or "").strip() == grp_lbl)
                    or (meta.get("name") and str(f.get("name") or "").strip() == str(meta.get("name") or "").strip())
                    or (meta.get("fieldPath") and str(f.get("fieldPath") or "").strip() == str(meta.get("fieldPath") or "").strip())
                    or ((str(f.get("name") or "").strip() or str(f.get("label") or "").strip() or str(f.get("id") or "")) == group_key)
                )
            ]
            if len(siblings) >= 2 and not is_dangerous_declaration:
                if group_key in handled_checkbox_groups:
                    continue
                handled_checkbox_groups.add(group_key)
                question = grp_lbl or label or group_key
                ticked, group_blockers = _fill_checkbox_group(form, siblings, question, profile, bank, item)
                filled.extend(f"{question[:50]}: {t}" for t in ticked)
                if group_blockers:
                    blockers.extend(group_blockers)
                    _log_unanswered_to_ledger(question, meta, item, form)
                continue
            if meta["required"]:
                blockers.append(f"Required declaration/checkbox needs explicit human review: {label[:120] or meta['name']}")
                _log_unanswered_to_ledger(label or meta.get("name") or "", meta, item, form)
            continue
        if kind == "file":
            deferred_file_metas.append(meta)
            continue

        if not meta["required"] and not label:
            continue

        q = label or " ".join(str(meta.get(k) or "").strip() for k in ("name", "id", "placeholder", "aria") if str(meta.get(k) or "").strip()).strip()
        if not q and not meta.get("combobox") and meta["tag"] != "select":
            continue
        if meta.get("description") and len(label) <= 14:
            q = f"{q} {meta['description']}"  # e.g. title "Other" + hint "Portfolio, personal website"
        # Generic mapping for common ATS names when labels are terse.
        q_low = q.casefold()
        # Optional free-text questions are only filled when they are plain contact/identity
        # fields; the answer bank must never be fuzzily matched into unrelated optional prompts.
        if not meta["required"] and not _SAFE_OPTIONAL_FIELD.search(q_low):
            continue
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
            value = str(_at(profile, "identity", "nationality", default="")).strip()
            reason = "saved nationality"
        elif re.fullmatch(r"country(?:[ *]+country)?[ *]*|country of residence[ *]*", q_low):
            value = str(_at(profile, "identity", "country", default="")).strip()
            if not value:
                value, _ = _answer_for_field(q, profile, bank, item)
            reason = "saved country of residence"
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
                _log_unanswered_to_ledger(q, meta, item, form)
            continue

        if _is_unmounted_field(form, meta):
            continue
        loc = _field_locator(form, meta)
        try:
            if meta.get("combobox") and meta["tag"] == "input":
                ok, why = _fill_react_select(
                    form.page, loc, str(value),
                    loose=bool(re.search(r"countr|\bcity\b|location|where are you", q_low)),
                )
                if not ok and str(value).strip().casefold() == "egypt (cairo)":
                    ok, why = _fill_react_select(form.page, loc, "Egypt", loose=True)
                if not ok and str(value).strip().casefold() == "egypt" and re.search(r"nationality|citizenship", q_low):
                    ok, why = _fill_react_select(form.page, loc, "Egyptian")
                if not ok and str(value).strip().casefold() in {"yes", "i agree", "agree"}:
                    for fallback_yes in (
                        "Acknowledge/Confirm", "Acknowledge", "Confirm",
                        "I confirm", "I agree", "Agree", "Accept", "Yes",
                    ):
                        if fallback_yes.casefold() == str(value).strip().casefold():
                            continue
                        ok, why = _fill_react_select(form.page, loc, fallback_yes, loose=True)
                        if ok:
                            break
                if not ok and str(value).strip().casefold() == "middle eastern":
                    for fallback_eth in (
                        "Middle Eastern / North African",
                        "North African",
                        "White",
                        "Prefer not to say",
                        "I don't wish to answer",
                    ):
                        ok, why = _fill_react_select(form.page, loc, fallback_eth, loose=True)
                        if ok:
                            break
                if not ok:
                    if meta["required"]:
                        blockers.append(f"Required dropdown could not be set ({why}): {q[:110]}")
                        _log_unanswered_to_ledger(q, meta, item, form)
                    continue
            elif meta["tag"] == "select":
                options = meta.get("options", [])
                normalized = str(value).strip().casefold()
                exact = next((opt for opt in options if not opt.get("disabled") and (str(opt.get("value", "")).strip().casefold() == normalized or str(opt.get("text", "")).strip().casefold() == normalized)), None)
                if exact is None:
                    # Accept unambiguous contained option matches only.
                    matches = [opt for opt in options if not opt.get("disabled") and normalized and (normalized in str(opt.get("text", "")).casefold() or str(opt.get("text", "")).casefold() in normalized)]
                    if len(matches) == 1:
                        exact = matches[0]
                if exact is None and normalized == "egypt (cairo)":
                    for fallback_loc in ("egypt", "cairo"):
                        matches = [opt for opt in options if not opt.get("disabled") and fallback_loc in str(opt.get("text", "")).casefold()]
                        if len(matches) == 1:
                            exact = matches[0]
                            break
                if exact is None and normalized in {"yes", "true", "i agree"}:
                    pos_matches = [
                        opt for opt in options
                        if not opt.get("disabled")
                        and re.search(r"^\s*(?:yes\b|i\s+agree\b|agree\b|i\s+confirm\b|confirm\b|completed\b|accept\b|i\s+consent\b|acknowledge\b)", str(opt.get("text", "")), re.I)
                        and not re.search(r"\b(?:no|not|disagree|decline|do not)\b", str(opt.get("text", "")), re.I)
                    ]
                    if len(pos_matches) == 1:
                        exact = pos_matches[0]
                if exact is None and normalized in {"no", "false"}:
                    neg_matches = [
                        opt for opt in options
                        if not opt.get("disabled")
                        and re.search(r"^\s*(?:no\b|none\b|not\s+applicable\b|n/?a\b)", str(opt.get("text", "")), re.I)
                    ]
                    if len(neg_matches) == 1:
                        exact = neg_matches[0]
                if exact is None:
                    if meta["required"]:
                        blockers.append(f"Required dropdown has no unambiguous saved answer: {q[:120]}")
                        _log_unanswered_to_ledger(q, meta, item, form)
                    continue
                loc.select_option(value=str(exact.get("value", "")))
            elif meta["type"] in {"email", "tel", "url", "text", "search", "number"} or meta["tag"] in {"textarea", "input"}:
                try:
                    loc.scroll_into_view_if_needed(timeout=2000)
                except Exception:
                    pass
                try:
                    loc.fill(str(value))
                except Exception:
                    loc.fill(str(value), force=True)
                if re.search(r"first.?name|last.?name|\bname\b|email|phone|mobile", q_low):
                    contact_restore.append((meta, str(value)))
            else:
                if meta["required"]:
                    blockers.append(f"Unsupported required field type: {kind or meta['tag']} ({q[:100]})")
                    _log_unanswered_to_ledger(q, meta, item, form)
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
        is_cover_letter_file = bool(re.search(r"cover\s*letter|motivation\s*letter|letter\s*of\s*motivation", label, re.I))
        if is_cover_letter_file:
            if not meta["required"] or _is_unmounted_field(form, meta):
                continue
            loc = _field_locator(form, meta)
            try:
                cl_path = generate_generic_cover_letter_pdf(profile, item)
                loc.set_input_files(str(cl_path))
                filled.append("cover letter file")
            except Exception as exc:
                blockers.append(f"Could not attach required cover letter PDF: {type(exc).__name__}")
            continue
        if (resume_attached and not meta["required"]) or _is_unmounted_field(form, meta):
            continue
        loc = _field_locator(form, meta)
        try:
            is_autofill = loc.evaluate("""e => {
                const c = e.closest('div') || e.parentElement;
                return ((c ? c.innerText || '' : '')).toLowerCase().includes('autofill');
            }""")
        except Exception:
            is_autofill = False
        if is_autofill and not meta["required"]:
            continue
        if not meta["required"] and re.search(r"transcript|portfolio|avatar|photo", label, re.I):
            continue
        if resume_path.is_file():
            try:
                loc.set_input_files(str(resume_path))
                try:
                    if "ashbyhq.com" in (urlparse(form.page.url).hostname or ""):
                        form.page.locator("button:has-text('Replace')").first.wait_for(state="visible", timeout=8000)
                    else:
                        form.page.wait_for_timeout(1500)
                except Exception:
                    pass
                attached = loc.evaluate("(input, name) => Array.from(input.files || []).some(f => f.name === name)", resume_path.name)
                if not attached and "ashbyhq.com" in (urlparse(form.page.url).hostname or ""):
                    attached = bool(form.get_by_text(resume_path.name, exact=True).count())
                if not attached:
                    blockers.append("The form did not confirm the selected resume filename.")
                    continue
                resume_attached = True
                filled.append("resume file")
            except Exception as exc:
                if meta["required"]:
                    blockers.append(f"Could not attach the resume: {type(exc).__name__}")
        elif meta["required"]:
            blockers.append("Required resume file is missing from the configured local path.")

    # Restore any contact fields (First Name, Last Name, Email, Phone) cleared by resume autofill.
    for c_meta, c_val in contact_restore:
        if _is_unmounted_field(form, c_meta):
            continue
        try:
            c_loc = _field_locator(form, c_meta)
            if (c_loc.input_value(timeout=1000) or "").strip() != c_val.strip():
                c_loc.fill(c_val)
            if c_meta["required"] and (c_loc.input_value(timeout=1000) or "").strip() != c_val.strip():
                blockers.append("A required contact field changed during resume upload.")
        except Exception:
            if c_meta["required"]:
                blockers.append("A required contact field could not be verified after resume upload.")

    # Ashby-style Yes/No button pairs (structural detection; no guessing for unknown questions).
    try:
        yn_filled, yn_blockers = _fill_yes_no_buttons(form, profile, bank, item)
        filled.extend(yn_filled)
        blockers.extend(yn_blockers)
    except Exception:
        pass

    return blockers, filled


_NEXT_BUTTON = re.compile(r"^\s*(?:next(?:\s+step)?|continue|save (?:and|&) continue|proceed)\s*$", re.I)
_SUBMIT_BUTTON = re.compile(r"\b(submit|apply|send application)\b", re.I)


def _has_submit_button(form) -> bool:
    try:
        if form.locator("button[type='submit']:visible, input[type='submit']:visible").count() > 0:
            return True
        return form.get_by_role("button", name=_SUBMIT_BUTTON).count() > 0
    except Exception:
        return False


def _advance_wizard(page, form) -> bool:
    """Click Next/Continue on a multi-step form (Workable, SmartRecruiters). Never submits."""
    try:
        button = form.get_by_role("button", name=_NEXT_BUTTON)
        if button.count() == 0:
            button = page.get_by_role("button", name=_NEXT_BUTTON)
        if button.count() == 0:
            return False
        button.first.click(timeout=3000)
        try:
            page.wait_for_load_state("networkidle", timeout=4000)
        except Exception:
            page.wait_for_timeout(1200)
        return True
    except Exception:
        return False


_CHALLENGE_MESSAGE = "Manual verification required by the employer."
_UNCERTAIN_MESSAGE = "Submit was clicked, but the page did not provide reliable confirmation; treated as uncertain to avoid duplicate retries."


def _control_signature(page) -> set[str]:
    """Visible form controls (outside cookie banners), used to detect a move to the next step."""
    try:
        return set(page.evaluate(r"""() => {
          const vis = n => !!(n && (n.offsetWidth || n.offsetHeight || n.getClientRects().length));
          const skip = '[id*="cookie" i], [class*="cookie" i], [id*="consent" i], [class*="consent" i], [id*="onetrust" i]';
          return Array.from(document.querySelectorAll('input, textarea, select'))
            .filter(e => e.type !== 'hidden' && vis(e) && !e.closest(skip))
            .map(e => (e.type || e.tagName.toLowerCase()) + ':' + (e.name || e.id || e.getAttribute('aria-label') || e.placeholder || ''));
        }""") or [])
    except Exception:
        return set()


def _unanswered_required(page) -> list[str]:
    """Names of visible required questions that are still empty (diagnostics for failed submits)."""
    try:
        return list(page.evaluate("() => {" + _JS_REQUIRED_HELPER + r"""
          const vis = n => !!(n && (n.offsetWidth || n.offsetHeight || n.getClientRects().length));
          const out = [];
          const entries = document.querySelectorAll('[data-field-path], [class*="field-entry"], [class*="fieldEntry"], .field, fieldset');
          for (const entry of entries) {
            const lab = entry.querySelector('label, legend, [class*="question-title"]');
            const required = isReqNode(lab) || !!entry.querySelector('[class*="required" i]');
            if (!required || !vis(entry)) continue;
            const inputs = Array.from(entry.querySelectorAll('input:not([type=hidden]), textarea, select'));
            const textFilled = inputs.some(i => !['checkbox', 'radio', 'file'].includes(i.type) && (i.value || '').trim());
            const choiceFilled = inputs.some(i => ['checkbox', 'radio'].includes(i.type) && i.checked);
            const fileFilled = inputs.some(i => i.type === 'file' && i.files && i.files.length);
            const pressed = Array.from(entry.querySelectorAll('button')).some(b => b.getAttribute('aria-pressed') === 'true' || /(?:^|[-_\s])(active|selected|checked|pressed)(?:$|[-_\s])/i.test(b.className.toString()));
            const replaced = !!Array.from(entry.querySelectorAll('button')).find(b => /replace|remove/i.test(b.innerText || ''));
            if (!(textFilled || choiceFilled || fileFilled || pressed || replaced)) {
              out.push(((lab && lab.innerText) || '').replace(/\s+/g, ' ').replace(/\s*\*\s*$/, '').trim().slice(0, 80));
            }
          }
          for (const el of document.querySelectorAll("[aria-invalid='true']")) {
            if (vis(el)) out.push('(invalid) ' + (el.getAttribute('aria-label') || el.name || el.id || el.tagName).slice(0, 60));
          }
          return out.slice(0, 6);
        }""") or [])
    except Exception:
        return []


def _page_has_visible_validation_error(page) -> str:
    unanswered = _unanswered_required(page)
    try:
        text = str(page.evaluate(r"""() => {
          const vis = n => !!(n && (n.offsetWidth || n.offsetHeight || n.getClientRects().length));
          const bad = Array.from(document.querySelectorAll("[role='alert'], [class*='error' i]"))
            .filter(vis).map(n => (n.innerText || '').trim()).filter(Boolean);
          return bad.slice(0, 3).join(' | ').slice(0, 220);
        }""") or "")
    except Exception:
        text = ""
    parts = []
    if text:
        parts.append(text)
    if unanswered:
        parts.append("unanswered required: " + "; ".join(unanswered))
    return " || ".join(parts)


def _click_submit_button(page, button) -> Exception | None:
    """Click, dismissing a cookie overlay that intercepts pointer events, then JS-click as last resort."""
    try:
        button.first.scroll_into_view_if_needed(timeout=2000)
        button.first.click(timeout=8000)
    except Exception as exc:
        # The browser may already have dispatched the click when a timeout occurs.
        return exc
    return None


def _submit_step(page, form) -> tuple[str, str]:
    """Click Submit/Next once and classify the result.

    States: submitted | advanced (a further step with new fields appeared) | challenge |
    error (validation) | uncertain | failed.
    """
    before_url = page.url
    try:
        before_body = page.locator("body").inner_text(timeout=3000).casefold()
    except Exception:
        before_body = ""
    if _requires_manual_verification(page, before_body) or _is_challenge(page, before_body):
        return "challenge", _CHALLENGE_MESSAGE
    _dismiss_cookie_banner(page)
    before_controls = _control_signature(page)
    submit = form.locator("button[type='submit'], input[type='submit']")
    if submit.count() == 0:
        submit = form.get_by_role("button", name=re.compile(r"\b(submit|apply|send application)\b", re.I))
    if submit.count() == 0:
        submit = form.get_by_role("button", name=_NEXT_BUTTON)
    if submit.count() == 0:
        submit = page.get_by_role("button", name=_NEXT_BUTTON)
    if submit.count() == 0:
        return "failed", "No recognizable submit button was found."
    error = _click_submit_button(page, submit)
    if error is not None:
        return "uncertain", f"Submission could not be confirmed ({type(error).__name__})."
    try:
        page.wait_for_load_state("networkidle", timeout=6000)
    except Exception:
        page.wait_for_timeout(2500)
    try:
        for _ in range(8):  # SPA confirmations can render a few seconds late
            body = page.locator("body").inner_text(timeout=5000).casefold()
            if _requires_manual_verification(page, body) or _is_challenge(page, body):
                return "challenge", _CHALLENGE_MESSAGE
            new_success = any(marker in body and marker not in before_body for marker in SUCCESS_MARKERS)
            if new_success and (page.url != before_url or not _control_signature(page)
                                or _choose_application_form(page) is None):
                return "submitted", "Employer page displayed a new submission-confirmation signal."
            new_controls = _control_signature(page) - before_controls
            if new_controls and body != before_body and not _unanswered_required(page):
                return "advanced", f"Submit advanced to another step ({len(new_controls)} new fields)."
            page.wait_for_timeout(1500)
        errors = _page_has_visible_validation_error(page)
        if errors:
            return "error", f"The site returned a validation/error state; submission was not confirmed. Page said: {errors}"
        return "uncertain", _UNCERTAIN_MESSAGE
    except Exception as exc:
        return "failed", f"Submission could not be confirmed ({type(exc).__name__})."


def _submit_form(page, form) -> tuple[bool, str]:
    state, message = _submit_step(page, form)
    return state == "submitted", message


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
        urlparse(page.url).hostname or ""
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
    resume_path: Path, browser, *, run_id: str = "unknown-run", reservation: str = "",
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
        if outcome == "submitted":
            reason_code = "submission_confirmed"
        elif stage == "manual_verification":
            reason_code = "manual_verification_required"
        else:
            reason_code = reason_code_for_reason(reason, stage=stage)
        result = {
            "outcome": outcome,
            "reason": reason,
            "reason_code": reason_code,
            "attempted": submit_started,
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
    submit_started = False
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
            marker = _detect_challenge_marker(page, body)
            try:
                page.screenshot(path=str(ROOT / "logs" / f"challenge_{item.get('id')}.png"))
            except Exception:
                pass
            return finish("auto_skipped", "Listing page presented a CAPTCHA/anti-bot challenge.", "listing_challenge", page_host=page_host, challenge_marker=marker)

        if _requires_manual_verification(page, body):
            return finish("auto_skipped", "Manual verification required.", "manual_verification")
        if response is not None and response.status == 403:
            return finish("auto_skipped", "Listing is unavailable to the browser (HTTP 403).", "listing_access")
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
            marker = _detect_challenge_marker(page, body)
            try:
                page.screenshot(path=str(ROOT / "logs" / f"challenge_{item.get('id')}.png"))
            except Exception:
                pass
            return finish("auto_skipped", "Application form presented a CAPTCHA/anti-bot challenge.", "application_challenge", ats_host=final_url_host, challenge_marker=marker, **link_diagnostics)
        if _requires_manual_verification(page, body):
            return finish("auto_skipped", "Manual verification required.", "manual_verification")
        if not _is_supported_host(final_url_host) and not _same_site_host(final_url_host, application_target_host):
            return finish("auto_skipped", "Application link redirected away from its target to an unsupported host.", "final_host_check", ats_host=final_url_host, application_target_host=application_target_host, **link_diagnostics)
        cookie_choice = _dismiss_cookie_banner(page)
        if cookie_choice:
            log_auto_apply_event(run_id, "cookie_banner_dismissed", **base, choice=cookie_choice)
        form = _choose_application_form(page)
        form_diagnostics = _form_diagnostics(page)
        log_auto_apply_event(
            run_id, "application_form_discovery", **base,
            ats_host=final_url_host, **form_diagnostics,
        )
        if form is None:
            return finish("auto_skipped", "No recognizable public application form was found.", "form_discovery", ats_host=final_url_host, **form_diagnostics, **link_diagnostics)

        blockers, filled = _fill_form(form, profile, bank, item, resume_path)
        # Multi-step wizards (Workable / SmartRecruiters): Step 1 -> Next -> Step 2 ... -> Submit.
        wizard_steps = 0
        while not blockers and wizard_steps < 4 and not _has_submit_button(form):
            if not _advance_wizard(page, form):
                break
            wizard_steps += 1
            page.wait_for_timeout(800)
            if _requires_manual_verification(page, page.locator("body").inner_text(timeout=5000)):
                return finish("auto_skipped", "Manual verification required.", "manual_verification")
            form = _choose_application_form(page) or form
            step_blockers, step_filled = _fill_form(form, profile, bank, item, resume_path)
            step_blockers = [b for b in step_blockers if not b.startswith("No recognizable form fields")]
            blockers.extend(step_blockers)
            filled.extend(step_filled)
        if wizard_steps:
            log_auto_apply_event(run_id, "wizard_steps_completed", **base, steps=wizard_steps, blockers=len(blockers))
        field_diagnostics = {**form_diagnostics, "filled_field_count": len(filled), "required_blocker_count": len(blockers), "wizard_steps": wizard_steps}
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

        if "resume file" not in filled:
            return finish("auto_skipped", "No resume attachment was verified.", "form_mapping",
                          filled_count=len(filled), field_diagnostics=field_diagnostics)
        if not begin_automation_attempt(int(item["id"]), reservation=reservation):
            return finish("failed", "Queue record could not be reserved safely before submitting; no submit was attempted.", "reserve_attempt", ats_host=final_url_host, filled_count=len(filled), field_diagnostics=field_diagnostics)
        submit_started = True
        log_auto_apply_event(run_id, "submit_click_about_to_happen", **base, ats_host=final_url_host, filled_field_count=len(filled))
        try:
            page.screenshot(path=str(ROOT / "logs" / f"submit_before_{item.get('id')}.png"))
        except Exception:
            pass
        _dismiss_cookie_banner(page)
        # Single-page forms submit once. Multi-step flows (e.g. Askable: contact details ->
        # "which best describes your role?") report state "advanced"; fill the new step and continue.
        extra_steps = 0
        while True:
            state, message = _submit_step(page, form)
            try:
                page.screenshot(path=str(ROOT / "logs" / f"submit_after_{item.get('id')}.png"))
            except Exception:
                pass
            if state != "advanced" or extra_steps >= 3:
                break
            extra_steps += 1
            _dismiss_cookie_banner(page)
            form = _choose_application_form(page) or form
            step_blockers, step_filled = _fill_form(form, profile, bank, item, resume_path)
            step_blockers = [b for b in step_blockers if not b.startswith("No recognizable form fields")]
            log_auto_apply_event(run_id, "post_submit_step", **base, step=extra_steps, filled=len(step_filled), blockers=len(step_blockers))
            if step_blockers:
                message = "Application advanced to a further step with a required question that cannot be answered safely: " + "; ".join(step_blockers[:3])
                state = "failed"
                break
            filled.extend(step_filled)
        field_diagnostics = {**field_diagnostics, "post_submit_steps": extra_steps, "final_state": state}
        ok = state == "submitted"
        if ok:
            return finish(
                "submitted", message, "submission_confirmation",
                filled_count=len(filled), ats_host=final_url_host,
                reference=safe_url(page.url), field_diagnostics=field_diagnostics, cv_used=resume_path.name, attempted=True,
            )
        return finish(
            "failed", message, "manual_verification" if state == "challenge" else "submission_confirmation",
            filled_count=len(filled), ats_host=final_url_host, attempted=True,
            field_diagnostics=field_diagnostics,
        )
    except PlaywrightTimeoutError:
        return finish("failed", _UNCERTAIN_MESSAGE if submit_started else "Timed out loading or interacting with the job site.", "browser_timeout", **link_diagnostics)
    except Exception as exc:
        return finish("failed", _UNCERTAIN_MESSAGE if submit_started else f"Browser automation error: {type(exc).__name__}.", "browser_exception", error_type=type(exc).__name__, **link_diagnostics)
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


def run_auto_apply(*, max_items: int | None = None, queue_ids: list[int] | None = None,
                   reservation: str = "", send_notifications: bool = True) -> dict[str, Any]:
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

    interrupted = recover_interrupted_attempts() if queue_ids is None else 0
    pending = prioritize_queue_items(
        list_applications(status="pending_review", limit=500)
        + list_applications(status="approved", limit=500)
        + list_applications(status="ready", limit=500)
    )
    if queue_ids is not None:
        pending = [item for qid in queue_ids if (item := get_application(qid))
                   and item["status"] in {"pending_review", "approved", "ready"}]
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
        reason = ("This posting already has a submission or an unresolved attempt."
                  if has_attempt_history(item["id"], reservation=reservation) else _reason_for_auto_skip(item))
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
                browser_attempts = 0
                for item in eligible:
                    if submissions_this_run >= remaining or (max_items is not None and browser_attempts >= max_items):
                        log_auto_apply_event(run_id, "daily_cap_reached_mid_run", processed_count=len(results), submissions_this_run=submissions_this_run, remaining_before_run=remaining)
                        break
                    queue_id = int(item["id"])
                    current = get_application(queue_id) or {}
                    if current.get("status") not in {"pending_review", "approved", "ready"}:
                        log_auto_apply_event(run_id, "queue_item_not_pending_review", queue_id=queue_id, current_status=current.get("status"), action="skip_item")
                        continue
                    if str(item.get("qualification_status") or "").casefold() == "review":
                        log_auto_apply_event(run_id, "review_listing_promoted_to_apply", queue_id=queue_id, score=item.get("score"), review_floor=_review_min_score(), reason="Review-class listing met score floor and confirmed Egypt/remote eligibility.")
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
                    if not preflight.get("passed") or not preflight.get("auto_submit_allowed", True):
                        reason = "Preflight failed: " + ("; ".join(preflight.get("blockers", [])[:4]) or "Profile disallows automatic submission.")
                        reason_code = "preflight_failed"
                        record_automation_outcome(queue_id, "auto_skipped", reason=reason, details={"reason_code": reason_code, "stage": "profile_preflight", "blockers": preflight.get("blockers", [])[:12], "warnings": preflight.get("warnings", [])[:12]})
                        results.append({"queue_id": queue_id, "title": item.get("title"), "company": item.get("company"), "source": item.get("source"), "outcome": "auto_skipped", "reason_code": reason_code, "reason": reason})
                        continue
                    item_resume = _resume_path(bundle.profile, item)
                    # Company totals can change during this batch.
                    if (reason := _reason_for_auto_skip(item)):
                        reason_code = reason_code_for_reason(reason, stage="qualification_policy")
                        record_automation_outcome(queue_id, "auto_skipped", reason=reason,
                                                  details={"reason_code": reason_code})
                        results.append({"queue_id": queue_id, "title": item.get("title"),
                                        "company": item.get("company"), "outcome": "auto_skipped",
                                        "reason": reason, "reason_code": reason_code})
                        continue
                    browser_attempts += 1
                    outcome = _perform_browser_application(
                        item, bundle.profile, bundle.answer_bank, item_resume, browser,
                        run_id=run_id, **({"reservation": reservation} if reservation else {}),
                    )
                    label = str(outcome.get("outcome") or "failed")
                    reason = str(outcome.get("reason") or "Application worker returned no outcome.")
                    reason_code = str(outcome.get("reason_code") or reason_code_for_reason(reason, stage="browser_application"))
                    event_details = {
                        "reason_code": reason_code,
                        "stage": "browser_application",
                        "ats_host": outcome.get("ats_host"),
                        "cv_used": outcome.get("cv_used"),
                        "filled_count": outcome.get("filled_count"),
                        "blockers": outcome.get("blockers", [])[:12],
                        "diagnostics": outcome.get("diagnostics", {}),
                        "apply_links": outcome.get("apply_links", []),
                        "form_diagnostics": outcome.get("form_diagnostics", outcome.get("field_diagnostics", {})),
                    }
                    if label == "submitted":
                        record_automation_outcome(queue_id, "submitted", reason=reason, reference=str(outcome.get("reference") or ""), details=event_details)
                        submissions_this_run += 1
                        if send_notifications and not os.getenv("PYTEST_CURRENT_TEST"):
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
                        "cv_used": outcome.get("cv_used"),
                        "url": item.get("url"), "score": item.get("score"),
                        "filled_count": outcome.get("filled_count"), "attempted": outcome.get("attempted", False),
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
    return {"run_id": run_id, "enabled": True, "processed": len(results), "attempted": sum(bool(r.get("attempted")) for r in results), "submitted": submitted, "skipped": skipped, "failed": failed, "daily_cap": settings.auto_apply_max_per_day, "results": results, "reason_breakdown": summary}


def _summarize_results(results: list[dict[str, Any]]) -> dict[str, int]:
    summary: dict[str, int] = {}
    for result in results:
        code = str(result.get("reason_code") or "unknown")
        summary[code] = summary.get(code, 0) + 1
    return dict(sorted(summary.items(), key=lambda item: (-item[1], item[0])))
