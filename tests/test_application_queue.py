import json
from types import SimpleNamespace

import pytest

import app.storage as storage
from app.application_queue import (
    application_events,
    decide_application,
    enqueue_application,
    get_application,
    list_applications,
    record_manual_submission,
    resolve_application_question,
    run_preflight,
)
from app.models import Job


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(
        storage,
        "settings",
        SimpleNamespace(database_path=str(tmp_path / "queue-test.sqlite3")),
    )
    storage.init_db()
    return tmp_path / "queue-test.sqlite3"


@pytest.fixture
def private_files(tmp_path):
    profile_path = tmp_path / "candidate_profile.json"
    answers_path = tmp_path / "application_answers.json"
    profile_path.write_text(json.dumps({
        "identity": {
            "full_name": "Sample Candidate",
            "email": "candidate@example.com",
            "city": "Cairo",
            "country": "Egypt",
        },
        "links": {},
        "education": [],
        "work_authorization": {"authorized_to_work_in_egypt": True},
    }), encoding="utf-8")
    answers_path.write_text(json.dumps({"answers": {}}), encoding="utf-8")
    return profile_path, answers_path


def _stored_job(source="test", source_id="1", url="https://example.com/jobs/1?utm_source=mail"):
    job = Job(
        source=source,
        source_id=source_id,
        title="Junior Backend Developer",
        company="Example Co",
        location="Remote — Egypt",
        url=url,
        description="Node.js, Express, REST APIs",
    )
    storage.upsert_job(job, "match", 90, ["Relevant skills"], [])
    return job


def test_enqueue_is_canonical_url_deduplicated_and_does_not_reset_human_state(db):
    first = _stored_job()
    first_id = enqueue_application(first, "match", 90, ["first"], [])
    assert first_id is not None
    assert decide_application(first_id, "approve")["status"] == "approved"

    second = _stored_job(
        source="another_source",
        source_id="other-id",
        url="https://EXAMPLE.com/jobs/1?utm_medium=alert#apply",
    )
    duplicate_id = enqueue_application(second, "review", 55, ["duplicate"], ["check"])

    assert duplicate_id == first_id
    items = list_applications()
    assert len(items) == 1
    assert items[0]["status"] == "approved"
    assert items[0]["sightings_count"] == 2


def test_preflight_requires_review_approval_and_valid_private_files(db, private_files):
    job = _stored_job(url="https://example.com/jobs/preflight")
    queue_id = enqueue_application(job, "match", 90, [], [])
    profile_path, answers_path = private_files

    before_approval = run_preflight(
        queue_id, profile_path=str(profile_path), answer_bank_path=str(answers_path)
    )
    assert not before_approval["passed"]
    assert any("approve" in item.lower() for item in before_approval["blockers"])

    decide_application(queue_id, "approve", "Reviewed listing manually")
    result = run_preflight(
        queue_id, profile_path=str(profile_path), answer_bank_path=str(answers_path)
    )
    assert result["passed"] is True
    assert result["status"] == "ready"
    from app.config import settings
    assert result["auto_submit_allowed"] is bool(settings.auto_apply_enabled)
    assert get_application(queue_id)["preflight_status"] == "passed"


def test_preflight_fails_when_private_profile_is_missing(db, tmp_path):
    job = _stored_job(url="https://example.com/jobs/missing-profile")
    queue_id = enqueue_application(job, "match", 90, [], [])
    decide_application(queue_id, "approve")
    result = run_preflight(
        queue_id,
        profile_path=str(tmp_path / "missing-profile.json"),
        answer_bank_path=str(tmp_path / "missing-answers.json"),
    )
    assert not result["passed"]
    assert any("not found" in item.lower() for item in result["blockers"])
    assert get_application(queue_id)["status"] == "approved"


def test_resolver_returns_answer_but_audit_never_stores_answer_text(db, private_files):
    job = _stored_job(url="https://example.com/jobs/answer")
    queue_id = enqueue_application(job, "match", 90, [], [])
    profile_path, answers_path = private_files

    result = resolve_application_question(
        queue_id,
        "What is your email address?",
        profile_path=str(profile_path),
        answer_bank_path=str(answers_path),
    )
    assert result.status == "auto_fill"
    assert result.answer == "candidate@example.com"

    event_json = json.dumps(application_events(queue_id))
    assert "answer_resolved" in event_json
    assert "candidate@example.com" not in event_json


def test_manual_submission_requires_passed_preflight_and_records_only_afterward(db, private_files):
    job = _stored_job(url="https://example.com/jobs/submission")
    queue_id = enqueue_application(job, "match", 90, [], [])
    with pytest.raises(ValueError, match="preflight-passed"):
        record_manual_submission(queue_id)

    decide_application(queue_id, "approve")
    profile_path, answers_path = private_files
    run_preflight(queue_id, profile_path=str(profile_path), answer_bank_path=str(answers_path))
    result = record_manual_submission(
        queue_id, reference="confirmation-123", notes="Submitted manually by candidate"
    )
    assert result["status"] == "submitted"
    assert result["submission_reference"] == "confirmation-123"
    assert any(e["event_type"] == "manual_submission_recorded" for e in application_events(queue_id))


def test_rejected_item_is_not_in_pending_review_list(db):
    job = _stored_job(url="https://example.com/jobs/rejected")
    queue_id = enqueue_application(job, "review", 40, [], ["eligibility unclear"])
    decide_application(queue_id, "reject", "Not eligible from Egypt")
    assert get_application(queue_id)["status"] == "rejected"
    assert list_applications(status="pending_review") == []


def test_automation_outcome_records_skip_without_storing_answers(db):
    from app.application_queue import record_automation_outcome

    job = _stored_job(url="https://example.com/jobs/auto-skip")
    queue_id = enqueue_application(job, "review", 60, [], ["eligibility unknown"])
    record_automation_outcome(
        queue_id,
        "auto_skipped",
        reason="Egypt eligibility not confirmed",
        details={"ats_host": "jobs.lever.co"},
    )
    item = get_application(queue_id)
    assert item["status"] == "auto_skipped"
    events = application_events(queue_id)
    assert events[-1]["event_type"] == "application_auto_skipped"
    assert "Egypt eligibility not confirmed" in events[-1]["details"]["reason"]
