from types import SimpleNamespace

import app.runner as runner
from app.models import Job


def configure(monkeypatch, fetch, send):
    monkeypatch.setattr(
        runner,
        "settings",
        SimpleNamespace(
            notify_review_candidates=False,
            telegram_bot_token="test-token",
            telegram_chat_id="test-chat",
        ),
    )
    monkeypatch.setattr(runner, "init_db", lambda: None)
    monkeypatch.setattr(runner, "enabled_sources", lambda: [("test", fetch)])
    monkeypatch.setattr(runner, "send_message", send)


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


def test_source_failure_does_not_send_no_jobs_message(monkeypatch):
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
    assert messages == []
    assert report["telegram_status_message_sent"] is False


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
