"""Real-browser tests for react-select, checkbox groups, hidden radios, Yes/No buttons, wizards."""
from __future__ import annotations

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import sync_playwright  # noqa: E402

import app.application_automation as aa  # noqa: E402


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except Exception as exc:  # chromium not installed in this environment
            pytest.skip(f"Chromium unavailable: {exc}")
        yield b
        b.close()


@pytest.fixture()
def page(browser):
    pg = browser.new_page()
    yield pg
    pg.close()


REACT_SELECT = """
<label for="country">Country*</label>
<div class="select__control" id="ctl">
  <div class="select__value-container">
    <div class="select__placeholder" id="ph">Select...</div>
    <div class="select__single-value" id="sv" style="display:none"></div>
    <input id="country" class="select__input" role="combobox" aria-haspopup="true" aria-required="true" autocomplete="off">
  </div>
</div>
<div id="menu" style="display:none"></div>
<script>
const OPTS = ["Egypt", "Egypt (Sinai)", "Germany", "Portugal"];
const input = document.getElementById('country'), menu = document.getElementById('menu');
function render(q) {
  menu.innerHTML = '';
  OPTS.filter(o => o.toLowerCase().includes(q.toLowerCase())).forEach((o, i) => {
    const d = document.createElement('div');
    d.setAttribute('role', 'option'); d.id = 'react-select-2-option-' + i; d.className = 'select__option'; d.textContent = o;
    d.onclick = () => pick(o);
    menu.appendChild(d);
  });
  menu.style.display = 'block';
}
function pick(v) {
  document.getElementById('sv').textContent = v; document.getElementById('sv').style.display = 'block';
  document.getElementById('ph').style.display = 'none'; menu.style.display = 'none'; input.value = '';
}
document.getElementById('ctl').addEventListener('mousedown', () => { input.focus(); render(input.value); });
input.addEventListener('input', () => render(input.value));
input.addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); const f = menu.querySelector('[role=option]'); if (f) pick(f.textContent); } });
</script>
"""


def test_react_select_click_type_choose(page):
    page.set_content(REACT_SELECT)
    loc = page.locator("#country")
    ok, why = aa._fill_react_select(page, loc, "Egypt")
    assert ok, why
    assert page.locator("#sv").inner_text() == "Egypt"  # exact option, not "Egypt (Sinai)"


def test_react_select_unmatched_value_is_not_guessed(page):
    page.set_content(REACT_SELECT)
    ok, why = aa._fill_react_select(page, page.locator("#country"), "Narnia")
    assert not ok
    assert page.locator("#sv").is_hidden()


def test_react_select_is_detected_and_filled_through_fill_form(page, monkeypatch, tmp_path):
    page.set_content(f"<form>{REACT_SELECT}<input type='email' id='e' required><button type='submit'>Submit</button></form>")
    monkeypatch.setattr(aa, "_answer_for_field", lambda q, *a, **k: ("Egypt", "test"))
    profile = {"identity": {"email": "me@example.com", "full_name": "Mohamed Ahmed Mahmoud"}}
    blockers, filled = aa._fill_form(page.locator("form"), profile, {}, {}, tmp_path / "none.pdf")
    assert blockers == []
    assert page.locator("#sv").inner_text() == "Egypt"
    assert page.locator("#e").input_value() == "me@example.com"


CHECKBOX_GROUP = """
<form><fieldset><legend>Which areas of engineering interest you?*</legend>
 <label><input type="checkbox" name="question_69583802[]" value="1"> Ubuntu Server</label>
 <label><input type="checkbox" name="question_69583802[]" value="2"> Commercial Systems</label>
 <label><input type="checkbox" name="question_69583802[]" value="3"> Cloud</label>
 <label><input type="checkbox" name="question_69583802[]" value="4"> Desktop</label>
 <label><input type="checkbox" name="question_69583802[]" value="5"> Other</label>
</fieldset></form>
"""
PROFILE = {"skills": {"priority": ["Python", "Docker", "Azure", "Linux"], "additional": []}}


def test_multi_checkbox_group_ticks_only_profile_supported_options(page, monkeypatch, tmp_path):
    page.set_content(CHECKBOX_GROUP)
    monkeypatch.setattr(aa, "_answer_for_field", lambda q, *a, **k: (None, "none"))
    blockers, filled = aa._fill_form(page.locator("form"), PROFILE, {}, {}, tmp_path / "none.pdf")
    checked = page.eval_on_selector_all("input:checked", "els => els.map(e => e.parentElement.innerText.trim())")
    assert blockers == []
    assert sorted(checked) == ["Cloud", "Ubuntu Server"]


def test_required_checkbox_group_without_supported_option_is_a_blocker(page, monkeypatch, tmp_path):
    page.set_content(CHECKBOX_GROUP.replace("Ubuntu Server", "Mainframe Systems").replace(">Cloud<", ">Retail Banking<").replace("> Cloud", "> Retail Banking").replace("Desktop", "Hardware Design"))
    monkeypatch.setattr(aa, "_answer_for_field", lambda q, *a, **k: (None, "none"))
    blockers, _ = aa._fill_form(page.locator("form"), {"skills": {"priority": ["COBOL"]}}, {}, {}, tmp_path / "none.pdf")
    assert any("Required checkbox group" in b for b in blockers)
    assert page.locator("input:checked").count() == 0


def test_checkbox_group_uses_saved_answer_list_when_present(page, monkeypatch, tmp_path):
    page.set_content(CHECKBOX_GROUP)
    monkeypatch.setattr(aa, "_answer_for_field", lambda q, *a, **k: ("Desktop, Cloud", "saved"))
    blockers, _ = aa._fill_form(page.locator("form"), PROFILE, {}, {}, tmp_path / "none.pdf")
    checked = page.eval_on_selector_all("input:checked", "els => els.map(e => e.parentElement.innerText.trim())")
    assert blockers == [] and sorted(checked) == ["Cloud", "Desktop"]


WORKABLE_RADIO = """
<form><fieldset><legend>Are you legally able to work in Egypt?*</legend>
 <label class="styled"><input type="radio" name="q1" value="yes" required
   style="position:absolute;opacity:0;width:0;height:0"><svg width="14" height="14"><circle cx="7" cy="7" r="6"/></svg> Yes</label>
 <label class="styled"><input type="radio" name="q1" value="no" required
   style="position:absolute;opacity:0;width:0;height:0"><svg width="14" height="14"><circle cx="7" cy="7" r="6"/></svg> No</label>
</fieldset></form>
"""


def test_hidden_input_styled_radio_is_selected(page, monkeypatch, tmp_path):
    page.set_content(WORKABLE_RADIO)
    monkeypatch.setattr(aa, "_answer_for_field", lambda q, *a, **k: ("Yes", "saved"))
    blockers, filled = aa._fill_form(page.locator("form"), {}, {}, {}, tmp_path / "none.pdf")
    assert blockers == []
    assert page.locator("input[value=yes]").is_checked()
    assert not page.locator("input[value=no]").is_checked()


ASHBY_YES_NO = """
<div class="ashby-application-form-field-entry"><label>I am based in Cairo or happy to relocate there.*</label>
  <div class="grp"><button type="button" class="opt">Yes</button><button type="button" class="opt">No</button></div></div>
<div class="fieldEntry"><label>Do you hold an active security clearance?*</label>
  <div><button type="button" class="opt">Yes</button><button type="button" class="opt">No</button></div></div>
<script>document.querySelectorAll('button.opt').forEach(b => b.onclick = () => {
  b.parentElement.querySelectorAll('button').forEach(x => x.classList.remove('active')); b.classList.add('active'); });</script>
"""


def test_yes_no_buttons_answered_when_supported_and_blocked_when_unknown(page, monkeypatch):
    page.set_content(ASHBY_YES_NO)
    monkeypatch.setattr(aa, "_answer_for_field", lambda q, *a, **k: (None, "none"))
    filled, blockers = aa._fill_yes_no_buttons(page.locator("body"), {}, {}, {})
    assert any("based in Cairo" in f and f.endswith("Yes") for f in filled)
    assert page.locator(".grp button.active").inner_text() == "Yes"
    # Unknown factual question: not guessed, reported as a blocker, nothing clicked.
    assert any("security clearance" in b for b in blockers)
    assert page.locator(".fieldEntry button.active").count() == 0


WIZARD = """
<div id="s1"><input type="email" id="e"><button type="button" onclick="
  document.getElementById('s1').style.display='none'; document.getElementById('s2').style.display='block'">Next</button></div>
<div id="s2" style="display:none"><input type="text" id="t"><button type="submit">Submit application</button></div>
"""


def test_wizard_progression_stops_at_submit(page):
    page.set_content(WIZARD)
    body = page.locator("body")
    assert not aa._has_submit_button(body)
    assert aa._advance_wizard(page, body)
    assert aa._has_submit_button(body)
    assert not aa._advance_wizard(page, body)  # no further Next; never clicks Submit


def test_late_spa_confirmation_with_new_wording_counts_as_submitted(page):
    page.set_content("""<form id="f"><input type="email" value="a@b.c"><button type="submit">Submit Application</button></form>
      <script>document.getElementById('f').onsubmit = e => { e.preventDefault();
        setTimeout(() => { document.body.innerHTML = '<div>Success</div><p>Your application was successfully submitted.</p>'; }, 1800); };</script>""")
    ok, message = aa._submit_form(page, page.locator("form"))
    assert ok, message


def test_recaptcha_footer_text_is_not_a_challenge(page):
    page.set_content("<form><input></form><small>This site is protected by reCAPTCHA and the Google Privacy Policy.</small>")
    assert not aa._is_challenge(page, page.locator("body").inner_text())
    assert aa._is_challenge(page, "Please verify you are human to continue")


def test_validation_errors_are_reported_not_called_uncertain(page):
    page.set_content("""<form id="f"><input aria-invalid="true" id="x"><span role="alert">Please select an option</span>
      <button type="submit">Submit</button></form><script>document.getElementById('f').onsubmit = e => e.preventDefault();</script>""")
    ok, message = aa._submit_form(page, page.locator("form"))
    assert not ok and "validation" in message.lower() and "Please select an option" in message
