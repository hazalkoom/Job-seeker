import pytest


@pytest.fixture(autouse=True)
def _isolate_env_for_tests(monkeypatch):
    """Ensure tests run with standard default environment unless explicitly opted-in by monkeypatch."""
    monkeypatch.delenv("ALLOW_UNSPECIFIED_REMOTE", raising=False)
