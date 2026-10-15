from __future__ import annotations

def test_rss_source_skips_failed_feed_and_continues(monkeypatch, caplog):
    from types import SimpleNamespace
    from app.sources import rss_feeds

    monkeypatch.setattr(
        rss_feeds,
        "settings",
        SimpleNamespace(rss_feeds=(
            ("Broken Feed", "https://broken.example/jobs.xml"),
            ("Working Feed", "https://working.example/jobs.xml"),
        )),
    )

    def fake_get_text(url):
        if "broken.example" in url:
            raise RuntimeError("temporary feed outage")
        return '''<?xml version="1.0"?><rss version="2.0"><channel>
          <item><title>Junior Backend Developer</title>
          <link>https://working.example/jobs/1</link>
          <description>Python and Django</description>
          <pubDate>Mon, 12 Oct 2026 08:00:00 +0000</pubDate>
          </item></channel></rss>'''

    monkeypatch.setattr(rss_feeds, "get_text", fake_get_text)
    jobs = rss_feeds.fetch_jobs()

    assert len(jobs) == 1
    assert jobs[0].title == "Junior Backend Developer"
    assert jobs[0].source == "rss:working_feed"
    assert "Broken Feed" in caplog.text
    assert "temporary feed outage" in caplog.text


def test_rss_atom_prefers_alternate_link_and_preserves_updated_date_kind(monkeypatch):
    from types import SimpleNamespace
    from app.sources import rss_feeds

    monkeypatch.setattr(
        rss_feeds,
        "settings",
        SimpleNamespace(rss_feeds=(("Remote Engineering", "https://example.com/feed.atom"),)),
    )
    monkeypatch.setattr(
        rss_feeds,
        "get_text",
        lambda url: '''<?xml version="1.0" encoding="utf-8"?>
        <feed xmlns="http://www.w3.org/2005/Atom">
          <entry>
            <title>Junior Python Developer</title>
            <link rel="self" href="https://example.com/feed.atom/1" />
            <link rel="alternate" href="https://example.com/jobs/1" />
            <summary>Remote software engineering role</summary>
            <updated>2026-10-11T10:00:00Z</updated>
          </entry>
        </feed>''',
    )

    jobs = rss_feeds.fetch_jobs()

    assert len(jobs) == 1
    assert jobs[0].url == "https://example.com/jobs/1"
    assert jobs[0].date_kind == "updated"
    assert jobs[0].posted_at.startswith("2026-10-11")
    assert jobs[0].remote is True
    assert jobs[0].eligibility == ""


def test_remote_rss_feed_does_not_assume_worldwide_eligibility(monkeypatch):
    from types import SimpleNamespace
    from app.sources import rss_feeds

    monkeypatch.setattr(
        rss_feeds,
        "settings",
        SimpleNamespace(rss_feeds=((
            "We Work Remotely Backend",
            "https://weworkremotely.com/categories/remote-back-end-programming-jobs.rss",
        ),)),
    )
    monkeypatch.setattr(
        rss_feeds,
        "get_text",
        lambda url: '''<rss version="2.0"><channel><item>
          <title>Junior Backend Engineer</title>
          <link>https://example.com/jobs/1</link>
          <description>Python developer. Company is based in Berlin.</description>
          <pubDate>Mon, 12 Oct 2026 08:00:00 +0000</pubDate>
        </item></channel></rss>''',
    )

    jobs = rss_feeds.fetch_jobs()

    assert len(jobs) == 1
    assert jobs[0].remote is True
    assert jobs[0].location == "Remote (eligibility not supplied)"
    assert jobs[0].eligibility == ""


def test_rss_does_not_infer_eligibility_from_unrelated_worldwide_mention(monkeypatch):
    from types import SimpleNamespace
    from app.sources import rss_feeds

    monkeypatch.setattr(
        rss_feeds,
        "settings",
        SimpleNamespace(rss_feeds=(("Remote Engineering", "https://example.com/remote-jobs.xml"),)),
    )
    monkeypatch.setattr(
        rss_feeds,
        "get_text",
        lambda url: '''<rss version="2.0"><channel><item>
          <title>Junior Backend Engineer</title>
          <link>https://example.com/jobs/2</link>
          <description>Our product is used worldwide. Role location and eligible countries are not specified.</description>
          <pubDate>Mon, 12 Oct 2026 08:00:00 +0000</pubDate>
        </item></channel></rss>''',
    )

    jobs = rss_feeds.fetch_jobs()

    assert len(jobs) == 1
    assert jobs[0].remote is True
    assert jobs[0].location == "Remote (eligibility not supplied)"
    assert jobs[0].eligibility == ""


def test_rss_accepts_explicit_remote_worldwide_eligibility(monkeypatch):
    from types import SimpleNamespace
    from app.sources import rss_feeds

    monkeypatch.setattr(
        rss_feeds,
        "settings",
        SimpleNamespace(rss_feeds=(("General Jobs", "https://example.com/jobs.xml"),)),
    )
    monkeypatch.setattr(
        rss_feeds,
        "get_text",
        lambda url: '''<rss version="2.0"><channel><item>
          <title>Junior Backend Engineer — Remote worldwide</title>
          <link>https://example.com/jobs/3</link>
          <description>Python and SQL.</description>
          <pubDate>Mon, 12 Oct 2026 08:00:00 +0000</pubDate>
        </item></channel></rss>''',
    )

    jobs = rss_feeds.fetch_jobs()

    assert len(jobs) == 1
    assert jobs[0].remote is True
    assert jobs[0].eligibility == "Remote worldwide"
