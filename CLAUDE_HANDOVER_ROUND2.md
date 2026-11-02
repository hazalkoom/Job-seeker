# Job Hunter — Round 2 Handover & In-Depth Diagnostic Report for Claude

## 1. What Was Deployed & Verified in Round 1
- **Files Replaced:**
  - `app/matching.py` (Claude's AI-role & timezone regex updates)
  - `app/application_automation.py` (Claude's react-select, checkbox groups, wizard steps, Supabase success markers, review promotion)
  - `tests/test_ai_workflow_and_review_policy.py`
  - `tests/test_modern_ats_widgets.py`
- **Queue Item #30 Status Fixed:** Marked as `submitted` ("Confirmed from submit_after_30.png").
- **Test Suite:** All **180 tests** passed (`pytest -q`).
- **Encrypted Autopilot & GitHub Actions:**
  - Re-encrypted with `scripts/prepare_github_autopilot.sh`
  - Committed and pushed to `main` (`8ded0bc`).
  - GitHub Actions workflow and local `run_once.py` executed.

---

## 2. Latest Cycle Results (The Problem)
Telegram report from latest run:
- **Applications confirmed submitted:** 0
- **Automatically skipped:** 67
- **Submission errors / uncertain outcomes:** 4 (Items #41, #47, #98, #99, plus earlier #31, #39)

---

## 3. Root Cause Investigation & Hard Proof (OCR & DOM Analysis)

### A. Ashby ATS: Why Submissions Failed as "Uncertain" (#98, #99 Resend, #39 Chatbase, #31 Supabase)
All 4 jobs reached the final stage: form was chosen, fields filled, submit was clicked.
However, OCR of `submit_after_98.png`, `submit_after_99.png`, and `submit_after_39.png` revealed the form **never actually submitted**: the button still read `Submit Application →` and the form was still on screen.

#### The Smoking Gun DOM Structure in Ashby:
Ashby renders question containers like this:
```html
<div class="_fieldEntry_1e3gg_28 ashby-application-form-field-entry" data-field-path="_systemfield_location">
  <label class="_heading_f7cvd_52 _required_f7cvd_91 _label_1e3gg_42 ashby-application-form-question-title" for="_systemfield_location">
    What country are you based in?
  </label>
  <div class="_inputContainer_d7ago_28">
    <input class="_input_d7ago_28 ashby-application-form-input-autocomplete"
           placeholder="Start typing..." role="combobox" value="">
    <button class="_toggleButton_d7ago_32">...</button>
  </div>
</div>
```
```html
<div class="_fieldEntry_1e3gg_28 ashby-application-form-field-entry" data-field-path="295ef7c6-521d-4b0f-b168-3cb291d24585">
  <label class="_heading_f7cvd_52 _required_f7cvd_91 _label_1e3gg_42 ashby-application-form-question-title" for="295ef7c6-521d-4b0f-b168-3cb291d24585">
    Are you in an Americas time zone?
  </label>
  <div class="_container_1svni_28 ashby-application-form-input-yesno">
    <button class="ashby-application-form-input-yesno-option" data-option="yes">Yes</button>
    <button class="ashby-application-form-input-yesno-option" data-option="no">No</button>
    <input type="checkbox" name="295ef7c6-521d-4b0f-b168-3cb291d24585">
  </div>
</div>
```

#### Why it Broke:
1. **Missing `id` on autocomplete input:** The `<label for="_systemfield_location">` points to `_systemfield_location`, but the `<input>` has **NO `id` attribute**! It only lives inside `data-field-path="_systemfield_location"`.
   - `_labels(form)` looks for `label[for=el.id]`. Since `el.id` is empty, the label is empty, so "What country are you based in?" is never filled.
2. **Missing `id` on Yes/No input:** The `<label for="<uuid>">` points to the question UUID, but the hidden checkbox has `name="<uuid>"` and **NO `id`**. The buttons are `<button data-option="yes">` and `<button data-option="no">`.
   - Result: "Are you in an Americas time zone?" and Chatbase's "I am based in Cairo or happy to relocate there.*" are left unclicked.
3. **Client-side validation blocks submit:** Both fields have class `_required_f7cvd_91` (or `*`). When `submit.first.click()` is clicked, Ashby displays inline validation errors, the form does NOT submit, and after polling 12s, the runner marks it as `submission_uncertain`.

---

### B. Workable ATS Cookie Banner (#41 Foodics)
- **Error:** `TimeoutError` when clicking submit.
- **Proof:** OCR on `logs/submit_after_41.png`:
  `"cookies to improve user's experience, personalise ads and analyse traffic. You can accept all, decline all optional cookies..."`
- A full-screen/fixed-bottom cookie consent dialog intercepted Playwright clicks on the application form.

---

### C. Multi-Step Questionnaire (#47 Askable)
- **Error:** `submission_uncertain`.
- **Proof:** OCR on `logs/submit_after_47.png`:
  `"Thanks, Mohamed. A few quick questions to finish your application. About 2 minutes. Which best describes your current or most recent role? [ ] Software engineer / developer ..."`
- The contact step was submitted, but the runner treated the next step as a static page or uncertain submit rather than advancing through the second questionnaire screen.

---

### D. Why the 67 Jobs Were Auto-Skipped
Here is the exact SQLite breakdown from `jobs.sqlite3`:
1. **32 listings:** `remote role does not confirm that applicants in egypt/worldwide are eligible`
   - Listings on Jobicy/Himalayas with generic "Remote" or unstated regions.
   - *Question for Claude:* Should generic "Remote" without country restrictions be treated as eligible or have an optional toggle?
2. **23 listings:** `No supported ATS or explicit public employer application form was found`
   - Aggregators (Himalayas, Remotive) linking to external signups or account-gated pages.
3. **14 listings:** Scored below the automatic threshold (70/100).
4. **10 listings:** `Full employer description is unavailable`
   - Startup.jobs RSS feed returns HTTP 403 (Cloudflare block) when attempting to fetch full description.

---

## 4. Specific Action Items Needed in `application_automation.py`

1. **Ashby Container & Field-Path Matching:**
   - In `_labels()` or Ashby-specific logic, find fields by `.ashby-application-form-field-entry` or `[data-field-path]`.
   - Match label from `label.ashby-application-form-question-title` or parent container.
   - Handle autocomplete inputs (`.ashby-application-form-input-autocomplete` / `role="combobox"`):
     - For `_systemfield_location` / country: type "Egypt", wait for dropdown option, click "Egypt".
   - Handle Ashby Yes/No buttons:
     - For "Are you in an Americas time zone?": click `data-option="no"`.
     - For "I am based in Cairo or happy to relocate there": click `data-option="yes"`.
     - For general yes/no, resolve using verified profile/saved answers bank.
2. **Dismiss Cookie Banners (Workable / Greenhouse):**
   - Click "Accept all", "Accept cookies", or "Agree" if cookie banners appear on Workable or other ATS pages before interacting with forms.
3. **Multi-Step Form Advancement:**
   - Detect questionnaires that follow initial contact info (e.g. Askable) and select the matching single-choice option ("Software engineer / developer").

---

## 5. Candidate Answers & Profile Confirmed Answers Bank

These values are now stored and verified in `candidate_profile.json` and `application_answers.json`:

1. **Portfolio URL**: `https://mohamed-ahmed-five.vercel.app/`
2. **LinkedIn URL**: `https://www.linkedin.com/in/mohamed-ahmed-mahmoud-766912268/`
3. **GitHub URL**: `https://github.com/hazalkoom`
4. **Twitter / X Link**: Leave blank / empty (not provided).
5. **Universal "Why do you want to join us / work for us?" (Non-specific)**:
   > "I am excited to join an ambitious engineering team where I can apply my experience in building scalable REST APIs, reliable backend services, and clean web applications. I thrive in collaborative, fast-paced environments where code quality, system performance, and continuous learning are valued, and I am eager to contribute immediately while growing alongside talented engineers."
6. **Timezone Overlap**:
   - Resend question: *"Are you in an Americas time zone?"* -> Answer: **No** (Location is Cairo, Egypt / UTC+2 / EET).
   - Overlap question: *"Are you comfortable with 3-4 hours overlap with US Eastern (EST) or European (CET)?"* -> Answer: **Yes**.
7. **Compensation Expectation**:
   - When asked in USD: **$1,000 – $1,500 / month** (target: **$1,200/month** or **$15,000/year**).
   - When asked in EGP: **20,000 EGP / month net** (range: 15,000 – 25,000 EGP).
8. **Work Authorization / Relocation**:
   - Location: Cairo, Egypt.
   - For remote worldwide / Egypt: Authorized / Contractor ready.
   - For onsite US / UK / Europe: Requires visa sponsorship.
