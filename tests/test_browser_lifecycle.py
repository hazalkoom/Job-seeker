from dataclasses import replace
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from threading import Thread

import pytest

from app import application_automation as automation, storage
from app.application_queue import enqueue_application, get_application, record_automation_outcome
from app.models import Job


@pytest.fixture
def employer_server():
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def _html(self, content):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(content.encode())

        def do_GET(self):
            self._html("""
                <form action="/apply" method="post" enctype="multipart/form-data">
                  <label>Full name <input name="full_name" required></label>
                  <label>Email <input name="email" type="email" required></label>
                  <label>Resume <input name="resume" type="file" required></label>
                  <button type="submit">Submit application</button>
                </form>
            """)

        def do_POST(self):
            requests.append(self.rfile.read(int(self.headers["Content-Length"])))
            self._html("<h1>We received your application</h1>")

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/job", requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_browser_submits_pdf_once_and_persists_confirmation(employer_server, tmp_path, monkeypatch):
    from playwright.sync_api import Error, sync_playwright

    url, requests = employer_server
    monkeypatch.setattr(storage, "settings", replace(storage.settings, database_path=str(tmp_path / "jobs.sqlite3")))
    monkeypatch.setattr(automation, "ROOT", tmp_path)
    monkeypatch.setattr(automation, "log_auto_apply_event", lambda *args, **kwargs: None)
    storage.init_db()
    job = Job(source="fixture", source_id="one", title="Junior Developer", company="Example",
              location="Remote", description="", url=url, posted_at=datetime.now(timezone.utc).isoformat())
    storage.upsert_job(job, "match", 90, [], [])
    queue_id = enqueue_application(job, "match", 90, [], [])
    with storage._connect() as db:
        db.execute("UPDATE application_queue SET status='ready' WHERE id=?", (queue_id,))
    resume = tmp_path / "Fixture.pdf"
    resume.write_bytes(b"%PDF-1.4\nsynthetic test fixture\n")
    profile = {"identity": {"full_name": "Example Applicant", "email": "applicant@example.invalid"}}

    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch()
        except Error:
            if os.getenv("JOBHUNTER_REQUIRE_CHROMIUM"):
                raise
            pytest.skip("Chromium is unavailable")
        try:
            result = automation._perform_browser_application(
                get_application(queue_id), profile, {}, resume, browser, run_id="fixture"
            )
        finally:
            browser.close()

    assert result["outcome"] == "submitted", result
    assert get_application(queue_id)["status"] == "applying"
    assert len(requests) == 1
    assert b'filename="Fixture.pdf"' in requests[0]
    assert b"applicant@example.invalid" in requests[0]
    record_automation_outcome(queue_id, result["outcome"], reference=result["reference"])
    assert get_application(queue_id)["status"] == "submitted"
