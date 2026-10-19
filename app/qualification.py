"""Transparent experience-requirement extraction for software-job listings.

This module uses conservative, explainable patterns rather than pretending a
regular expression is a human recruiter. Each detected requirement preserves its
original sentence so the matcher can explain why a listing was rejected/reviewed.
"""
from __future__ import annotations

import html
import re
from dataclasses import dataclass

_NUMBER = r"(?:\d+(?:\.\d+)?|zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)"
_NUMBERS = {
    "zero": 0.0, "one": 1.0, "two": 2.0, "three": 3.0, "four": 4.0,
    "five": 5.0, "six": 6.0, "seven": 7.0, "eight": 8.0,
    "nine": 9.0, "ten": 10.0, "eleven": 11.0, "twelve": 12.0,
}

_RANGE = re.compile(
    rf"(?P<low>{_NUMBER})\s*(?:-|–|—|to)\s*(?P<high>{_NUMBER})\s*\+?\s*(?:years?|yrs?)\b",
    re.I,
)
_SINGLE = re.compile(rf"(?P<n>{_NUMBER})\s*(?:\+|plus)?\s*(?:years?|yrs?)\b", re.I)
_REVERSE = re.compile(rf"\b(?:experience|background)\s+(?:of|with|at least|minimum of)\s+(?P<n>{_NUMBER})\s*\+?\s*(?:years?|yrs?)\b", re.I)
_EXPERIENCE_CONTEXT = re.compile(
    r"\b(?:experience|experienced|exp\.?|professional background|work background|"
    r"in (?:software|backend|frontend|full[- ]stack|web|python|java|node(?:\.js)?|"
    r"engineering|development|programming|it)\s+(?:development|engineering|work|experience)?|"
    r"(?:software|backend|frontend|full[- ]stack|web|python|java|node(?:\.js)?|"
    r"engineering|development|programming)\s+experience)\b",
    re.I,
)
_SOFT_LANGUAGE = re.compile(
    r"\b(?:preferred|preferably|ideally|desirable|desired|nice to have|nice-to-have|"
    r"a plus|is a plus|bonus|advantage|asset|helpful|would help|not required|"
    r"not mandatory|not essential|optional|not necessary|beneficial)\b",
    re.I,
)
_NEGATED_REQUIREMENT = re.compile(
    r"\b(?:not required|not mandatory|not essential|not necessary|no requirement for)\b",
    re.I,
)


def _number(value: str) -> float:
    normalized = value.strip().lower()
    if normalized in _NUMBERS:
        return _NUMBERS[normalized]
    return float(normalized)


def _plain_text(value: str) -> str:
    value = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", value or "")
    value = re.sub(r"(?s)<[^>]+>", " ", value)
    value = html.unescape(value)
    value = value.replace("\u00a0", " ")
    return re.sub(r"[ \t]+", " ", value).strip()


def _segments(text: str) -> list[str]:
    cleaned = _plain_text(text)
    # Keep bullet/requirement lines separate. Semicolons and sentence ends are
    # useful boundaries; commas are deliberately not split because phrases like
    # "3+ years preferred, but not required" need their context.
    chunks = re.split(r"[\r\n•▪●◦]+|(?<=[.!?;])\s+", cleaned)
    return [re.sub(r"^\s*[-*▪•]+\s*", "", c).strip(" \t-•") for c in chunks if c.strip()]


def _mentions_for_segment(segment: str) -> list[tuple[float, float, str]]:
    candidates: list[tuple[float, float, str]] = []
    occupied: list[tuple[int, int]] = []

    def has_experience_context(match: re.Match[str]) -> bool:
        # Need context in the same requirement fragment so years in a company's
        # history, product age, or unrelated dates don't become experience rules.
        window = segment[max(0, match.start() - 100): min(len(segment), match.end() + 110)]
        return bool(_EXPERIENCE_CONTEXT.search(window))

    for match in _RANGE.finditer(segment):
        if not has_experience_context(match):
            continue
        try:
            low, high = _number(match.group("low")), _number(match.group("high"))
        except ValueError:
            continue
        if high < low or high > 40:
            continue
        candidates.append((low, high, segment))
        occupied.append(match.span())

    for match in _SINGLE.finditer(segment):
        if any(start <= match.start() < end for start, end in occupied):
            continue
        if not has_experience_context(match):
            continue
        try:
            years = _number(match.group("n"))
        except ValueError:
            continue
        if years > 40:
            continue
        candidates.append((years, years, segment))
        occupied.append(match.span())

    # Less common wording such as "experience of 3 years".
    for match in _REVERSE.finditer(segment):
        try:
            years = _number(match.group("n"))
        except ValueError:
            continue
        if 0 <= years <= 40:
            candidates.append((years, years, segment))

    # Deduplicate number ranges that were matched by more than one pattern.
    unique: dict[tuple[float, float, str], None] = {}
    for candidate in candidates:
        unique[candidate] = None
    return list(unique)


@dataclass(frozen=True, slots=True)
class ExperienceMention:
    minimum_years: float
    maximum_years: float
    kind: str  # required or preferred
    evidence: str


@dataclass(frozen=True, slots=True)
class ExperienceAssessment:
    mentions: tuple[ExperienceMention, ...]

    @property
    def maximum_required_years(self) -> float | None:
        required = [m.maximum_years for m in self.mentions if m.kind == "required"]
        return max(required) if required else None

    @property
    def maximum_preferred_years(self) -> float | None:
        preferred = [m.maximum_years for m in self.mentions if m.kind == "preferred"]
        return max(preferred) if preferred else None

    @property
    def required_evidence(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(m.evidence for m in self.mentions if m.kind == "required"))

    @property
    def preferred_evidence(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(m.evidence for m in self.mentions if m.kind == "preferred"))


def assess_experience(description: str) -> ExperienceAssessment:
    """Extract experience requirements, splitting hard requirements from preferences.

    A range's upper bound is used conservatively. E.g. a mandatory "1-3 years"
    range is not considered a <=1-year role. Preferred/nice-to-have thresholds are
    kept separate and sent to review instead of being treated as mandatory.
    """
    mentions: list[ExperienceMention] = []
    for segment in _segments(description):
        sentence = segment[:500]
        soft = bool(_SOFT_LANGUAGE.search(sentence)) or bool(_NEGATED_REQUIREMENT.search(sentence))
        for low, high, evidence in _mentions_for_segment(sentence):
            mentions.append(
                ExperienceMention(
                    minimum_years=low,
                    maximum_years=high,
                    kind="preferred" if soft else "required",
                    evidence=evidence[:260],
                )
            )
    # Same exact evidence and range may be found in nested/overlapping patterns.
    deduped: dict[tuple[float, float, str, str], ExperienceMention] = {}
    for mention in mentions:
        deduped[(mention.minimum_years, mention.maximum_years, mention.kind, mention.evidence)] = mention
    return ExperienceAssessment(tuple(deduped.values()))
