"""Round 2: Ashby id-less inputs + data-option Yes/No, cookie overlays, multi-step forms,
excluded-skill leakage, period-aware compensation, timezone answers, opt-in generic remote."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import sync_playwright  # noqa: E402

import app.application_automation as aa  # noqa: E402
from app.application_profile import load_answer_bank, load_candidate_profile  # noqa: E402
from app.matching import classify  # noqa: E402
from app.models import Job  # noqa: E402

FIXTURES = Path(__file__).with_name("fixtures")


@pytest.fixture(scope="module")
def profile():
    return load_candidate_profile(FIXTURES / "candidate.json")


@pytest.fixture(scope="module")
def bank():
    return load_answer_bank(FIXTURES / "answers.json")


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


ITEM = {"company": "Resend", "title": "Software Engineer, Trust & Safety"}

# ----------------------------------------------------------------------------------
# Ashby fixture: no <form>, <label for="_systemfield_location"> but the <input> has NO id,
# required markers drawn by CSS/class (absent from innerText), Yes/No via data-option buttons.
# ----------------------------------------------------------------------------------
ASHBY = """
<style>
  .req::after { content: '*'; color: red; }
  ._active_x { background: #222; color: #fff; }
</style>
<div id="app">
 <div class="ashby-application-form-field-entry" data-field-path="_systemfield_name">
   <label class="ashby-application-form-question-title" for="_systemfield_name">Name</label>
   <input type="text" id="_systemfield_name" required>
 </div>
 <div class="ashby-application-form-field-entry" data-field-path="_systemfield_location">
   <label class="ashby-application-form-question-title _required_abc" for="_systemfield_location">What country are you based in?</label>
   <div><input type="text" role="combobox" class="ashby-application-form-autocomplete-input" placeholder="Start typing..." autocomplete="off">
   <ul id="lb" role="listbox" style="display:none"></ul></div>
 </div>
 <div class="ashby-application-form-field-entry" data-field-path="tz1">
   <label class="ashby-application-form-question-title req">Are you in an Americas time zone?</label>
   <div class="yn"><button type="button" data-option="yes">Yes</button><button type="button" data-option="no">No</button>
   <input type="checkbox" name="c9f1-uuid-1" style="display:none"></div>
 </div>
 <div class="ashby-application-form-field-entry" data-field-path="tz2">
   <label class="ashby-application-form-question-title req">Do you have at least 3-4 hours of overlap with US/CET hours?</label>
   <div class="yn"><button type="button" data-option="yes">Yes</button><button type="button" data-option="no">No</button>
   <input type="checkbox" name="c9f1-uuid-2" style="display:none"></div>
 </div>
 <div class="ashby-application-form-field-entry" data-field-path="cairo">
   <label class="ashby-application-form-question-title req">I am based in Cairo or happy to relocate there.</label>
   <div class="yn"><button type="button" data-option="yes">Yes</button><button type="button" data-option="no">No</button>
   <input type="checkbox" name="c9f1-uuid-3" style="display:none"></div>
 </div>
 <div class="ashby-application-form-field-entry" data-field-path="clr">
   <label class="ashby-application-form-question-title req">Do you hold an active security clearance?</label>
   <div class="yn"><button type="button" data-option="yes">Yes</button><button type="button" data-option="no">No</button>
   <input type="checkbox" name="c9f1-uuid-4" style="display:none"></div>
 </div>
 <div class="ashby-application-form-field-entry" data-field-path="why">
   <label class="ashby-application-form-question-title req">Why do you want to join us?</label>
   <textarea></textarea>
 </div>
 <div class="ashby-application-form-field-entry" data-field-path="hear">
   <label class="ashby-application-form-question-title req">How did you hear about us?</label>
   <textarea></textarea>
 </div>
 <div class="ashby-application-form-field-entry" data-field-path="other">
   <label class="ashby-application-form-question-title">Other</label>
   <div class="ashby-application-form-question-description">Portfolio, personal website, etc.</div>
   <input type="text">
 </div>
 <div class="ashby-application-form-field-entry" data-field-path="twitter">
   <label class="ashby-application-form-question-title">Twitter / X</label>
   <input type="text">
 </div>
 <button type="submit" id="go">Submit Application</button>
</div>
<script>
 const OPTS = ["Egypt", "Egypt, Cairo Governorate", "Germany"];
 const inp = document.querySelector('input[role=combobox]'), lb = document.getElementById('lb');
 inp.addEventListener('input', () => {
   lb.innerHTML = '';
   setTimeout(() => {                       // asynchronous, like Ashby's location API
     OPTS.filter(o => o.toLowerCase().includes(inp.value.toLowerCase())).forEach(o => {
       const li = document.createElement('li'); li.setAttribute('role', 'option'); li.textContent = o;
       li.onmousedown = li.onclick = () => { inp.value = o; lb.style.display = 'none'; };
       lb.appendChild(li);
     });
     lb.style.display = 'block';
   }, 700);
 });
 document.querySelectorAll('.yn button').forEach(b => b.onclick = () => {
   b.parentElement.querySelectorAll('button').forEach(x => x.classList.remove('_active_x'));
   b.classList.add('_active_x');
 });
</script>
"""


def _active(page, path: str) -> str:
    return page.eval_on_selector(f"[data-field-path='{path}'] button._active_x", "e => e.dataset.option") if page.locator(f"[data-field-path='{path}'] button._active_x").count() else ""


def test_ashby_idless_inputs_required_css_and_yes_no_buttons(page, profile, bank, tmp_path):
    page.set_content(ASHBY)
    metas = aa._labels(page.locator("body"))
    by_path = {m["fieldPath"]: m for m in metas if m["fieldPath"] and m["tag"] == "input" and m["type"] != "checkbox"}
    loc = by_path["_systemfield_location"]
    assert loc["label"] == "What country are you based in?"      # label[for] could not match: input has no id
    assert loc["required"] and loc["combobox"]                    # required via class, not "*" text
    assert metas and any(m["yesNoWidget"] for m in metas)

    blockers, filled = aa._fill_form(page.locator("body"), profile, bank, ITEM, tmp_path / "none.pdf")

    assert page.locator("input[role=combobox]").input_value() == "Egypt"
    assert _active(page, "tz1") == "no"       # "Are you in an Americas time zone?" -> No
    assert _active(page, "tz2") == "yes"      # US/CET overlap -> Yes
    assert _active(page, "cairo") == "yes"    # based in Cairo or relocate -> Yes
    assert _active(page, "clr") == ""         # unknown factual question: never guessed
    assert any("security clearance" in b for b in blockers)
    texts = page.eval_on_selector_all("textarea", "els => els.map(e => e.value)")
    assert texts[0].startswith("I am excited to join an ambitious engineering team")   # saved universal answer
    assert texts[1].casefold().startswith("company careers page")
    inputs = page.eval_on_selector_all("[data-field-path='other'] input, [data-field-path='twitter'] input", "els => els.map(e => e.value)")
    assert inputs == ["https://portfolio.example.invalid/", ""]    # portfolio filled via hint; Twitter left blank


def test_css_asterisk_marks_a_field_required(page):
    page.set_content("""<style>.req::after{content:'*'}</style>
      <div data-field-path="a"><label class="req">Name?</label><input type="text"></div>
      <div data-field-path="b"><label>Nickname</label><input type="text"></div>""")
    metas = {m["fieldPath"]: m for m in aa._labels(page.locator("body")) if m["tag"] == "input"}
    assert metas["a"]["required"] and not metas["b"]["required"]


def test_unanswered_required_questions_are_named_in_the_failure_message(page, monkeypatch):
    monkeypatch.setattr(page, "wait_for_timeout", lambda ms: None)
    page.set_content("""<style>.req::after{content:'*'}</style>
      <div class="ashby-application-form-field-entry" data-field-path="q"><label class="req">Are you in an Americas time zone?</label>
        <div><button type="button" data-option="yes">Yes</button><button type="button" data-option="no">No</button></div></div>
      <button type="submit" id="go">Submit Application</button>
      <script>document.getElementById('go').onclick = () => {};</script>""")
    state, message = aa._submit_step(page, page.locator("body"))
    assert state == "error"
    assert "unanswered required: Are you in an Americas time zone?" in message


# ----------------------------------------------------------------------------------
# Workable cookie overlay
# ----------------------------------------------------------------------------------
COOKIE_PAGE = """
<form id="f"><input type="email" value="a@b.c"><button type="submit">Submit application</button></form>
<div id="cookie-banner" style="position:fixed;inset:0;background:rgba(0,0,0,.5);z-index:99">
  <div style="position:absolute;bottom:0;background:#fff;width:100%">This website uses cookies to improve your experience.
    <button id="settings">Cookies settings</button>
    <button id="accept" onclick="document.body.dataset.choice='accept'; document.getElementById('cookie-banner').remove()">Accept all</button>
    <button id="decline" onclick="document.body.dataset.choice='decline'; document.getElementById('cookie-banner').remove()">Decline all</button>
  </div></div>
<script>document.getElementById('f').onsubmit = e => { e.preventDefault(); document.body.innerHTML = '<p>Your application was successfully submitted.</p>'; };</script>
"""


def test_cookie_overlay_is_declined_by_default_and_submit_succeeds(page):
    page.set_content(COOKIE_PAGE)
    ok, message = aa._submit_form(page, page.locator("form"))
    assert ok, message


def test_cookie_choice_default_is_decline_and_accept_is_configurable(page, monkeypatch):
    page.set_content(COOKIE_PAGE)
    assert aa._dismiss_cookie_banner(page) == "declined"
    assert page.evaluate("document.body.dataset.choice") == "decline"
    monkeypatch.setenv("AUTO_APPLY_COOKIE_CHOICE", "accept")
    page.set_content(COOKIE_PAGE)
    assert aa._dismiss_cookie_banner(page) == "accepted"
    assert page.evaluate("document.body.dataset.choice") == "accept"


def test_cookie_banner_without_cookie_ids_is_found_by_its_text(page):
    page.set_content("""<button id="go" onclick="document.body.dataset.go='1'">Apply</button>
      <div data-ui="overlay-xyz" style="position:fixed;inset:0;background:rgba(0,0,0,.5)"><div class="box1">
        <p>This website uses cookies to improve user's experience and analyse traffic.</p>
        <button onclick="document.body.dataset.choice='accept'; this.closest('[data-ui]').remove()">Accept all</button>
        <button onclick="document.body.dataset.choice='decline'; this.closest('[data-ui]').remove()">Decline all</button></div></div>""")
    assert aa._dismiss_cookie_banner(page) == "declined"
    assert page.evaluate("document.body.dataset.choice") == "decline"


def test_non_cookie_dialogs_are_left_alone(page):
    page.set_content("<div role='dialog'>Please review the terms. <button onclick=\"document.body.dataset.x='clicked'\">I agree</button></div>")
    assert aa._dismiss_cookie_banner(page) is None
    assert page.evaluate("document.body.dataset.x || ''") == ""


# ----------------------------------------------------------------------------------
# Askable-style two-step flow: contact details -> "Which best describes your role?"
# ----------------------------------------------------------------------------------
STEPPER = """
<div id="app"><div id="s1"><input type="text" name="name" value="Mohamed"><input type="email" name="email" value="a@b.c">
  <button id="c1" type="submit">Continue</button></div></div>
<script>
 const app = document.getElementById('app');
 document.getElementById('c1').onclick = () => {
   app.innerHTML = `<div><p>Thanks, Mohamed. A few quick questions.</p>
     <h2>Which best describes your current or most recent role?</h2>
     <div><label><input type="radio" name="role" value="a" style="opacity:0;position:absolute"> Software engineer / developer</label></div>
     <div><label><input type="radio" name="role" value="b" style="opacity:0;position:absolute"> Senior, staff, or principal software engineer</label></div>
     <div><label><input type="radio" name="role" value="c" style="opacity:0;position:absolute"> Engineering lead or manager who still writes or reviews code</label></div>
     <div><label><input type="radio" name="role" value="d" style="opacity:0;position:absolute"> Site reliability, platform or infrastructure engineer</label></div>
     <div><label><input type="radio" name="role" value="e" style="opacity:0;position:absolute"> Software test or automation engineer</label></div>
     <div><label><input type="radio" name="role" value="f" style="opacity:0;position:absolute"> Student, or learning software development</label></div>
     <button id="c2" type="submit">Continue</button></div>`;
   document.getElementById('c2').onclick = () => {
     if (!document.querySelector('input[name=role]:checked')) return;
     app.innerHTML = '<p>Thanks for applying! Your application is complete.</p>';
   };
 };
</script>
"""


def test_submit_that_advances_to_a_second_step_is_followed_through(page, profile, bank, tmp_path):
    page.set_content(STEPPER)
    state, message = aa._submit_step(page, page.locator("body"))
    assert state == "advanced", message

    metas = [m for m in aa._labels(page.locator("body")) if m["type"] == "radio"]
    assert len(metas) == 6 and all("current or most recent role" in m["label"] for m in metas)  # heading-derived question

    blockers, filled = aa._fill_form(page.locator("body"), profile, bank, ITEM, tmp_path / "none.pdf")
    assert blockers == []
    assert page.eval_on_selector("input[name=role]:checked", "e => e.value") == "a"   # not Senior/Lead/SRE/Student

    state, message = aa._submit_step(page, page.locator("body"))
    assert state == "submitted", message


def test_role_option_chooser_requires_an_unambiguous_junior_dev_option():
    mk = lambda *labels: [{"optionLabel": t} for t in labels]
    pick = aa._choose_role_option(mk("Software engineer / developer", "Senior, staff, or principal software engineer", "Student, or learning software development"))
    assert pick["optionLabel"] == "Software engineer / developer"
    assert aa._choose_role_option(mk("Marketing manager", "Student", "Other")) is None


def test_unanswerable_second_step_is_reported_not_guessed(page, profile, bank, tmp_path):
    page.set_content("""<h2>Do you hold a top-secret clearance?</h2>
      <label><input type="radio" name="x" required> Yes</label><label><input type="radio" name="x" required> No</label>""")
    blockers, _ = aa._fill_form(page.locator("body"), profile, bank, ITEM, tmp_path / "none.pdf")
    assert any("clearance" in b for b in blockers)
    assert page.locator("input:checked").count() == 0


# ----------------------------------------------------------------------------------
# Profile-driven answers
# ----------------------------------------------------------------------------------
def test_cover_letter_never_claims_excluded_stacks(profile):
    letter = aa._generate_cover_letter(profile, ITEM)
    for excluded in profile["skills"]["excluded_primary_stacks"]:
        assert excluded not in letter, excluded
    assert "Python" in letter


def test_checkbox_interest_matching_ignores_excluded_stacks(profile):
    keywords = aa._profile_skill_keywords(profile)
    assert "java" not in keywords and "php" not in keywords and "spring boot" not in keywords


@pytest.mark.parametrize("question,expected", [
    ("Are you in an Americas time zone?", "No"),
    ("Are you located in the US/Canada time zones?", "No"),
    ("Do you have a 3-4 hour overlap with US Eastern or CET hours?", "Yes"),
    ("Are you comfortable working in an Americas time zone?", "Yes"),
])
def test_timezone_answers(profile, bank, question, expected):
    assert aa._answer_for_field(question, profile, bank, ITEM)[0] == expected


@pytest.mark.parametrize("question,expected", [
    ("What country are you based in?", "Egypt"),
    ("Which country do you currently live in?", "Egypt"),
    ("What city do you live in?", "Cairo"),
])
def test_location_answers(profile, bank, question, expected):
    assert aa._answer_for_field(question, profile, bank, ITEM)[0] == expected


def test_authorization_country_questions_are_not_answered_as_residence(profile, bank):
    value, _ = aa._answer_for_field("Which countries are you authorized to work in?", profile, bank, ITEM)
    assert value != "Egypt"


def test_compensation_is_period_aware(profile, bank):
    monthly, _ = aa._answer_for_field("What are your monthly salary expectations in USD?", profile, bank, ITEM)
    assert monthly == "222.44"
    annual, _ = aa._answer_for_field("Expected annual compensation in USD", profile, bank, ITEM)
    assert annual == "2669"                      # 222.44 x 12 (12,000 EGP/month equivalent)
    hourly, _ = aa._answer_for_field("What is your hourly rate in USD?", profile, bank, ITEM)
    assert hourly == "1.62"                      # targeting 12,000 EGP/month net after taxes


def test_explicit_annual_target_overrides_twelve_times_monthly():
    bank = {"answers": {"salary_expectation_usd": {"target_amount": 1200, "annual_target_amount": 15000}}}
    value, _ = aa._compensation_answer("Expected annual salary (USD)", bank)
    assert value == "15000"


def test_why_join_us_uses_the_saved_answer_not_a_generated_letter(profile, bank):
    saved = bank["answers"]["why_this_company"]["answer"]
    for q in ("Why do you want to work at Resend?", "Why join us?", "Why foodics? why you?"):
        assert aa._answer_for_field(q, profile, bank, ITEM)[0] == saved, q
    letter, _ = aa._answer_for_field("Please attach or paste a cover letter", profile, bank, ITEM)
    assert letter.startswith("Hello Resend hiring team")


# ----------------------------------------------------------------------------------
# Opt-in generic "Remote" (ALLOW_UNSPECIFIED_REMOTE)
# ----------------------------------------------------------------------------------
FILLER = " You will collaborate with engineers, write maintainable code, review pull requests and ship software every week. " * 2


def _job(description="Build Python and Django APIs. This role is remote.", location="Remote", title="Junior Backend Developer"):
    return Job(
        source="t", source_id=title + location, title=title, company="Acme", location=location,
        url="https://boards.greenhouse.io/acme/jobs/1", description=description + FILLER,
        posted_at=(datetime.now(timezone.utc) - timedelta(days=1)).isoformat(), date_kind="posted",
        remote=True, employment_type="Full time", workplace_type="remote", eligibility="", description_quality="full",
    )


def _item(job, status, score):
    return {
        "id": 1, "status": "pending_review", "qualification_status": status, "score": score, "title": job.title,
        "company": job.company, "location": job.location, "url": job.url, "source": job.source, "source_id": job.source_id,
        "description": job.description, "posted_at": job.posted_at, "date_kind": "posted", "remote": 1,
        "employment_type": "Full time", "workplace_type": "remote", "eligibility": "", "description_quality": "full",
    }


def test_generic_remote_is_not_assumed_open_by_default(monkeypatch):
    monkeypatch.delenv("ALLOW_UNSPECIFIED_REMOTE", raising=False)
    _, _, reasons, concerns = classify(_job())
    assert any("does not confirm" in c for c in concerns)
    assert not any("no stated country restriction" in r for r in reasons)


def test_toggle_assumes_open_remote_when_nothing_restricts(monkeypatch):
    monkeypatch.setenv("ALLOW_UNSPECIFIED_REMOTE", "true")
    status, score, reasons, concerns = classify(_job())
    assert any("no stated country restriction" in r for r in reasons)
    assert not any("does not confirm" in c for c in concerns)
    assert aa._reason_for_auto_skip(_item(_job(), status, score)) is None


@pytest.mark.parametrize("kwargs", [
    {"location": "Remote - Germany"},
    {"location": "Remote (US)"},
    {"description": "Python APIs. You must be based in Spain. This role is remote."},
    {"description": "Python APIs. Candidates must be authorized to work in their country of residence. Remote."},
    {"description": "Python APIs. US citizen required, security clearance. Remote."},
])
def test_toggle_never_overrides_explicit_restrictions(monkeypatch, kwargs):
    monkeypatch.setenv("ALLOW_UNSPECIFIED_REMOTE", "true")
    status, _, reasons, concerns = classify(_job(**kwargs))
    assert not any("no stated country restriction" in r for r in reasons), (kwargs, reasons)


def test_assumed_open_listings_use_a_stricter_score_floor(monkeypatch):
    monkeypatch.setenv("ALLOW_UNSPECIFIED_REMOTE", "true")
    job = _job()
    status, score, _, _ = classify(job)
    monkeypatch.setenv("AUTO_APPLY_UNSPECIFIED_REMOTE_MIN_SCORE", str(score + 1))
    reason = aa._reason_for_auto_skip(_item(job, status, score))
    assert reason and "Assumed-open" in reason
    monkeypatch.setenv("AUTO_APPLY_UNSPECIFIED_REMOTE_MIN_SCORE", str(score))
    assert aa._reason_for_auto_skip(_item(job, status, score)) is None
