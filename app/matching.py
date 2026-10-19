from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Literal

from app.config import settings
from app.models import Job
from app.qualification import assess_experience

Status = Literal["match", "review", "reject"]

# Core technologies relevant to this job seeker's backend/full-stack background.
SKILLS: dict[str, list[str]] = {
    "Node.js / Express": [r"\bnode(?:\.js|js)\b", r"\bexpress(?:\.js)?\b"],
    "Django": [r"\bdjango\b"],
    "FastAPI": [r"\bfastapi\b"],
    "Python": [r"\bpython\b"],
    "Angular": [r"\bangular\b"],
    "Java": [r"\bjava\b"],
    "TypeScript / JavaScript": [
        r"\btypescript\b",
        r"\bjavascript\b",
        r"\bnodejs\b",
    ],
}

# AI application engineering is relevant when the role is still software development.
AI_APPLICATION_SKILLS: dict[str, list[str]] = {
    "AI / LLM applications": [
        r"\bllms?\b",
        r"\blarge language models?\b",
        r"\bgenerative ai\b",
        r"\bgenai\b",
        r"\bai agents?\b",
        r"\bagentic(?: ai)?\b",
        r"\brag\b",
        r"\bretrieval[- ]augmented generation\b",
        r"\blangchain\b",
        r"\bllamaindex\b",
        r"\bopenai api\b",
        r"\banthropic api\b",
        r"\bmodel context protocol\b",
        r"\bmcp servers?\b",
    ],
}

# AI coding tools are bonus signals, not required skills.
AI_CODING_TOOLS: dict[str, list[str]] = {
    "Claude Code": [r"\bclaude\s*code\b"],
    "OpenCode": [r"\bopencode\b"],
    "Antigravity": [r"\bantigravity(?:\s+cli)?\b"],
    "OpenAI Codex": [r"\b(?:openai\s+)?codex\b"],
    "GitHub Copilot": [r"\bgithub\s+copilot\b", r"\bcopilot\b"],
    "Cursor": [r"\bcursor\b"],
    "Windsurf": [r"\bwindsurf\b"],
    "Gemini CLI": [r"\bgemini\s+cli\b"],
    "AI-assisted / vibe coding": [
        r"\bai[- ]assisted (?:software )?(?:coding|development)\b",
        r"\bvibe[- ]?coding\b",
        r"\bai coding agents?\b",
    ],
}

IRRELEVANT_TITLE = [
    r"\bproduct\s+engineer\b",
    r"\bproduct\s+manager\b",
    r"\bproduct\s+owner\b",
    r"\bdata\s+analyst\b",
    r"\bbusiness\s+analyst\b",
    r"\bdata\s+scientist\b",
    r"\bapplied\s+scientist\b",
    r"\bresearch\s+scientist\b",
    r"\baccount\s+executive\b",
    r"\bsales\b",
    r"\brecruit(?:er|ing|ment)\b",
    r"\btalent\s+acquisition\b",
    r"\bcustomer\s+(?:support|success)\b",
    r"\baccounting\b",
    r"\bcompensation\b",
    r"\bqa\b",
    r"\bquality\s+assurance\b",
    r"\bdevops\s+engineer\b",
    r"\bsecurity\s+engineer\b",
    r"\bnetwork(?:ing)?\s+engineer\b",
    r"\bembedded\b",
    r"\bmobile\s+(?:developer|engineer)\b",
    r"\breact\s*native\b",
]

SENIOR_TITLE = [
    r"\bsr\.?\b",
    r"\bsenior\b",
    r"\bstaff\b",
    r"\bprincipal\b",
    r"\blead\b",
    r"\bteam\s+lead\b",
    r"\btech(?:nical)?\s+lead\b",
    r"\bhead\s+of\b",
    r"\bmanager\b",
    r"\bdirector\b",
    r"\barchitect\b",
    r"\bmid[- ]level\b",
    r"\bintermediate\b",
    r"\bengineer\s*(?:ii|iii|iv|2|3|4)\b",
    r"\bdeveloper\s*(?:ii|iii|iv|2|3|4)\b",
    r"\bfounding\s+engineer\b",
]

AI_TARGET_ROLE = [
    r"\b(?:ai|llm|generative ai|genai|agentic ai|ai automation|ai agent|llm application)\s+(?:application\s+)?(?:software\s+)?(?:engineer|developer)\b",
    r"\b(?:ai|llm)\s+application\s+(?:engineer|developer)\b",
    r"\b(?:workflow|automation)\s+(?:software\s+)?(?:engineer|developer)\b",
    r"\bvibe[- ]?coding\s+(?:engineer|developer)\b",
    r"\bvibe[- ]?coder\b",
    r"\bagentic\s+(?:software\s+)?(?:engineer|developer)\b",
    r"\bai[- ]assisted\s+(?:software\s+)?(?:engineer|developer)\b",
]

TARGET_ROLE = [
    r"\bbackend\b",
    r"\bback[- ]end\b",
    r"\bfull[- ]?stack\b",
    r"\bsoftware\s+(?:engineer|developer)\b",
    r"\b(?:python|django|fastapi|node(?:\.js|js)|express|angular|java|typescript|javascript)\s+(?:engineer|developer)\b",
    r"\b(?:python|django|fastapi|node(?:\.js|js)|express|angular|java|typescript|javascript)\s+(?:backend|back[- ]end|full[- ]?stack)\b",
    r"\bfrontend\b",
    r"\bfront[- ]end\b",
    *AI_TARGET_ROLE,
]

EXCLUDED_TITLE = [
    r"\bphp\b",
    r"\bgolang\b",
    r"\bgo\s+(?:developer|engineer|backend)\b",
]

ENTRY = [
    r"\bintern(ship)?\b",
    r"\bjunior\b",
    r"\bgraduate\b",
    r"\bentry[- ]level\b",
    r"\bfresher\b",
    r"\bnew grad(?:uate)?\b",
    r"\bno experience\b",
    r"\bwithout experience\b",
    r"\b0\s*[-–to]+\s*1\s*years?\b",
    r"\b1\s*[-–to]+\s*year\b",
    r"\b1\+?\s*years?\b",
    r"\bup to one year\b",
    r"\bearly career\b",
    r"\btrainee\b",
]

# Giza and Smart Village are relevant local locations in addition to Cairo/Mansoura.
LOCAL_CITIES = ["cairo", "mansoura", "giza", "smart village"]

REMOTE_WORDS = [
    r"\bremote\b",
    r"\bwork from home\b",
    r"\bdistributed\b",
    r"\btelecommute\b",
]
HYBRID_WORDS = [r"\bhybrid\b"]
ONSITE_WORDS = [
    r"\bon[- ]?site\b",
    r"\bin[- ]office\b",
    r"\boffice based\b",
    r"\bin person\b",
]

# Description prose must discuss applicant eligibility, not global customers.
WORLDWIDE_ELIGIBILITY = [
    r"\bremote\s*(?:[-–,:]\s*|\s+)(?:worldwide|anywhere|globally)\b",
    r"\bworldwide remote\b",
    r"\bremote\s+(?:position|role|job)\b.{0,60}\b(?:available|open|eligible|accepting)\b.{0,40}\b(?:worldwide|anywhere|all countries|any country)\b",
    r"\bwork(?:ing)? remotely from anywhere(?: in the world)?\b",
    r"\bwork from anywhere(?: in the world)?\b",
    r"\b(?:hire|hiring|recruiting)\s+(?:remote\s+)?(?:employees|applicants|candidates|workers)?\s*worldwide\b",
    r"\b(?:applicants|candidates|employees|workers)\b.{0,60}\b(?:may be based|can be based|can work|may work|accepted|eligible)\b.{0,40}\b(?:anywhere|worldwide|in any country)\b",
    r"\bopen to applicants worldwide\b",
    r"\b(?:all countries|any country)\b.{0,50}\b(?:remote|work|hire|applicants|candidates|employees)\b",
]

WORLDWIDE_LOCATION_LABELS = [
    r"^\s*(?:remote\s*)?(?:worldwide|anywhere|global(?:ly)?)(?:\s*\([^)]*\))?\s*$",
    r"\bremote\s*(?:[-–,:]\s*|\s+)(?:worldwide|anywhere|globally)\b",
    r"\bworldwide remote\b",
    r"\bwork from anywhere(?: in the world)?\b",
]

EGYPT_ELIGIBILITY = [
    r"\begyptian applicants\b",
    r"\bapplicants? (?:based in|located in|from) egypt\b",
    r"\bcandidates? (?:based in|located in|from) egypt\b",
    r"\bopen to (?:applicants?|candidates?) from egypt\b",
    r"\b(?:remote|work(?:ing)? remotely) (?:from|in) egypt\b",
    r"\bwork from egypt\b",
    r"\begypt[- ]based (?:remote|candidates|applicants|employees)\b",
    r"\b(?:hiring|hire|recruiting) (?:in|from) egypt\b",
    r"\bavailable to (?:applicants?|candidates?|employees) based in egypt\b",
]

REGIONAL_ELIGIBILITY = [
    r"\bemea\b",
    r"\bafrica\b",
    r"\bmiddle east\b",
]

RESTRICTED_COUNTRY_TERMS = [
    r"\b(united states|u\.?s\.?a?\.?|canada|united kingdom|uk|ireland|germany|france|spain|italy|netherlands|poland|india|australia|new zealand|singapore|philippines|brazil|mexico)\b",
]

# Reject clear mandatory US work authorization, residency, citizenship, or
# certain explicit no-sponsorship restrictions. A mere US mention is not enough.
US_WORK_RESTRICTIONS = [
    (
        r"\b(?:must|required|requires|requiring|need(?:s)?)\b.{0,80}"
        r"\b(?:be\s+)?(?:legally\s+)?(?:authorized|authorised|eligible|permitted)\s+to work\b"
        r".{0,50}\b(?:the\s+)?(?:united states(?: of america)?|u\.?s\.?a?\.?|usa)\b"
    ),
    (
        r"\b(?:u\.?s\.?a?\.?|usa|united states(?: of america)?)\s+"
        r"(?:work authorization|work permit|working rights)\b"
        r".{0,50}\b(?:required|mandatory|must have|essential)\b"
    ),
    (
        r"\b(?:must|required|requires|requiring|need(?:s)?)\b.{0,80}"
        r"\b(?:work authorization|work permit|working rights|permission to work)\b"
        r".{0,50}\b(?:in|for)\s+(?:the\s+)?"
        r"(?:united states(?: of america)?|u\.?s\.?a?\.?|usa)\b"
    ),
    (
        r"\b(?:must|required|requires|requiring|only applicants?|only candidates?)\b"
        r".{0,80}\b(?:be\s+)?(?:located|based|reside|live)\s+in\s+"
        r"(?:the\s+)?(?:united states(?: of america)?|u\.?s\.?a?\.?|usa)\b"
    ),
    (
        r"\b(?:must|required|requires|requiring|only applicants?|only candidates?)\b"
        r".{0,50}\b(?:be\s+)?in\s+(?:the\s+)?"
        r"(?:united states(?: of america)?|u\.?s\.?a?\.?|usa)\b"
    ),
    (
        r"\b(?:must|required|requires|only)\b.{0,60}"
        r"\b(?:u\.?s\.?a?\.?|usa|united states)\s+"
        r"(?:citizen|citizens|citizenship|permanent resident|green card holder)\b"
    ),
    (
        r"\b(?:u\.?s\.?a?\.?|usa|united states)\s+"
        r"(?:citizens|permanent residents|green card holders)\s+only\b"
    ),
    (
        r"\b(?:united states|u\.?s\.?a?\.?|usa)\b.{0,100}"
        r"\b(?:visa sponsorship|work visa sponsorship)\b.{0,60}"
        r"\b(?:not available|not provided|will not sponsor|cannot sponsor|does not sponsor)\b"
    ),
    (
        r"\b(?:visa sponsorship|work visa sponsorship)\b.{0,60}"
        r"\b(?:not available|not provided|will not sponsor|cannot sponsor|does not sponsor)\b"
        r".{0,100}\b(?:united states|u\.?s\.?a?\.?|usa)\b"
    ),
]


def _has(patterns: list[str], text: str) -> bool:
    return any(re.search(pattern, text, re.I | re.S) for pattern in patterns)


def _explicitly_restricted_from_egypt(eligibility: str) -> bool:
    """Candidate-country fields are restrictions, unlike a generic office location."""
    value = (eligibility or "").strip().lower()

    if (
        not value
        or _has(WORLDWIDE_ELIGIBILITY, value)
        or _has(WORLDWIDE_LOCATION_LABELS, value)
        or _has(EGYPT_ELIGIBILITY, value)
    ):
        return False

    if _has(REGIONAL_ELIGIBILITY, value):
        return False  # Verify which countries are included in regional eligibility.

    if not _has(RESTRICTED_COUNTRY_TERMS, value):
        return False

    # Some APIs list permitted candidate countries. If Egypt is absent, treat
    # that field as a restriction; don't infer restrictions from office location.
    return not re.search(r"\begypt\b", value, re.I)


def _strip_html(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"(?s)<[^>]+>", " ", value or "")).strip()


def _posting_age(posted_at: str) -> tuple[bool, str]:
    if not posted_at:
        return False, "Posting date missing; cannot verify seven-day freshness"

    try:
        raw = str(posted_at).strip()

        if raw.isdigit():
            number = int(raw)
            dt = datetime.fromtimestamp(
                number / 1000 if number > 10_000_000_000 else number,
                tz=timezone.utc,
            )
        else:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)

        age = datetime.now(timezone.utc) - dt.astimezone(timezone.utc)

        if age < timedelta(days=-1):
            return False, "Posting date unexpectedly in the future"

        if age > timedelta(days=settings.max_posting_age_days):
            return False, (
                f"Older than {settings.max_posting_age_days} days ({age.days} days)"
            )

        return True, (
            f"Date is within {settings.max_posting_age_days} days "
            f"({max(0, age.days)} days ago)"
        )

    except (ValueError, TypeError, OSError, OverflowError):
        return False, "Posting date could not be parsed"


def _spring_boot_required(text: str) -> bool:
    """Reject clear mandatory Spring Boot experience requirements."""
    boot = r"spring\s*boot"

    required_patterns = [
        rf"\b(?:must|required|requires|requiring|mandatory|essential)\b.{{0,100}}\b{boot}\b",
        rf"\b{boot}\b.{{0,100}}\b(?:required|mandatory|essential|must have)\b",
        rf"\b(?:experience|proficiency|expertise)\b.{{0,70}}\bwith\s+{boot}\b.{{0,40}}\b(?:required|must|essential)\b",
        rf"\bminimum\b.{{0,50}}\bexperience\b.{{0,60}}\b{boot}\b",
    ]

    if not _has(required_patterns, text):
        return False

    sentences = re.split(r"(?<=[.!?;\n])\s+", text)

    for sentence in sentences:
        if re.search(boot, sentence, re.I) and _has(
            [
                r"\bnot required\b",
                r"\bnot mandatory\b",
                r"\bpreferred\b",
                r"\bnice to have\b",
                r"\bbonus\b",
                r"\boptional\b",
                r"\bwilling to learn\b",
            ],
            sentence,
        ):
            continue

        if _has(required_patterns, sentence):
            return True

    return False


def _us_work_restriction_found(text: str) -> bool:
    """Reject explicit US employment restrictions without rejecting mere US mentions."""
    sentences = re.split(r"(?<=[.!?;\n])\s+", text)

    for sentence in sentences:
        if not _has(US_WORK_RESTRICTIONS, sentence):
            continue

        if _has(
            [
                r"\bnot required\b",
                r"\bnot mandatory\b",
                r"\bnot necessary\b",
                r"\bpreferred\b",
                r"\bpreferably\b",
                r"\bnice to have\b",
                r"\boptional\b",
            ],
            sentence,
        ):
            continue

        return True

    return False


def classify(job: Job) -> tuple[Status, int, list[str], list[str]]:
    """Return status (match/review/reject), score, positive reasons, and concerns."""
    title = (job.title or "").strip()
    title_lower = title.lower()
    location = (job.location or "").strip()
    description = _strip_html(str(job.description or ""))

    body = (
        f"{title} {description} {job.eligibility or ''} "
        f"{job.employment_type or ''}"
    ).lower()

    concerns: list[str] = []
    reasons: list[str] = []

    if not str(job.url or "").startswith(("https://", "http://")):
        return "reject", 0, [], ["Missing valid application URL"]

    if _has(EXCLUDED_TITLE, title_lower):
        return "reject", 0, [], ["PHP/Go appears to be the primary stack"]

    if _has(SENIOR_TITLE, title_lower):
        return "reject", 0, [], ["Senior/lead/manager/architect title"]

    if _has(IRRELEVANT_TITLE, title_lower):
        return "reject", 0, [], ["Title is outside the target developer roles"]

    ai_role = _has(AI_TARGET_ROLE, title_lower)

    if not _has(TARGET_ROLE, title_lower):
        return "reject", 0, [], [
            "Title is not a target backend/full-stack/software/AI-application developer role"
        ]

    matched_skills = [
        name for name, patterns in SKILLS.items() if _has(patterns, body)
    ]
    matched_ai_skills = [
        name
        for name, patterns in AI_APPLICATION_SKILLS.items()
        if _has(patterns, body)
    ]
    matched_skills.extend(matched_ai_skills)

    if not matched_skills and ai_role:
        # AI software roles may focus on APIs/agents rather than conventional stacks.
        # AI tool mentions alone are a fallback only for a clearly AI-oriented title.
        ai_tool_patterns = [
            pattern
            for patterns in AI_CODING_TOOLS.values()
            for pattern in patterns
        ]
        if _has(ai_tool_patterns, body):
            matched_skills.append("AI-assisted software development")

    if not matched_skills:
        return "reject", 0, [], [
            "No relevant technology or AI-application skill detected"
        ]

    reasons.append("Relevant skills: " + ", ".join(matched_skills))

    matched_ai_tools = [
        name
        for name, patterns in AI_CODING_TOOLS.items()
        if _has(patterns, body)
    ]

    if matched_ai_tools:
        reasons.append(
            "AI-assisted development tools: " + ", ".join(matched_ai_tools)
        )

    if _spring_boot_required(body):
        return "reject", 0, reasons, [
            "Existing Spring Boot experience appears mandatory"
        ]

    if _us_work_restriction_found(body):
        return "reject", 0, reasons, [
            "Job requires US work authorization, US residency, or US citizenship"
        ]

    experience = assess_experience(description)
    experience_limit = float(getattr(settings, "max_required_experience_years", 2.0))
    if (
        experience.maximum_required_years is not None
        and experience.maximum_required_years > experience_limit
    ):
        evidence = experience.required_evidence[:2]
        evidence_text = " | ".join(evidence)
        return "reject", 0, reasons, [
            f"Explicit mandatory experience requirement exceeds target ({experience.maximum_required_years:g} years; maximum configured {experience_limit:g})",
            *( [f"Experience evidence: {evidence_text}"] if evidence_text else [] ),
        ]

    if (
        experience.maximum_preferred_years is not None
        and experience.maximum_preferred_years > experience_limit
    ):
        evidence_text = " | ".join(experience.preferred_evidence[:2])
        concerns.append(
            f"Above-target experience is listed as preferred, not mandatory ({experience.maximum_preferred_years:g} years); review whether the employer is flexible"
        )
        if evidence_text:
            concerns.append(f"Preferred-experience evidence: {evidence_text}")

    if experience.maximum_required_years is not None:
        ev = " | ".join(experience.required_evidence[:2])
        reasons.append(
            f"Experience requirement within target (up to {experience.maximum_required_years:g} year(s))"
            + (f": {ev}" if ev else "")
        )
    elif not experience.mentions:
        reasons.append("No explicit multi-year experience requirement detected")

    description_quality = str(getattr(job, "description_quality", "full") or "unknown").lower()
    if description_quality != "full" and getattr(settings, "require_full_description_for_match", True):
        if description_quality == "metadata":
            label = "Only metadata/tags are available"
        elif description_quality == "summary":
            label = "Only a source summary/snippet is available"
        else:
            label = "Description completeness is unknown"
        concerns.append(
            f"{label}; hidden mandatory requirements cannot be ruled out. Verify the full employer description"
        )

    title_entry = _has(ENTRY, title_lower)
    body_entry = _has(ENTRY, body)

    if title_entry:
        reasons.append("Entry-level wording in title")
    elif body_entry:
        reasons.append("Entry-level wording in description")
    else:
        concerns.append("Experience level is unclear; verify the full listing")

    loc = location.lower()
    local_city = any(
        re.search(rf"\b{re.escape(city)}\b", loc)
        for city in LOCAL_CITIES
    )

    remote = (
        bool(job.remote)
        or _has(REMOTE_WORDS, loc)
        or job.workplace_type == "remote"
    )
    hybrid = _has(HYBRID_WORDS, loc) or job.workplace_type == "hybrid"
    onsite = _has(ONSITE_WORDS, loc) or job.workplace_type == "onsite"

    if local_city:
        reasons.append("Cairo/Giza/Mansoura/Smart Village location")

        if hybrid:
            reasons.append("Hybrid work mode")
        elif onsite:
            reasons.append("On-site work mode")
        elif remote:
            reasons.append("Remote work mode")
        # Unspecified work mode is acceptable in a target city.

    elif not remote:
        return "reject", 0, reasons, [
            "On-site/hybrid location is not Cairo, Mansoura, Giza, or Smart Village"
        ]

    else:
        location_and_restrictions = f"{loc} {job.eligibility or ''}".lower()
        eligibility_text = f"{location_and_restrictions} {description}".lower()

        egypt_explicit = (
            _has(EGYPT_ELIGIBILITY, location_and_restrictions)
            or _has(EGYPT_ELIGIBILITY, description)
        )

        # A structured location label may be concise. Description prose must
        # explicitly discuss applicant eligibility or hiring countries.
        worldwide_explicit = (
            _has(WORLDWIDE_LOCATION_LABELS, location_and_restrictions)
            or _has(WORLDWIDE_ELIGIBILITY, description)
        )
        egypt_explicit = (
            egypt_explicit
            or _has(EGYPT_ELIGIBILITY, location_and_restrictions)
        )

        if worldwide_explicit or egypt_explicit:
            reasons.append(
                "International remote eligibility mentions worldwide/Egypt"
            )

        elif _explicitly_restricted_from_egypt(job.eligibility):
            return "reject", 0, reasons, [
                "Source's candidate-country restrictions do not include Egypt"
            ]

        elif _has(REGIONAL_ELIGIBILITY, eligibility_text):
            concerns.append(
                "Regional eligibility (EMEA/Africa/Middle East) may include Egypt; "
                "verify the hiring-country list"
            )

        else:
            concerns.append(
                "Remote role does not confirm that applicants in Egypt are eligible"
            )

    fresh, freshness_reason = _posting_age(job.posted_at)

    if not fresh:
        return "reject", 0, reasons, concerns + [freshness_reason]

    reasons.append(freshness_reason)

    if getattr(job, "date_kind", "posted") != "posted":
        concerns.append(
            "Only last-updated date is available; original posting date is unverified"
        )

    score = 40 + (25 if title_entry else 15 if body_entry else 0)
    score += 15 if local_city else 10
    score += min(15, 5 * len(matched_skills))
    score += 5  # Recent posting

    if matched_ai_tools:
        score += 5  # AI-tool experience is useful, but not essential.

    score = min(score, 100)

    hard_uncertainty = any(
        (
            "eligibility" in concern.lower()
            or "eligible" in concern.lower()
        )
        or "experience level is unclear" in concern.lower()
        or "regional eligibility" in concern.lower()
        or "original posting date is unverified" in concern.lower()
        or "hidden mandatory requirements cannot be ruled out" in concern.lower()
        or "above-target experience is listed as preferred" in concern.lower()
        for concern in concerns
    )

    if hard_uncertainty:
        return "review", score, reasons, concerns

    # Only a clearly junior title can become a confirmed MATCH. If junior wording
    # appears only in the description, leave it in REVIEW to avoid noisy alerts.
    if not title_entry:
        return "review", score, reasons, concerns

    if score < settings.min_match_score:
        return "review", score, reasons, concerns + [
            f"Score below configured threshold ({settings.min_match_score})"
        ]

    return "match", score, reasons, concerns


def evaluate(job: Job) -> tuple[bool, int, list[str], list[str]]:
    """Backward-compatible wrapper: only confirmed matches pass."""
    status, score, reasons, concerns = classify(job)
    return status == "match", score, reasons, concerns