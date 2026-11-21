from datetime import datetime, timedelta, timezone

from app.application_automation import _is_supported_host, _reason_for_auto_skip
from app.matching import _himalayas_eligibility_decision


def _job(**overrides):
    posted = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    description = (
        "We are looking for a Junior Backend Developer to build and maintain APIs. "
        "You will work with Node.js, Express, REST APIs, PostgreSQL, tests, and CI/CD. "
        "The role is remote worldwide and candidates may work from anywhere in the world. "
        "Applicants can work from Egypt. We welcome early-career candidates who enjoy "
        "learning, collaborating, and shipping reliable software. No more than two years "
        "of professional experience is required for this role."
    )
    item = {
        "id": 1,
        "status": "pending_review",
        "qualification_status": "match",
        "score": 90,
        "title": "Junior Backend Developer",
        "company": "Example Co",
        "location": "Remote worldwide",
        "url": "https://jobs.lever.co/example/abc123",
        "source": "test",
        "source_id": "abc123",
        "description": description,
        "posted_at": posted,
        "date_kind": "posted",
        "remote": 1,
        "employment_type": "Full time",
        "workplace_type": "remote",
        "eligibility": "",
        "description_quality": "full",
    }
    item.update(overrides)
    return item


def test_auto_policy_accepts_fresh_full_remote_role_confirmed_for_egypt():
    assert _reason_for_auto_skip(_job()) is None


def test_auto_policy_skips_updated_only_posting_even_if_recent_update():
    reason = _reason_for_auto_skip(_job(date_kind="updated"))
    assert reason and "original publication date" in reason


def test_auto_policy_skips_remote_role_with_unclear_egypt_eligibility():
    description = (
        "We are looking for a Junior Backend Developer. Work with Node.js and Express "
        "to maintain APIs and databases. Collaborate with engineering teams and write "
        "tests. This role is remote and supports a distributed team. Please read all "
        "requirements before applying. The team ships software and maintains services."
    )
    reason = _reason_for_auto_skip(_job(description=description, location="Remote", remote=1))
    assert reason and "egypt" in reason.casefold()


def test_auto_policy_skips_mandatory_experience_above_two_years():
    description = _job()["description"] + " Applicants must have at least 4 years of experience."
    reason = _reason_for_auto_skip(_job(description=description))
    assert reason and "experience" in reason.lower()


def test_auto_policy_skips_summary_only_job():
    reason = _reason_for_auto_skip(_job(description_quality="summary"))
    assert reason and "Full employer description" in reason


def test_ats_host_allowlist_is_domain_aware():
    assert _is_supported_host("jobs.lever.co")
    assert _is_supported_host("job-boards.greenhouse.io")
    assert _is_supported_host("wd5.myworkdayjobs.com")
    assert not _is_supported_host("fakelever.co.evil.example")
    assert not _is_supported_host("example.com")


def test_himalayas_restricted_country_list_does_not_pass_egypt_gate():
    import json
    value = "himalayas:v1:" + json.dumps({
        "locationRestrictionsPresent": True,
        "locationRestrictions": [{"name": "Portugal", "alpha2": "PT"}],
        "timezoneRestrictionsPresent": True,
        "timezoneRestrictions": [],
    })
    verdict, evidence = _himalayas_eligibility_decision(value)
    assert verdict == "blocked"
    assert "exclude Egypt" in evidence


def test_auto_policy_skips_unavailable_employer_form_without_auto_approval():
    from app.application_automation import _is_supported_host

    assert not _is_supported_host("careers.example.org")


def test_auto_policy_accepts_score_65_after_lowering_autopilot_floor(monkeypatch):
    from dataclasses import replace
    import app.application_automation as automation

    monkeypatch.setattr(automation, "settings", replace(automation.settings, auto_apply_min_score=60))
    assert automation._reason_for_auto_skip(_job(score=65)) is None


def test_dedicated_ai_engineer_role_is_excluded_from_automation_scope():
    reason = _reason_for_auto_skip(_job(title="AI Engineer"))
    assert reason and "AI/ML role" in reason


def test_ai_integration_role_is_not_excluded_by_dedicated_ai_gate():
    reason = _reason_for_auto_skip(_job(title="Customs AI Integration & Automation Engineer"))
    assert not (reason and "Dedicated AI/ML role" in reason)


def test_unpaid_internship_is_not_auto_applied():
    description = _job()["description"] + " Internship Details: Stipend: None initially."
    reason = _reason_for_auto_skip(_job(title="Backend Engineer Internship", description=description))
    assert reason and "Unpaid internship" in reason


def test_custom_public_application_target_is_candidate_but_aggregator_signup_is_not():
    from app.application_automation import _is_explicit_application_target, _is_aggregator_host

    assert _is_explicit_application_target(
        "https://careers.example.org/jobs/123/apply",
        "https://jobs.example.net/job/123",
        "Apply now",
    )
    assert not _is_explicit_application_target(
        "https://himalayas.app/signup/talent?redirect=%2Fjob",
        "https://himalayas.app/companies/example/jobs/123",
        "Apply now",
    )
    assert _is_aggregator_host("www.himalayas.app")


def test_himalayas_signup_apply_route_is_classified_as_account_required():
    from app.application_automation import _job_board_requires_account

    diagnostics = {"apply_links": [{
        "host": "himalayas.app", "path": "/signup/talent", "text": "Apply now"
    }]}
    assert _job_board_requires_account("himalayas.app", diagnostics)
    assert not _job_board_requires_account("careers.example.org", diagnostics)


def test_jobposting_jsonld_extraction_and_title_overlap():
    from app.application_automation import _iter_job_postings, _meaningful_title_overlap

    data = {"@graph": [{"@type": "Organization", "name": "Example"}, {
        "@type": "JobPosting", "title": "Junior Backend Developer",
        "description": "<p>Build APIs and web services.</p>",
        "hiringOrganization": {"name": "Example Co"},
    }]}
    posting = next(_iter_job_postings(data))
    assert posting["title"] == "Junior Backend Developer"
    assert _meaningful_title_overlap("Junior Backend Developer", posting["title"])
    assert not _meaningful_title_overlap("Frontend Engineer", "Senior Finance Manager")


def test_public_listing_enrichment_skips_unverified_date_without_request(monkeypatch):
    import app.application_automation as automation

    def fail_client(*args, **kwargs):
        raise AssertionError("network should not be called for unverified posting dates")

    monkeypatch.setattr(automation.httpx, "Client", fail_client)
    item, diagnostics = automation._enrich_public_listing({
        "id": 1, "job_id": 1, "title": "Junior Developer",
        "url": "https://example.com/job", "description_quality": "summary",
        "date_kind": "updated", "posted_at": "2026-10-26",
    })
    assert item["description_quality"] == "summary"
    assert diagnostics["result"] == "original_posting_date_unverified"
    assert not diagnostics["attempted"]


def test_public_listing_enrichment_accepts_matching_jobposting_jsonld(monkeypatch):
    import app.application_automation as automation

    description = "Build and maintain REST APIs with Python, Django, PostgreSQL, Docker, tests, monitoring, and CI/CD. " * 6
    html = """<html><head><title>Junior Backend Developer at Example Co</title>
    <script type="application/ld+json">{"@type":"JobPosting","title":"Junior Backend Developer","description":"%s","datePosted":"2026-10-26T09:00:00Z","hiringOrganization":{"name":"Example Co"}}</script>
    </head><body><main>Junior Backend Developer</main></body></html>""" % description

    class FakeResponse:
        status_code = 200
        url = "https://careers.example.org/jobs/1"
        text = html

    class FakeClient:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def get(self, url): return FakeResponse()

    monkeypatch.setattr(automation.httpx, "Client", FakeClient)
    monkeypatch.setattr(automation, "_persist_listing_enrichment", lambda item: None)
    item, diagnostics = automation._enrich_public_listing({
        "id": 9, "job_id": 9, "title": "Junior Backend Developer",
        "company": "Unknown company", "source": "rss:test",
        "url": "https://careers.example.org/jobs/1", "description": "Python role.",
        "description_quality": "summary", "date_kind": "posted",
        "posted_at": "2026-10-26T09:00:00+00:00",
    })
    assert diagnostics["result"] == "enriched"
    assert item["description_quality"] == "full"
    assert len(item["description"]) > 180
    assert item["company"] == "Example Co"
    assert item["posted_at"].startswith("2026-10-26")


def test_location_answer_handles_plain_country_label():
    from app.application_automation import _location_answer

    profile = {"identity": {"country": "Egypt", "city": "Cairo"}}
    assert _location_answer("Country", profile) == "Egypt"
    assert _location_answer("Country*", profile) == "Egypt"
    assert _location_answer("Country of Residence", profile) == "Egypt"
    assert _location_answer("Are you authorized to work in this country?", profile) is None


def test_select_cv_for_job_routes_to_tailored_cvs(tmp_path, monkeypatch):
    from app import application_automation as automation
    from scripts.generate_tailored_cvs import CV_SPECS

    monkeypatch.setattr(automation, "ROOT", tmp_path)
    (tmp_path / "cvs").mkdir()
    for spec in CV_SPECS:
        (tmp_path / "cvs" / spec["filename"]).write_bytes(b"%PDF-1.4")
    _select_cv_for_job = automation._select_cv_for_job

    assert _select_cv_for_job({"title": "Python Django Backend Developer", "description": "Django REST"}) .name == "Mohamed_Ahmed-Backend_Django.pdf"
    assert _select_cv_for_job({"title": "Developer Support Engineer", "description": "APIs"}) .name == "Mohamed_Ahmed-Developer_Support.pdf"
    assert _select_cv_for_job({"title": "Junior Software Engineer", "description": "Python TypeScript"}) .name == "Mohamed_Ahmed-Junior_Software_Engineer.pdf"
    assert _select_cv_for_job({"title": "React Frontend Developer", "description": "React Next.js"}) .name == "Mohamed_Ahmed-React_Developer.pdf"


def test_playwright_greenhouse_react_select_country_degree_and_hidden_privacy(tmp_path):
    from playwright.sync_api import sync_playwright
    from app.application_automation import _dismiss_cookie_banner, _fill_form

    html = """
    <html><body>
      <div data-ui="cookie-consent">
        <p>This website uses cookies to improve your experience.</p>
        <button type="button">Decline all</button>
      </div>
      <form>
        <div class="field-wrapper">
          <label for="country_input">Country*</label>
          <div class="select__control" onclick="document.getElementById('country_opts').style.display='block'">
            <input id="country_input" class="select__input" role="combobox" aria-required="true" />
            <input type="text" aria-hidden="true" required style="opacity:0;width:1px" />
          </div>
          <div id="country_opts" style="display:none">
            <div role="option" onclick="document.getElementById('country_input').value='Egypt';this.parentElement.style.display='none'">Egypt</div>
            <div role="option" onclick="document.getElementById('country_input').value='Egypt (EG)';this.parentElement.style.display='none'">Egypt (EG)</div>
          </div>
        </div>
        <div class="field-wrapper">
          <label for="deg_input">Please confirm that your first university degree (bachelor or undergrad) completed, or is expected to complete*</label>
          <div class="select__control" onclick="document.getElementById('deg_opts').style.display='block'">
            <input id="deg_input" class="select__input" role="combobox" aria-required="true" />
          </div>
          <div id="deg_opts" style="display:none">
            <div role="option" onclick="document.getElementById('deg_input').value='Yes, completed';this.parentElement.style.display='none'">Yes, completed</div>
            <div role="option" onclick="document.getElementById('deg_input').value='Yes, expected to complete';this.parentElement.style.display='none'">Yes, expected to complete</div>
          </div>
        </div>
        <div>
          <label style="display:none">Candidate Privacy Notice*
            <input type="checkbox" required style="display:none" />
          </label>
        </div>
        <button type="submit">Submit Application</button>
      </form>
    </body></html>
    """
    profile = {"identity": {"full_name": "Mohamed Ahmed", "email": "m@example.com", "phone": "+201000000000", "city": "Cairo", "country": "Egypt"}}
    bank = {"answers": {"first_university_degree_completed": {"answer": "Yes"}}}
    resume = tmp_path / "cv.pdf"
    resume.write_bytes(b"%PDF-1.4\n")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_content(html)
        assert _dismiss_cookie_banner(page) == "declined"
        form = page.locator("form").first
        blockers, filled = _fill_form(form, profile, bank, {"company": "Canonical", "title": "Software Engineer"}, resume)
        browser.close()

    assert blockers == []
    assert any("Country" in f for f in filled)
    assert any("first university degree" in f.lower() for f in filled)
    assert any("consent:" in f for f in filled)
