from datetime import datetime, timezone
from types import SimpleNamespace

from app.sources import google_jobs


def test_google_jobs_runs_one_query_per_six_hour_slot(monkeypatch):
    rotating = tuple(f"rotating query {i}" for i in range(8))

    monkeypatch.setattr(
        google_jobs,
        "settings",
        SimpleNamespace(
            google_jobs_fixed_query="fixed Egypt query",
            google_jobs_rotating_queries=rotating,
        ),
    )

    run_times = [
        datetime(2026, 10, 19, hour, 17, tzinfo=timezone.utc)
        for hour in (0, 6, 12, 18)
    ]

    selected = [
        google_jobs._query_terms(now=run_time)
        for run_time in run_times
    ]

    assert selected[0] == ["fixed Egypt query"]
    assert all(len(queries) == 1 for queries in selected)
    assert len({queries[0] for queries in selected[1:]}) == 3
    assert all(
        queries[0] in rotating
        for queries in selected[1:]
    )