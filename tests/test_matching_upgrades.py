from datetime import datetime, timezone

from app.matching import classify
from app.models import Job


def make_job(**overrides):
    values = {
        "source": "test",
        "source_id": "upgrade-test",
        "title": "Junior Node.js Backend Developer",
        "company": "Example",
        "location": "Cairo, Egypt",
        "url": "https://example.com/jobs/1",
        "description": (
            "Junior Node.js developer using Express. "
            "0-1 years of experience."
        ),
        "posted_at": datetime.now(timezone.utc).isoformat(),
        "remote": False,
        "employment_type": "Full-time",
        "workplace_type": "onsite",
        "eligibility": "Egypt",
    }

    values.update(overrides)
    return Job(**values)


def test_explicit_us_work_authorization_requirement_is_rejected():
    status, _, _, concerns = classify(
        make_job(
            description=(
                "Junior Node.js developer. 0-1 years of experience. "
                "Must be legally authorized to work in the United States."
            )
        )
    )

    assert status == "reject"
    assert any("US work authorization" in concern for concern in concerns)


def test_us_location_mention_alone_does_not_trigger_rejection():
    status, _, _, concerns = classify(
        make_job(
            description=(
                "Our engineering team works with colleagues in the United States. "
                "Junior Node.js developer. 0-1 years of experience."
            )
        )
    )

    assert status == "match"
    assert not concerns


def test_us_authorization_preference_is_not_treated_as_mandatory():
    status, _, _, concerns = classify(
        make_job(
            description=(
                "Junior Node.js developer. 0-1 years of experience. "
                "US work authorization is preferred but not required."
            )
        )
    )

    assert status == "match"
    assert not any("US work authorization" in concern for concern in concerns)


def test_junior_ai_application_developer_is_supported():
    status, _, reasons, concerns = classify(
        make_job(
            title="Junior AI Application Developer",
            description=(
                "Build LLM applications with Python, RAG, and the OpenAI API. "
                "Entry-level role with 0-1 years of experience."
            ),
        )
    )

    assert status == "match"
    assert any("AI / LLM applications" in reason for reason in reasons)
    assert not concerns


def test_ai_coding_assistant_keywords_boost_relevance_without_being_required():
    status, score, reasons, concerns = classify(
        make_job(
            description=(
                "Junior Node.js developer. 0-1 years of experience. "
                "Our workflow uses Claude Code, OpenCode, Antigravity CLI and Cursor."
            )
        )
    )

    assert status == "match"
    assert score >= 70
    assert any("AI-assisted development tools" in reason for reason in reasons)
    assert not concerns


def test_giza_based_junior_job_is_accepted():
    status, _, reasons, concerns = classify(
        make_job(location="Smart Village, Giza, Egypt")
    )

    assert status == "match"
    assert any("Giza" in reason for reason in reasons)
    assert not concerns


def test_senior_ai_role_is_still_rejected():
    status, _, _, concerns = classify(
        make_job(
            title="Senior AI Software Engineer",
            description="LLM applications with Python and LangChain.",
        )
    )

    assert status == "reject"
    assert any(
        "Senior/lead/manager/architect title" in concern
        for concern in concerns
    )