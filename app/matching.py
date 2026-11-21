from __future__ import annotations

import os
import re
import json
from datetime import datetime, timedelta, timezone
from typing import Literal

from app.config import settings
from app.models import Job
from app.qualification import assess_experience

Status = Literal["match", "review", "reject"]

# Core technologies relevant to this job seeker's backend/full-stack background.
SKILLS: dict[str, list[str]] = {
    "Node.js / Express": [r"\bnode(?:\.js|js)\b", r"\bexpress(?:\.js)?\b", r"\bnest(?:\.js|js)\b"],
    "Django": [r"\bdjango\b"],
    "FastAPI": [r"\bfastapi\b"],
    "Python": [r"\bpython\b"],
    "Angular": [r"\bangular\b"],
    "React / Next.js": [r"\breact(?:\.js|js)?\b", r"\bnext(?:\.js|js)\b"],
    "Frontend / Web": [r"\bhtml5?\b", r"\bcss3?\b", r"\btailwind\b"],
    "Docker / Containers & Linux": [
        r"\bdocker\b",
        r"\blinux\b",
        r"\bubuntu\b",
        r"\bbash\b",
        r"\bcontainers?\b",
        r"\bkubernetes\b",
        r"\bk3s\b",
    ],
    "TypeScript / JavaScript": [
        r"\btypescript\b",
        r"\bjavascript\b",
        r"\bnodejs\b",
    ],
    "SQL / Databases": [
        r"\bsql\b",
        r"\bpostgres(?:ql)?\b",
        r"\bmongodb\b",
        r"\bmysql\b",
        r"\bredis\b",
    ],
    "QA / Testing": [
        r"\bqa\b",
        r"\bquality\s+assurance\b",
        r"\btest\s+cases?\b",
        r"\btest\s+automation\b",
        r"\bmanual\s+testing\b",
        r"\bautomated\s+testing\b",
        r"\bregression\s+testing\b",
        r"\bapi\s+testing\b",
        r"\bselenium\b",
        r"\bplaywright\b",
        r"\bcypress\b",
        r"\bjest\b",
        r"\bpytest\b",
    ],
    "Application & IT Support": [
        r"\bapplication\s+support\b",
        r"\btechnical\s+support\b",
        r"\bit\s+support\b",
        r"\bcustomer\s+support\b",
        r"\bhelp\s*desk\b",
        r"\bservice\s*desk\b",
        r"\btroubleshooting\b",
        r"\bincident\s+management\b",
        r"\bticketing\b",
        r"\blinux\b",
        r"\bactive\s+directory\b",
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
        r"\bprompt engineering\b",
        r"\bopenai\b",
        r"\banthropic\b",
        r"\bclaude\b",
        r"\bvector (?:db|database|store)s?\b",
        r"\bembeddings?\b",
    ],
    # Workflow-automation / integration work is software development for this candidate.
    "Workflow automation / integrations": [
        r"\bn8n\b",
        r"\bzapier\b",
        r"\bmake\.com\b",
        r"\bintegromat\b",
        r"\bpower automate\b",
        r"\bworkflow automation\b",
        r"\bautomation workflows?\b",
        r"\bai workflows?\b",
        r"\bworkflow engine\b",
        r"\bapi integrations?\b",
        r"\bthird[- ]party integrations?\b",
        r"\bwebhooks?\b",
        r"\betl\b",
        r"\bautomation scripts?\b",
        r"\bbusiness process automation\b",
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
    r"\baccounting\b",
    r"\bcompensation\b",
    r"\bdevops\s+engineer\b",
    r"\bsecurity\s+engineer\b",
    r"\bnetwork(?:ing)?\s+engineer\b",
    r"\bembedded\b",
    r"\bmobile\s+(?:developer|engineer)\b",
    r"\breact\s*native\b",
    r"\bcall\s*center\b",
    r"\bcustomer\s+service\b",
    r"\bsre\b",
    r"\bsite\s+reliability\b",
    r"\bplatform\s+engineer\b",
    r"\bcloud\s+(?:architect|engineer|infrastructure)\b",
    r"\binfrastructure\s+engineer\b",
    r"\bdata\s+engineer\b",
    r"\bmlops\b",
    r"\bmachine\s+learning\s+(?:engineer|researcher|scientist)\b",
    r"\bai\s+research(?:er|scientist)?\b",
    r"\bdeep\s+learning\b",
    r"\bcomputer\s+vision\b",
    r"\bnlp\s+(?:engineer|researcher|scientist)\b",
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
    r"\b(?:ai|llm|genai|gen\s*ai|generative\s+ai|agentic)\b.{0,40}\b(?:workflows?|automations?|integrations?|agents?)\b.{0,25}\b(?:engineer|developer)\b",
    r"\b(?:ai|llm)\s+(?:workflow|automation|integration)s?\s+(?:specialist|builder)\b",
    r"\b(?:workflow|process|business|intelligent)\s+automation\s+(?:engineer|developer|specialist)\b",
    r"\bautomation\s+(?:engineer|developer)\b",
    r"\bintegrations?\s+(?:software\s+)?(?:engineer|developer)\b",
    r"\bvibe[- ]?coding\s+(?:engineer|developer)\b",
    r"\bvibe[- ]?coder\b",
    r"\bagentic\s+(?:software\s+)?(?:engineer|developer)\b",
    r"\bai[- ]assisted\s+(?:software\s+)?(?:engineer|developer)\b",
]

QA_TARGET_ROLE = [
    r"\bqa\s*(?:engineer|developer|tester|analyst|specialist|testing)?\b",
    r"\bquality\s+assurance\s*(?:engineer|developer|tester|analyst|specialist|testing)?\b",
    r"\b(?:software\s+|manual\s+|automation\s+|junior\s+)?test(?:er|ing)\b",
    r"\b(?:software\s+)?test\s+(?:engineer|developer|automation|analyst|specialist)\b",
    r"\bqa\s+automation\s*(?:engineer|developer)?\b",
    r"\bautomation\s+test(?:er|ing|engineer)?\b",
    r"\bsdet\b",
    r"\bquality\s+(?:engineer|analyst)\b",
]

SUPPORT_TARGET_ROLE = [
    r"\bapplication\s+support\s*(?:engineer|specialist|analyst|developer|technician)?\b",
    r"\btechnical\s+support\s*(?:engineer|specialist|analyst|technician|representative|associate)?\b",
    r"\bsupport\s+(?:engineer|specialist|developer|analyst|technician)\b",
    r"\bcustomer\s+support\s+engineer\b",
    r"\bdeveloper\s+support\s*(?:engineer|specialist)?\b",
    r"\bit\s+(?:support|specialist|technician|administrator|engineer|analyst|help\s*desk)\b",
    r"\b(?:help\s*desk|service\s*desk|desktop\s+support|systems?\s+support|production\s+support|cloud\s+support|platform\s+support)\b",
    r"\bsolutions?\s+engineer\b",
    r"\bcustomer\s+solutions?\s*(?:engineer|specialist)?\b",
    r"\bimplementation\s+(?:engineer|specialist)\b",
]

TARGET_ROLE = [
    r"\bbackend\b",
    r"\bback[- ]end\b",
    r"\bfull[- ]?stack\b",
    r"\bfrontend\b",
    r"\bfront[- ]end\b",
    r"\bsoftware\s+(?:engineer|developer|development)\b",
    r"\bweb\s+(?:developer|engineer|development)\b",
    r"\bapplication\s+(?:developer|engineer)\b",
    r"\b(?:junior|entry[- ]level|graduate|associate|trainee|intern(?:ship)?)\s+(?:developer|engineer|programmer)\b",
    r"\b(?:python|django|fastapi|node(?:\.js|js)?|nestjs|express|angular|react|next(?:\.js|js)?|vue|typescript|javascript)\s+(?:engineer|developer|programmer|backend|back[- ]end|frontend|front[- ]end|full[- ]?stack)\b",
    *QA_TARGET_ROLE,
    *SUPPORT_TARGET_ROLE,
    *AI_TARGET_ROLE,
]

EXCLUDED_TITLE = [
    r"\bjava\b",
    r"\bspring(?:\s*boot)?\b",
    r"\bphp\b",
    r"\blaravel\b",
    r"\bsymfony\b",
    r"\bgolang\b",
    r"\bgo\s+(?:developer|engineer|backend)\b",
    r"(?:^|[\s(])\.net\b",
    r"\bc#(?:\s|$|\))",
    r"\basp\.net\b",
    r"\bruby\b",
    r"\bon\s+rails\b",
    r"\b(?:c\+\+|rust|elixir|scala|kotlin|swift|objective-c|flutter|android|ios)\s+(?:software\s+)?(?:developer|engineer)\b",
]

NON_ENGLISH_TITLE = [
    r"\b(?:french|german|spanish|italian|dutch|portuguese|polish|russian|turkish|hebrew|japanese|korean|mandarin|chinese)[- ]speaking\b",
    r"\bentwickler(?:in)?\b",
    r"\b(?:fluent|native)\s+(?:in\s+)?(?:french|german|spanish|italian|dutch|portuguese|polish|russian|turkish|hebrew|japanese|korean|mandarin)\b",
]

NON_ENGLISH_BODY = [
    r"\b(?:fluent|fluency|native|c1|c2|b2)\s+(?:level\s+)?(?:in\s+)?(?:french|german|spanish|italian|dutch|portuguese|polish|russian|turkish|hebrew|japanese|korean|mandarin)\s+(?:language\s+)?(?:is\s+)?(?:required|mandatory|must|essential)\b",
    r"\b(?:must|need to|required to)\s+(?:be\s+)?(?:fluent|native|proficient)?\s*(?:in|speak|write)\s+(?:fluent\s+)?(?:french|german|spanish|italian|dutch|portuguese|polish|russian|turkish|hebrew|japanese|korean|mandarin)\b",
]

EGYPT_HIRING_COMPANIES = {
    "supabase", "canonical", "gitlab", "automattic", "askable", "chatbase",
    "instabug", "luciq", "robusta", "robusta studio", "foodics", "paymob",
    "swvl", "vezeeta", "thndr", "valu", "fawry", "breadfast", "bosta",
    "kashier", "khazna", "dopay", "arabybrand", "advansys", "valeo",
    "vodafone", "orange", "ericsson", "deel", "remote", "toptal",
    "andela", "yassir", "careem", "talabat", "noon", "elmenus", "maxab",
    "trella", "wuilt", "gameball",
}

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

# Giza, Smart Village, and Greater Cairo neighborhoods in addition to Cairo/Mansoura.
LOCAL_CITIES = [
    "cairo",
    "mansoura",
    "giza",
    "smart village",
    "new cairo",
    "nasr city",
    "nasser city",
    "maadi",
    "heliopolis",
    "sheikh zayed",
    "6th of october",
    "october city",
    "10th of ramadan",
    "obour",
    "dokki",
    "mohandessin",
    "zamalek",
    "tagamoa",
    "fifth settlement",
    "5th settlement",
    "rehab",
    "madinaty",
    "shorouk",
]

NON_LOCAL_EGYPT_CITIES = (
    "alexandria",
    "aswan",
    "luxor",
    "hurghada",
    "sharm",
    "assiut",
    "port said",
    "suez",
    "ismailia",
    "tanta",
    "damanhur",
    "zagazig",
    "minya",
    "sohag",
    "qena",
    "beni suef",
    "fayoum",
    "kafr el sheikh",
    "damietta",
    "ameria",
    "amreya",
    "bolkly",
)

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
    r"^\s*(?:remote\s*|home\s*based\s*)?(?:worldwide|anywhere|global(?:ly)?)(?:\s*\([^)]*\))?\s*$",
    r"\b(?:remote|home\s*based)\s*(?:[-–,:]\s*|\s+)(?:worldwide|anywhere|global(?:ly)?)\b",
    r"\b(?:worldwide|global)\s*remote\b",
    r"\bworldwide\b",
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
    r"\bmena\b",
    r"(?<!south )\bafrica\b",
    r"\bnorth africa\b",
    r"\bmiddle east\b",
    r"\bgcc\b",
    r"\beu(?:ropean)?\s+(?:and\s+us\s+|or\s+us\s+)?time\s*zones?\b",
    r"\beuropean\s+(?:working\s+|business\s+)?hours\b",
    r"\b(?:cet|cest|eet|eest)\b",
    r"\b(?:utc|gmt)\s*[+±]?\s*[123](?::00)?\b",
    r"\b(?:utc|gmt)\s*[+-]\s*0?[0-3]\s*(?:to|-|–|and)\s*(?:utc|gmt)?\s*\+\s*[2-9]\b",
    r"\bcairo\s+(?:time|hours)\b",
    r"\bnatively remote\b",
]

# A regional word only counts as *eligibility* in a sentence that talks about where
# applicants live/work (not "customers across EMEA" or "our EMEA sales team").
REGIONAL_ELIGIBILITY_CONTEXT = [
    r"\bremote(?:ly)?\b",
    r"\bbased\b",
    r"\blocated\b",
    r"\blocation\b",
    r"\bhiring\b",
    r"\bhire\b",
    r"\bcandidates?\b",
    r"\bapplicants?\b",
    r"\btime\s*zones?\b",
    r"\btimezones?\b",
    r"\boverlap\b",
    r"\bwork(?:ing)?\s+(?:from|in|within)\b",
    r"\bopen to\b",
    r"\beligible\b",
    r"\bregion\b",
    r"\bcountries\b",
]

_COUNTRY_OR_REGION = (
    r"(?:the\s+)?(?:United States|U\.?S\.?A?\.?|USA|Canada|United Kingdom|UK|"
    r"Ireland|Germany|Portugal|Serbia|North Macedonia|Macedonia|France|Spain|Italy|"
    r"Netherlands|Poland|Greece|Belgium|Austria|Switzerland|Denmark|Sweden|Norway|"
    r"Finland|Iceland|Czechia|Czech Republic|Romania|Bulgaria|Croatia|Slovenia|"
    r"Slovakia|Hungary|Estonia|Latvia|Lithuania|Cyprus|Luxembourg|Malta|"
    r"European Union|EU|EEA|Europe|Australia|New Zealand|India|Singapore|"
    r"Philippines|Brazil|Mexico|Argentina|Chile|Colombia|Peru|Costa Rica|"
    r"Latin America|LATAM|Asia-Pacific|Asia Pacific|APAC|North America|"
    r"South Africa|Nigeria|Kenya|Turkey|Turkiye|UAE|United Arab Emirates|"
    r"Saudi Arabia|Israel|Pakistan|Ukraine|Japan|China|Hong Kong|Malaysia|"
    r"Indonesia|Vietnam|Thailand|Uruguay|Ecuador|Dominican Republic)"
)

_CANDIDATE_LOCATION_RESTRICTIONS = [
    re.compile(
        rf"\b(?:must|required to|need to|have to)\s+(?:be\s+)?"
        rf"(?:based|located|resident|living|residing)\s+(?:in|within)\s+"
        rf"{_COUNTRY_OR_REGION}\b",
        re.I,
    ),
    re.compile(
        rf"\b(?:must|required to|need to|have to)\s+(?:live|reside)\s+"
        rf"(?:in|within)\s+{_COUNTRY_OR_REGION}\b",
        re.I,
    ),
    re.compile(
        rf"\b(?:only\s+)?(?:open|available|restricted|limited)\s+to\s+"
        rf"(?:applicants|candidates|residents|employees|contractors)\s+"
        rf"(?:who are\s+)?(?:based|located|resident|living|residing)\s+"
        rf"(?:in|within)\s+{_COUNTRY_OR_REGION}\b",
        re.I,
    ),
    re.compile(
        rf"\b(?:must|required to|need to|have to)\s+(?:have|possess)\s+"
        rf"(?:the\s+)?(?:right|legal right|authorization|authorisation|"
        rf"work authorization|work authorisation)\s+to work in\s+"
        rf"{_COUNTRY_OR_REGION}\b",
        re.I,
    ),
    re.compile(
        rf"\b(?:remote|work)\s+(?:only\s+)?(?:within|from)\s+"
        rf"{_COUNTRY_OR_REGION}\b",
        re.I,
    ),
]


def _explicit_candidate_location_restriction(description: str) -> str:
    """Find explicit residency/work-location restrictions in job description."""
    for segment in re.split(
        r"[\r\n•▪●◦]+|(?<=[.!?;])\s+",
        description or "",
    ):
        segment = segment.strip()
        if not segment:
            continue

        for pattern in _CANDIDATE_LOCATION_RESTRICTIONS:
            if pattern.search(segment):
                if re.search(r"\begypt\b", segment, re.I):
                    return "CONFLICT: " + segment[:240]
                return segment[:240]

    return ""

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


_ASSUMED_OPEN_BLOCKERS = [
    r"\b(?:u\.?s\.?a?\.?|united states|canada|u\.?k\.?|united kingdom|european union|eu)[- ]?(?:based|only|residents?|citizens?)\b",
    r"\b(?:u\.?s\.?|united states)\s+citizen",
    r"\b(?:must|need to|required to|should)\s+(?:be\s+)?(?:located|based|reside|live|resident)\b",
    r"\bauthori[sz]ed to work\b",
    r"\bwork authori[sz]ation\b",
    r"\bright to work\b",
    r"\bsecurity clearance\b",
    r"\bcitizenship\b",
]


def _allow_unspecified_remote() -> bool:
    """Opt-in (ALLOW_UNSPECIFIED_REMOTE=true): treat a plain 'Remote' with no stated country
    restriction as open to Egypt. Default is off because many such roles are US-only."""
    return os.getenv("ALLOW_UNSPECIFIED_REMOTE", "").strip().casefold() in {"1", "true", "yes", "on"}


def _assumed_open_remote(location_and_restrictions: str, description: str) -> bool:
    if not _allow_unspecified_remote():
        return False
    if re.search(rf"\b{_COUNTRY_OR_REGION}\b", location_and_restrictions or "", re.I):
        return False  # "Remote - Germany", "Remote (US)" is a country restriction
    return not _has(_ASSUMED_OPEN_BLOCKERS, f"{location_and_restrictions} {description}")


def _has(patterns: list[str], text: str) -> bool:
    return any(re.search(pattern, text, re.I | re.S) for pattern in patterns)


_TZ_RANGE = re.compile(
    r"(?:utc|gmt)\s*([+-]?\s*\d{1,2})(?::\d{2})?\s*(?:to|-|–|and|through)\s*(?:utc|gmt)?\s*([+-]?\s*\d{1,2})(?::\d{2})?",
    re.I,
)


def _timezone_range_includes_egypt(text: str) -> bool:
    """True for ranges such as 'UTC-3 to UTC+3' or 'GMT+0 - GMT+4' (Egypt = UTC+2)."""
    for match in _TZ_RANGE.finditer(text or ""):
        try:
            low = int(match.group(1).replace(" ", ""))
            high = int(match.group(2).replace(" ", ""))
        except ValueError:
            continue
        if low > high:
            low, high = high, low
        if low <= 2 <= high and high - low <= 12:
            return True
    return False


def _regional_eligibility_found(location_and_restrictions: str, description: str) -> bool:
    """Regional/timezone eligibility from structured fields, or from eligibility prose."""
    if _has(REGIONAL_ELIGIBILITY, location_and_restrictions):
        return True
    if _timezone_range_includes_egypt(location_and_restrictions):
        return True
    for segment in re.split(r"[\r\n•▪●◦]+|(?<=[.!?;])\s+", description or ""):
        segment = segment.strip()
        if not segment:
            continue
        if (
            _has(REGIONAL_ELIGIBILITY, segment) or _timezone_range_includes_egypt(segment)
        ) and _has(REGIONAL_ELIGIBILITY_CONTEXT, segment):
            return True
    return False

def _himalayas_eligibility_decision(value: str):
    """Return (allowed|blocked|unknown, evidence) for structured Himalayas data."""
    prefix = "himalayas:v1:"
    raw = (value or "").strip()

    if not raw.startswith(prefix):
        return None

    try:
        payload = json.loads(raw[len(prefix):])
    except (TypeError, ValueError):
        return "unknown", "Himalayas country restrictions could not be parsed"

    if not (
        payload.get("locationRestrictionsPresent")
        and payload.get("timezoneRestrictionsPresent")
    ):
        return (
            "unknown",
            "Himalayas API did not supply complete country/timezone eligibility fields",
        )

    countries = payload.get("locationRestrictions")
    timezones = payload.get("timezoneRestrictions")

    if not isinstance(countries, list) or not isinstance(timezones, list):
        return "unknown", "Himalayas eligibility fields are malformed"

    # A non-empty locationRestrictions array is an allow-list.
    if countries:
        egypt_allowed = any(
            isinstance(country, dict)
            and (
                str(country.get("alpha2", "")).strip().upper() == "EG"
                or str(country.get("name", "")).strip().casefold()
                in {"egypt", "arab republic of egypt"}
                or str(country.get("slug", "")).strip().casefold()
                in {"egypt", "arab-republic-of-egypt"}
            )
            for country in countries
        )

        if not egypt_allowed:
            names = [
                str(
                    country.get("name")
                    or country.get("alpha2")
                    or country.get("slug")
                    or "unknown"
                )
                for country in countries
                if isinstance(country, dict)
            ]
            return (
                "blocked",
                "Himalayas candidate-location restrictions exclude Egypt; "
                "allowed countries: " + (", ".join(names) or "not identified"),
            )

    # Himalayas uses standard, non-daylight-saving offsets for country matching.
    # Egypt's standard offset is UTC+2. An empty list means no timezone restriction.
    if timezones:
        offsets = []
        unknown_offset = False

        for entry in timezones:
            text = (
                str(entry).strip().upper()
                .replace("UTC", "")
                .replace("GMT", "")
                .strip()
            )

            try:
                if ":" in text:
                    sign = -1 if text.startswith("-") else 1
                    unsigned = text.lstrip("+-")
                    hours, minutes = unsigned.split(":", 1)
                    offset = sign * (
                        int(hours) + int(minutes) / 60.0
                    )
                else:
                    offset = float(text)

                offsets.append(offset)
            except (TypeError, ValueError):
                unknown_offset = True

        if 2.0 not in offsets:
            if unknown_offset or not offsets:
                return (
                    "unknown",
                    "Himalayas timezone restrictions need manual verification "
                    "for Egypt (UTC+2 standard time)",
                )

            return (
                "blocked",
                "Himalayas timezone restrictions exclude Egypt's standard "
                "UTC+2 offset: " + ", ".join(map(str, timezones)),
            )

    return (
        "allowed",
        "Himalayas structured country/timezone restrictions permit Egypt",
    )


def _explicitly_restricted_from_egypt(eligibility: str) -> bool:
    """Candidate-country fields are restrictions, unlike a generic office location."""
    value = (eligibility or "").strip().lower()

    if not value or _has(EGYPT_ELIGIBILITY, value):
        return False

    if _has(REGIONAL_ELIGIBILITY, value) or _timezone_range_includes_egypt(value):
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


def _company_hires_in_egypt(company: str, title_and_location: str) -> bool:
    co = re.sub(r"[^a-z0-9]+", " ", (company or "").lower()).strip()
    if not co or co not in EGYPT_HIRING_COMPANIES:
        return False
    if re.search(rf"\b{_COUNTRY_OR_REGION}\b", title_and_location or "", re.I):
        return False
    return True


def is_relevant_title(title: str) -> bool:
    """Fast title-only check used to pre-filter alert cards before ATS HTTP probing."""
    title_lower = (title or "").strip().lower()
    if not title_lower:
        return False
    if (
        _has(EXCLUDED_TITLE, title_lower)
        or _has(NON_ENGLISH_TITLE, title_lower)
        or _has(SENIOR_TITLE, title_lower)
        or _has(IRRELEVANT_TITLE, title_lower)
    ):
        return False
    return _has(TARGET_ROLE, title_lower)


def _compute_calibrated_score(
    *,
    title_lower: str,
    body: str,
    matched_skills: list[str],
    matched_ai_tools: list[str],
    title_entry: bool,
    body_entry: bool,
    has_experience_mentions: bool,
    local_city: bool,
) -> int:
    """Calibrate 0-100 job score so 90-100 reflects the candidate's #1 thrive roles."""
    skills_set = set(matched_skills)
    is_support_title = _has(SUPPORT_TARGET_ROLE, title_lower) and not _has(
        [r"\b(?:backend|back[- ]end|full[- ]?stack|software\s+engineer|software\s+developer)\b"],
        title_lower,
    )
    is_qa_title = _has(QA_TARGET_ROLE, title_lower) and not _has(
        [r"\b(?:backend|back[- ]end|full[- ]?stack|software\s+engineer|software\s+developer)\b"],
        title_lower,
    )
    is_frontend_only_title = _has([r"\b(?:frontend|front[- ]end|ui)\b"], title_lower) and not _has(
        [r"\b(?:backend|back[- ]end|full[- ]?stack)\b"], title_lower
    )
    is_backend_title = _has(
        [
            r"\b(?:backend|back[- ]end|api)\b",
            r"\b(?:node(?:\.js|js)?|express|nestjs|python|django|fastapi|typescript)\s+(?:engineer|developer)\b",
        ],
        title_lower,
    )
    is_fullstack_title = _has([r"\bfull[- ]?stack\b"], title_lower)

    has_node_ts = bool({"Node.js / Express", "TypeScript / JavaScript"} & skills_set)
    has_node_express = "Node.js / Express" in skills_set
    has_python_stack = bool({"Python", "Django", "FastAPI"} & skills_set)
    has_python_framework = bool({"Django", "FastAPI"} & skills_set)
    has_angular = "Angular" in skills_set
    has_react = "React / Next.js" in skills_set
    has_db = "SQL / Databases" in skills_set
    has_docker_linux = "Docker / Containers & Linux" in skills_set or bool(
        re.search(r"\b(?:docker|linux|ubuntu|posix)\b", body)
    )
    has_testing = "QA / Testing" in skills_set
    has_ai_app = bool(
        {"AI / LLM applications", "Workflow automation / integrations"} & skills_set
    ) or _has(AI_TARGET_ROLE, title_lower)

    # 1. Base role alignment (34 to 46 pts)
    if is_support_title:
        score = 34
    elif is_qa_title:
        score = 38
    elif is_frontend_only_title:
        score = 40 if has_angular else 36
    elif is_backend_title:
        score = 46
    elif is_fullstack_title:
        score = 45 if has_angular else 42
    else:
        score = 44

    # 2. Stack strength points (weighted by candidate's actual proficiency)
    stack_points = 0
    if has_node_express:
        stack_points += 16  # #1 strongest backend framework
    elif has_node_ts:
        stack_points += 12

    if has_python_framework:
        stack_points += 15  # #2 strongest backend framework (Django / FastAPI)
    elif has_python_stack:
        stack_points += 12

    if has_angular:
        stack_points += 10  # Strongest frontend framework (2 yrs)
    elif has_react:
        stack_points += 5   # Secondary frontend framework (1 yr)

    if has_db:
        stack_points += 6
    if has_docker_linux:
        stack_points += 4
    if has_testing:
        stack_points += 4
    if has_ai_app:
        stack_points += 10
    if is_support_title and "Application & IT Support" in skills_set:
        stack_points += 8

    score += min(26, stack_points)

    # 3. Seniority / entry-level clarity (up to 16 pts)
    if title_entry:
        score += 16
    elif body_entry:
        score += 12
    elif not has_experience_mentions:
        score += 10

    # 4. Location / Egypt accessibility (10 to 12 pts)
    score += 12 if local_city else 10

    # 5. Freshness & AI coding tool bonus
    score += 4
    if matched_ai_tools:
        score += 4

    # 6. Role tier ceilings per candidate interview
    if is_support_title:
        score = min(score, 78)
    elif is_qa_title:
        score = min(score, 85)
    elif is_frontend_only_title and has_react and not has_angular:
        score = min(score, 82)
    elif is_fullstack_title and has_react and not has_angular:
        score = min(score, 85)
    elif is_fullstack_title and has_angular:
        score = min(score, 95)

    return max(0, min(score, 100))


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
        excl_concerns = ["Title focuses on an excluded primary stack"]
        if _spring_boot_required(body):
            excl_concerns.append("Existing Spring Boot experience appears mandatory")
        return "reject", 0, [], excl_concerns

    if _has(NON_ENGLISH_TITLE, title_lower) or _has(NON_ENGLISH_BODY, body):
        return "reject", 0, [], ["Role requires non-English language fluency (e.g. French/German)"]

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

    if not matched_skills and ai_role:
        # The title itself is an AI-workflow / automation / integration developer role.
        # Short or generic descriptions should not reject it for lacking a stack keyword.
        matched_skills.append("AI workflow / automation development (title)")

    if not matched_skills and _has(QA_TARGET_ROLE, title_lower):
        matched_skills.append("QA / Testing")

    if not matched_skills and _has(SUPPORT_TARGET_ROLE, title_lower):
        matched_skills.append("Application & IT Support")

    if not matched_skills and str(getattr(job, "source", "")).endswith("_alert"):
        matched_skills.append("Software / Web development (alert title)")

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

    explicit_location_restriction = _explicit_candidate_location_restriction(
        description
    )

    if explicit_location_restriction.startswith("CONFLICT:"):
        concerns.append(
            "Conflicting country eligibility evidence; manual verification required: "
            + explicit_location_restriction.removeprefix("CONFLICT: ").strip()
        )
    elif explicit_location_restriction:
        return "reject", 0, reasons, [
            "Description explicitly restricts applicant location/work authorization outside Egypt: "
            + explicit_location_restriction
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
    remote = (
        bool(job.remote)
        or _has(REMOTE_WORDS, loc)
        or job.workplace_type == "remote"
    )
    hybrid = _has(HYBRID_WORDS, loc) or job.workplace_type == "hybrid"
    onsite = _has(ONSITE_WORDS, loc) or job.workplace_type == "onsite"

    local_city = any(
        re.search(rf"\b{re.escape(city)}\b", loc)
        for city in LOCAL_CITIES
    ) or (
        not remote
        and bool(re.search(r"\begypt\b", loc))
        and not any(
            re.search(rf"\b{re.escape(other)}\b", loc)
            for other in NON_LOCAL_EGYPT_CITIES
        )
    )

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

        structured_himalayas = _himalayas_eligibility_decision(job.eligibility)

        if structured_himalayas is not None:
            verdict, evidence = structured_himalayas

            if verdict == "blocked":
                return "reject", 0, reasons, [evidence]

            if verdict == "unknown":
                concerns.append(evidence)
            else:
                reasons.append(evidence)

        else:
            egypt_explicit = (
                _has([r"\begypt\b"], location_and_restrictions)
                or _has(EGYPT_ELIGIBILITY, location_and_restrictions)
                or _has(EGYPT_ELIGIBILITY, description)
            )

            worldwide_explicit = (
                _has(WORLDWIDE_LOCATION_LABELS, location_and_restrictions)
                or _has(WORLDWIDE_ELIGIBILITY, description)
            )

            # Check the candidate-country restriction before generic worldwide wording.
            explicitly_restricted = _explicitly_restricted_from_egypt(
                job.eligibility
            )

            if explicitly_restricted:
                return "reject", 0, reasons, [
                    "Source's candidate-country restrictions do not include Egypt"
                ]

            allow_regional = getattr(settings, "allow_regional_emea", True)
            regional_found = _regional_eligibility_found(
                location_and_restrictions, description
            )
            if worldwide_explicit or egypt_explicit:
                reasons.append(
                    "International remote eligibility mentions worldwide/Egypt"
                )
            elif _company_hires_in_egypt(job.company, f"{title_lower} {location_and_restrictions}"):
                reasons.append(
                    "International remote eligibility mentions worldwide/Egypt (employer hires in Egypt)"
                )
            elif regional_found and allow_regional:
                reasons.append(
                    "Regional remote eligibility (EMEA/Africa/Middle East) permits Egypt"
                )
            elif regional_found:
                concerns.append(
                    "Regional eligibility (EMEA/Africa/Middle East) may include Egypt; "
                    "verify the hiring-country list"
                )
            elif _assumed_open_remote(f"{title_lower} {location_and_restrictions}", description):
                reasons.append(
                    "Remote role with no stated country restriction; assumed open to Egypt "
                    "(ALLOW_UNSPECIFIED_REMOTE=true)"
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

    score = _compute_calibrated_score(
        title_lower=title_lower,
        body=body,
        matched_skills=matched_skills,
        matched_ai_tools=matched_ai_tools,
        title_entry=title_entry,
        body_entry=body_entry,
        has_experience_mentions=bool(experience.mentions),
        local_city=local_city,
    )

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