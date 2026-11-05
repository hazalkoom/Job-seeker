# Job Hunter Features & Capabilities

Job Hunter 4.0 Autopilot is an intelligent, bounded job discovery, qualification, and application ecosystem designed specifically for developers based in Egypt seeking early-career software roles locally and worldwide.

---

## 1. Multi-Source Ingestion Engine (17+ Channels)

Job Hunter aggregates job postings across public APIs, developer communities, career pages, RSS feeds, and email alerts without requiring paid aggregators.

| Connector Name | Module | Type | Target Scope |
|---|---|---|---|
| **Greenhouse** | [`app/sources/greenhouse.py`](file:///run/media/hazalkoom/FD16124010E85459/job-hunter/Job-Seeker-push-20261019-121011/app/sources/greenhouse.py) | Public ATS API | 30+ Tech companies (Canonical, GitLab, Stripe, Elastic, Reddit, Mozilla, etc.) |
| **Ashby** | [`app/sources/ashby.py`](file:///run/media/hazalkoom/FD16124010E85459/job-hunter/Job-Seeker-push-20261019-121011/app/sources/ashby.py) | Public ATS API | 17+ Modern scaleups (Supabase, Linear, Replit, Thndr, Neon, Inngest, Weaviate, etc.) |
| **Workable** | [`app/sources/workable.py`](file:///run/media/hazalkoom/FD16124010E85459/job-hunter/Job-Seeker-push-20261019-121011/app/sources/workable.py) | Public ATS API | 18+ Egyptian tech leaders & startups (Instabug, Vezeeta, Robusta, Paymob, Swvl, etc.) |
| **SmartRecruiters** | [`app/sources/smartrecruiters.py`](file:///run/media/hazalkoom/FD16124010E85459/job-hunter/Job-Seeker-push-20261019-121011/app/sources/smartrecruiters.py) | Public ATS API | Enterprise & Egyptian telecoms/fintechs (Vodafone, Orange, Ericsson, Valeo, valU, Fawry, Cegedim) |
| **Lever** | [`app/sources/lever.py`](file:///run/media/hazalkoom/FD16124010E85459/job-hunter/Job-Seeker-push-20261019-121011/app/sources/lever.py) | Public ATS API | Remote-friendly engineering companies (Kraken, Kinsta, etc.) |
| **Recruitee** | [`app/sources/recruitee.py`](file:///run/media/hazalkoom/FD16124010E85459/job-hunter/Job-Seeker-push-20261019-121011/app/sources/recruitee.py) | Public ATS API | European & remote-first tech organizations |
| **BambooHR** | [`app/sources/bamboohr.py`](file:///run/media/hazalkoom/FD16124010E85459/job-hunter/Job-Seeker-push-20261019-121011/app/sources/bamboohr.py) | Public ATS API | Mid-market tech companies & agencies |
| **Breezy HR** | [`app/sources/breezy.py`](file:///run/media/hazalkoom/FD16124010E85459/job-hunter/Job-Seeker-push-20261019-121011/app/sources/breezy.py) | Public ATS API | Modern remote-friendly startups |
| **Hacker News "Who is hiring?"** | [`app/sources/hn_jobs.py`](file:///run/media/hazalkoom/FD16124010E85459/job-hunter/Job-Seeker-push-20261019-121011/app/sources/hn_jobs.py) | Algolia HN API | Monthly Y Combinator hiring threads parsed for direct ATS links |
| **Himalayas** | [`app/sources/himalayas.py`](file:///run/media/hazalkoom/FD16124010E85459/job-hunter/Job-Seeker-push-20261019-121011/app/sources/himalayas.py) | Public JSON API | Remote jobs with structured timezone and country eligibility constraints |
| **Jobicy** | [`app/sources/jobicy.py`](file:///run/media/hazalkoom/FD16124010E85459/job-hunter/Job-Seeker-push-20261019-121011/app/sources/jobicy.py) | Public JSON API | Worldwide remote software engineering listings |
| **RemoteOK** | [`app/sources/remoteok.py`](file:///run/media/hazalkoom/FD16124010E85459/job-hunter/Job-Seeker-push-20261019-121011/app/sources/remoteok.py) | Public JSON API | Global remote software engineering roles |
| **Remotive** | [`app/sources/remotive.py`](file:///run/media/hazalkoom/FD16124010E85459/job-hunter/Job-Seeker-push-20261019-121011/app/sources/remotive.py) | Public JSON API | Curated software developer listings |
| **Arbeitnow** | [`app/sources/arbeitnow.py`](file:///run/media/hazalkoom/FD16124010E85459/job-hunter/Job-Seeker-push-20261019-121011/app/sources/arbeitnow.py) | Public JSON API | European remote listings with visa sponsorship/remote flags |
| **European Tech Opportunities** | [`app/sources/european_tech_opportunities.py`](file:///run/media/hazalkoom/FD16124010E85459/job-hunter/Job-Seeker-push-20261019-121011/app/sources/european_tech_opportunities.py) | Public REST API | Junior/intern/graduate tech opportunities in Europe & remote |
| **Nomado24** | [`app/sources/nomado24.py`](file:///run/media/hazalkoom/FD16124010E85459/job-hunter/Job-Seeker-push-20261019-121011/app/sources/nomado24.py) | Public JSON API | Entry-level international remote roles |
| **Email Job Alerts** | [`app/sources/email_alerts.py`](file:///run/media/hazalkoom/FD16124010E85459/job-hunter/Job-Seeker-push-20261019-121011/app/sources/email_alerts.py) | Gmail IMAP SSL | Subscribed search alerts (LinkedIn, Indeed, Wuzzuf, Bayt, Glassdoor) |
| **RSS / Atom Feeds** | [`app/sources/rss_feeds.py`](file:///run/media/hazalkoom/FD16124010E85459/job-hunter/Job-Seeker-push-20261019-121011/app/sources/rss_feeds.py) | XML Feeds | We Work Remotely (Backend & Full Stack), Startup.jobs feeds |
| **Google Jobs via SerpAPI** | [`app/sources/google_jobs.py`](file:///run/media/hazalkoom/FD16124010E85459/job-hunter/Job-Seeker-push-20261019-121011/app/sources/google_jobs.py) | SerpAPI | Rotating query matrix targeting Egypt and remote roles |

---

## 2. Explainable Qualification & Eligibility Engine

Rather than relying on brittle LLM prompts or simple keyword matches, [`app/matching.py`](file:///run/media/hazalkoom/FD16124010E85459/job-hunter/Job-Seeker-push-20261019-121011/app/matching.py) uses transparent, deterministic rules that produce concrete evidence lists for every decision:

### Strict Experience Limit
- Extracts mandatory professional experience sentences (e.g., `"Requires 3+ years of experience in backend development"`).
- Rejects any posting where mandatory requirements exceed `MAX_REQUIRED_EXPERIENCE_YEARS` (default: **2.0 years**).
- Items where extra experience is explicitly described as "preferred" or "nice-to-have" are promoted to `review`, not rejected.

### Hard Stack Exclusions
- Automatically rejects postings whose primary title focuses on non-target stacks:
  - `.NET`, `C#`, `ASP.NET`
  - `Ruby`, `Ruby on Rails`
  - `PHP`, `Laravel`, `Symfony`
  - `Go`, `Golang`
  - `C++`, `Rust`, `Scala`, `Elixir`, `Kotlin`, `Swift`, `Flutter`

### Language Barrier Gate
- Rejects roles where non-English language fluency is mandatory (e.g., German, French, Spanish, Italian, Dutch, Polish, Russian, Turkish).
- Rejects foreign title variants such as German `Entwickler(in)`.

### Location & Remote Eligibility Rules
1. **Local Workplace Mode**:
   - Accepts all workplace modes (`on-site`, `hybrid`, `remote`) in Greater Cairo, Giza, Smart Village, Mansoura, New Cairo, Maadi, 6th of October, and Sheikh Zayed.
2. **International Remote Mode**:
   - Accepts remote listings outside Egypt when the description explicitly confirms worldwide eligibility (`"worldwide"`, `"anywhere"`, `"work from anywhere"`), mentions Egypt/EMEA, or originates from a company verified to hire in Egypt (`EGYPT_HIRING_COMPANIES`: Supabase, Canonical, GitLab, Automattic, Deel, Remote, Toptal, etc.).
   - Rejects roles restricted to US citizens, security clearances, or explicit foreign work authorizations.

---

## 3. Autonomous ATS Form Automation

The automation engine ([`app/application_automation.py`](file:///run/media/hazalkoom/FD16124010E85459/job-hunter/Job-Seeker-push-20261019-121011/app/application_automation.py)) operates headlessly via Playwright with advanced form navigation capabilities:

- **Complex Comboboxes (`react-select`)**: Dynamically clicks, types, waits for async suggestions, and selects unambiguous options (with location fuzzy-matching for `"Cairo, Egypt"`).
- **Ashby Structural Yes/No Buttons**: Interacts with modern CSS-based Yes/No controls and interprets CSS asterisks (`::after`) to identify required fields without native HTML tags.
- **Hidden Styled Radios & Checkboxes**: Force-clicks the parent styled labels to toggle custom SVG checkboxes.
- **Multi-Step Wizards**: Automatically detects when submitting advances to Step 2 (e.g., Workable/SmartRecruiters questionnaires) and completes up to 3 subsequent steps.
- **Cookie Banner Dismissal**: Detects OneTrust and Workable cookie banners and dismisses them before form interactions.
- **PDF Cover Letter Generator ([`app/cover_letter.py`](file:///run/media/hazalkoom/FD16124010E85459/job-hunter/Job-Seeker-push-20261019-121011/app/cover_letter.py))**: Generates standard `%PDF-1.4` cover letters on the fly when file uploads are mandatory.
- **Company Cap Guard**: Enforces a strict limit of **at most 2 applications per company within 30 rolling days**.

---

## 4. Multi-Currency Salary Conversion Engine

Configured with your base target of **12,000 EGP/month** (`144,000 EGP/year`), [`data/fx_rates.json`](file:///run/media/hazalkoom/FD16124010E85459/job-hunter/Job-Seeker-push-20261019-121011/data/fx_rates.json) and [`app/application_automation.py`](file:///run/media/hazalkoom/FD16124010E85459/job-hunter/Job-Seeker-push-20261019-121011/app/application_automation.py) automatically resolve period and currency prompts across major international currencies:

| Currency | Monthly Equivalent | Annual Target |
|---|---|---|
| **EGP (Egyptian Pound)** | `12,000` | `144,000` |
| **USD (US Dollar)** | `222.44` | `2,669` |
| **EUR (Euro)** | `198.20` | `2,378` |
| **GBP (British Pound)** | `165.35` | `1,984` |
| **JPY (Japanese Yen)** | `35,227` | `422,724` |
| **SAR (Saudi Riyal)** | `834.15` | `10,010` |
| **AED (UAE Dirham)** | `816.90` | `9,803` |
| **CAD (Canadian Dollar)** | `308.50` | `3,702` |
| **AUD (Australian Dollar)** | `342.10` | `4,105` |
| **CHF (Swiss Franc)** | `196.40` | `2,357` |

*Note: Hourly prompts return `None` and are flagged for human review to prevent accidental low rate submissions.*

---

## 5. Per-Skill Experience Matrix

When forms ask numeric questions such as *"How many years of Python experience do you have?"*, the engine resolves the exact verified years table:

| Technology / Skill | Configured Experience |
|---|---|
| **Python** | 3 years |
| **JavaScript / Node.js / Express** | 3 years |
| **Django** | 2 years |
| **TypeScript / Angular** | 2 years |
| **PostgreSQL / SQL / Redis / Mongo** | 2 years |
| **Docker / Linux / Ubuntu / Bash / Git** | 2 years |
| **React** | 1 year |
| **FastAPI** | 1 year |
| **QA / Testing / Pytest / Jest** | 1 year |
| **Kubernetes / K3s** | 1 year |
| *Unlisted skill / Rust / Ruby / etc.* | `0` years |

---

## 6. Question Ledger & Self-Learning Telegram Digest

When the headless browser encounters a required question that has no verified answer in `application_answers.json`:

1. It marks the field as a blocker and aborts the submission safely without guessing.
2. It logs the exact question text, field type, company, ATS host, and **full HTML snippet** to SQLite (`question_ledger`) and `data/pending_questions.json`.
3. At the end of the run, the Telegram bot sends a **`❓ Questions Needed to Unlock Skipped Forms`** digest listing the pending questions with their options and occurrences.
4. Once you add the answer to `application_answers.json` and re-encrypt, future runs will automatically answer that question.

---

## 7. 1-Tap Manual Cards for Login-Gated Boards

Because Job Hunter adheres strictly to ethical automation, it **never** automates logins on LinkedIn, Indeed, Wuzzuf, or Glassdoor:

1. When a high-scoring listing (`60+`) is found on an alert aggregator, the system first attempts to resolve the employer's direct public ATS link.
2. If no direct ATS exists, it generates a **1-Tap Manual Apply Card** delivered to Telegram.
3. The card includes direct links, the optimal matching tailored CV, and quick-copy links (Portfolio, LinkedIn, GitHub).

---

## 8. Read-Only Gmail Application Inbox Reconciler

[`app/sources/application_inbox.py`](file:///run/media/hazalkoom/FD16124010E85459/job-hunter/Job-Seeker-push-20261019-121011/app/sources/application_inbox.py) logs into your Gmail via SSL with strict `readonly=True` to track application lifecycles without altering your mailbox:

- **Confirmations**: Correlates receipt emails (`"Thank you for applying to..."`) with pending queue items and promotes their state to `submitted`.
- **Interviews**: Flags incoming interview invitations or screening questionnaires.
- **Rejections**: Records rejection notices for historical tracking.

---

## 9. Diagnostic & Operations CLI Toolkit (`python -m jobhunter`)

Full command-line toolkit to audit the system locally:

- `python -m jobhunter audit funnel`: Displays the full 7-stage conversion funnel and queue status breakdown.
- `python -m jobhunter sources health`: Probes the ATS company database and tests endpoint connectivity.
- `python -m jobhunter ats probe <company>`: Checks if a given company has a live ATS page.
- `python -m jobhunter ats discover <url>`: Crawls a careers page, extracts ATS iframes/links, and probes them.
- `python -m jobhunter form inspect <url>`: Opens any ATS job page headlessly, dumps all detected fields, and previews resolved answers without submitting.
- `python -m jobhunter questions gaps`: Lists unanswered required questions.
- `python -m jobhunter inbox status`: Inspects recent Gmail interview and confirmation messages.
- `python -m jobhunter report html`: Generates a static HTML dashboard at `logs/dashboard.html`.
