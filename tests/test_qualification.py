from datetime import datetime, timezone

from app.matching import classify
from app.models import Job
from app.qualification import assess_experience


def example_job(**overrides):
    values = dict(
        source="test",
        source_id="job-1",
        title="Junior Backend Developer",
        company="Example Company",
        location="Cairo, Egypt",
        url="https://example.com/jobs/1",
        description="Build APIs with Python and Django. 0-1 years of experience.",
        posted_at=datetime.now(timezone.utc).isoformat(),
        date_kind="posted",
        remote=False,
        employment_type="Full-time",
        workplace_type="onsite",
        eligibility="Egypt",
        description_quality="full",
    )
    values.update(overrides)
    return Job(**values)


def test_mandatory_three_plus_years_are_rejected_with_quote():
    job = example_job(description="Junior role. Must have 3+ years of professional experience with Python.")
    status, _, _, concerns = classify(job)
    assert status == "reject"
    assert any("3 years" in concern for concern in concerns)
    assert any("Must have 3+ years" in concern for concern in concerns)


def test_mandatory_range_uses_upper_bound():
    assessment = assess_experience("This role requires 1-3 years of professional experience.")
    assert assessment.maximum_required_years == 3


def test_preferred_four_years_is_not_mistaken_for_a_hard_requirement():
    assessment = assess_experience("4+ years of experience is preferred but not required.")
    assert assessment.maximum_required_years is None
    assert assessment.maximum_preferred_years == 4
    status, _, _, concerns = classify(example_job(
        description="Junior backend developer using Python. 4+ years of experience is preferred but not required."
    ))
    assert status == "review"
    assert any("preferred, not mandatory" in concern for concern in concerns)


def test_preferred_years_in_an_unrelated_sentence_do_not_override_a_hard_requirement():
    assessment = assess_experience(
        "3 years of professional experience required. A master's degree is preferred."
    )
    assert assessment.maximum_required_years == 3
    assert assessment.maximum_preferred_years is None


def test_bachelors_degree_is_not_a_rejection_rule():
    status, _, _, concerns = classify(example_job(
        description="Junior backend developer using Python. 0-1 years of experience. Bachelor's degree in Computer Science required."
    ))
    assert status == "match"
    assert not concerns


def test_summary_only_cannot_be_a_confirmed_match():
    status, _, _, concerns = classify(example_job(description_quality="summary"))
    assert status == "review"
    assert any("full employer description" in concern.lower() for concern in concerns)


def test_metadata_only_cannot_be_a_confirmed_match():
    status, _, _, concerns = classify(example_job(
        description="Tags: python, django",
        description_quality="metadata",
    ))
    assert status == "review"
    assert any("metadata/tags" in concern.lower() for concern in concerns)


def test_explicit_high_experience_is_rejected_even_in_a_summary():
    status, _, _, concerns = classify(example_job(
        description="Junior backend developer using Python and Django. 4+ years of professional experience required.",
        description_quality="summary",
    ))
    assert status == "reject"
    assert any("mandatory experience requirement exceeds target" in concern.lower() for concern in concerns)


def test_company_age_is_not_interpreted_as_job_experience():
    assessment = assess_experience("Our company has operated for 12 years. Junior software role.")
    assert assessment.mentions == ()


def test_spelled_out_years_are_understood():
    assessment = assess_experience("At least three years of professional experience is required.")
    assert assessment.maximum_required_years == 3


def test_no_experience_required_is_not_parsed_as_a_positive_year_requirement():
    assessment = assess_experience("No prior professional experience required for this graduate role.")
    assert assessment.maximum_required_years is None
    assert assessment.maximum_preferred_years is None


def test_job_default_description_quality_fails_closed():
    job = Job(
        source="test", source_id="unknown", title="Junior Python Developer",
        company="Example", location="Cairo", url="https://example.com/job",
        description="Python and Django role. 0-1 years of experience.",
        posted_at=datetime.now(timezone.utc).isoformat(),
    )
    assert job.description_quality == "unknown"
    status, _, _, concerns = classify(job)
    assert status == "review"
    assert any("description completeness is unknown" in concern.lower() for concern in concerns)
