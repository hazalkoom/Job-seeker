from types import SimpleNamespace

import app.runner as runner
from app.models import Job


def configure(monkeypatch, fetch, send):
    monkeypatch.setattr(
        runner,
        "settings",
        SimpleNamespace(
            notify_review_candidates=False,
            review_digest_size=2,
            telegram_bot_token="test-token",
            telegram_chat_id="test-chat",
        ),
    )
    monkeypatch.setattr(runner, "init_db", lambda: None)
    monkeypatch.setattr(runner, "enabled_sources", lambda: [("test", fetch)])
    monkeypatch.setattr(runner, "send_message", send)
    # Runner tests mock job persistence; queue persistence is tested separately.
    monkeypatch.setattr(runner, "enqueue_application", lambda *args: None)


def test_no_new_jobs_sends_status_message(monkeypatch):
    messages = []
    configure(
        monkeypatch,
        lambda: [],
        lambda message: messages.append(message) or True,
    )

    report = runner.run_once()

    assert len(messages) == 1
    assert "No new matching jobs" in messages[0]
    assert report["telegram_status_message_sent"] is True
    assert report["job_alerts_sent"] == 0
    assert report["telegram_messages_sent"] == 1


def test_source_failure_sends_partial_run_status_message(monkeypatch):
    messages = []

    def broken_source():
        raise RuntimeError("Test source unavailable")

    configure(
        monkeypatch,
        broken_source,
        lambda message: messages.append(message) or True,
    )

    report = runner.run_once()

    assert report["source_errors"]
    assert len(messages) == 1
    assert "source errors" in messages[0]
    assert "test" in messages[0]
    assert report["telegram_status_message_sent"] is True


def test_failed_job_alert_does_not_send_no_jobs_message(monkeypatch):
    job = Job(
        source="test",
        source_id="1",
        title="Junior Backend Developer",
        company="Example",
        location="Cairo",
        url="https://example.com/job",
    )
    messages = []

    configure(
        monkeypatch,
        lambda: [job],
        lambda message: messages.append(message) or False,
    )
    monkeypatch.setattr(
        runner, "classify", lambda job: ("match", 90, [], [])
    )
    monkeypatch.setattr(
        runner, "upsert_job", lambda *args: (True, True)
    )

    report = runner.run_once()

    assert len(messages) == 1
    assert "No new matching jobs" not in messages[0]
    assert report["telegram_status_message_sent"] is False



def test_review_candidates_are_sent_as_capped_digest(monkeypatch):
    messages = []
    marked = []
    jobs = [
        Job("test", str(i), f"Junior Backend Developer {i}", "Example Co", "Remote",
            f"https://example.com/jobs/{i}", posted_at=f"2026-10-{i:02d}", remote=True)
        for i in range(1, 4)
    ]
    monkeypatch.setattr(
        runner,
        "settings",
        SimpleNamespace(
            notify_review_candidates=True, review_digest_size=2,
            telegram_bot_token="test-token", telegram_chat_id="test-chat",
        ),
    )
    monkeypatch.setattr(runner, "init_db", lambda: None)
    monkeypatch.setattr(runner, "enabled_sources", lambda: [("test", lambda: jobs)])
    monkeypatch.setattr(runner, "send_message", lambda message: messages.append(message) or True)
    monkeypatch.setattr(runner, "classify", lambda job: ("review", int(job.source_id) * 10, [], ["Check eligibility"]))
    monkeypatch.setattr(runner, "upsert_job", lambda *args: (True, True))
    monkeypatch.setattr(runner, "mark_notified", lambda job: marked.append(job.source_id))
    monkeypatch.setattr(runner, "enqueue_application", lambda *args: None)

    report = runner.run_once()

    assert len(messages) == 1
    assert "review shortlist" in messages[0]
    assert "3 more review candidates" not in messages[0]
    assert "1 more review candidates remain queued" in messages[0]
    assert report["review_digest_message_sent"] is True
    assert report["review_alerts_sent"] == 2
    assert set(marked) == {"2", "3"}


def test_review_candidates_remain_pending_when_digest_delivery_fails(monkeypatch):
    jobs = [Job("test", "1", "Junior Backend Developer", "Example Co", "Remote", "https://example.com/1")]
    marked = []
    configure(monkeypatch, lambda: jobs, lambda message: False)
    monkeypatch.setattr(runner, "settings", SimpleNamespace(
        notify_review_candidates=True, review_digest_size=5,
        telegram_bot_token="test-token", telegram_chat_id="test-chat",
    ))
    monkeypatch.setattr(runner, "classify", lambda job: ("review", 80, [], ["Check eligibility"]))
    monkeypatch.setattr(runner, "upsert_job", lambda *args: (True, True))
    monkeypatch.setattr(runner, "mark_notified", lambda job: marked.append(job.source_id))
    monkeypatch.setattr(runner, "enqueue_application", lambda *args: None)

    report = runner.run_once()

    assert marked == []
    assert report["review_alerts_sent"] == 0
    assert report["review_digest_message_sent"] is False


def test_run_report_contains_source_effectiveness_metrics(monkeypatch):
    job = Job(
        source="quality_test", source_id="1", title="Junior Backend Developer",
        company="Example Co", location="Cairo, Egypt", url="https://example.com/job/1",
        description="Junior Python/Django role. 0-1 years of experience.",
        description_quality="full",
    )
    configure(monkeypatch, lambda: [job], lambda message: True)
    monkeypatch.setattr(runner, "classify", lambda job: ("match", 90, ["Relevant skills: Python"], []))
    monkeypatch.setattr(runner, "upsert_job", lambda *args: (True, False))
    report = runner.run_once()
    metrics = report["source_effectiveness"]["quality_test"]
    assert metrics["unique_jobs"] == 1
    assert metrics["match"] == 1
    assert metrics["full_descriptions"] == 1
    assert metrics["newly_stored"] == 1


def test_run_once_persists_match_to_application_queue(tmp_path, monkeypatch):
    import app.storage as storage
    from app.application_queue import list_applications

    monkeypatch.setattr(
        storage, "settings",
        SimpleNamespace(database_path=str(tmp_path / "runner-queue.sqlite3")),
    )
    storage.init_db()
    job = Job(
        source="queue_integration",
        source_id="42",
        title="Junior Backend Engineer",
        company="Example Co",
        location="Cairo, Egypt",
        url="https://example.com/jobs/42?utm_source=test",
    )
    monkeypatch.setattr(runner, "settings", SimpleNamespace(
        notify_review_candidates=False, review_digest_size=5,
        telegram_bot_token="", telegram_chat_id="",
    ))
    monkeypatch.setattr(runner, "init_db", storage.init_db)
    monkeypatch.setattr(runner, "enabled_sources", lambda: [("queue_integration", lambda: [job])])
    monkeypatch.setattr(runner, "classify", lambda _job: ("match", 92, ["skills"], []))
    monkeypatch.setattr(runner, "send_message", lambda _message: True)

    report = runner.run_once()
    items = list_applications()

    assert report["confirmed_matches"] == 1
    assert len(items) == 1
    assert items[0]["title"] == "Junior Backend Engineer"
    assert items[0]["status"] == "pending_review"
    assert items[0]["qualification_status"] == "match"
