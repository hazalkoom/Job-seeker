from app.referrals import build_referral_draft, contact_search_links


def test_referral_draft_is_personalized_and_does_not_send_anything():
    job = {
        "title": "Junior Backend Engineer",
        "company": "Example Co",
        "url": "https://example.com/jobs/123",
        "description": "Python APIs",
        "reasons": '["Relevant skills: Python, Django, Node.js / Express"]',
    }
    contact = {"name": "Ada Lovelace", "company": "Example Co", "role": "Software Engineer"}
    draft = build_referral_draft(job, contact)
    assert draft.startswith("Hi Ada,")
    assert "Junior Backend Engineer" in draft
    assert "Example Co" in draft
    assert "Python, Django, Node.js / Express" in draft
    assert "No worries at all if not" in draft
    assert "https://example.com/jobs/123" in draft


def test_referral_draft_does_not_assume_a_contact_is_a_referrer():
    draft = build_referral_draft(
        {"title": "Graduate Developer", "company": "Example Co", "url": "https://example.com/j", "reasons": "[]"},
        {"name": "Sam Example", "company": "Example Co", "role": "Recruiter"},
    )
    assert "whether you might be comfortable" in draft
    assert "referring me" in draft


def test_contact_search_links_are_manual_searches():
    links = contact_search_links("Example Co")
    assert "linkedin.com/search/results/people" in links["linkedin_people_search"]
    assert "site%3Alinkedin.com" in links["google_public_profiles"]
    assert "scrape" not in " ".join(links.values()).lower()


def test_referral_draft_includes_linkedin_separately_from_portfolio_and_cv(monkeypatch):
    from types import SimpleNamespace
    import app.referrals as referrals

    monkeypatch.setattr(referrals, "settings", SimpleNamespace(
        candidate_summary="Backend developer familiar with Python and Node.js.",
        candidate_display_name="Mohamed Ahmed Mahmoud",
        candidate_linkedin_url="https://www.linkedin.com/in/example-profile/",
        candidate_portfolio_url="https://example.dev/",
        candidate_cv_url="https://drive.google.com/file/d/example/view",
    ))
    draft = referrals.build_referral_draft(
        {"title": "Junior Backend Engineer", "company": "Example Co", "url": "https://example.com/job", "reasons": "[]"},
        {"name": "Ada Lovelace", "company": "Example Co", "role": "Software Engineer"},
    )
    assert "LinkedIn: https://www.linkedin.com/in/example-profile/" in draft
    assert "Portfolio: https://example.dev/" in draft
    assert "CV: https://drive.google.com/file/d/example/view" in draft
