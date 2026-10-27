from app.sources import himalayas as source


def _item(**overrides):
    item = {
        "id": "himalayas-date-test-1",
        "title": "Junior Backend Developer",
        "companyName": "Example Labs",
        "location": "Remote",
        "url": "https://himalayas.app/jobs/example",
        "description": "Build and maintain backend APIs with Python and Node.js.",
        "locationRestrictions": [],
        "timezoneRestrictions": [],
    }
    item.update(overrides)
    return item


def test_himalayas_original_published_at_is_marked_posted(monkeypatch):
    monkeypatch.setattr(source, "SEARCHES", ("python developer",))
    monkeypatch.setattr(source, "_search", lambda _term: [_item(
        publishedAt="2026-10-26T10:00:00Z",
        updatedAt="2026-10-27T10:00:00Z",
    )])

    jobs = source.fetch_jobs()

    assert len(jobs) == 1
    assert jobs[0].posted_at == "2026-10-26T10:00:00Z"
    assert jobs[0].date_kind == "posted"


def test_himalayas_falls_back_to_updated_at_but_marks_it_updated(monkeypatch):
    monkeypatch.setattr(source, "SEARCHES", ("python developer",))
    monkeypatch.setattr(source, "_search", lambda _term: [_item(
        updatedAt="2026-10-27T10:00:00Z",
    )])

    jobs = source.fetch_jobs()

    assert len(jobs) == 1
    assert jobs[0].posted_at == "2026-10-27T10:00:00Z"
    assert jobs[0].date_kind == "updated"


def test_himalayas_without_any_date_uses_unknown_date_kind(monkeypatch):
    monkeypatch.setattr(source, "SEARCHES", ("python developer",))
    monkeypatch.setattr(source, "_search", lambda _term: [_item()])

    jobs = source.fetch_jobs()

    assert len(jobs) == 1
    assert jobs[0].posted_at == ""
    assert jobs[0].date_kind == "unknown"
