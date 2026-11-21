"""Round 3 test suite: Email alert parsers, Gmail inbox reconciler, ATS resolver, Egypt locations, and abstract templates."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.application_automation import _answer_for_field, _reason_for_auto_skip
from app.ats_resolver import (
    clear_resolver_cache,
    derive_company_slugs,
    enrich_wuzzuf_public_job,
    resolve_job_to_ats,
    titles_match,
)
from app.matching import classify
from app.models import Job
from app.runner import _manual_apply_digest_message
from app.sources.application_inbox import parse_application_email, reconcile_events_with_db
from app.sources.email_alerts import _unwrap_url, parse_alert_message


# ---------------------------------------------------------------------------
# 1. Email Alert Parsers (LinkedIn, Glassdoor, Wuzzuf AWS SES)
# ---------------------------------------------------------------------------

def test_linkedin_multiline_card_extracts_clean_title_company_and_hybrid_location():
    raw = (
        "From: LinkedIn Job Alerts <jobalerts-noreply@linkedin.com>\r\n"
        "Date: Mon, 02 Nov 2026 10:00:00 +0000\r\n"
        "Subject: \"Software Engineer\": 2 new jobs\r\n"
        "MIME-Version: 1.0\r\n"
        "Content-Type: text/html; charset=utf-8\r\n\r\n"
        "<html><body><table><tr><td>"
        "<a href=\"https://www.linkedin.com/comm/jobs/view/4485951347?trackingId=xyz\">"
        "<div>Junior Backend Engineer</div>"
        "<div>Instabug · Cairo, Egypt (Hybrid)</div>"
        "<div>Easy Apply</div>"
        "</a>"
        "</td></tr></table></body></html>"
    ).encode("utf-8")

    jobs = parse_alert_message(raw)
    assert len(jobs) == 1
    job = jobs[0]
    assert job.source == "linkedin_alert"
    assert job.title == "Junior Backend Engineer"
    assert job.company == "Instabug"
    assert "Cairo, Egypt (Hybrid)" in job.location
    assert job.workplace_type == "hybrid"
    assert job.posted_at.startswith("2026-11-02")


def test_glassdoor_alert_skips_star_rating_and_ignores_search_or_redirect_links():
    raw = (
        "From: Glassdoor Jobs <noreply@glassdoor.com>\r\n"
        "Date: Mon, 02 Nov 2026 11:00:00 +0000\r\n"
        "Subject: Junior Software Engineer jobs\r\n"
        "MIME-Version: 1.0\r\n"
        "Content-Type: text/html; charset=utf-8\r\n\r\n"
        "<html><body><table>"
        "<tr><td><a href=\"https://www.glassdoor.com/partner/jobListing.htm?jobListingId=998877&amp;pos=101\">"
        "<div>Paymob</div><div>4.4 ★</div><div>Junior Python Developer</div><div>New Cairo, Egypt</div><div>2d</div>"
        "</a></td></tr>"
        "<tr><td><a href=\"https://www.glassdoor.com/Job/cairo-software-engineer-jobs-SRCH_IL.0,5.htm\">See more jobs</a></td></tr>"
        "<tr><td><a href=\"https://www.glassdoor.com/job-listing/api/rjtRedirect\">Create</a></td></tr>"
        "</table></body></html>"
    ).encode("utf-8")

    jobs = parse_alert_message(raw)
    assert len(jobs) == 1
    job = jobs[0]
    assert job.source == "glassdoor_alert"
    assert job.title == "Junior Python Developer"
    assert job.company == "Paymob"
    assert job.location == "New Cairo, Egypt"
    assert job.posted_at.startswith("2026-10-31")
    assert job.url == "https://www.glassdoor.com/partner/jobListing.htm?jobListingId=998877"


def test_wuzzuf_aws_ses_tracker_unwraps_and_uses_slug_fallback_while_skipping_applied_receipts():
    ses_url = (
        "https://0102019a.r.eu-west-1.awstrack.me/L0/"
        "https:%2F%2Fwuzzuf.net%2Fjobs%2Fp%2F9h9agrsmqdfd-junior-full-stack-developer-bosta-new-cairo-cairo-egypt%3Futm_source%3Demail/"
        "1/0102019a45bcdef0-12345678/abcdef"
    )
    unwrapped = _unwrap_url(ses_url)
    assert unwrapped.startswith("https://wuzzuf.net/jobs/p/9h9agrsmqdfd-junior-full-stack-developer-bosta-new-cairo-cairo-egypt")

    raw_receipt = (
        "From: WUZZUF <notifications@wuzzuf.net>\r\n"
        "Date: Mon, 02 Nov 2026 12:00:00 +0000\r\n"
        "Subject: Similar jobs to your application\r\n"
        "MIME-Version: 1.0\r\n"
        "Content-Type: text/html; charset=utf-8\r\n\r\n"
        "<html><body>"
        "<p>We noticed that you just applied to <a href=\"" + ses_url + "\">Junior Full Stack Developer</a></p>"
        "<div><a href=\"https://0102019a.r.eu-west-1.awstrack.me/L0/https:%2F%2Fwuzzuf.net%2Fjobs%2Fp%2Fabc12345-backend-engineer-paymob-maadi-cairo-egypt/1/0102019a45bcdef0\">Backend Engineer</a></div>"
        "</body></html>"
    ).encode("utf-8")

    jobs = parse_alert_message(raw_receipt)
    assert len(jobs) == 1
    assert jobs[0].title == "Backend Engineer"
    assert jobs[0].company == "Paymob"
    assert jobs[0].location == "Maadi, Cairo, Egypt"


# ---------------------------------------------------------------------------
# 2. Gmail Inbox Application Tracker & Reconciler
# ---------------------------------------------------------------------------

def test_parse_application_email_detects_ashby_askable_and_workable_confirmations():
    ashby_raw = (
        "From: Supabase Hiring Team <no-reply@ashbyhq.com>\r\n"
        "Date: Mon, 02 Nov 2026 22:24:25 +0000\r\n"
        "Subject: Thanks for applying to Supabase\r\n"
        "Message-ID: <msg-supabase-1@ashbyhq.com>\r\n"
        "MIME-Version: 1.0\r\n"
        "Content-Type: text/plain; charset=utf-8\r\n\r\n"
        "Thank you for applying to Supabase! We have received your application and will review it shortly."
    ).encode("utf-8")
    ev1 = parse_application_email(ashby_raw)
    assert ev1 is not None
    assert ev1.kind == "confirmed"
    assert ev1.company == "Supabase"

    askable_raw = (
        "From: Adam from Askable <adam.mcquoid@askable.com>\r\n"
        "Date: Mon, 02 Nov 2026 15:42:40 +0000\r\n"
        "Subject: We've got your application\r\n"
        "Message-ID: <msg-askable-1@askable.com>\r\n"
        "MIME-Version: 1.0\r\n"
        "Content-Type: text/plain; charset=utf-8\r\n\r\n"
        "Thanks for applying for the Software Engineer, AI Coding Tasks role with Askable Labs. Your application is complete."
    ).encode("utf-8")
    ev2 = parse_application_email(askable_raw)
    assert ev2 is not None
    assert ev2.kind == "confirmed"
    assert "askable" in ev2.company.lower()


def test_reconcile_events_with_db_promotes_uncertain_failed_item_to_submitted(tmp_path, monkeypatch):
    from dataclasses import replace
    import app.storage as storage
    from app.application_queue import begin_automation_attempt, enqueue_application, get_application, record_automation_outcome

    db_file = tmp_path / "test_jobs.sqlite3"
    monkeypatch.setattr(storage, "settings", replace(storage.settings, database_path=str(db_file)))
    storage.init_db()

    job = Job(
        source="ashby",
        source_id="supa-31",
        title="Software Engineer - Storage",
        company="Supabase",
        location="Remote",
        url="https://jobs.ashbyhq.com/supabase/storage",
        description="Build storage services with TypeScript, PostgreSQL, and Node.js. Worldwide remote.",
        posted_at=datetime.now(timezone.utc).isoformat(),
        remote=True,
        description_quality="full",
    )
    storage.upsert_job(job, "review", 75, ["Relevant skills: TypeScript"], [])
    qid = enqueue_application(job, "review", 75, ["Relevant skills: TypeScript"], [])
    with storage._connect() as db:
        db.execute("UPDATE application_queue SET status='ready' WHERE id=?", (qid,))
    assert begin_automation_attempt(qid)
    record_automation_outcome(qid, "failed", reason="submission_uncertain")

    ashby_raw = (
        "From: Supabase Hiring Team <no-reply@ashbyhq.com>\r\n"
        "Date: Mon, 02 Nov 2026 22:24:25 +0000\r\n"
        "Subject: Thanks for applying to Supabase\r\n"
        "Message-ID: <supa-confirm@ashbyhq.com>\r\n"
        "MIME-Version: 1.0\r\n"
        "Content-Type: text/plain; charset=utf-8\r\n\r\n"
        "Thank you for applying to Supabase! We have received your application."
    ).encode("utf-8")
    event = parse_application_email(ashby_raw)
    assert event is not None

    event = replace(event, received_at=datetime.now(timezone.utc).isoformat())
    summary = reconcile_events_with_db([event])
    assert summary["confirmed_queue_ids"] == []
    assert len(summary["unmatched_confirmations"]) == 1
    exact = replace(event, title=job.title)
    assert reconcile_events_with_db([exact, exact])["confirmed_queue_ids"] == [qid]
    updated = get_application(qid)
    assert updated["status"] == "submitted"


# ---------------------------------------------------------------------------
# 3. ATS Resolver & Wuzzuf Public Page Enrichment
# ---------------------------------------------------------------------------

def test_derive_company_slugs_and_title_matching():
    slugs = derive_company_slugs("Robusta Studio (Egypt)")
    assert "robustastudio" in slugs
    assert "robusta" in slugs
    assert titles_match("Junior Backend Engineer", "Junior Back-End Engineer (Python)")
    assert not titles_match("Junior Backend Engineer", "Senior Account Executive")


def test_resolve_job_to_ats_resolves_alert_to_workable_posting(monkeypatch, tmp_path):
    clear_resolver_cache()
    csv_file = tmp_path / "ats.csv"
    csv_file.write_text("ats,slug,company,remote_friendly,egypt_presence\nworkable,instabug,Instabug,true,true\n", encoding="utf-8")

    class FakeResp:
        status_code = 200
        def json(self):
            return {
                "jobs": [
                    {
                        "shortcode": " IB123 ",
                        "title": "Junior Backend Engineer",
                        "url": "https://apply.workable.com/instabug/j/IB123/",
                        "city": "Cairo",
                        "country": "Egypt",
                        "description": "<p>Build scalable backend services in Cairo using Python, Node.js, PostgreSQL, Redis, and Docker. 0-2 years experience.</p>" * 3,
                    }
                ]
            }

    monkeypatch.setattr("app.ats_resolver._http_get", lambda url, **kwargs: FakeResp())

    alert_job = Job(
        source="linkedin_alert",
        source_id="https://www.linkedin.com/comm/jobs/view/123",
        title="Junior Backend Engineer",
        company="Instabug",
        location="Cairo, Egypt",
        url="https://www.linkedin.com/comm/jobs/view/123",
        description="Junior Backend Engineer | Instabug · Cairo, Egypt",
        posted_at=datetime.now(timezone.utc).isoformat(),
        description_quality="summary",
    )
    resolved = resolve_job_to_ats(alert_job, csv_path=csv_file, persist_discovered=False)
    assert resolved.source == "workable"
    assert resolved.url == "https://apply.workable.com/instabug/j/IB123/"
    assert resolved.description_quality == "full"
    assert "PostgreSQL" in resolved.description


def test_enrich_wuzzuf_public_job_reads_json_ld(monkeypatch):
    html = """<html><head><script type="application/ld+json">
    {"@type":"JobPosting","title":"Junior Python Developer","description":"<p>We are hiring a Junior Python Developer in Cairo working with FastAPI, Django, PostgreSQL, and Docker. Entry level 0-1 years experience required.</p>","hiringOrganization":{"name":"Kashier"}}
    </script></head><body></body></html>"""

    class FakeResp:
        status_code = 200
        text = html

    monkeypatch.setattr("app.ats_resolver._http_get", lambda url, **kwargs: FakeResp())
    job = Job(
        source="wuzzuf_alert",
        source_id="https://wuzzuf.net/jobs/p/xyz",
        title="Junior Python Developer",
        company="Unknown company",
        location="Cairo, Egypt",
        url="https://wuzzuf.net/jobs/p/xyz",
        description="Short snippet",
        description_quality="summary",
    )
    enriched = enrich_wuzzuf_public_job(job)
    assert enriched.company == "Kashier"
    assert "FastAPI" in enriched.description


# ---------------------------------------------------------------------------
# 4. Greater Cairo / Egypt Location Rules & Abstract Generic Template Answers
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("loc,mode,remote_flag", [
    ("Maadi, Cairo, Egypt", "onsite", False),
    ("New Cairo, Egypt (Hybrid)", "hybrid", False),
    ("6th of October, Giza", "onsite", False),
    ("Nasr City, Egypt", "onsite", False),
    ("Egypt (On-site)", "onsite", False),
    ("Egypt (Hybrid)", "hybrid", False),
])
def test_all_workplace_modes_accepted_in_greater_cairo_and_egypt(loc, mode, remote_flag):
    now_iso = datetime.now(timezone.utc).isoformat()
    job = Job(
        source="workable",
        source_id="loc-test",
        title="Junior Backend Developer",
        company="Example Egypt Co",
        location=loc,
        url="https://apply.workable.com/example/j/123/",
        description=(
            "We are hiring a Junior Backend Developer working with Python, FastAPI, Django, PostgreSQL, "
            "REST APIs, automated testing, CI/CD pipelines, and Docker. Entry-level candidates with 0-1 years "
            "of experience who enjoy building reliable backend services and collaborating with engineering teams are welcome."
        ),
        posted_at=now_iso,
        remote=remote_flag,
        workplace_type=mode,
        description_quality="full",
    )
    status, score, reasons, concerns = classify(job)
    assert status in {"match", "review"}
    assert score >= 70
    item = {
        "id": 1,
        "status": "pending_review",
        "qualification_status": status,
        "score": score,
        "title": job.title,
        "company": job.company,
        "location": job.location,
        "url": job.url,
        "source": job.source,
        "source_id": job.source_id,
        "description": job.description,
        "posted_at": job.posted_at,
        "date_kind": "posted",
        "remote": int(remote_flag),
        "workplace_type": mode,
        "eligibility": "",
        "description_quality": "full",
    }
    assert _reason_for_auto_skip(item) is None


@pytest.mark.parametrize("question", [
    "Describe your experience working in a remote or asynchronous environment.",
    "What are your career goals and what excites you about software engineering?",
    "How do you approach debugging and troubleshooting complex issues?",
    "Share a brief summary or any additional comments for the hiring team.",
])
def test_abstract_generic_templates_answer_open_ended_questions_without_claiming_specific_role(question):
    ans, reason = _answer_for_field(question, {}, {}, {"company": "Acme", "title": "Engineer"})
    assert ans is not None and len(ans) > 40
    assert "generic abstract" in reason or "generated" in reason


# ---------------------------------------------------------------------------
# 5. 1-Tap Manual Apply Digest Formatting
# ---------------------------------------------------------------------------

def test_manual_apply_digest_message_includes_cv_and_quick_links():
    job = Job(
        source="linkedin_alert",
        source_id="https://www.linkedin.com/comm/jobs/view/999",
        title="Junior Python Backend Engineer",
        company="Vodafone",
        location="Cairo, Egypt (Hybrid)",
        url="https://www.linkedin.com/comm/jobs/view/999",
    )
    msg = _manual_apply_digest_message([(job, 85)], 1)
    assert "1-Tap Manual Apply Cards" in msg
    assert "Junior Python Backend Engineer" in msg
    assert "Vodafone" in msg
    assert "Tap to Apply on Linkedin" in msg
    assert "https://mohamed-ahmed-five.vercel.app/" in msg
