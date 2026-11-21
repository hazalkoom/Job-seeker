from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import pytest

import app.application_automation as aa
from app.application_profile import load_profile_bundle
from app.application_queue import (
    company_submitted_count_last_30_days,
    enqueue_application,
    get_application,
    prioritize_queue_items,
    record_automation_outcome,
)
from app.ats_resolver import classify_apply_path, extract_ats_from_url
from app.cover_letter import build_generic_cover_letter_text, generate_generic_cover_letter_pdf
from app.funnel import (
    FunnelTracker,
    format_pending_questions_telegram_digest,
    list_pending_questions,
    record_unanswered_question,
)
from app.jobhunter_cli import main as cli_main
from app.matching import classify
from app.models import Job
from app.sources.email_alerts import parse_alert_message as _parse_alert_message
from app.sources.hn_jobs import parse_hn_comment
from app.storage import init_db, upsert_job
from app.tools.discover import extract_ats_links_from_html


@pytest.fixture()
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "test_round4.sqlite3"
    monkeypatch.setattr("app.config.settings", aa.settings)
    monkeypatch.setenv("DATABASE_PATH", str(db_file))
    object.__setattr__(aa.settings, "database_path", str(db_file))
    init_db()
    return db_file


def _make_job(
    *,
    title: str = "Junior Backend Engineer",
    company: str = "Canonical",
    location: str = "Remote",
    url: str = "https://boards.greenhouse.io/canonical/jobs/12345",
    source: str = "greenhouse:canonical",
    description: str = (
        "Build backend services using Python, Django, FastAPI, PostgreSQL, and Docker. "
        "Collaborate with distributed engineering teams to design REST APIs and write automated tests. " * 3
    ),
    remote: bool = True,
) -> Job:
    return Job(
        source=source,
        source_id=url,
        title=title,
        company=company,
        location=location,
        url=url,
        description=description,
        posted_at=(datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),
        date_kind="posted",
        remote=remote,
        employment_type="Full-time",
        workplace_type="remote" if remote else "onsite",
        eligibility="",
        description_quality="full",
    )


def test_classify_apply_path_and_queue_prioritization():
    assert classify_apply_path("https://boards.greenhouse.io/canonical/jobs/1") == "direct_ats"
    assert classify_apply_path("https://jobs.ashbyhq.com/supabase/abc") == "direct_ats"
    assert classify_apply_path("https://www.linkedin.com/jobs/view/123", "linkedin_alert") == "login_gated"
    assert classify_apply_path("https://wuzzuf.net/jobs/p/123", "wuzzuf_alert") == "login_gated"
    assert classify_apply_path("https://startup.jobs/backend-dev-123", "rss:startup") == "aggregator_redirect"
    assert classify_apply_path("https://himalayas.app/jobs/acme/dev", "himalayas") == "aggregator_redirect"

    items = [
        {"id": 1, "url": "https://startup.jobs/role-1", "source": "rss:startup", "score": 95},
        {"id": 2, "url": "https://www.linkedin.com/jobs/view/2", "source": "linkedin_alert", "score": 90},
        {"id": 3, "url": "https://boards.greenhouse.io/canonical/jobs/3", "source": "greenhouse:canonical", "score": 75},
        {"id": 4, "url": "https://jobs.ashbyhq.com/thndr/4", "source": "ashby:thndr", "score": 88},
    ]
    ordered = prioritize_queue_items(items)
    assert [i["id"] for i in ordered] == [4, 3, 1, 2]


def test_question_ledger_records_and_formats_telegram_digest(temp_db, tmp_path, monkeypatch):
    pending_json = tmp_path / "pending_questions.json"
    monkeypatch.setattr("app.funnel.PENDING_QUESTIONS_JSON", pending_json)

    key = record_unanswered_question(
        question_text="In which country do you currently work?",
        field_type="select",
        field_name="question_991",
        html_snippet='<select id="question_991" required><option>Egypt (Cairo)</option></select>',
        options=["Egypt (Cairo)", "United Kingdom"],
        ats_host="boards.greenhouse.io",
        job_url="https://boards.greenhouse.io/canonical/jobs/1",
        company="Canonical",
        queue_id=10,
    )
    assert key
    # Record a second occurrence
    record_unanswered_question(
        question_text="In which country do you currently work?",
        field_type="select",
        field_name="question_991",
        options=["Egypt (Cairo)", "United Kingdom"],
        ats_host="boards.greenhouse.io",
        company="Canonical",
    )
    pending = list_pending_questions()
    assert len(pending) == 1
    assert pending[0]["occurrences"] == 2
    assert "Egypt (Cairo)" in pending[0]["options"]
    assert pending_json.is_file()

    digest = format_pending_questions_telegram_digest(pending)
    assert "Questions Needed" in digest
    assert "In which country do you currently work?" in digest
    assert "Canonical" in digest


def test_funnel_tracker_computes_stage_breakdown():
    tracker = FunnelTracker(fetched_total=120, deduped_total=100)
    tracker.record_classification("greenhouse:canonical", "match", [])
    tracker.record_classification("rss:startup", "reject", ["Mandatory experience requirement exceeds target."])
    tracker.record_apply_path("greenhouse:canonical", "direct_ats", resolved=False)
    tracker.ingest_auto_apply_report(
        {
            "processed": 1,
            "submitted": 1,
            "skipped": 0,
            "failed": 0,
            "results": [{"source": "greenhouse:canonical", "outcome": "submitted", "filled_count": 6}],
        }
    )
    summary = tracker.to_dict()
    assert summary["matched_total"] == 1
    assert summary["rejected_total"] == 1
    assert summary["submitted_total"] == 1
    assert any("Path breakdown" in line for line in tracker.format_telegram_summary_lines())


def test_multi_currency_12k_egp_compensation():
    fixtures = Path(__file__).with_name("fixtures")
    bundle = load_profile_bundle(fixtures / "candidate.json", fixtures / "answers.json")
    profile, bank = bundle.profile, bundle.answer_bank
    item = {"title": "Backend Engineer", "company": "Acme"}

    assert aa._answer_for_field("What are your monthly salary expectations in USD?", profile, bank, item)[0] == "222.44"
    assert aa._answer_for_field("Expected annual compensation in USD", profile, bank, item)[0] == "2669"
    assert aa._answer_for_field("Expected monthly salary in EUR", profile, bank, item)[0] == "198.20"
    assert aa._answer_for_field("Expected annual salary in EUR", profile, bank, item)[0] == "2378"
    assert aa._answer_for_field("Desired monthly salary in GBP (£)", profile, bank, item)[0] == "165.35"
    assert aa._answer_for_field("Desired annual salary in British Pounds (GBP)", profile, bank, item)[0] == "1984"
    assert aa._answer_for_field("Monthly salary expectation in Japanese Yen (JPY)", profile, bank, item)[0] == "35227"
    assert aa._answer_for_field("Annual salary expectation in JPY", profile, bank, item)[0] == "422724"
    assert aa._answer_for_field("Expected monthly salary in EGP", profile, bank, item)[0] == "12000"
    assert aa._answer_for_field("Expected annual salary in EGP", profile, bank, item)[0] == "144000"


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("How many years of Python experience do you have?", "3"),
        ("How many years of experience with Django?", "2"),
        ("Years of experience with FastAPI", "1"),
        ("How many years of JavaScript experience?", "3"),
        ("How many years of experience do you have in TypeScript?", "2"),
        ("Years of Angular experience", "2"),
        ("How many years of React experience?", "1"),
        ("How many years of PostgreSQL experience?", "2"),
        ("How many years of Docker experience?", "2"),
        ("How many years of Linux experience?", "2"),
        ("How many years of Git experience?", "2"),
        ("How many years of QA experience?", "1"),
        ("How many years of Kubernetes experience?", "1"),
        ("How many years of Rust experience do you have?", "0"),
        ("How many years of Ruby on Rails experience?", "0"),
    ],
)
def test_per_skill_years_table(question: str, expected: str):
    fixtures = Path(__file__).with_name("fixtures")
    bundle = load_profile_bundle(fixtures / "candidate.json", fixtures / "answers.json")
    ans, _ = aa._answer_for_field(question, bundle.profile, bundle.answer_bank, {"title": "Dev", "company": "X"})
    assert ans == expected


def test_canonical_and_contractor_specific_answers():
    fixtures = Path(__file__).with_name("fixtures")
    bundle = load_profile_bundle(fixtures / "candidate.json", fixtures / "answers.json")
    profile, bank = bundle.profile, bundle.answer_bank
    item = {"title": "Software Engineer (Contract)", "company": "Canonical", "employment_type": "Contract"}

    country_ans, _ = aa._answer_for_field("In which country do you currently work?", profile, bank, item)
    assert country_ans == "Egypt (Cairo)"

    deg_ans, _ = aa._answer_for_field(
        "Please confirm that your first university degree (bachelor or undergrad) completed",
        profile,
        bank,
        item,
    )
    assert deg_ans == "Yes"

    auth_ans, _ = aa._answer_for_field(
        "Are you legally authorized to work remotely as an independent contractor?",
        profile,
        bank,
        item,
    )
    assert auth_ans == "Yes"


def test_hard_exclusions_and_egypt_hiring_companies(monkeypatch):
    monkeypatch.delenv("ALLOW_UNSPECIFIED_REMOTE", raising=False)

    # .NET / Ruby / French requirements are rejected
    dotnet_job = _make_job(title="Junior .NET Backend Developer", company="Canonical")
    assert classify(dotnet_job)[0] == "reject"

    ruby_job = _make_job(title="Junior Ruby on Rails Engineer", company="Canonical")
    assert classify(ruby_job)[0] == "reject"

    french_job = _make_job(
        title="Junior Python Developer",
        company="Canonical",
        description="Build Python APIs. Must be fluent in French and English. " * 4,
    )
    assert classify(french_job)[0] == "reject"

    # Known Egypt-hiring company with generic "Remote" location is accepted even when ALLOW_UNSPECIFIED_REMOTE is unset
    canonical_remote = _make_job(title="Junior Python Engineer", company="Canonical", location="Remote")
    status, score, reasons, concerns = classify(canonical_remote)
    assert status in {"match", "review"}
    assert any("employer hires in Egypt" in r for r in reasons)
    assert not any("does not confirm" in c for c in concerns)


def test_per_company_30_day_cap_skips_third_application(temp_db):
    j1 = _make_job(url="https://boards.greenhouse.io/canonical/jobs/101")
    j2 = _make_job(url="https://boards.greenhouse.io/canonical/jobs/102")
    j3 = _make_job(url="https://boards.greenhouse.io/canonical/jobs/103")
    upsert_job(j1, "match", 85, ["ok"], [])
    upsert_job(j2, "match", 85, ["ok"], [])
    upsert_job(j3, "match", 85, ["ok"], [])
    q1 = enqueue_application(j1, "match", 85, ["ok"], [])
    q2 = enqueue_application(j2, "match", 85, ["ok"], [])
    q3 = enqueue_application(j3, "match", 85, ["ok"], [])
    q3_item = get_application(q3)

    record_automation_outcome(q1, "submitted", reason="ok")
    record_automation_outcome(q2, "submitted", reason="ok")

    assert company_submitted_count_last_30_days("Canonical") == 2
    skip_reason = aa._reason_for_auto_skip(q3_item)
    assert skip_reason is not None
    assert "Company cap reached" in skip_reason


def test_generic_pdf_cover_letter_generation(tmp_path):
    fixtures = Path(__file__).with_name("fixtures")
    bundle = load_profile_bundle(fixtures / "candidate.json", fixtures / "answers.json")
    item = {"title": "Backend Engineer", "company": "Canonical"}
    text = build_generic_cover_letter_text(bundle.profile, item)
    assert "Example Applicant" in text
    assert "Java" not in text

    pdf_path = generate_generic_cover_letter_pdf(bundle.profile, item, output_dir=tmp_path)
    assert pdf_path.is_file()
    raw = pdf_path.read_bytes()
    assert raw.startswith(b"%PDF-1.4")
    assert b"%%EOF" in raw


def test_email_alerts_ignores_application_confirmation_receipts():
    raw_receipt = (
        b"From: Indeed Apply <indeedapply@indeed.com>\r\n"
        b"Subject: Indeed Application: Full Stack Engineer\r\n"
        b"Content-Type: text/html; charset=utf-8\r\n\r\n"
        b"<html><body><h1>Application submitted</h1>"
        b"<p>Your application was sent to Acme Corp.</p>"
        b"<a href='https://www.indeed.com/viewjob?jk=12345'>Full Stack Engineer</a>"
        b"</body></html>"
    )
    assert _parse_alert_message(raw_receipt) == []


def test_hn_jobs_parser_and_ats_html_extractor():
    comment = {
        "objectID": "998877",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "comment_text": (
            "AcmeAI | Junior Python Backend Engineer | Remote (Worldwide) | Full-time<p>"
            "We build developer tools using Python, FastAPI, PostgreSQL, and Docker. "
            "Apply directly at https://jobs.ashbyhq.com/supabase/12345-abcd"
        ),
    }
    job = parse_hn_comment(comment)
    assert job is not None
    assert job.company == "AcmeAI"
    assert "ashbyhq.com/supabase" in job.url

    html_sample = """
    <html><body>
      <a href="https://boards.greenhouse.io/canonical/jobs/111">Apply on Greenhouse</a>
      <iframe src="https://jobs.ashbyhq.com/thndr"></iframe>
      <a href="https://acme.recruitee.com/o/backend-dev">Recruitee</a>
    </body></html>
    """
    links = extract_ats_links_from_html(html_sample, default_company="TestCo")
    found_pairs = {(d["ats"], d["slug"]) for d in links}
    assert ("greenhouse", "canonical") in found_pairs
    assert ("ashby", "thndr") in found_pairs
    assert ("recruitee", "acme") in found_pairs
    assert extract_ats_from_url("https://acme.bamboohr.com/careers/12") == ("bamboohr", "acme")
    assert extract_ats_from_url("https://acme.breezy.hr/p/123") == ("breezy", "acme")


def test_cli_subcommands_run_cleanly(temp_db, tmp_path, capsys):
    out_html = tmp_path / "dash.html"
    assert cli_main(["audit", "funnel"]) == 0
    assert cli_main(["questions", "gaps"]) == 0
    assert cli_main(["report", "html", "--output", str(out_html)]) == 0
    assert out_html.is_file()
    captured = capsys.readouterr().out
    assert "Funnel Audit" in captured


def test_no_captcha_bypass_or_stealth_packages_in_repo():
    root = Path(__file__).resolve().parent.parent
    req = (root / "requirements.txt").read_text(encoding="utf-8").lower()
    forbidden = ("2captcha", "anticaptcha", "capmonster", "playwright-stealth", "puppeteer-extra-plugin-stealth", "cf_clearance")
    for pkg in forbidden:
        assert pkg not in req
