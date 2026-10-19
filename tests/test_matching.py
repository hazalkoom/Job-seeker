from datetime import datetime, timezone

from app.matching import classify, evaluate
from app.models import Job


def job(**overrides):
    data = dict(
        source="test", source_id="1", title="Junior Node.js Backend Developer",
        company="Example", location="Cairo, Egypt", url="https://example.com/job",
        description="Entry-level role working with Node.js, Express and PostgreSQL.",
        posted_at=datetime.now(timezone.utc).isoformat(), remote=False,
        employment_type="Full-time", workplace_type="onsite", eligibility="Egypt",
        description_quality="full",
    )
    data.update(overrides)
    return Job(**data)


def test_relevant_junior_cairo_job_passes():
    passes, score, reasons, concerns = evaluate(job())
    assert passes
    assert score >= 70
    assert any("node.js" in reason.lower() for reason in reasons)
    assert not concerns


def test_senior_role_rejected():
    status, _, _, concerns = classify(job(title="Senior Node.js Engineer"))
    assert status == "reject"
    assert "Senior/lead/manager/architect title" in concerns


def test_java_junior_without_spring_boot_requirement_passes():
    status, _, reasons, concerns = classify(job(
        title="Junior Java Developer",
        description="Entry-level role using Java, OOP and REST APIs. Spring Boot is preferred, not required.",
    ))
    assert status == "match"
    assert any("java" in reason.lower() for reason in reasons)


def test_mandatory_spring_boot_experience_rejected():
    status, _, _, concerns = classify(job(
        title="Junior Java Developer",
        description="Junior position. Must have 2 years of experience with Spring Boot.",
    ))
    assert status == "reject"
    assert any("Spring Boot" in concern for concern in concerns)


def test_two_years_experience_is_within_configured_limit():
    status, _, reasons, concerns = classify(job(
        description="Junior role requiring at least 2 years of professional experience with Node.js.",
    ))
    assert status == "match"
    assert any("within target" in reason for reason in reasons)
    assert not concerns


def test_more_than_two_years_experience_rejected():
    status, _, _, concerns = classify(job(
        description="Junior role requiring at least 3 years of professional experience with Node.js.",
    ))
    assert status == "reject"
    assert any("exceeds target" in concern for concern in concerns)


def test_onsite_outside_cairo_or_mansoura_rejected():
    status, _, _, concerns = classify(job(
        title="Junior Django Developer", location="Alexandria, Egypt", remote=False,
        workplace_type="onsite", description="Entry-level Django developer.",
    ))
    assert status == "reject"
    assert any(
        "not Cairo, Mansoura, Giza, or Smart Village" in concern
        for concern in concerns
    )


def test_international_remote_without_egypt_eligibility_goes_to_review():
    status, _, _, concerns = classify(job(
        title="Junior Django Developer", location="Remote", remote=True,
        workplace_type="remote", description="Junior Django developer. Entry-level position.",
        eligibility="",
    ))
    assert status == "review"
    assert any("applicants in Egypt" in concern for concern in concerns)


def test_explicit_country_restriction_excluding_egypt_is_rejected():
    status, _, _, concerns = classify(job(
        title="Junior Django Developer", location="Remote - United States", remote=True,
        workplace_type="remote", description="Junior Django developer. Entry-level position.",
        eligibility="United States only",
    ))
    assert status == "reject"
    assert any("country restrictions" in concern for concern in concerns)


def test_worldwide_remote_junior_role_passes():
    status, _, _, concerns = classify(job(
        title="Junior FastAPI Developer", location="Worldwide", remote=True,
        workplace_type="remote", eligibility="Worldwide; candidates may work from anywhere",
        description="Junior FastAPI developer. Entry-level role.",
    ))
    assert status == "match"
    assert not concerns


def test_missing_posting_date_rejected_not_assumed_fresh():
    status, _, _, concerns = classify(job(posted_at=""))
    assert status == "reject"
    assert any("date missing" in concern.lower() for concern in concerns)


def test_old_listing_rejected():
    from datetime import timedelta
    old_date = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
    status, _, _, concerns = classify(job(posted_at=old_date))
    assert status == "reject"
    assert any("older than" in concern.lower() for concern in concerns)


def test_recently_updated_but_original_post_date_unknown_is_review():
    status, _, _, concerns = classify(job(date_kind="updated"))
    assert status == "review"
    assert any("original posting date is unverified" in concern for concern in concerns)


def test_lead_variants_are_rejected():
    for title in (
        "Product Engineering Lead",
        "Lead Backend Developer",
        "Head of Engineer - Web3/Crypto",
        "Sr. Full-Stack Software Engineer",
        "Software Engineer III",
        "Mid-level Python Engineer",
        "Founding Engineer (Fullstack)",
    ):
        status, _, _, concerns = classify(job(title=title))
        assert status == "reject", (title, status, concerns)


def test_product_engineer_is_rejected_even_if_description_mentions_target_stack():
    status, _, _, concerns = classify(job(
        title="Product Engineer",
        description="Build products using Python, Django, Node.js, and PostgreSQL.",
    ))
    assert status == "reject"
    assert any("outside the target developer roles" in item for item in concerns)


def test_sales_role_is_rejected_even_if_description_mentions_python():
    status, _, _, concerns = classify(job(
        title="Analytics & AI Account Executive, Sales",
        description="Our platform uses Python and machine learning.",
    ))
    assert status == "reject"


def test_non_junior_title_does_not_become_match_from_generic_description_copy():
    status, _, _, _ = classify(job(
        title="Software Engineer - Python",
        description="We build products with Python. Our company supports entry-level talent.",
    ))
    assert status == "review"


def test_junior_backend_role_still_matches():
    status, _, _, concerns = classify(job(
        title="Junior Backend Developer - Python",
        description="Junior role working with Python and Django. 0-1 years of experience.",
    ))
    assert status == "match"
    assert not concerns

def test_us_work_authorization_required_is_rejected():
    status, _, _, concerns = classify(job(
        description=(
            "Junior Node.js developer. Must be legally authorized "
            "to work in the United States. Visa sponsorship is not available."
        ),
    ))

    assert status == "reject"
    assert any("US work authorization" in concern for concern in concerns)


def test_us_residency_required_is_rejected():
    status, _, _, concerns = classify(job(
        description=(
            "Junior backend developer. Candidates must be located "
            "in the US or have permission to work there."
        ),
    ))

    assert status == "reject"
    assert any("US work authorization" in concern for concern in concerns)


def test_us_work_authorization_required_wording_is_rejected():
    status, _, _, concerns = classify(job(
        description=(
            "Junior backend developer. US work authorization is required."
        ),
    ))

    assert status == "reject"
    assert any("US work authorization" in concern for concern in concerns)


def test_us_work_authorization_preference_is_not_automatically_rejected():
    status, _, _, concerns = classify(job(
        description=(
            "Junior Node.js developer. US work authorization is preferred, "
            "but international applicants may apply and visa sponsorship is available."
        ),
    ))

    assert status == "match"
    assert not any("US work authorization" in concern for concern in concerns)