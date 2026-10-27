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
