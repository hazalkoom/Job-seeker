"""Tests for Round 5: Canonical question resolution, hourly after-tax compensation, and Ashby checkbox groups."""

from __future__ import annotations

import json
from pathlib import Path
import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import sync_playwright

import app.application_automation as aa

ROOT = Path(__file__).resolve().parent.parent

ITEM = {
    "id": 999,
    "title": "Software Engineer",
    "company": "Canonical",
    "url": "https://job-boards.greenhouse.io/canonical/jobs/123456",
    "remote": True,
}


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except Exception as exc:
            pytest.skip(f"Chromium unavailable: {exc}")
        yield b
        b.close()


@pytest.fixture()
def page(browser):
    pg = browser.new_page()
    yield pg
    pg.close()


@pytest.fixture
def profile():
    with (ROOT / "candidate_profile.json").open(encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def bank():
    with (ROOT / "application_answers.json").open(encoding="utf-8") as f:
        return json.load(f)


def test_canonical_companies_post_graduation_question(profile, bank):
    q = "In the past ten years, looking only at the time since you graduated your first undergraduate degree, how many companies have you worked for?"
    val, reason = aa._answer_for_field(q, profile, bank, ITEM)
    assert val == "0"
    assert "0 companies" in reason


def test_canonical_privacy_notice_agreement(profile, bank):
    q = "Please confirm that you have read and agree to Canonical's Recruitment Privacy Notice and Privacy Policy."
    val, reason = aa._answer_for_field(q, profile, bank, ITEM)
    assert val == "Yes"


def test_canonical_location_and_nationality_answers(profile, bank):
    val, _ = aa._answer_for_field("Where are you presently located?", profile, bank, ITEM)
    assert val in {"Egypt", "Cairo, Egypt"}

    val, _ = aa._answer_for_field("Please indicate your nationality", profile, bank, ITEM)
    assert val == "Egypt"

    val, _ = aa._answer_for_field("Location Start typing...", profile, bank, ITEM)
    assert "Egypt" in val


def test_hourly_compensation_targets_12k_net_after_taxes(profile, bank):
    usd_val, _ = aa._answer_for_field("Desired hourly rate $USD/hr", profile, bank, ITEM)
    assert usd_val == "1.62"

    egp_val, _ = aa._answer_for_field("Desired hourly rate (EGP/hr)", profile, bank, ITEM)
    assert egp_val == "88"

    eur_val, _ = aa._answer_for_field("Expected hourly rate in EUR", profile, bank, ITEM)
    assert eur_val == "1.45"

    gbp_val, _ = aa._answer_for_field("Hourly rate (GBP)", profile, bank, ITEM)
    assert gbp_val == "1.20"


def test_canonical_technical_essay_questions(profile, bank):
    val, _ = aa._answer_for_field("Describe your Python software development experience", profile, bank, ITEM)
    assert "FastAPI" in val and "Django" in val

    val, _ = aa._answer_for_field("Describe your experiences with embedded software development on Linux.", profile, bank, ITEM)
    assert "Linux" in val and "Ubuntu" in val

    val, _ = aa._answer_for_field("What hypervisor technologies are you familiar with? Describe your experience with these.", profile, bank, ITEM)
    assert "Docker" in val or "virtual machine" in val

    val, _ = aa._answer_for_field("Briefly describe your experience developing backend services in C/C++/Go/Python.", profile, bank, ITEM)
    assert "REST" in val or "backend" in val


def test_placeholder_select_is_not_treated_as_field_label(page):
    """Greenhouse-style dropdown where input has placeholder 'Select...' inside a .field with <label>."""
    html = """
    <form id="app-form">
      <div class="field">
        <label for="job_application_answers_country">What country do you live in? <span class="asterisk">*</span></label>
        <div class="select__control">
          <input id="job_application_answers_country" type="text" placeholder="Select..." class="select__input" />
        </div>
      </div>
    </form>
    """
    page.set_content(html)
    form = page.locator("#app-form")
    fields = aa._labels(form)
    assert len(fields) == 1
    # Label should be extracted from .field label, not 'Select...'
    assert fields[0]["label"] == "What country do you live in?"
    assert fields[0]["placeholder"] == "Select..."


def test_ashby_checkbox_group_does_not_flag_unselected_options(page, profile, bank, tmp_path):
    """Ashby-style container with multiple checkboxes and required asterisk."""
    html = """
    <form id="app-form">
      <div class="field-entry required">
        <div class="question-title">Which roles are you interested in? <span class="required">*</span></div>
        <div class="options">
          <label><input type="checkbox" id="chk-fullstack" name="roles[]"> Full-Stack Developer</label>
          <label><input type="checkbox" id="chk-backend" name="roles[]"> Backend Developer</label>
          <label><input type="checkbox" id="chk-uiux" name="roles[]"> UI/UX / Product Design</label>
          <label><input type="checkbox" id="chk-mgmt" name="roles[]"> Engineering Management / Tech Lead</label>
        </div>
      </div>
    </form>
    """
    page.set_content(html)
    form = page.locator("#app-form")
    fields = aa._labels(form)
    assert len(fields) == 4
    # All checkboxes in the entry should share the group question
    for f in fields:
        assert f["label"] == "Which roles are you interested in?"
        # Individual checkboxes shouldn't be marked required individually
        assert not f["required"]
        assert f["groupRequired"]

    cv = tmp_path / "resume.pdf"
    cv.write_bytes(b"%PDF-1.4 mock")
    blockers, filled = aa._fill_form(form, profile, bank, ITEM, cv)
    assert not blockers
    # Fullstack and/or backend should be ticked
    assert any("roles" in item.lower() or "full-stack" in item.lower() or "backend" in item.lower() for item in filled)
    # UI/UX and Mgmt should NOT be ticked
    assert not page.locator("#chk-uiux").is_checked()
    assert not page.locator("#chk-mgmt").is_checked()
