from app.sources.common import normalize_job, workplace


def test_normalize_job_requires_valid_url_and_title():
    assert normalize_job(source="x", source_id=1, title="", company="C", location="Cairo", url="https://x.test") is None
    assert normalize_job(source="x", source_id=1, title="Junior Dev", company="C", location="Cairo", url="not-a-url") is None


def test_normalize_job_cleans_html_and_dates():
    job = normalize_job(
        source="x", source_id=1, title="<b>Junior Dev</b>", company="<i>Example</i>",
        location="Cairo", url="https://example.com/job", description="<p>Python &amp; SQL</p>",
        posted_at="2026-10-11T10:00:00Z",
    )
    assert job is not None
    assert job.title == "Junior Dev"
    assert job.company == "Example"
    assert job.description == "Python & SQL"
    assert job.posted_at == "2026-10-11T10:00:00Z"


def test_workplace_detection():
    assert workplace("Remote - Egypt", True) == "remote"
    assert workplace("Cairo, Hybrid", False) == "hybrid"
    assert workplace("Mansoura on-site", False) == "onsite"


def test_storage_migrates_legacy_database_without_deleting_rows(tmp_path, monkeypatch):
    import sqlite3
    from types import SimpleNamespace

    from app import storage

    database = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(database) as conn:
        conn.execute("""CREATE TABLE jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL, source_id TEXT NOT NULL, title TEXT NOT NULL,
            company TEXT NOT NULL, location TEXT NOT NULL, url TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '', posted_at TEXT NOT NULL DEFAULT '',
            remote INTEGER NOT NULL DEFAULT 0, employment_type TEXT NOT NULL DEFAULT '',
            score INTEGER NOT NULL DEFAULT 0, reasons TEXT NOT NULL DEFAULT '[]',
            concerns TEXT NOT NULL DEFAULT '[]', created_at TEXT, notified_at TEXT,
            UNIQUE(source, source_id)
        )""")
        conn.execute(
            "INSERT INTO jobs (source, source_id, title, company, location, url, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("old", "1", "Old listing", "Company", "Cairo", "https://example.com", "2026-10-01T00:00:00+00:00"),
        )
    monkeypatch.setattr(storage, "settings", SimpleNamespace(database_path=str(database)))
    storage.init_db()
    rows = storage.list_jobs(limit=10)
    assert len(rows) == 1
    assert rows[0]["title"] == "Old listing"
    assert rows[0]["status"] == "review"

    # Also verify a new row can be inserted into an old schema with a required created_at.
    from app.models import Job
    new_job = Job(
        source="test", source_id="new", title="Junior Python Developer", company="Example",
        location="Cairo", url="https://example.com/new", description="Junior Python developer",
        posted_at="2026-10-12T00:00:00+00:00",
    )
    storage.upsert_job(new_job, "match", 90, ["test"], [])
    assert len(storage.list_jobs(limit=10)) == 2


def test_jobicy_source_maps_public_feed(monkeypatch):
    from app.sources import jobicy

    calls = []
    def fake_get_json(url, *, params=None):
        calls.append(dict(params or {}))
        return {
            "success": True,
            "jobs": [{
                "id": 123,
                "jobTitle": "Junior Python Developer",
                "companyName": "Example Ltd",
                "jobGeo": "Anywhere",
                "url": "https://jobicy.com/jobs/123",
                "jobDescription": "Entry-level Python developer role.",
                "pubDate": "2026-10-12T06:00:00+00:00",
                "jobType": ["Full-Time"],
                "jobLevel": "Entry",
            }],
            "nextCursor": None,
        }

    monkeypatch.setattr(jobicy, "get_json", fake_get_json)
    jobs = jobicy.fetch_jobs()
    assert len(jobs) == 1
    assert jobs[0].source == "jobicy"
    assert jobs[0].title == "Junior Python Developer"
    assert jobs[0].eligibility == "Anywhere"
    assert calls == [{"count": 200}]


def test_email_alert_parser_supports_wuzzuf_linkedin_indeed_and_bayt():
    from app.sources.email_alerts import parse_alert_message

    raw = b'''From: alerts@example.com\r\nDate: Mon, 12 Oct 2026 08:00:00 +0000\r\nSubject: Job alerts\r\nMIME-Version: 1.0\r\nContent-Type: text/html; charset=utf-8\r\n\r\n<html><body>
      <div><a href="https://wuzzuf.net/jobs/p/abc-junior-node-backend">Junior Node.js Backend Developer</a><p>Acme Tech | Cairo, Egypt | Posted 2 days ago</p></div>
      <div><a href="https://www.linkedin.com/jobs/view/123456/">Junior Python Developer</a><p>Example Co | Remote worldwide | 1 day ago</p></div>
      <div><a href="https://eg.indeed.com/viewjob?jk=xyz">Junior Django Developer</a><p>Example Labs | Mansoura, Egypt | Posted today</p></div>
      <div><a href="https://www.bayt.com/en/egypt/jobs/junior-angular-developer-12345/">Junior Angular Developer</a><p>Web Company | Cairo, Egypt | 3 days ago</p></div>
    </body></html>'''
    jobs = parse_alert_message(raw)
    assert len(jobs) == 4
    assert {job.source for job in jobs} == {
        "wuzzuf_alert", "linkedin_alert", "indeed_alert", "bayt_alert"
    }
    assert all(job.posted_at for job in jobs)
    assert next(job for job in jobs if job.source == "wuzzuf_alert").title == "Junior Node.js Backend Developer"


def test_email_alert_parser_does_not_guess_posted_date():
    from app.sources.email_alerts import parse_alert_message

    raw = b'''From: alerts@example.com\r\nDate: Mon, 12 Oct 2026 08:00:00 +0000\r\nSubject: Job alerts\r\nMIME-Version: 1.0\r\nContent-Type: text/html; charset=utf-8\r\n\r\n<html><body><div><a href="https://wuzzuf.net/jobs/p/abc">Junior Python Developer</a><p>Acme | Cairo, Egypt</p></div></body></html>'''
    jobs = parse_alert_message(raw)
    assert len(jobs) == 1
    assert jobs[0].posted_at == ""
    assert jobs[0].date_kind == "unknown"


def test_rss_source_reads_rss_and_atom_feeds(monkeypatch):
    from app.sources import rss_feeds
    from types import SimpleNamespace

    monkeypatch.setattr(rss_feeds, "settings", SimpleNamespace(rss_feeds=(("Example Jobs", "https://example.com/jobs.xml"),)))
    monkeypatch.setattr(rss_feeds, "get_text", lambda url: '''<?xml version="1.0"?><rss version="2.0"><channel><item><title>Junior Backend Developer</title><link>https://example.com/jobs/1</link><description>Python Django role in Cairo</description><pubDate>Mon, 12 Oct 2026 08:00:00 +0000</pubDate><author>Example Ltd</author></item></channel></rss>''')
    jobs = rss_feeds.fetch_jobs()
    assert len(jobs) == 1
    assert jobs[0].title == "Junior Backend Developer"
    assert jobs[0].company == "Example Ltd"
    assert jobs[0].posted_at.startswith("2026-10-12")


def test_wuzzuf_weekly_digest_format_extracts_each_card_and_ignores_tracking_parameters():
    from app.sources.email_alerts import parse_alert_message

    raw = '''From: Nancy Farid <nancy.farid@wuzzuf.net>\r\nDate: Tue, 22 Sep 2026 12:42:00 +0000\r\nSubject: Latest jobs based on your profile\r\nMIME-Version: 1.0\r\nContent-Type: text/html; charset=utf-8\r\n\r\n<html><body>
      <p>Hello Mohamed, here are the most recent jobs based on your profile.</p>
      <table><tr><td><div class="job-card">
        <a href="https://wuzzuf.net/jobs/p/0nziiilcjdnu-python-back-end-developer-outsourced-prometeon-tyres-group-egypt-alexandria-egypt?v=nwaug26&amp;l=rje&amp;t=tracking&amp;a=Nancy+Weekly+jobs&amp;o=1">Python Back End Developer - Outsourced</a>
        <p>Prometeon tyres group – Egypt - Ameria, Alexandria</p><p>6 days ago | Full Time | Entry Level · -4 Yrs of Exp</p>
      </div></td></tr>
      <tr><td><div class="job-card">
        <a href="https://wuzzuf.net/jobs/p/junior-python-example?campaign=weekly">Junior Python Developer</a>
        <p>Example Tech - Cairo, Egypt</p><p>2 days ago | Full Time | Entry Level · 0-1 Yrs of Exp</p>
      </div></td></tr></table>
    </body></html>'''.encode('utf-8')

    jobs = parse_alert_message(raw)
    assert len(jobs) == 2
    first = next(job for job in jobs if job.title.startswith("Python Back End"))
    assert first.source == "wuzzuf_alert"
    assert first.company == "Prometeon tyres group"
    assert first.location.lower() in {"ameria", "ameria, alexandria"}
    assert first.posted_at.startswith("2026-09-16")
    assert "?" not in first.url


def test_email_alert_canonicalization_preserves_indeed_job_key_but_drops_tracking():
    from app.sources.email_alerts import _canonical_job_url

    first = _canonical_job_url("https://eg.indeed.com/viewjob?jk=abc123&from=email&vjk=tracking", "indeed_alert")
    second = _canonical_job_url("https://eg.indeed.com/viewjob?from=weekly&jk=abc123", "indeed_alert")
    assert first == second == "https://eg.indeed.com/viewjob?jk=abc123"

    wuzzuf = _canonical_job_url("https://wuzzuf.net/jobs/p/abc?utm_source=email&campaign=weekly", "wuzzuf_alert")
    assert wuzzuf == "https://wuzzuf.net/jobs/p/abc"
