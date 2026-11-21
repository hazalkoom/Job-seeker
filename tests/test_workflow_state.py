from dataclasses import replace
from pathlib import Path
import shutil

import pytest

from app import storage, workflow_state as state
from app.application_queue import begin_automation_attempt, enqueue_application, get_application
from app.models import Job


@pytest.fixture
def database(tmp_path, monkeypatch):
    config = replace(storage.settings, database_path=str(tmp_path / "original.sqlite3"))
    monkeypatch.setattr(storage, "settings", config)
    monkeypatch.setattr(state, "settings", config)
    monkeypatch.setenv("GNUPGHOME", str(tmp_path))
    monkeypatch.setenv("JOBHUNTER_STATE_KEY", "fixture key used only in tests")
    storage.init_db()
    return config


def add_job(url, source_id):
    job = Job(source="fixture", source_id=source_id, title="Junior Developer", company="Example",
              location="Remote", description="", url=url)
    storage.upsert_job(job, "match", 90, [], [])
    return enqueue_application(job, "match", 90, [], [])


def test_ats_aliases_share_one_queue_item(database):
    first = add_job("https://boards.greenhouse.io/example/jobs/123", "greenhouse")
    second = add_job("https://job-boards.greenhouse.io/example/jobs/123?utm_source=board", "feed")
    assert first == second


def test_reserved_checkpoint_restores_uncertain_without_retry(database, tmp_path, monkeypatch):
    if shutil.which("gpg") is None:
        pytest.skip("GnuPG is unavailable")
    queue_id = add_job("https://jobs.lever.co/example/abc", "one")
    assert state.reserve([queue_id], "101") == [queue_id]
    encrypted = tmp_path / "reserved.gpg"
    state.snapshot(encrypted, "101", "reserved")
    assert not encrypted.read_bytes().startswith(b"SQLite format")
    restored = replace(database, database_path=str(tmp_path / "restored.sqlite3"))
    monkeypatch.setattr(storage, "settings", restored)
    monkeypatch.setattr(state, "settings", restored)
    with pytest.raises(ValueError, match="different workflow"):
        state.restore(encrypted, "102", "reserved")
    assert not Path(restored.database_path).exists()
    state.restore(encrypted, "101", "reserved")
    assert get_application(queue_id)["status"] == "failed"
    with storage._connect() as db:
        db.execute("UPDATE application_queue SET status='ready' WHERE id=?", (queue_id,))
    assert not begin_automation_attempt(queue_id, reservation="102")


def test_missing_or_corrupt_state_does_not_initialize_empty_queue(database, tmp_path, monkeypatch):
    restored = replace(database, database_path=str(tmp_path / "restored.sqlite3"))
    monkeypatch.setattr(state, "settings", restored)
    with pytest.raises(Exception):
        state.restore(tmp_path / "missing.sqlite3", "101", "legacy")
    corrupt = tmp_path / "corrupt.sqlite3"
    corrupt.write_bytes(b"not a database")
    with pytest.raises(Exception):
        state.restore(corrupt, "101", "legacy")
    assert not Path(restored.database_path).exists()
