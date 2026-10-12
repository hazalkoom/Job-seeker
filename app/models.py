from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class Job:
    source: str
    source_id: str
    title: str
    company: str
    location: str
    url: str
    description: str = ""
    posted_at: str = ""
    date_kind: str = "posted"  # posted, updated, or unknown
    remote: bool = False
    employment_type: str = ""
    workplace_type: str = "unknown"  # remote, hybrid, onsite, unknown
    eligibility: str = ""  # candidate/location restrictions, if supplied by source

    @property
    def text(self) -> str:
        return " ".join(
            str(value or "")
            for value in (self.title, self.description, self.employment_type)
        )
