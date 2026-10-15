from types import SimpleNamespace


def _eto_item(**overrides):
    item = {
        "linkedinJobId": "1234567890",
        "company": "Example Labs",
        "title": "Junior Python Software Engineer",
        "location": "Remote - Germany",
        "link": "https://www.linkedin.com/jobs/view/1234567890",
        "category": "software-engineering",
        "industries": "Software Development",
        "employmentType": "new-grad",
        "startDate": "June 2027",
        "firstSeenAt": "2026-10-12T12:00:00.000000+00:00",
    }
    item.update(overrides)
    return item


def test_european_tech_opportunities_maps_api_fields_and_marks_date_unverified(monkeypatch):
    from app.sources import european_tech_opportunities as source

    monkeypatch.setattr(source, "settings", SimpleNamespace(
        max_posting_age_days=7, european_tech_opportunities_max_pages=3,
    ))
    calls = []

    def fake_get_json(url, *, params=None):
        calls.append((url, dict(params or {})))
        if params["category"] == "software-engineering":
            return {"data": [_eto_item()], "pagination": {"totalPages": 1, "total": 1}}
        return {"data": [], "pagination": {"totalPages": 0, "total": 0}}

    monkeypatch.setattr(source, "get_json", fake_get_json)
    jobs = source.fetch_jobs()

    assert len(jobs) == 1
    job = jobs[0]
    assert job.source == "european_tech_opportunities"
    assert job.source_id == "1234567890"
    assert job.company == "Example Labs"
    assert job.title == "Junior Python Software Engineer"
    assert job.url == "https://www.linkedin.com/jobs/view/1234567890"
    assert job.posted_at == "2026-10-12T12:00:00.000000+00:00"
    assert job.date_kind == "unknown"
    assert job.remote is True
    assert job.eligibility == ""
    assert "software-engineering" in job.description
    assert len(calls) == 2
    assert calls[0][1]["first-seen"] == "7-days"
    assert calls[0][1]["page-size"] == 100


def test_european_tech_opportunities_continues_after_category_failure(monkeypatch):
    from app.sources import european_tech_opportunities as source

    monkeypatch.setattr(source, "settings", SimpleNamespace(
        max_posting_age_days=7, european_tech_opportunities_max_pages=2,
    ))

    def fake_get_json(url, *, params=None):
        if params["category"] == "software-engineering":
            raise RuntimeError("temporary API outage")
        return {"data": [_eto_item(
            linkedinJobId="9876543210",
            title="Machine Learning Engineer Intern",
            category="machine-learning",
            employmentType="internship",
            link="https://www.linkedin.com/jobs/view/9876543210",
        )], "pagination": {"totalPages": 1, "total": 1}}

    monkeypatch.setattr(source, "get_json", fake_get_json)
    jobs = source.fetch_jobs()
    assert len(jobs) == 1
    assert jobs[0].source_id == "9876543210"
    assert jobs[0].title == "Machine Learning Engineer Intern"


def test_european_first_seen_window_matches_api_supported_values():
    from app.sources.european_tech_opportunities import _first_seen_window

    assert _first_seen_window(1) == "24-hours"
    assert _first_seen_window(7) == "7-days"
    assert _first_seen_window(14) == "30-days"
    assert _first_seen_window(45) == ""


def test_nomado24_maps_tags_publication_date_and_deduplicates_queries(monkeypatch):
    from app.sources import nomado24 as source

    monkeypatch.setattr(source, "settings", SimpleNamespace(
        nomado24_language="en", nomado24_max_pages=2,
        nomado24_search_terms=("backend", "python"),
    ))
    calls = []
    item = {
        "slug": "junior-python-backend",
        "title": "Junior Python Backend Developer",
        "companyName": "Example GmbH",
        "location": "Remote (Germany / EU)",
        "remote": True,
        "workArrangement": "remote",
        "language": "en",
        "tags": ["Python", "Django", "PostgreSQL"],
        "source": "Example Careers",
        "publishedAt": "2026-10-12T08:30:00.000Z",
        "url": "https://www.nomado24.de/en/remote-jobs/job/junior-python-backend",
    }

    def fake_get_json(url, *, params=None):
        calls.append((url, dict(params or {})))
        return {"data": [item], "meta": {"page": params["page"], "perPage": 100, "count": 1}}

    monkeypatch.setattr(source, "get_json", fake_get_json)
    jobs = source.fetch_jobs()

    assert len(jobs) == 1
    job = jobs[0]
    assert job.source == "nomado24"
    assert job.source_id == "junior-python-backend"
    assert job.company == "Example GmbH"
    assert job.remote is True
    assert job.workplace_type == "remote"
    assert job.posted_at == "2026-10-12T08:30:00.000Z"
    assert job.date_kind == "posted"
    assert "Python" in job.description and "Django" in job.description
    assert job.eligibility == ""
    assert len(calls) == 2
    assert calls[0][1] == {"page": 1, "per_page": 100, "language": "en", "q": "backend"}


def test_nomado24_continues_to_next_search_term_after_failure(monkeypatch):
    from app.sources import nomado24 as source

    monkeypatch.setattr(source, "settings", SimpleNamespace(
        nomado24_language="en", nomado24_max_pages=1,
        nomado24_search_terms=("backend", "python"),
    ))

    def fake_get_json(url, *, params=None):
        if params["q"] == "backend":
            raise RuntimeError("temporary API outage")
        return {"data": [{
            "slug": "python-role",
            "title": "Junior Python Developer",
            "companyName": "Example",
            "location": "Remote (EU)",
            "remote": True,
            "workArrangement": "remote",
            "tags": ["Python"],
            "publishedAt": "2026-10-12T08:30:00Z",
            "url": "https://www.nomado24.de/en/remote-jobs/job/python-role",
        }], "meta": {"count": 1}}

    monkeypatch.setattr(source, "get_json", fake_get_json)
    jobs = source.fetch_jobs()
    assert len(jobs) == 1
    assert jobs[0].source_id == "python-role"


def test_enabled_sources_registers_both_international_sources():
    from app.sources import enabled_sources

    names = {name for name, _fetch in enabled_sources()}
    assert "european_tech_opportunities" in names
    assert "nomado24" in names


def test_european_tech_opportunities_paginates_until_provider_total_or_page_cap(monkeypatch):
    from app.sources import european_tech_opportunities as source

    monkeypatch.setattr(source, "PAGE_SIZE", 2)
    monkeypatch.setattr(source, "settings", SimpleNamespace(
        max_posting_age_days=7, european_tech_opportunities_max_pages=3,
    ))
    calls = []

    def fake_get_json(url, *, params=None):
        calls.append(dict(params or {}))
        if params["category"] != "software-engineering":
            return {"data": [], "pagination": {"totalPages": 0}}
        if params["page"] == 1:
            return {"data": [_eto_item(linkedinJobId="1"), _eto_item(linkedinJobId="2")],
                    "pagination": {"totalPages": 2}}
        return {"data": [_eto_item(linkedinJobId="3")], "pagination": {"totalPages": 2}}

    monkeypatch.setattr(source, "get_json", fake_get_json)
    jobs = source.fetch_jobs()
    assert {job.source_id for job in jobs} == {"1", "2", "3"}
    assert [call["page"] for call in calls if call["category"] == "software-engineering"] == [1, 2]


def test_nomado24_paginates_full_pages_and_stops_on_short_page(monkeypatch):
    from app.sources import nomado24 as source

    monkeypatch.setattr(source, "PAGE_SIZE", 2)
    monkeypatch.setattr(source, "settings", SimpleNamespace(
        nomado24_language="en", nomado24_max_pages=3,
        nomado24_search_terms=("backend",),
    ))
    calls = []

    def item(slug):
        return {
            "slug": slug,
            "title": f"Junior Python Developer {slug}",
            "companyName": "Example",
            "location": "Remote (EU)",
            "remote": True,
            "workArrangement": "remote",
            "tags": ["Python"],
            "publishedAt": "2026-10-12T08:30:00Z",
            "url": f"https://www.nomado24.de/en/remote-jobs/job/{slug}",
        }

    def fake_get_json(url, *, params=None):
        calls.append(dict(params or {}))
        if params["page"] == 1:
            return {"data": [item("1"), item("2")], "meta": {"count": 2}}
        return {"data": [item("3")], "meta": {"count": 1}}

    monkeypatch.setattr(source, "get_json", fake_get_json)
    jobs = source.fetch_jobs()
    assert {job.source_id for job in jobs} == {"1", "2", "3"}
    assert [call["page"] for call in calls] == [1, 2]


def test_international_sources_do_not_convert_generic_anywhere_labels_to_eligibility(monkeypatch):
    from app.sources import european_tech_opportunities as eto
    from app.sources import nomado24

    assert eto._safe_location("Remote worldwide", True) == "Remote (eligibility not supplied)"
    assert nomado24._safe_location("Anywhere", True) == "Remote (Germany/EU; applicant eligibility not supplied)"


def test_telegram_message_links_nomado24_attribution():
    from app.models import Job
    from app.telegram import format_message

    job = Job(
        source="nomado24",
        source_id="junior-python-role",
        title="Junior Python Developer",
        company="Example",
        location="Remote (Germany/EU; applicant eligibility not supplied)",
        url="https://www.nomado24.de/en/remote-jobs/job/junior-python-role",
        posted_at="2026-10-12T08:30:00Z",
        remote=True,
        workplace_type="remote",
    )
    message = format_message(job, "review", 75, [], ["Remote role does not confirm Egypt eligibility"])
    assert '<a href="https://www.nomado24.de">Nomado24</a>' in message
