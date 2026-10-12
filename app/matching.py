
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Literal

from app.config import settings
from app.models import Job

Status = Literal["match", "review", "reject"]

# Keep the job hunt focused on the user's target stack and actual developer roles.
# Generic mentions of a technology elsewhere in a company's description are not enough.
SKILLS: dict[str, list[str]] = {
    "Node.js / Express": [r"\bnode(?:\.js|js)\b", r"\bexpress(?:\.js)?\b"],
    "Django": [r"\bdjango\b"],
    "FastAPI": [r"\bfastapi\b"],
    "Python": [r"\bpython\b"],
    "Angular": [r"\bangular\b"],
    "Java": [r"\bjava\b"],
}

# These are not the requested junior backend/full-stack/frontend developer roles.
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

# Seniority markers include abbreviations and variants missed by exact-word matching.
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

# The title itself must be a target software-development role.
TARGET_ROLE = [
    r"\bbackend\b",
    r"\bback[- ]end\b",
    r"\bfull[- ]?stack\b",
    r"\bsoftware\s+(?:engineer|developer)\b",
    r"\b(?:python|django|fastapi|node(?:\.js|js)|express|angular|java)\s+(?:engineer|developer)\b",
    r"\b(?:python|django|fastapi|node(?:\.js|js)|express|angular|java)\s+(?:backend|back[- ]end|full[- ]?stack)\b",
    r"\bfrontend\b",
    r"\bfront[- ]end\b",
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

# Reject explicit requirements for 2+ years; don't treat every number in a job post as experience.
HIGH_EXPERIENCE = [
    r"\b(?:minimum|min\.?|at least|requires?|requiring)\s+(?:of\s+)?(?:2|3|4|5|6|7|8|9|10|two|three|four|five|six|seven|eight|nine|ten)\+?\s+years?\b",
    r"\b(?:2|3|4|5|6|7|8|9|10)\+?\s+years?\s+(?:of\s+)?(?:relevant |professional |hands-on )?experience\b",
    r"\b(?:0|1)\s*[-–to]+\s*(?:2|3|4|5|6|7|8|9|10)\s+years?\b",
    r"\b(?:2|3|4|5|6|7|8|9|10)\s*[-–]\s*(?:3|4|5|6|7|8|9|10)\s+years?\b",
    r"\b(?:two|three|four|five|six|seven|eight|nine|ten) years? (?:of )?experience\b",
    r"\bexperience of (?:2|3|4|5|6|7|8|9|10)\+? years?\b",
]

LOCAL_CITIES = ["cairo", "mansoura"]
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

WORLDWIDE_ELIGIBILITY = [
    r"\bworldwide\b",
    r"\bremote worldwide\b",
    r"\bwork from anywhere\b",
    r"\banywhere in the world\b",
    r"\banywhere\b",
    r"\ball countries\b",
    r"\bglobally remote\b",
    r"\bglobal remote\b",
    r"\bany location worldwide\b",
]

EGYPT_ELIGIBILITY = [
    r"\begyptian applicants\b",
    r"\bcandidates based in egypt\b",
    r"\bopen to applicants from egypt\b",
    r"\bremote.{0,60}\begypt\b",
    r"\begypt.{0,60}\bremote\b",
    r"\bwork from egypt\b",
]

REGIONAL_ELIGIBILITY = [
    r"\bemea\b",
    r"\bafrica\b",
    r"\bmiddle east\b",
]

# Reject clear mandatory US work authorization, residency, or citizenship restrictions.
# A preference for US authorization alone should not cause automatic rejection.
US_WORK_RESTRICTIONS = [
    # Must be legally authorized to work in the United States.
    (
        r"\b(?:must|required|requires|requiring|need(?:s)?)\b.{0,80}"
        r"\b(?:be\s+)?(?:legally\s+)?(?:authorized|authorised|eligible|permitted)\s+to work\b"
        r".{0,50}\b(?:the\s+)?(?:united states(?: of america)?|u\.?s\.?a?\.?|usa)\b"
    ),

    # US work authorization explicitly stated as required.
    (
        r"\b(?:u\.?s\.?a?\.?|usa|united states(?: of america)?)\s+"
        r"(?:work authorization|work permit|working rights)\b"
        r".{0,50}\b(?:required|mandatory|must have|essential)\b"
    ),

    # Must have authorization or permission to work in the US.
    (
        r"\b(?:must|required|requires|requiring|need(?:s)?)\b.{0,80}"
        r"\b(?:work authorization|work permit|working rights|permission to work)\b"
        r".{0,50}\b(?:in|for)\s+(?:the\s+)?"
        r"(?:united states(?: of america)?|u\.?s\.?a?\.?|usa)\b"
    ),

    # Mandatory US residency or physical location.
    (
        r"\b(?:must|required|requires|requiring|only applicants?|only candidates?)\b"
        r".{0,80}\b(?:be\s+)?(?:located|based|reside|live)\s+in\s+"
        r"(?:the\s+)?(?:united states(?: of america)?|u\.?s\.?a?\.?|usa)\b"
    ),

    # Must be in the US.
    (
        r"\b(?:must|required|requires|requiring|only applicants?|only candidates?)\b"
        r".{0,50}\b(?:be\s+)?in\s+(?:the\s+)?"
        r"(?:united states(?: of america)?|u\.?s\.?a?\.?|usa)\b"
    ),

    # Mandatory US citizenship or permanent residency.
    (
        r"\b(?:must|required|requires|only)\b.{0,60}"
        r"\b(?:u\.?s\.?a?\.?|usa|united states)\s+"
        r"(?:citizen|citizens|citizenship|permanent resident|green card holder)\b"
    ),

    # US citizens or permanent residents only.
    (
        r"\b(?:u\.?s\.?a?\.?|usa|united states)\s+"
        r"(?:citizens|permanent residents|green card holders)\s+only\b"
    ),
]

RESTRICTED_COUNTRY_TERMS = [
    r"\b(united states|u\.?s\.?a?\.?|canada|united kingdom|uk|ireland|germany|france|spain|italy|netherlands|poland|india|australia|new zealand|singapore|philippines|brazil|mexico)\b",
]


def _has(patterns: list[str], text: str) -> bool:
    return any(re.search(pattern, text, re.I | re.S) for pattern in patterns)


def _explicitly_restricted_from_egypt(eligibility: str) -> bool:
    """Candidate-country fields are restrictions, unlike a generic office location."""
    value = (eligibility or "").strip().lower()

    if not value or _has(WORLDWIDE_ELIGIBILITY, value) or _has(EGYPT_ELIGIBILITY, value):
        return False

    if _has(REGIONAL_ELIGIBILITY, value):
        return False  # Regional labels need a human to verify whether Egypt is included.

    if not _has(RESTRICTED_COUNTRY_TERMS, value):
        return False

    # Remotive/Himalayas candidate-location fields list accepted countries;
    # if Egypt is absent, reject.
    return True


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
            # Handle common UTC ISO strings and date-only values.
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))

            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)

        age = datetime.now(timezone.utc) - dt.astimezone(timezone.utc)

        if age < timedelta(days=-1):
            return False, "Posting date unexpectedly in the future"

        if age > timedelta(days=settings.max_posting_age_days):
            return False, f"Older than {settings.max_posting_age_days} days ({age.days} days)"

        return True, (
            f"Date is within {settings.max_posting_age_days} days "
            f"({max(0, age.days)} days ago)"
        )

    except (ValueError, TypeError, OSError, OverflowError):
        return False, "Posting date could not be parsed"


def _spring_boot_required(text: str) -> bool:
    """Conservative check: reject clear mandatory Spring Boot experience requirements."""
    boot = r"spring\s*boot"

    required_patterns = [
        rf"\b(?:must|required|requires|requiring|mandatory|essential)\b.{{0,100}}\b{boot}\b",
        rf"\b{boot}\b.{{0,100}}\b(?:required|mandatory|essential|must have)\b",
        rf"\b(?:experience|proficiency|expertise)\b.{{0,70}}\bwith\s+{boot}\b.{{0,40}}\b(?:required|must|essential)\b",
        rf"\bminimum\b.{{0,50}}\bexperience\b.{{0,60}}\b{boot}\b",
    ]

    if not _has(required_patterns, text):
        return False

    # Explicit preference/negation within the nearby sentence should not count as mandatory.
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

        # Avoid rejecting a listing when the sentence explicitly says the condition
        # is not required or only describes it as a preference.
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

    if not _has(TARGET_ROLE, title_lower):
        return "reject", 0, [], [
            "Title is not a target backend/full-stack/software/frontend developer role"
        ]

    matched_skills = [
        name for name, patterns in SKILLS.items() if _has(patterns, body)
    ]

    if not matched_skills:
        return "reject", 0, [], ["No relevant technology detected"]

    reasons.append("Relevant skills: " + ", ".join(matched_skills))

    if _spring_boot_required(body):
        return "reject", 0, reasons, [
            "Existing Spring Boot experience appears mandatory"
        ]

    # This check is independent of the Spring Boot check.
    if _us_work_restriction_found(body):
        return "reject", 0, reasons, [
            "Job requires US work authorization, US residency, or US citizenship"
        ]

    if _has(HIGH_EXPERIENCE, body):
        return "reject", 0, reasons, [
            "Explicit experience requirement above one year"
        ]

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
        reasons.append("Cairo/Mansoura location")

        if hybrid:
            reasons.append("Hybrid work mode")
        elif onsite:
            reasons.append("On-site work mode")
        elif remote:
            reasons.append("Remote work mode")
        # If a listing is in an allowed city, unspecified work mode is acceptable.

    elif not remote:
        # Hybrid/onsite roles are acceptable only in Cairo or Mansoura.
        return "reject", 0, reasons, [
            "On-site/hybrid location is not Cairo or Mansoura"
        ]

    else:
        location_and_restrictions = (
            f"{loc} {job.eligibility or ''}"
        ).lower()
        eligibility_text = (
            f"{location_and_restrictions} {description}"
        ).lower()

        egypt_explicit = (
            _has(EGYPT_ELIGIBILITY, location_and_restrictions)
            or _has(EGYPT_ELIGIBILITY, description)
        )

        if (
            _has(WORLDWIDE_ELIGIBILITY, eligibility_text)
            or egypt_explicit
            or re.search(r"\begypt\b", location_and_restrictions)
        ):
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
        # A listing with no verifiable date should not be sent as a fresh match.
        return "reject", 0, reasons, concerns + [freshness_reason]

    reasons.append(freshness_reason)

    if getattr(job, "date_kind", "posted") != "posted":
        concerns.append(
            "Only last-updated date is available; original posting date is unverified"
        )

    score = 40 + (25 if title_entry else 15 if body_entry else 0)
    score += 15 if local_city else 10
    score += min(15, 5 * len(matched_skills))
    score += 5
    score = min(score, 100)

    hard_uncertainty = any(
        (
            "eligibility" in concern.lower()
            or "eligible" in concern.lower()
        )
        or "experience level is unclear" in concern.lower()
        or "regional eligibility" in concern.lower()
        or "original posting date is unverified" in concern.lower()
        for concern in concerns
    )

    if hard_uncertainty:
        return "review", score, reasons, concerns

    # Description-level wording can match accidentally. Only an explicitly junior
    # title may become a confirmed MATCH; otherwise it stays REVIEW.
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
