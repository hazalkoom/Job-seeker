from datetime import datetime, timedelta, timezone

from app.matching import classify
from app.models import Job
from app.sources.himalayas import _eligibility_metadata, _location


def make_job(
    eligibility: str,
    description: str = (
        "Junior Node.js backend developer. 0-1 years of experience. "
        "Remote role open worldwide."
    ),
) -> Job:
    posted = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()

    return Job(
        source="himalayas",
        source_id="eligibility-test",
        title="Junior Backend Developer",
        company="Example",
        location="Remote",
        url="https://example.com/jobs/1",
        description=description,
        posted_at=posted,
        date_kind="posted",
        remote=True,
        workplace_type="remote",
        eligibility=eligibility,
        description_quality="full",
    )


def test_country_restrictions_override_generic_worldwide_description():
    metadata = _eligibility_metadata({
        "locationRestrictions": [
            {"alpha2": "MK", "name": "North Macedonia", "slug": "north-macedonia"},
            {"alpha2": "PT", "name": "Portugal", "slug": "portugal"},
            {"alpha2": "RS", "name": "Serbia", "slug": "serbia"},
        ],
        "timezoneRestrictions": [],
    })

    status, _, _, concerns = classify(make_job(metadata))

    assert status == "reject"
    assert any("exclude Egypt" in item for item in concerns)


def test_empty_country_and_timezone_lists_mean_worldwide():
    metadata = _eligibility_metadata({
        "locationRestrictions": [],
        "timezoneRestrictions": [],
    })

    status, _, reasons, concerns = classify(make_job(metadata))

    assert status == "match"
    assert any("permit Egypt" in item for item in reasons)
    assert not concerns


def test_egypt_country_and_standard_timezone_are_allowed():
    metadata = _eligibility_metadata({
        "locationRestrictions": [
            {"alpha2": "EG", "name": "Egypt", "slug": "egypt"}
        ],
        "timezoneRestrictions": ["UTC+2", "UTC+3"],
    })

    status, _, reasons, concerns = classify(
        make_job(
            metadata,
            "Junior Node.js backend developer. 0-1 years of experience.",
        )
    )

    assert status == "match"
    assert any("permit Egypt" in item for item in reasons)
    assert not concerns


def test_timezone_restriction_excluding_egypt_is_rejected():
    metadata = _eligibility_metadata({
        "locationRestrictions": [],
        "timezoneRestrictions": ["UTC-5", "UTC-4"],
    })

    status, _, _, concerns = classify(make_job(metadata))

    assert status == "reject"
    assert any("timezone restrictions exclude Egypt" in item for item in concerns)


def test_missing_structured_restrictions_stays_in_review():
    metadata = _eligibility_metadata({"title": "Junior Backend Developer"})

    status, _, _, concerns = classify(make_job(metadata))

    assert status == "review"
    assert any("did not supply complete" in item for item in concerns)


def test_country_restrictions_are_not_mislabeled_as_worksite_location():
    location = _location({
        "locationRestrictions": [
            {"alpha2": "MK", "name": "North Macedonia", "slug": "north-macedonia"},
            {"alpha2": "PT", "name": "Portugal", "slug": "portugal"},
        ],
    })

    assert location.startswith("Remote (candidate must be located in:")
    assert "Portugal" in location
    assert "North Macedonia" in location


def test_himalayas_search_filters_for_egypt(monkeypatch):
    from app.sources import himalayas

    seen = {}

    def fake_get_json(url, *, params=None):
        seen.update(params or {})
        return {"jobs": []}

    monkeypatch.setattr(himalayas, "get_json", fake_get_json)

    assert himalayas._search("junior backend developer") == []
    assert seen["country"] == "EG"


def test_country_allow_list_cannot_be_overridden_by_worldwide_description():
    status, _, _, concerns = classify(make_job("Germany, Portugal, Serbia"))

    assert status == "reject"
    assert any("candidate-country restrictions" in item.lower() for item in concerns)


def test_must_be_based_in_germany_rejects_even_if_worldwide_is_mentioned():
    status, _, _, concerns = classify(make_job(
        "",
        "Junior Node.js backend developer. 0-1 years of experience. "
        "This remote role is open worldwide. Applicants must be based in Germany.",
    ))

    assert status == "reject"
    assert any("restricts applicant location" in item.lower() for item in concerns)


def test_conflicting_country_statement_goes_to_review():
    status, _, _, concerns = classify(make_job(
        "",
        "Junior Node.js backend developer. 0-1 years of experience. "
        "Applicants must be based in Germany or Egypt; remote role.",
    ))

    assert status == "review"
    assert any("conflicting country eligibility" in item.lower() for item in concerns)


def test_ordinary_foreign_office_mention_does_not_reject_remote_job():
    status, _, _, concerns = classify(make_job(
        "",
        "Junior Node.js backend developer. 0-1 years of experience. "
        "Our headquarters are in Germany, and applicants may work remotely from Egypt.",
    ))

    assert status == "match"
    assert not concerns