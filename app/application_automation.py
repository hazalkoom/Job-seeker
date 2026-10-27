"""Bounded autonomous application runner for supported public ATS forms.

This module uses ordinary user-facing forms. It does not defeat CAPTCHAs,
anti-bot checks, logins, or access controls, and it never guesses answers to
required factual/legal questions. Unsupported or ambiguous forms are skipped
and recorded so the periodic runner can continue to other jobs.
"""
from __future__ import annotations

import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse
from zoneinfo import ZoneInfo

from app.application_profile import ProfileLoadError, load_profile_bundle, resolve_answer
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

ROOT = Path(__file__).resolve().parent.parent
SUPPORTED_ATS_HOSTS = (
    "greenhouse.io", "lever.co", "ashbyhq.com", "workable.com",
    "smartrecruiters.com", "jobvite.com", "icims.com", "bamboohr.com",
    "recruitee.com", "personio.com", "teamtailor.com", "myworkdayjobs.com",
)
CAPTCHA_MARKERS = (
    "captcha", "verify you are human", "checking your browser",
    "unusual traffic", "security challenge", "are you a robot",
)
SUCCESS_MARKERS = (
    "thank you for applying", "application submitted", "application received",
    "we received your application", "successfully applied", "thanks for applying",
    "your application has been sent", "thank you for your interest",
)


def _record(queue_id: int, event_type: str, details: dict[str, Any] | None = None) -> None:
    from app.application_queue import _event, _now

    init_db()
    with _connect() as conn:
        _event(conn, int(queue_id), event_type, details or {})


def _resume_path(profile: dict[str, Any]) -> Path:
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


def _is_supported_host(host: str) -> bool:
    host = (host or "").casefold().rstrip(".")
    return any(host == domain or host.endswith("." + domain) for domain in SUPPORTED_ATS_HOSTS)


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
    if experience.maximum_preferred_years is not None and experience.maximum_preferred_years > limit:
        return f"Preferred experience exceeds the configured {limit:g}-year limit; not safe for automatic submission."

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
    forms = page.locator("form")
    if _is_supported_host(host) and forms.count() > 0:
        # Ensure there is at least one application-like control; login forms are not application forms.
        if page.locator("input[type='email'], input[name*='email' i], input[type='file']").count() > 0:
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
        text = f"{link.get('text', '')} {link.get('title', '')} {href}".casefold()
        if not re.search(r"\bapply\b|application form|submit application|apply now", text):
            continue
        if not _is_supported_host(urlparse(href).hostname or ""):
            continue
        score = 3 if re.search(r"/apply(?:/|$|\?)", urlparse(href).path, re.I) else 0
        score += 2 if re.search(r"apply now|submit application|application form", text) else 0
        candidates.append((score, href))
    if candidates:
        return sorted(candidates, reverse=True)[0][1]
    return None


def _is_challenge(page, body: str) -> bool:
    low = body.casefold()
    if any(marker in low for marker in CAPTCHA_MARKERS):
        return True
    try:
        if page.locator("iframe[src*='recaptcha'], iframe[src*='hcaptcha'], iframe[src*='challenges.cloudflare.com'], textarea[name='g-recaptcha-response']").count() > 0:
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
      const fieldset = el.closest('fieldset');
      let groupQuestion = '';
      if (fieldset) {
        const legend = fieldset.querySelector('legend');
        if (legend) groupQuestion = legend.innerText || '';
      }
      if (groupQuestion && (el.type === 'radio' || el.type === 'checkbox')) label = groupQuestion;
      return {
        index,
        tag: el.tagName.toLowerCase(),
        type: (el.type || '').toLowerCase(),
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
    if re.search(r"\b(cover letter|why (?:are you interested|do you want)|why this (?:role|company)|tell us about yourself|motivation|additional information)\b", low):
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
    return None, result.reason


def _fill_form(form, profile: dict[str, Any], bank: dict[str, Any], item: dict[str, Any], resume_path: Path) -> tuple[list[str], list[str]]:
    blockers: list[str] = []
    filled: list[str] = []
    fields = _labels(form)
    handled_radio_groups: set[str] = set()
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
                matches = [field for field in group if target in str(field.get("optionLabel") or "").casefold() or target == str(field.get("value") or "").casefold()]
                if not matches and target in {"yes", "no"}:
                    matches = [field for field in group if re.search(rf"\b{target}\b", str(field.get("optionLabel") or ""), re.I) or str(field.get("value") or "").casefold() == target]
                if len(matches) == 1:
                    try:
                        form.locator("input, textarea, select, button").nth(matches[0]["index"]).check()
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
            if re.search(r"privacy|terms|consent|accurate|truth|certif|authorize|authorise|agree|declaration", label, re.I):
                if meta["required"]:
                    blockers.append(f"Required legal/consent checkbox needs site-specific consent: {label[:120] or meta['name']}")
                continue
            if meta["required"]:
                blockers.append(f"Required checkbox choice is not confidently mapped: {label[:120] or meta['name']}")
            continue
        if kind == "file":
            if resume_path.is_file():
                try:
                    form.locator("input, textarea, select, button").nth(meta["index"]).set_input_files(str(resume_path))
                    filled.append("resume file")
                except Exception as exc:
                    if meta["required"]:
                        blockers.append(f"Could not attach the resume: {type(exc).__name__}")
            elif meta["required"]:
                blockers.append("Required resume file is missing from the configured local path.")
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
        elif re.search(r"^name$|full.?name|candidate.?name", q_low):
            identity = profile.get("identity", {}) if isinstance(profile.get("identity"), dict) else {}
            value = str(identity.get("full_name") or "").strip()
            reason = "saved candidate identity"
        elif re.search(r"current company|current employer", q_low):
            value, reason = None, "Current-employer question is not mapped from profile"
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
        page.wait_for_timeout(1800)
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
    return best if best_score >= 5 else None


def _perform_browser_application(item: dict[str, Any], profile: dict[str, Any], bank: dict[str, Any], resume_path: Path, browser) -> dict[str, Any]:
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

    context = browser.new_context(accept_downloads=False)
    page = context.new_page()
    page.set_default_timeout(int(settings.auto_apply_timeout_seconds * 1000))
    try:
        page.goto(str(item["url"]), wait_until="domcontentloaded", timeout=int(settings.auto_apply_timeout_seconds * 1000))
        page.wait_for_timeout(700)
        body = page.locator("body").inner_text(timeout=5000)
        if _is_challenge(page, body):
            return {"outcome": "auto_skipped", "reason": "Listing page presented a CAPTCHA/anti-bot challenge."}

        application_url = _find_apply_url(page)
        if not application_url:
            return {"outcome": "auto_skipped", "reason": "No supported public ATS application form was found from this listing."}
        if not _is_supported_host(urlparse(application_url).hostname or ""):
            return {"outcome": "auto_skipped", "reason": "Application form host is not in the supported ATS list."}
        if application_url != page.url:
            page.goto(application_url, wait_until="domcontentloaded", timeout=int(settings.auto_apply_timeout_seconds * 1000))
            page.wait_for_timeout(500)
        body = page.locator("body").inner_text(timeout=5000)
        if _is_challenge(page, body):
            return {"outcome": "auto_skipped", "reason": "Application form presented a CAPTCHA/anti-bot challenge."}
        final_url_host = urlparse(page.url).hostname or ""
        if not _is_supported_host(final_url_host):
            return {"outcome": "auto_skipped", "reason": "Redirected to an unsupported application host."}
        form = _choose_application_form(page)
        if form is None:
            return {"outcome": "auto_skipped", "reason": "No recognizable public application form was found."}

        blockers, filled = _fill_form(form, profile, bank, item, resume_path)
        if blockers:
            return {
                "outcome": "auto_skipped",
                "reason": "Required fields could not be answered safely: " + "; ".join(blockers[:5]),
                "filled_count": len(filled),
                "ats_host": final_url_host,
            }
        if not filled:
            return {"outcome": "auto_skipped", "reason": "No application fields were confidently filled."}

        if not begin_automation_attempt(int(item["id"])):
            return {"outcome": "failed", "reason": "Queue record could not be reserved safely before submitting; no submit was attempted."}
        ok, message = _submit_form(page, form)
        if ok:
            return {
                "outcome": "submitted",
                "reason": message,
                "filled_count": len(filled),
                "ats_host": final_url_host,
                "reference": page.url,
            }
        return {
            "outcome": "failed",
            "reason": message,
            "filled_count": len(filled),
            "ats_host": final_url_host,
        }
    except PlaywrightTimeoutError:
        return {"outcome": "failed", "reason": "Timed out loading or interacting with the job site."}
    except Exception as exc:
        return {"outcome": "failed", "reason": f"Browser automation error: {type(exc).__name__}."}
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
    """Process pending queue items autonomously under a strict daily cap."""
    init_db()
    if not settings.auto_apply_enabled:
        return {"enabled": False, "processed": 0, "submitted": 0, "skipped": 0, "failed": 0, "results": []}
    if settings.auto_apply_max_per_day <= 0:
        return {"enabled": True, "processed": 0, "submitted": 0, "skipped": 0, "failed": 0, "results": [], "reason": "Daily submission cap is zero."}
    try:
        bundle = load_profile_bundle()
    except ProfileLoadError as exc:
        return {"enabled": True, "processed": 0, "submitted": 0, "skipped": 0, "failed": 0, "results": [], "error": str(exc)}
    if bundle.issues:
        return {"enabled": True, "processed": 0, "submitted": 0, "skipped": 0, "failed": 0, "results": [], "error": "Candidate profile/answer bank validation failed: " + "; ".join(bundle.issues)}

    remaining = settings.auto_apply_max_per_day - _submitted_today()
    if max_items is not None:
        remaining = min(remaining, max(0, int(max_items)))
    if remaining <= 0:
        return {"enabled": True, "processed": 0, "submitted": 0, "skipped": 0, "failed": 0, "results": [], "reason": "Daily application cap has been reached."}

    interrupted = recover_interrupted_attempts()
    pending = (
        list_applications(status="pending_review", limit=500)
        + list_applications(status="approved", limit=500)
        + list_applications(status="ready", limit=500)
    )
    if not pending:
        return {"enabled": True, "processed": 0, "submitted": 0, "skipped": 0, "failed": interrupted, "results": [], "reason": "No pending queue items."}

    # Policy filtering and skips happen before opening a browser.
    eligible: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []
    for item in pending:
        reason = _reason_for_auto_skip(item)
        if reason:
            record_automation_outcome(int(item["id"]), "auto_skipped", reason=reason, details={"score": item.get("score"), "source": item.get("source")})
            results.append({"queue_id": item["id"], "title": item.get("title"), "company": item.get("company"), "outcome": "auto_skipped", "reason": reason})
        else:
            eligible.append(item)

    if not eligible:
        return {"enabled": True, "processed": len(results), "submitted": 0, "skipped": len(results), "failed": 0, "results": results, "reason": "All pending listings were automatically skipped by the qualification policy."}

    resume_path = _resume_path(bundle.profile)
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        reason = "Playwright is not installed; install requirements and Chromium before autonomous submission."
        for item in eligible:
            record_automation_outcome(int(item["id"]), "auto_skipped", reason=reason)
            results.append({"queue_id": item["id"], "title": item.get("title"), "company": item.get("company"), "outcome": "auto_skipped", "reason": reason})
        return {"enabled": True, "processed": len(results), "submitted": 0, "skipped": len(results), "failed": 0, "results": results, "error": reason}

    # Launch once per cycle. Unsupported forms never block processing of other jobs.
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=settings.auto_apply_headless)
            try:
                submissions_this_run = 0
                for item in eligible:
                    if submissions_this_run >= remaining:
                        break
                    queue_id = int(item["id"])
                    current = get_application(queue_id) or {}
                    if current.get("status") != "pending_review":
                        continue
                    # Mark as approved automatically, with an explicit audit reason.
                    if current.get("status") == "pending_review":
                        automatic_approve_application(queue_id, "Automatically approved by configured eligibility policy; no manual review required.")
                    preflight = run_preflight(queue_id)
                    if not preflight.get("passed"):
                        reason = "Preflight failed: " + "; ".join(preflight.get("blockers", [])[:4])
                        record_automation_outcome(queue_id, "auto_skipped", reason=reason)
                        results.append({"queue_id": queue_id, "title": item.get("title"), "company": item.get("company"), "outcome": "auto_skipped", "reason": reason})
                        continue
                    outcome = _perform_browser_application(item, bundle.profile, bundle.answer_bank, resume_path, browser)
                    label = str(outcome.get("outcome") or "failed")
                    if label == "submitted":
                        record_automation_outcome(queue_id, "submitted", reason=str(outcome.get("reason") or "Submission confirmed"), reference=str(outcome.get("reference") or ""), details={"ats_host": outcome.get("ats_host"), "filled_count": outcome.get("filled_count")})
                        submissions_this_run += 1
                    elif label == "auto_skipped":
                        record_automation_outcome(queue_id, "auto_skipped", reason=str(outcome.get("reason") or "Skipped by application policy"), details={"ats_host": outcome.get("ats_host"), "filled_count": outcome.get("filled_count")})
                    else:
                        record_automation_outcome(queue_id, "failed", reason=str(outcome.get("reason") or "Unconfirmed submission"), details={"ats_host": outcome.get("ats_host"), "filled_count": outcome.get("filled_count")})
                    results.append({"queue_id": queue_id, "title": item.get("title"), "company": item.get("company"), "outcome": label, "reason": str(outcome.get("reason") or ""), "ats_host": outcome.get("ats_host")})
                    if settings.auto_apply_delay_seconds:
                        time.sleep(settings.auto_apply_delay_seconds)
            finally:
                browser.close()
    except Exception as exc:
        reason = f"Browser could not start or the browser session failed: {type(exc).__name__}."
        for item in eligible:
            if any(result.get("queue_id") == item["id"] for result in results):
                continue
            current = get_application(int(item["id"])) or {}
            if current.get("status") == "applying":
                # We cannot prove whether the remote site received the submission.
                record_automation_outcome(int(item["id"]), "failed", reason=reason + " Submission state is uncertain; do not retry automatically.")
                label = "failed"
            else:
                # No submit attempt was reserved; leave eligible record for the next timer run.
                label = "failed"
            results.append({"queue_id": item["id"], "title": item.get("title"), "company": item.get("company"), "outcome": label, "reason": reason})

    submitted = sum(result.get("outcome") == "submitted" for result in results)
    skipped = sum(result.get("outcome") == "auto_skipped" for result in results)
    failed = sum(result.get("outcome") == "failed" for result in results)
    return {"enabled": True, "processed": len(results), "submitted": submitted, "skipped": skipped, "failed": failed, "daily_cap": settings.auto_apply_max_per_day, "results": results}
