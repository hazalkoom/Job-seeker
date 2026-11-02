# Job Hunter — Claude Engineering Handover & Architecture Guide

## 1. Executive Summary & Purpose
**Job Hunter** is an autonomous Python & Playwright pipeline designed to run 4x daily on GitHub Actions (and locally) to:
1. Ingest job postings across 10+ sources (Ashby, Greenhouse, Lever, Workable, SmartRecruiters, Google Jobs, European Tech Opportunities, RemoteOK, Himalayas, Jobicy, Arbeitnow, and RSS feeds).
2. Filter & score listings against candidate criteria (Location/Egypt eligibility, junior/mid experience level <= 2 years, core tech stacks).
3. Select role-tailored 1-page PDF CVs (Backend, Full-Stack, Frontend, QA, App Support, IT Support).
4. Automate browser-based ATS form submission via Playwright headless Chromium.
5. Report all confirmed submissions, review cards, and run metrics directly to Telegram.

---

## 2. Root Cause: Why Telegram Reported "0 Submitted / 3 Auto-Skipped"

In the latest GitHub Actions cycle, the bot reported:
* `• AI Workflow Engineer at Basata Inc — auto_skipped`
* `• Junior Technical Support Specialist (U.S. Bank) — auto_skipped`
* `• AI Automation Engineer (Airtm) — auto_skipped`

### The 3 Core Bottlenecks:
1. **Overly Strict Qualification Filters (`app/matching.py` & `app/application_automation.py`):**
   * The policy filters out titles containing `AI Workflow Engineer` or `AI Automation Engineer` because legacy filters in `IRRELEVANT_TITLE` and `_reason_for_auto_skip` tagged them as "AI research/non-developer".
   * For international companies like U.S. Bank, the description contains strict geographic/US residency clauses (`"must be authorized to work in the US"`), which rightly failed the candidate location gate (`egypt_eligibility_unconfirmed`).
2. **Conservative Qualification Gate on Form Submission:**
   * In `app/application_automation.py`, `_reason_for_auto_skip` only approves jobs with status `"match"`. If a job has status `"review"` (due to vague experience wording or missing salary tags), it is auto-skipped instead of being attempted.
3. **Modern SPA Form Elements (Ashby, Greenhouse, Workable):**
   * **Ashby:** Invisible Google reCAPTCHA Enterprise was triggering a false-positive challenge abort in `_is_challenge()`.
   * **Greenhouse:** Uses `react-select` virtual DOM dropdowns and multi-checkbox fieldsets (`question_69583802[]`), which standard HTML form scripts struggle to interact with.
   * **Workable:** Wraps radio buttons in custom styled SVG containers where standard `.check()` requires forced label events.

---

## 3. High-Priority Tasks for Claude to Upgrade & Fix

### Priority 1: Relax and Modernize Job Matching (`app/matching.py`)
* **Allow AI Workflow & Automation Roles:** Remove `ai automation`, `workflow engineer`, `ai integration` from `IRRELEVANT_TITLE`. The candidate actively wants AI software development/integration roles!
* **Allow Auto-Submit for High-Scoring "Review" Jobs:** In `app/application_automation.py`, if a job has `score >= 70` and candidate eligibility is confirmed (Egypt or global remote), allow automatic application even if classified as `"review"`.
* **Lower False-Positive Location Drops:** Ensure EMEA, MENA, Africa, UTC+1 to UTC+3, and Worldwide remote roles without country exclusions are treated as fully eligible.

### Priority 2: Improve Browser Form Automation (`app/application_automation.py`)
* **Robust SPA Dropdown Handling:** Support `react-select` (Greenhouse, Lever) by clicking the control container, typing the target country/value, and hitting `Enter`.
* **Multi-Checkbox Array Mapping:** Support Greenhouse checkbox groups (e.g. `Which areas of engineering interest you?`) by checking matching option labels (e.g., `Ubuntu Server`, `Commercial Systems`, `Cloud`).
* **Handle Multi-Step ATS Wizards:** Some Workable and SmartRecruiters postings have Step 1 (Personal Info) -> Next -> Step 2 (Questions). Add next-button progression before form submission.

### Priority 3: Add More Direct ATS Companies (`data/ats_companies.csv`)
* Expand the board list for Ashby, Greenhouse, Lever, and Workable with companies hiring remote developers in EMEA/Egypt.

---

## 4. Candidate Information (Mohamed Ahmed Mahmoud)

* **Full Name:** Mohamed Ahmed Mahmoud
* **Location:** Cairo, Egypt (GMT+2)
* **Email:** `hazalkoom048@gmail.com` | **Phone:** `+20 109 078 4033`
* **LinkedIn:** `https://www.linkedin.com/in/mohamed-ahmed-mahmoud-766912268/`
* **GitHub:** `https://github.com/hazalkoom`
* **Education:**
  * Bachelor of Tourism and Hospitality, Mansoura University (Graduated Nov 2026, Grade: Good / GPA 3.0)
  * Diploma in Software Engineering (Computer Science), EPIC Institute of Technology
* **Military Status:** Exempted (معافى نهائي)
* **High School:** Top 10% in Mathematics and Native Language (Arabic)
* **Demographics (for EEO forms):** Male, Middle Eastern, Non-Hispanic, No disability, Not a veteran, Age: 22
* **Target Roles:**
  * Junior Software Engineer
  * Backend Developer (Node.js, Express, Python, FastAPI, Django, PostgreSQL, Redis, Docker)
  * Frontend Developer (React, Next.js, Angular, TypeScript, Tailwind CSS)
  * Full Stack Developer
  * Application Support & Technical Support Engineer
  * Junior QA & Software Testing Engineer (Jest, pytest, API testing)
  * IT Support & Systems Engineer
* **Salary Target:** 15,000 – 25,000 EGP / month net (or equivalent in USD/EUR for foreign contracts: $400 - $800/mo)
* **Work Preference:** Remote from Egypt, or on-site/hybrid in Cairo/Giza/Mansoura/Smart Village. Willing to travel internationally 2-4 times a year for company offsites.

---

## 5. Verified Candidate Projects (DO NOT INVENT OTHER PROJECTS)

1. **SmartCart Full-Stack E-Commerce Platform:**
   * Tech: TypeScript, React/Next.js, Node.js, Express.js, PostgreSQL, MongoDB, Redis, Docker, Paymob.
   * Highlights: 50+ RESTful APIs, checkout & payment webhooks, BullMQ asynchronous queues, 200+ Jest automated tests.
2. **AeroLock — Real-Time Distributed Services Engine:**
   * Tech: Python, FastAPI, gRPC, PostgreSQL, Redis Redlock, WebSockets, Azure Cloud, K3s.
   * Highlights: Microservices architecture, Redis distributed locking for multi-node concurrency control.
3. **RealEstate Engine — Modular Backend Platform:**
   * Tech: Python, Django, PostgreSQL, GraphQL, pytest, Qdrant Vector DB.
   * Highlights: Eliminated N+1 bottlenecks using GraphQL DataLoaders, validated domain logic with pytest.
4. **Cantera Scientific Engine (Open Source Contributor):**
   * Tech: C++, Python, Linux, GitHub Actions CI/CD matrix build pipelines.
   * Highlights: Resolved memory leaks, runtime crashes, and cross-platform build toolchain failures.

---

## 6. How to Run & Test Locally

```bash
# 1. Install dependencies
pip install -r requirements.txt
python -m playwright install --with-deps chromium

# 2. Run unit test suite (151 tests)
pytest -q

# 3. Dry-run a specific job form without submitting
python scripts/dry_run_form.py "<job_or_ats_url>"

# 4. Generate the 1-page role CVs
python scripts/generate_role_cvs.py

# 5. Run full search and apply cycle locally
python run_once.py
```
