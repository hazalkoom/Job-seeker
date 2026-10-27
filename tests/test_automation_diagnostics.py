import json

from app.automation_diagnostics import (
    log_auto_apply_event,
    reason_code_for_reason,
    safe_url,
    sanitize,
)


def test_reason_codes_distinguish_common_automatic_skip_causes():
    assert reason_code_for_reason("No supported public ATS application form was found from this listing.") == "no_supported_ats_form"
    assert reason_code_for_reason("Full employer description is unavailable; skipped from a snippet.") == "description_unavailable"
    assert reason_code_for_reason("Remote role does not confirm Egypt eligibility") == "egypt_eligibility_unconfirmed"
    assert reason_code_for_reason("Required fields could not be answered safely: Required question needs an exact saved answer") == "required_field_unanswered"


def test_safe_url_removes_query_fragment_and_credentials():
    result = safe_url("https://username:password@jobs.example/jobs/123?token=do-not-share&ref=foo#apply")
    assert result == "https://jobs.example/jobs/123"
    assert "password" not in result
    assert "token=" not in result


def test_sanitize_drops_answer_values_and_redacts_emails_tokens():
    value = sanitize({
        "answer": "candidate's private answer",
        "field_value": "some value",
        "url": "https://jobs.example/apply?secret=one",
        "note": "contact me at candidate@example.com token=abc",
    })
    assert value["answer"] == "<redacted>"
    assert value["field_value"] == "<redacted>"
    assert "secret=one" not in value["url"]
    assert "candidate@example.com" not in value["note"]
    assert "token=abc" not in value["note"]


def test_log_auto_apply_event_writes_jsonl_and_stderr_without_answers(tmp_path, monkeypatch, capsys):
    log_path = tmp_path / "application_automation.jsonl"
    monkeypatch.setenv("AUTO_APPLY_AUDIT_LOG_PATH", str(log_path))
    log_auto_apply_event(
        "run-123", "qualification_decision", queue_id=7,
        decision="skip", reason="No supported public ATS application form was found.",
        answer="must never be stored", listing_url="https://jobs.example/j/1?tracking=x",
    )
    assert log_path.is_file()
    saved = json.loads(log_path.read_text(encoding="utf-8").splitlines()[0])
    assert saved["run_id"] == "run-123"
    assert saved["answer"] == "<redacted>"
    assert "tracking=x" not in saved["listing_url"]
    assert "must never be stored" not in log_path.read_text(encoding="utf-8")
    assert "AUTO_APPLY_AUDIT" in capsys.readouterr().err
