"""Tests for Round 6: calibrated 0-100 job scoring, React-Select DOM-shift resilience,
Canonical screening coverage, and clean hybrid Telegram Job Cards.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.matching import classify
from app.models import Job
import app.application_automation as aa
import app.runner as runner


def _make_job(**overrides) -> Job:
    data = dict(
        source="test",
        source_id="round6-1",
        title="Junior Node.js Backend Developer",
        company="Example Co",
        location="Cairo, Egypt",
        url="https://boards.greenhouse.io/example/jobs/1",
        description=(
            "Entry-level Junior Backend Developer working with Node.js, Express, "
            "TypeScript, PostgreSQL, and Docker. 0-1 years of experience."
        ),
        posted_at=datetime.now(timezone.utc).isoformat(),
        remote=False,
        employment_type="Full-time",
        workplace_type="onsite",
        eligibility="Egypt",
        description_quality="full",
    )
    data.update(overrides)
    return Job(**data)


# ---------------------------------------------------------------------------
# 1. Calibrated 0-100 Job Scoring & Strict Exclusions
# ---------------------------------------------------------------------------


def test_calibrated_scoring_thrive_backend_roles_reach_90_to_100():
    nodejs_job = _make_job(
        title="Junior Node.js Backend Developer",
        location="Cairo, Egypt",
        description=(
            "Junior backend engineer using Node.js, Express, TypeScript, "
            "PostgreSQL, Redis, Docker, and Linux. 0-1 years experience."
        ),
    )
    status_node, score_node, reasons_node, concerns_node = classify(nodejs_job)
    assert status_node == "match"
    assert not concerns_node
    assert 90 <= score_node <= 100
    assert any("Node.js" in r for r in reasons_node)

    python_job = _make_job(
        title="Junior Python Backend Engineer",
        location="Worldwide",
        remote=True,
        workplace_type="remote",
        eligibility="Worldwide; work from anywhere",
        description=(
            "Junior backend role building REST APIs with Python, FastAPI, Django, "
            "PostgreSQL, and Redis. 0-1 years experience."
        ),
    )
    status_py, score_py, _, concerns_py = classify(python_job)
    assert status_py == "match"
    assert not concerns_py
    assert 90 <= score_py <= 100


def test_calibrated_scoring_angular_fullstack_beats_react_fullstack():
    angular_job = _make_job(
        title="Junior Full-Stack Developer (Angular & Node.js)",
        description=(
            "Junior full-stack developer building web apps with Angular, TypeScript, "
            "Node.js, Express, PostgreSQL, and Docker. Entry-level."
        ),
    )
    react_job = _make_job(
        title="Junior Full-Stack Developer (React & Node.js)",
        description=(
            "Junior full-stack developer building web apps with React, TypeScript, "
            "Node.js, Express, PostgreSQL, and Docker. Entry-level."
        ),
    )
    status_ng, score_ng, _, _ = classify(angular_job)
    status_re, score_re, _, _ = classify(react_job)

    assert status_ng == "match"
    assert status_re == "match"
    assert 85 <= score_ng <= 95
    assert 75 <= score_re <= 85
    assert score_ng > score_re


def test_calibrated_scoring_technical_support_is_bounded_65_to_78():
    support_job = _make_job(
        title="Junior Technical Support Engineer",
        description=(
            "Junior technical support engineer troubleshooting customer APIs, "
            "writing SQL queries, and debugging Linux environments. 0-1 years experience."
        ),
    )
    status, score, _, concerns = classify(support_job)
    assert status == "match"
    assert not concerns
    assert 65 <= score <= 78


@pytest.mark.parametrize(
    "excluded_title",
    [
        "Java Backend Developer",
        "Junior Spring Boot Engineer",
        "Site Reliability Engineer (SRE)",
        "Platform Engineer - Kubernetes",
        "Machine Learning Researcher",
        "Deep Learning Engineer",
    ],
)
def test_excluded_and_irrelevant_titles_are_rejected(excluded_title):
    status, score, _, _ = classify(
        _make_job(
            title=excluded_title,
            description="Junior engineering role with Python, Docker, and PostgreSQL.",
        )
    )
    assert status == "reject"
    assert score == 0


# ---------------------------------------------------------------------------
# 2. Canonical Answer Coverage & React-Select <RequiredInput /> DOM Shift Fix
# ---------------------------------------------------------------------------


def test_canonical_screening_questions_return_expected_answers():
    profile = {
        "identity": {
            "full_name": "Mohamed Ahmed Mahmoud",
            "country": "Egypt",
            "city": "Cairo",
        },
        "skills": {
            "priority": ["TypeScript", "JavaScript", "Node.js", "Python", "Django", "FastAPI", "Angular", "React", "Docker", "Linux", "PostgreSQL"],
        },
    }
    bank = {}
    item = {"company": "Canonical", "title": "Software Engineer"}

    ans, _ = aa._answer_for_field(
        "During this application process I agree to use only my own words. I understand that plagiarism may disqualify my application.",
        profile, bank, item,
    )
    assert ans == "Yes"

    ans, _ = aa._answer_for_field(
        "We require all colleagues to meet in person 2-4 times a year, at internal company events.",
        profile, bank, item,
    )
    assert ans == "Yes"

    ans, _ = aa._answer_for_field("How did you perform in mathematics at high school?", profile, bank, item)
    assert ans == "Top 10%"

    ans, _ = aa._answer_for_field("How did you perform in your native language at high school?", profile, bank, item)
    assert ans == "Top 10%"

    ans, _ = aa._answer_for_field(
        "Which programming languages are you most familiar with, and which kinds of projects have you worked on with them?",
        profile, bank, item,
    )
    assert ans is not None
    assert "TypeScript" in ans and "Python" in ans
    assert "SmartCart" in ans and "AeroLock" in ans

    ans, _ = aa._answer_for_field("Which gender do you identify as?", profile, bank, item)
    assert ans == "Male"

    ans, _ = aa._answer_for_field("Please indicate your race or ethnicity", profile, bank, item)
    assert ans == "Middle Eastern"


def test_react_select_dummy_required_input_unmount_does_not_shift_indices(tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as exc:
            pytest.skip(f"Chromium unavailable: {exc}")
        page = browser.new_page()
        try:
            html = """
            <form id="app-form">
              <div class="field" id="f1">
                <label for="cb1">During this application process I agree to use only my own words. *</label>
                <div class="select__control" id="ctl1">
                  <div class="select__single-value" id="sv1" style="display:none"></div>
                  <input id="cb1" class="select__input" role="combobox" aria-haspopup="listbox" autocomplete="off" />
                </div>
                <input id="dummy1" class="requiredInput" required tabindex="-1" style="opacity:0; pointer-events:none; width:100%; height:1px" />
                <div id="menu1" style="display:none"></div>
              </div>
              <div class="field" id="f2">
                <label for="cb2">What country do you live in? *</label>
                <div class="select__control" id="ctl2">
                  <div class="select__single-value" id="sv2" style="display:none"></div>
                  <input id="cb2" class="select__input" role="combobox" aria-haspopup="listbox" autocomplete="off" />
                </div>
                <input id="dummy2" class="requiredInput" required tabindex="-1" style="opacity:0; pointer-events:none; width:100%; height:1px" />
                <div id="menu2" style="display:none"></div>
              </div>
              <div class="field" id="f3">
                <label for="after_input">Email *</label>
                <input id="after_input" type="email" required />
              </div>
              <fieldset>
                <legend>Which kinds of projects are you most excited about working on? *</legend>
                <label><input type="checkbox" id="proj_ubuntu" name="projects[]" value="1"> Ubuntu Server</label>
                <label><input type="checkbox" id="proj_cloud" name="projects[]" value="2"> Cloud</label>
                <label><input type="checkbox" id="proj_cobol" name="projects[]" value="3"> Mainframe COBOL</label>
              </fieldset>
            </form>
            <script>
              function wireSelect(cbId, ctlId, svId, dummyId, menuId, options) {
                const cb = document.getElementById(cbId);
                const ctl = document.getElementById(ctlId);
                const sv = document.getElementById(svId);
                const menu = document.getElementById(menuId);
                function render(q) {
                  menu.innerHTML = '';
                  options.filter(o => o.toLowerCase().includes(q.toLowerCase())).forEach((o, i) => {
                    const opt = document.createElement('div');
                    opt.setAttribute('role', 'option');
                    opt.className = 'select__option';
                    opt.id = cbId + '-opt-' + i;
                    opt.textContent = o;
                    opt.onclick = () => {
                      sv.textContent = o;
                      sv.style.display = 'block';
                      menu.style.display = 'none';
                      cb.value = '';
                      const dummy = document.getElementById(dummyId);
                      if (dummy) dummy.remove();
                    };
                    menu.appendChild(opt);
                  });
                  menu.style.display = 'block';
                }
                ctl.addEventListener('mousedown', () => { cb.focus(); render(cb.value); });
                cb.addEventListener('input', () => render(cb.value));
              }
              wireSelect('cb1', 'ctl1', 'sv1', 'dummy1', 'menu1', ['I agree', 'I disagree']);
              wireSelect('cb2', 'ctl2', 'sv2', 'dummy2', 'menu2', ['Egypt', 'Germany']);
            </script>
            """
            page.set_content(html)
            profile = {
                "identity": {
                    "full_name": "Mohamed Ahmed Mahmoud",
                    "email": "mohamed@example.com",
                    "country": "Egypt",
                    "city": "Cairo",
                },
                "skills": {"priority": ["Python", "Docker", "Linux", "Azure"]},
            }
            cv = tmp_path / "resume.pdf"
            cv.write_bytes(b"%PDF-1.4 mock")
            blockers, filled = aa._fill_form(page.locator("#app-form"), profile, {}, {"company": "Canonical"}, cv)
            assert blockers == [], blockers
            assert page.locator("#sv1").inner_text() == "I agree"
            assert page.locator("#sv2").inner_text() == "Egypt"
            assert page.locator("#after_input").input_value() == "mohamed@example.com"
            assert page.locator("#proj_ubuntu").is_checked()
            assert page.locator("#proj_cloud").is_checked()
            assert not page.locator("#proj_cobol").is_checked()
            assert page.locator("#dummy1").count() == 0
        finally:
            browser.close()


# ---------------------------------------------------------------------------
# 3. Clean Hybrid Telegram Notifications & Job Cards
# ---------------------------------------------------------------------------


def test_runner_sends_clean_autopilot_summary_and_job_cards_without_debug_spam(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTO_APPLY_REPORT_PATH", str(tmp_path / "latest_run_report.json"))
    messages: list[str] = []

    submitted_job = _make_job(
        source="greenhouse",
        source_id="sub-1",
        title="Junior Node.js Backend Developer",
        company="AutoSubmitted Corp",
        url="https://boards.greenhouse.io/autosub/jobs/1",
    )
    skipped_ats_job = _make_job(
        source="ashby",
        source_id="skip-1",
        title="Junior Full-Stack Developer (Angular)",
        company="Angular Systems",
        url="https://jobs.ashbyhq.com/angularsys/2",
        description="Junior Angular, TypeScript, Node.js, Express, PostgreSQL. 0-1 years experience.",
    )
    linkedin_job = _make_job(
        source="linkedin_alert",
        source_id="li-1",
        title="Junior Python Backend Developer",
        company="Cairo Tech",
        url="https://www.linkedin.com/jobs/view/123456",
        description="Junior Python, FastAPI, Django, PostgreSQL. 0-1 years experience.",
    )

    monkeypatch.setattr(
        runner,
        "settings",
        SimpleNamespace(
            auto_apply_enabled=True,
            auto_apply_min_score=60,
            auto_apply_card_min_score=65,
            notify_review_candidates=True,
            review_digest_size=5,
            telegram_bot_token="test-token",
            telegram_chat_id="test-chat",
        ),
    )
    monkeypatch.setattr(runner, "init_db", lambda: None)
    monkeypatch.setattr(runner, "enqueue_application", lambda *args: None)
    monkeypatch.setattr(
        runner,
        "enabled_sources",
        lambda: [("mock", lambda: [submitted_job, skipped_ats_job, linkedin_job])],
    )
    monkeypatch.setattr(runner, "upsert_job", lambda *args: (True, True))
    monkeypatch.setattr(runner, "send_message", lambda msg: messages.append(msg) or True)

    def fake_classify(job: Job):
        if job.source_id == "sub-1":
            return "match", 96, ["Relevant skills: Node.js / Express, PostgreSQL"], []
        if job.source_id == "skip-1":
            return "match", 91, ["Relevant skills: Angular, TypeScript / JavaScript, Node.js / Express"], []
        return "match", 88, ["Relevant skills: Python, FastAPI, Django"], []

    monkeypatch.setattr(runner, "classify", fake_classify)

    import app.application_automation as app_auto
    import app.sources.application_inbox as app_inbox

    monkeypatch.setattr(
        app_auto,
        "run_auto_apply",
        lambda: {
            "enabled": True,
            "processed": 2,
            "submitted": 1,
            "skipped": 1,
            "failed": 0,
            "results": [
                {
                    "queue_id": 1,
                    "title": submitted_job.title,
                    "company": submitted_job.company,
                    "source": submitted_job.source,
                    "outcome": "submitted",
                    "cv_used": "Mohamed_Ahmed-Backend.pdf",
                    "url": submitted_job.url,
                },
                {
                    "queue_id": 2,
                    "title": skipped_ats_job.title,
                    "company": skipped_ats_job.company,
                    "source": skipped_ats_job.source,
                    "outcome": "auto_skipped",
                    "reason": "CAPTCHA detected",
                    "url": skipped_ats_job.url,
                },
            ],
        },
    )
    monkeypatch.setattr(
        app_inbox,
        "fetch_and_reconcile_inbox",
        lambda lookback_days=7: {"confirmed_queue_ids": [], "confirmations": [], "interviews": [], "rejections": []},
    )

    report = runner.run_once()

    assert len(messages) == 2
    summary_msg, cards_msg = messages

    # 1. Autopilot Summary checks
    assert "<b>Job Hunter — Autopilot Summary</b>" in summary_msg
    assert "✅ Applications auto-submitted: <b>1</b>" in summary_msg
    assert "AutoSubmitted Corp" in summary_msg
    assert "✅ <a href=" in summary_msg
    assert "📊 Funnel" not in summary_msg
    assert "Path breakdown" not in summary_msg
    assert "Top blockers" not in summary_msg
    assert "auto_skipped" not in summary_msg
    assert "Questions Needed" not in summary_msg

    # 2. Job Cards Digest checks
    assert "🎯 <b>Job Hunter — Top Matching Jobs to Apply (Score 65+)</b>" in cards_msg
    assert "Angular Systems" in cards_msg
    assert "Cairo Tech" in cards_msg
    assert "Tap to Apply" in cards_msg
    assert "AutoSubmitted Corp" not in cards_msg
    # Higher score (91) should appear before lower score (88)
    assert cards_msg.index("Angular Systems") < cards_msg.index("Cairo Tech")
    assert report["manual_apply_cards"] == 2
    assert report["auto_apply_summary_message_sent"] is True
    assert report["manual_apply_digest_sent"] is True
