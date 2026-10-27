import json
from types import SimpleNamespace

import app.storage as storage
from app.application_queue import enqueue_application, get_application, record_automation_outcome
from app.automation_diagnostics import reason_code_for_reason, sanitize
from app.models import Job
from scripts import requeue_auto_skipped


def test_reason_code_is_stable_for_form_discovery_skip():
    assert reason_code_for_reason("No supported public ATS application form was found from this listing.") == "no_supported_ats_form"


def test_secret_assignment_redaction_in_strings():
    value = sanitize("This is token=abc123 and api_key=xyz987")
    assert "token=abc123" not in value
    assert "api_key=xyz987" not in value


def test_diagnostic_requeue_is_dry_run_by_default_and_one_time(tmp_path, monkeypatch, capsys):
    db_path = tmp_path / "queue.sqlite3"
    monkeypatch.setattr(storage, "settings", SimpleNamespace(database_path=str(db_path)))
    storage.init_db()
    job = Job(
        source="test", source_id="sample-1", title="Junior Backend Developer",
        company="Example Co", location="Remote", url="https://example.com/jobs/1",
        description="Public listing description",
    )
    storage.upsert_job(job, "review", 70, [], [])
    queue_id = enqueue_application(job, "review", 70, [], [])
    assert queue_id is not None
    record_automation_outcome(queue_id, "auto_skipped", reason="No supported public ATS application form was found from this listing.")

    assert requeue_auto_skipped.main(["--reason-code", "no_supported_ats_form"]) == 0
    dry = json.loads(capsys.readouterr().out)
    assert dry["mode"] == "dry_run"
    assert dry["candidate_count"] == 1
    assert get_application(queue_id)["status"] == "auto_skipped"

    assert requeue_auto_skipped.main(["--reason-code", "no_supported_ats_form", "--apply"]) == 0
    capsys.readouterr()
    assert get_application(queue_id)["status"] == "pending_review"
    assert requeue_auto_skipped.main(["--reason-code", "no_supported_ats_form", "--apply"]) == 0
    out = capsys.readouterr().out
    assert '"candidate_count": 0' in out


def test_inspector_includes_latest_matcher_and_application_reasons(tmp_path, monkeypatch, capsys):
    import sqlite3
    from types import SimpleNamespace
    from scripts import inspect_application_outcomes

    db_path = tmp_path / "jobs.sqlite3"
    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE jobs (
                id INTEGER PRIMARY KEY, source TEXT, source_id TEXT, title TEXT,
                company TEXT, url TEXT, location TEXT, posted_at TEXT, date_kind TEXT,
                description_quality TEXT, workplace_type TEXT, employment_type TEXT,
                status TEXT
            );
            CREATE TABLE application_queue (
                id INTEGER PRIMARY KEY, job_id INTEGER, status TEXT,
                qualification_status TEXT, score INTEGER, reasons TEXT, concerns TEXT,
                notes TEXT, preflight_status TEXT, preflight_blockers TEXT,
                preflight_warnings TEXT, updated_at TEXT
            );
            CREATE TABLE application_events (
                id INTEGER PRIMARY KEY, queue_id INTEGER, event_type TEXT,
                details TEXT, created_at TEXT
            );
            """
        )
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "latest_run_report.json").write_text(json.dumps({
        "seen_after_cross_source_dedup": 100,
        "newly_stored": 4,
        "confirmed_matches": 1,
        "review_candidates": 3,
        "rejected": 96,
        "top_rejection_reasons": [["No relevant technology detected", 45]],
        "source_errors": [{"source": "jobicy", "error": "Network unreachable"}],
        "auto_apply": {
            "enabled": True, "processed": 2, "submitted": 0,
            "skipped": 2, "failed": 0,
            "reason_breakdown": {"no_supported_ats_form": 2},
            "results": [{
                "queue_id": 7, "title": "Backend Developer", "company": "Example",
                "outcome": "auto_skipped", "reason_code": "no_supported_ats_form",
                "reason": "No supported public ATS application form was found.",
                "apply_links": [{"host": "jobs.example.com", "supported_ats": False,
                                 "url": "https://jobs.example.com/apply"}],
            }],
        },
    }), encoding="utf-8")

    monkeypatch.setattr(inspect_application_outcomes, "ROOT", tmp_path)
    monkeypatch.setattr(inspect_application_outcomes, "settings", SimpleNamespace(database_path=str(db_path)))
    assert inspect_application_outcomes.main(["--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["matcher_rejection_reasons"][0][0] == "No relevant technology detected"
    assert report["source_errors"][0]["source"] == "jobicy"
    assert report["application_run_results"][0]["reason_code"] == "no_supported_ats_form"


def test_description_unavailable_is_retried_once_after_enrichment_is_added(tmp_path, monkeypatch, capsys):
    db_path = tmp_path / "queue.sqlite3"
    monkeypatch.setattr(storage, "settings", SimpleNamespace(database_path=str(db_path)))
    storage.init_db()
    job = Job(
        source="test", source_id="summary-1", title="Junior Backend Developer",
        company="Example Co", location="Remote", url="https://example.com/jobs/summary-1",
        description="A short source summary",
    )
    storage.upsert_job(job, "review", 70, [], [])
    queue_id = enqueue_application(job, "review", 70, [], [])
    record_automation_outcome(
        queue_id, "auto_skipped",
        reason="Full employer description is unavailable; skipped rather than applying from a snippet.",
        details={"reason_code": "description_unavailable"},
    )

    assert requeue_auto_skipped.main(["--reason-code", "description_unavailable", "--apply"]) == 0
    capsys.readouterr()
    assert get_application(queue_id)["status"] == "pending_review"
    assert requeue_auto_skipped.main(["--reason-code", "description_unavailable", "--apply"]) == 0
    out = capsys.readouterr().out
    assert '"candidate_count": 0' in out
