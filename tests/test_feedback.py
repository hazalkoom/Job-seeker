import sqlite3
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app import storage
from app.feedback import add_feedback, feedback_summary, list_feedback
from app.models import Job


def _seed_job(database, monkeypatch):
    monkeypatch.setattr(storage, "settings", SimpleNamespace(database_path=str(database)))
    storage.init_db()
    job = Job(
        source="test", source_id="feedback-job", title="Junior Backend Developer",
        company="Example Co", location="Cairo, Egypt", url="https://example.com/jobs/1",
        description="Junior Python/Django role. 0-1 years of experience.",
        posted_at=datetime.now(timezone.utc).isoformat(), description_quality="full",
    )
    storage.upsert_job(job, "review", 80, ["Relevant skills: Python, Django"], ["Check full description"])
    with sqlite3.connect(database) as conn:
        return int(conn.execute("SELECT id FROM jobs WHERE source_id='feedback-job'").fetchone()[0])


def test_feedback_can_be_saved_and_reported_without_changing_the_job(tmp_path, monkeypatch):
    database = tmp_path / "feedback.sqlite3"
    job_id = _seed_job(database, monkeypatch)
    feedback_id = add_feedback(job_id, "too_experienced", "Full description asks for 4 years")

    assert feedback_id > 0
    assert feedback_summary() == {"too_experienced": 1}
    entries = list_feedback()
    assert entries[0]["job_id"] == job_id
    assert entries[0]["notes"] == "Full description asks for 4 years"
    rows = storage.list_jobs(status="review", limit=10)
    assert len(rows) == 1
    assert rows[0]["status"] == "review"


def test_feedback_rejects_unknown_feedback_type(tmp_path, monkeypatch):
    database = tmp_path / "feedback.sqlite3"
    job_id = _seed_job(database, monkeypatch)
    with pytest.raises(ValueError, match="Feedback type"):
        add_feedback(job_id, "send_everything", "")


def test_feedback_requires_existing_job(tmp_path, monkeypatch):
    database = tmp_path / "feedback.sqlite3"
    monkeypatch.setattr(storage, "settings", SimpleNamespace(database_path=str(database)))
    storage.init_db()
    with pytest.raises(ValueError, match="not found"):
        add_feedback(999, "good_fit")
