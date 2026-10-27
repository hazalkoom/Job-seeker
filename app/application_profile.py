"""Private candidate-profile loading and safe, auditable form-answer resolution."""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env", override=False)

PROFILE_PATH = ROOT / "candidate_profile.json"
ANSWERS_PATH = ROOT / "application_answers.json"


class ProfileLoadError(ValueError):
    """Raised when a profile or answer-bank file cannot be loaded safely."""


@dataclass(frozen=True, slots=True)
class AnswerResolution:
    status: str  # auto_fill, draft, review, unknown
    category: str
    answer: str | None
    reason: str
    source: str = ""

    @property
    def can_auto_fill(self) -> bool:
        return self.status == "auto_fill" and bool(self.answer)


@dataclass(frozen=True, slots=True)
class ProfileBundle:
    profile: dict[str, Any]
    answer_bank: dict[str, Any]
    issues: tuple[str, ...]

    @property
    def valid(self) -> bool:
        return not self.issues


def _load_object(path: str | Path, label: str) -> dict[str, Any]:
    path = Path(path)
    try:
        with path.open("r", encoding="utf-8") as stream:
            data = json.load(stream)
    except FileNotFoundError as exc:
        raise ProfileLoadError(f"{label} file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ProfileLoadError(
            f"{label} invalid JSON at line {exc.lineno}, column {exc.colno}"
        ) from exc
    except OSError as exc:
        raise ProfileLoadError(f"Could not read {label}: {exc}") from exc

    if not isinstance(data, dict):
        raise ProfileLoadError(f"{label} must be a JSON object")

    return data


def load_candidate_profile(path: str | Path = PROFILE_PATH) -> dict[str, Any]:
    return _load_object(path, "Candidate profile")


def load_answer_bank(path: str | Path = ANSWERS_PATH) -> dict[str, Any]:
    return _load_object(path, "Application answer bank")


def validate_profile(
    profile: dict[str, Any],
    answer_bank: dict[str, Any] | None = None,
) -> list[str]:
    """Validate profile structure without returning or printing private values."""
    issues: list[str] = []
    identity = profile.get("identity")
    links = profile.get("links")

    if not isinstance(identity, dict):
        issues.append("Missing identity object")
        identity = {}

    if not str(identity.get("full_name", "")).strip():
        issues.append("identity.full_name is required")

    email = str(identity.get("email", "")).strip()
    if email and not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
        issues.append("identity.email is not a valid email format")

    if not isinstance(links, dict):
        issues.append("Missing links object")
        links = {}

    for key in ("linkedin", "github", "portfolio", "cv_url"):
        value = str(links.get(key, "") or "").strip()
        if value:
            parsed = urlparse(value)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                issues.append(f"links.{key} must be an http(s) URL")

    education = profile.get("education", [])
    if not isinstance(education, list):
        issues.append("education must be a list")
    else:
        for index, item in enumerate(education):
            if not isinstance(item, dict) or not item.get("qualification"):
                issues.append(
                    f"education entry {index + 1} needs a qualification"
                )

    if answer_bank is not None:
        answers = answer_bank.get("answers")
        if not isinstance(answers, dict):
            issues.append("Answer bank is missing its answers object")
        else:
            issues.extend(
                f"Answer-bank entry {key!r} must be an object"
                for key, value in answers.items()
                if not isinstance(value, dict)
            )

    return issues


def load_profile_bundle(
    profile_path: str | Path = PROFILE_PATH,
    answer_bank_path: str | Path = ANSWERS_PATH,
) -> ProfileBundle:
    profile = load_candidate_profile(profile_path)
    bank = load_answer_bank(answer_bank_path)
    return ProfileBundle(profile, bank, tuple(validate_profile(profile, bank)))


def _norm(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().casefold())


def _at(
    data: dict[str, Any],
    *keys: str,
    default: Any = "",
) -> Any:
    value: Any = data
    for key in keys:
        if not isinstance(value, dict):
            return default
        value = value.get(key)
    return default if value is None else value


def _entry(bank: dict[str, Any], key: str) -> dict[str, Any]:
    entries = bank.get("answers", {})
    value = entries.get(key, {}) if isinstance(entries, dict) else {}
    return value if isinstance(value, dict) else {}


def _saved(
    bank: dict[str, Any],
    key: str,
    fallback: str | None = None,
    category: str = "",
) -> AnswerResolution:
    entry = _entry(bank, key)
    answer = entry.get("answer", fallback)
    answer = str(answer).strip() if answer is not None else ""

    if not answer:
        return AnswerResolution(
            "unknown", category or key, None,
            "No verified answer is saved.", key,
        )

    kind = str(entry.get("type", "factual")).casefold()

    if kind in {"draft", "template"}:
        status = "draft"
    elif entry.get("requires_review") or entry.get("auto_fill") is False:
        status = "review"
    else:
        status = "auto_fill"

    return AnswerResolution(
        status, category or key, answer,
        "Uses the saved profile or answer-bank entry.", key,
    )


def _education(
    question: str,
    profile: dict[str, Any],
    bank: dict[str, Any],
) -> AnswerResolution:
    education = profile.get("education", [])
    if not isinstance(education, list):
        education = []

    if "computer science" in question and (
        "bachelor" in question or "degree" in question
    ):
        return _saved(
            bank, "bachelors_in_computer_science", "No.", "education"
        )

    bachelor = next(
        (
            item for item in education
            if isinstance(item, dict)
            and "bachelor" in str(item.get("qualification", "")).casefold()
        ),
        None,
    )
    diploma = next(
        (
            item for item in education
            if isinstance(item, dict)
            and "diploma" in str(item.get("qualification", "")).casefold()
        ),
        None,
    )

    if "bachelor" in question and any(
        word in question
        for word in ("do you have", "hold", "completed", "earned", "obtain")
    ):
        if bachelor and bachelor.get("status") == "completed":
            return AnswerResolution(
                "auto_fill", "education", "Yes",
                "Profile marks the bachelor's qualification completed.",
                "profile.education",
            )

        expected = bachelor.get("expected_end_date", "") if bachelor else ""
        text = (
            f"Not completed yet; currently in progress, expected {expected}."
            if expected
            else "Not completed yet; currently in progress."
        )
        return AnswerResolution(
            "review", "education", text,
            "Degree is recorded as in progress; check the form's answer options.",
            "profile.education",
        )

    if any(
        word in question
        for word in (
            "highest qualification",
            "highest level of education",
            "highest education",
        )
    ):
        pieces = []

        if diploma:
            pieces.append(
                f"{diploma['qualification']} "
                f"({diploma.get('institution', 'institution not supplied')})"
            )

        if bachelor:
            if bachelor.get("status") == "completed":
                pieces.append(f"{bachelor['qualification']} (completed)")
            else:
                expected = bachelor.get("expected_end_date", "")
                suffix = f", expected {expected}" if expected else ""
                pieces.append(
                    f"{bachelor['qualification']} (in progress{suffix})"
                )

        if pieces:
            return AnswerResolution(
                "auto_fill", "education", "; ".join(pieces),
                "Derived from recorded education entries.",
                "profile.education",
            )

    return AnswerResolution(
        "review", "education", None,
        "Education question needs exact interpretation; do not infer equivalence.",
        "education",
    )


def resolve_answer(
    question: str,
    profile: dict[str, Any],
    answer_bank: dict[str, Any],
    *,
    target_country: str | None = None,
    company: str = "",
    job_title: str = "",
    relevant_skills: list[str] | tuple[str, ...] | None = None,
) -> AnswerResolution:
    """Resolve a form question without inventing facts or submitting anything."""
    q = _norm(question)

    if not q:
        return AnswerResolution(
            "unknown", "unknown", None, "Question text is empty."
        )

    # Sensitive, legal, and high-consequence questions must be reviewed.
    sensitive_pattern = (
        r"criminal|arrested|conviction|background check|disabilit|race|ethnic|"
        r"gender identity|sexual orientation|veteran|government id|national id|"
        r"passport number|legal declaration|under penalty of perjury|"
        r"military service|military status|military exemption|military conscription"
    )
    if re.search(sensitive_pattern, q):
        key = (
            "military_service_in_egypt"
            if "military" in q
            else "criminal_or_background_declaration"
        )
        saved = _entry(answer_bank, key).get("answer")
        return AnswerResolution(
            "review", "sensitive", str(saved) if saved else None,
            "Sensitive/legal declaration requires your explicit review.", key,
        )

    # Salary depends on net/gross, currency, period and employment type.
    if re.search(
        r"salary|compensation|pay expectation|desired pay|remuneration|rate expectation",
        q,
    ):
        amount = _at(profile, "compensation", "target_monthly_amount", default=None)
        currency = _at(profile, "compensation", "currency", default="EGP")
        basis = _at(profile, "compensation", "net_or_gross", default="unconfirmed")
        answer = (
            f"{amount} {currency} per month ({basis})"
            if amount is not None else None
        )
        return AnswerResolution(
            "review", "salary", answer,
            "Confirm gross/net, currency, period and employment type before answering.",
            "profile.compensation",
        )

    if any(
        term in q
        for term in (
            "visa sponsorship", "require sponsorship", "sponsorship now",
            "future sponsorship", "immigration sponsorship",
        )
    ):
        return AnswerResolution(
            "review", "sponsorship", None,
            "Sponsorship depends on the job country and employment arrangement.",
            "work_authorization",
        )

    # Egyptian authorization cannot be reused for another country.
    if any(
        term in q
        for term in (
            "authorized to work", "authorised to work",
            "legally eligible to work", "right to work",
        )
    ):
        country_is_egypt = (
            "egypt" in q or "egypt" in _norm(target_country or "")
        )
        if not country_is_egypt:
            return AnswerResolution(
                "review", "work_authorization", None,
                "Do not infer authorization for another or unspecified country "
                "from Egyptian authorization.",
                "work_authorization",
            )

        value = _at(
            profile, "work_authorization",
            "authorized_to_work_in_egypt", default=None,
        )
        if isinstance(value, bool):
            return AnswerResolution(
                "auto_fill", "work_authorization",
                "Yes" if value else "No",
                "Uses the recorded Egypt work-authorization fact.",
                "profile.work_authorization",
            )

        return AnswerResolution(
            "unknown", "work_authorization", None,
            "Egypt work authorization is not recorded.",
        )

    contacts = (
        (r"\b(email|e-mail)\b", "identity", "email", "contact"),
        (r"\b(phone|telephone|mobile|contact number)\b", "identity", "phone", "contact"),
    )
    for pattern, section, key, category in contacts:
        if re.search(pattern, q):
            value = str(_at(profile, section, key, default="")) or None
            return _saved(answer_bank, key, value, category)

    for needle, key in (
        ("linkedin", "linkedin"),
        ("github", "github"),
        ("portfolio", "portfolio"),
        ("personal website", "portfolio"),
    ):
        if needle in q:
            value = str(_at(profile, "links", key, default="")) or None
            return _saved(answer_bank, key, value, "link")

    if re.search(r"\b(resume|résumé|curriculum vitae|cv link|cv url)\b", q):
        url = str(
            _at(profile, "links", "cv_url", default="")
            or os.getenv("CANDIDATE_CV_URL", "")
        ).strip()

        if not url:
            return AnswerResolution(
                "review", "cv", None,
                "No shareable CV URL is configured; a local file path is not a URL.",
                "links.cv_url",
            )

        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return AnswerResolution(
                "review", "cv", None,
                "Configured CV link is not a valid http(s) URL.",
                "links.cv_url",
            )

        return AnswerResolution(
            "auto_fill", "cv", url,
            "Uses the configured shareable CV URL.", "links.cv_url",
        )

    if re.search(
        r"\b(current location|where are you based|city|country of residence|current country)\b",
        q,
    ):
        location = ", ".join(
            str(value).strip()
            for value in (
                _at(profile, "identity", "city", default=""),
                _at(profile, "identity", "country", default=""),
            )
            if str(value).strip()
        )
        if location:
            return AnswerResolution(
                "auto_fill", "location", location,
                "Uses the recorded current location.", "profile.identity",
            )
        return AnswerResolution(
            "unknown", "location", None, "Current location is missing."
        )

    if re.search(
        r"\b(full name|legal name|your name|first name|last name|given name|family name)\b",
        q,
    ):
        field = (
            "first_name" if "first name" in q or "given name" in q
            else "last_name" if "last name" in q or "family name" in q
            else "full_name"
        )
        value = str(_at(profile, "identity", field, default="")).strip()
        if value:
            return AnswerResolution(
                "auto_fill", "identity", value,
                "Uses the saved candidate identity.", f"profile.identity.{field}",
            )
        return AnswerResolution(
            "unknown", "identity", None, f"identity.{field} is missing."
        )

    if re.search(
        r"notice period|how soon can you start|when can you start|available to start",
        q,
    ):
        if _at(profile, "availability", "available_immediately", default=False) is True:
            return AnswerResolution(
                "auto_fill", "availability", "Immediately; I have no notice period.",
                "Uses the saved availability.", "profile.availability",
            )
        return AnswerResolution(
            "review", "availability", None, "Availability has not been verified."
        )

    if "relocat" in q or "move to" in q:
        saved = _entry(answer_bank, "relocation").get("answer")
        return AnswerResolution(
            "review", "relocation", str(saved) if saved else None,
            "Relocation depends on destination and timing.", "relocation",
        )

    if "unpaid" in q and "internship" in q:
        saved = _entry(answer_bank, "unpaid_internship").get("answer")
        return AnswerResolution(
            "review", "employment_conditions", str(saved) if saved else None,
            "Candidate reviews unpaid internships case by case.",
            "unpaid_internship",
        )

    if any(
        term in q
        for term in (
            "highest qualification", "highest level of education",
            "highest education", "bachelor", "degree", "education level",
        )
    ):
        return _education(q, profile, answer_bank)

    if re.search(r"years? of .*experience|how many years|years of experience with", q):
        return AnswerResolution(
            "review", "experience", None,
            "Years of experience must match the exact technology and employment type asked.",
            "profile.experience",
        )

    if any(
        term in q
        for term in (
            "english", "arabic", "language proficiency", "speak english", "speak arabic",
        )
    ):
        for language in ("English", "Arabic"):
            value = _at(profile, "languages", language, default="")
            if language.casefold() in q and value:
                display = (
                    str(value)
                    .replace("professional_working_proficiency", "Professional working proficiency")
                    .replace("native", "Native")
                )
                return AnswerResolution(
                    "auto_fill", "language", display,
                    "Uses recorded language proficiency.",
                    f"profile.languages.{language}",
                )
        return AnswerResolution(
            "unknown", "language", None,
            "Requested language proficiency is not recorded.",
        )

    templates = (
        ("tell_me_about_yourself", ("tell me about yourself", "introduce yourself", "about you")),
        ("most_relevant_project", ("relevant project", "project you are proud", "describe a project", "technical project")),
        ("technical_problem", ("technical problem", "difficult technical", "challenging bug", "performance issue")),
        ("ai_experience", ("ai experience", "experience with ai", "ai coding tools", "artificial intelligence tools")),
        ("why_this_role", ("why this role", "why are you interested in this role", "why are you interested in this position", "why do you want this job", "why apply")),
        ("why_this_company", ("why this company", "why do you want to work at", "why join")),
    )
    for key, phrases in templates:
        if any(phrase in q for phrase in phrases):
            text = str(_entry(answer_bank, key).get("answer") or "").strip()
            skills = ", ".join(relevant_skills or []) or "the relevant technologies"
            text = (
                text.replace("{relevant_skills}", skills)
                .replace("{job_title}", job_title or "this role")
                .replace("{company}", company or "the company")
            )
            if text:
                return AnswerResolution(
                    "draft", key, text,
                    "Tailored draft; review it against the job before use.", key,
                )
            return AnswerResolution(
                "unknown", key, None, "No approved draft exists for this question.", key
            )

    return AnswerResolution(
        "unknown", "unknown", None,
        "No verified answer mapping exists; do not guess.",
    )
