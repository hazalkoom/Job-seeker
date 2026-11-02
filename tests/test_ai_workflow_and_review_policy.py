from datetime import datetime, timedelta, timezone

import pytest

import app.application_automation as aa
from app.matching import classify, _timezone_range_includes_egypt
from app.models import Job

FILLER = (
    " You will collaborate with engineers, write maintainable code, review pull requests "
    "and ship reliable software to customers every week. "
) * 2


def _job(title, description, location="Remote", eligibility=""):
    return Job(
        source="t", source_id=title, title=title, company="Acme", location=location,
        url="https://boards.greenhouse.io/acme/jobs/1", description=description + FILLER,
        posted_at=(datetime.now(timezone.utc) - timedelta(days=1)).isoformat(), date_kind="posted",
        remote=True, employment_type="Full time", workplace_type="remote",
        eligibility=eligibility, description_quality="full",
    )


def _item(job: Job, status: str, score: int):
    return {
        "id": 1, "status": "pending_review", "qualification_status": status, "score": score,
        "title": job.title, "company": job.company, "location": job.location, "url": job.url,
        "source": job.source, "source_id": job.source_id, "description": job.description,
        "posted_at": job.posted_at, "date_kind": "posted", "remote": 1, "employment_type": "Full time",
        "workplace_type": "remote", "eligibility": job.eligibility, "description_quality": "full",
    }


@pytest.mark.parametrize("title", [
    "AI Workflow Engineer", "AI Automation Engineer", "AI Integration Engineer",
    "Workflow Automation Developer", "Agentic Workflow Engineer",
])
def test_ai_workflow_and_automation_titles_are_not_rejected(title):
    job = _job(title, "Build n8n and Python automations. Remote role for candidates based in EMEA.")
    status, score, _, concerns = classify(job)
    assert status in {"match", "review"}, concerns


def test_ai_workflow_title_with_no_stack_keywords_survives():
    status, _, reasons, _ = classify(_job("AI Workflow Engineer", "Help clients design processes. Remote for candidates in EMEA."))
    assert status != "reject"
    assert any("workflow" in r.lower() for r in reasons)


@pytest.mark.parametrize("text", [
    "Remote for candidates working UTC-1 to UTC+3.",
    "Remote; candidates should be based in the EET or CET time zones.",
    "Remote role open to candidates in the Middle East and North Africa.",
    "We are hiring remotely across the GMT+2 region.",
])
def test_egypt_compatible_timezones_confirm_eligibility(text):
    _, _, reasons, _ = classify(_job("Junior Backend Developer", "Python and Django APIs. " + text))
    assert any("Regional remote eligibility" in r for r in reasons), text


@pytest.mark.parametrize("text", [
    "We serve customers across EMEA from our US offices. Remote.",
    "Remote role for candidates located in South Africa.",
])
def test_regional_words_that_do_not_describe_applicant_eligibility_do_not_confirm(text):
    _, _, reasons, concerns = classify(_job("Junior Backend Developer", "Python and Django APIs. " + text))
    assert not any("Regional remote eligibility" in r for r in reasons)
    assert any("does not confirm" in c for c in concerns)


def test_us_work_authorization_still_rejects_ai_automation_role():
    status, *_ = classify(_job("AI Automation Engineer", "Python automations. Must be authorized to work in the United States."))
    assert status == "reject"


def test_timezone_range_helper():
    assert _timezone_range_includes_egypt("UTC-3 to UTC+3")
    assert _timezone_range_includes_egypt("GMT+0 - GMT+4")
    assert not _timezone_range_includes_egypt("UTC-8 to UTC-5")
    assert not _timezone_range_includes_egypt("UTC+5 to UTC+9")


def test_review_listing_with_confirmed_egypt_remote_eligibility_proceeds_to_apply():
    job = _job("AI Automation Engineer", "Python and n8n automations. Remote worldwide, work from anywhere in the world.")
    status, score, _, _ = classify(job)
    assert status == "review" and score >= 70
    assert aa._reason_for_auto_skip(_item(job, "review", score)) is None


def test_review_listing_without_confirmed_eligibility_is_still_skipped():
    job = _job("AI Automation Engineer", "Python and n8n automations. This role is remote.")
    status, score, _, _ = classify(job)
    reason = aa._reason_for_auto_skip(_item(job, status, score))
    assert reason and "egypt" in reason.casefold()


def test_review_floor_env_override(monkeypatch):
    job = _job("AI Automation Engineer", "Python and n8n automations. Remote worldwide, work from anywhere in the world.")
    _, score, _, _ = classify(job)
    monkeypatch.setenv("AUTO_APPLY_REVIEW_MIN_SCORE", str(score + 5))
    reason = aa._reason_for_auto_skip(_item(job, "review", score))
    assert reason and "review auto-apply threshold" in reason
    monkeypatch.setenv("AUTO_APPLY_REVIEW_MIN_SCORE", str(score))
    assert aa._reason_for_auto_skip(_item(job, "review", score)) is None
