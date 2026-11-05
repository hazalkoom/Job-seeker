# Configuration Reference — Job Hunter v4.0.0

This document is the comprehensive reference for all configuration files, environment variables, profile definitions, and dynamic data tables used across Job Hunter v4.0.0 Autopilot.

---

## 1. Overview of Configuration Layers

Job Hunter separates public code and operational knobs from private candidate identity:

```
┌────────────────────────────────────────────────────────────────────────┐
│                        CONFIGURATION HIERARCHY                         │
├────────────────────────────────────────────────────────────────────────┤
│ 1. Environment (.env)                                                  │
│    - API keys, source toggles, operational bounds, thresholds          │
│                                                                        │
│ 2. Candidate Profile (candidate_profile.json / .gpg)                   │
│    - Verified identity, contact info, per-skill experience matrix     │
│                                                                        │
│ 3. Application Answer Bank (application_answers.json / .gpg)           │
│    - Form field matching rules, multi-choice choices, Yes/No answers   │
│                                                                        │
│ 4. ATS Registry (data/ats_companies.csv)                               │
│    - 75+ verified company career boards across Greenhouse, Ashby, etc. │
│                                                                        │
│ 5. FX Rates (data/fx_rates.json)                                       │
│    - Canonical salary targets based on 12,000 EGP/mo across currencies │
└────────────────────────────────────────────────────────────────────────┘
```

> [!IMPORTANT]
> Files containing personal contact info, CV PDFs, or application answers must **never** be committed in plaintext to public git. They are committed only as GPG-encrypted blobs (`.gpg`) and decrypted during GitHub Actions runs or local execution.

---

## 2. Environment Variables (`.env`)

All settings in `app/config.py` can be set via `.env` or standard process environment variables.

### 2.1 Core System & Run Knobs

| Variable | Type | Default | Description |
|---|---|---|---|
| `DATABASE_PATH` | string | `jobs.sqlite3` | Absolute or relative path to the SQLite application database. |
| `REQUEST_TIMEOUT_SECONDS` | float | `18.0` | Default timeout in seconds for HTTP requests to external job APIs. |
| `MAX_POSTING_AGE_DAYS` | integer | `7` | Maximum age of a job posting in days before it is considered stale and skipped. |
| `ALLOW_REGIONAL_EMEA` | boolean | `true` | Allows regional EMEA listings when applicants in Egypt are not excluded. |

### 2.2 Qualification & Matching Rules

| Variable | Type | Default | Description |
|---|---|---|---|
| `MIN_MATCH_SCORE` | integer | `70` | Score threshold (0–100) required for a job to qualify for immediate alerts. |
| `MAX_REQUIRED_EXPERIENCE_YEARS` | float | `2.0` | Maximum mandatory professional experience in years. Postings requiring >2.0 yrs are rejected. |
| `REQUIRE_FULL_DESCRIPTION_FOR_MATCH` | boolean | `true` | If `true`, a posting cannot be a confirmed `MATCH` if only a summary or metadata is available. |
| `NOTIFY_REVIEW_CANDIDATES` | boolean | `false` | If `true`, sends a separate Telegram digest for jobs classified as `REVIEW`. |
| `REVIEW_DIGEST_SIZE` | integer | `5` | Maximum number of review candidates included in a review digest (1–15). |

### 2.3 Autonomous Application (Autopilot)

| Variable | Type | Default | Description |
|---|---|---|---|
| `AUTO_APPLY_ENABLED` | boolean | `false` | Master opt-in switch. Must be explicitly set to `true` to enable form submissions. |
| `AUTO_APPLY_MAX_PER_DAY` | integer | `25` | Strict daily ceiling on submitted applications across all cycles. |
| `AUTO_APPLY_MIN_SCORE` | integer | `60` | Minimum score required for an eligible job to enter the application queue. |
| `AUTO_APPLY_DELAY_SECONDS` | float | `8.0` | Politeness pause between successive autonomous submissions. |
| `AUTO_APPLY_HEADLESS` | boolean | `true` | Runs Chromium in headless mode. Set to `false` for visual browser debugging. |
| `AUTO_APPLY_RESUME_PATH` | string | `private/Mohamed_Ahmed_CV.pdf` | Path to the PDF resume uploaded to form file input fields. |
| `AUTO_APPLY_TIMEOUT_SECONDS` | integer | `30` | Playwright navigation and fill timeout per form stage (10–90 seconds). |

### 2.4 Notifications (Telegram)

| Variable | Type | Default | Description |
|---|---|---|---|
| `TELEGRAM_BOT_TOKEN` | string | `""` | Telegram Bot token obtained from `@BotFather`. |
| `TELEGRAM_CHAT_ID` | string | `""` | Telegram chat or channel ID where job alerts and manual cards are delivered. |

### 2.5 Ingestion Source Toggles

Every source can be selectively enabled or disabled:

| Variable | Default | Source / Integration |
|---|---|---|
| `ENABLE_GREENHOUSE` | `true` | Greenhouse job boards |
| `ENABLE_LEVER` | `true` | Lever career sites |
| `ENABLE_ASHBY` | `true` | Ashby job boards |
| `ENABLE_WORKABLE` | `true` | Workable job boards |
| `ENABLE_SMARTRECRUITERS` | `true` | SmartRecruiters career portals |
| `ENABLE_RECRUITEE` | `true` | Recruitee company careers |
| `ENABLE_BAMBOOHR` | `true` | BambooHR open positions |
| `ENABLE_BREEZY` | `true` | Breezy HR careers |
| `ENABLE_HN_JOBS` | `true` | Hacker News monthly "Who is hiring?" thread |
| `ENABLE_ARBEITNOW` | `true` | Arbeitnow API |
| `ENABLE_REMOTEOK` | `true` | RemoteOK API |
| `ENABLE_REMOTIVE` | `true` | Remotive API |
| `ENABLE_HIMALAYAS` | `true` | Himalayas API |
| `ENABLE_JOBICY` | `true` | Jobicy API |
| `ENABLE_EUROPEAN_TECH_OPPORTUNITIES` | `true` | European Tech Opportunities API |
| `ENABLE_NOMADO24` | `true` | Nomado24 API |
| `ENABLE_GOOGLE_JOBS` | `true` | Google Jobs via SerpApi |
| `ENABLE_CAREER_PAGES` | `true` | Custom schema.org direct career pages |
| `ENABLE_RSS_FEEDS` | `true` | Public RSS/Atom career feeds |
| `ENABLE_EMAIL_ALERTS` | `false` | IMAP mailbox monitoring for job alerts |

### 2.6 Source-Specific Configurations

#### Google Jobs (SerpApi)
- `SERPAPI_API_KEY`: API key from SerpApi.
- `GOOGLE_JOBS_FIXED_QUERY`: Fixed query run on every cycle (default queries junior backend/full-stack in Egypt).
- `GOOGLE_JOBS_ROTATING_QUERIES`: Semicolon-separated list of queries rotated across scheduled cycles.

#### Email Alerts (IMAP)
- `EMAIL_ALERTS_IMAP_HOST`: IMAP server (e.g. `imap.gmail.com`).
- `EMAIL_ALERTS_IMAP_PORT`: IMAP SSL port (default `993`).
- `EMAIL_ALERTS_USERNAME`: IMAP username (e.g. `your-email@gmail.com`).
- `EMAIL_ALERTS_PASSWORD`: IMAP app password (do NOT use your main Google account password).
- `EMAIL_ALERTS_MAILBOX`: Mailbox folder (default `INBOX`).
- `EMAIL_ALERTS_LOOKBACK_DAYS`: Age limit for alert emails (default `14`).
- `EMAIL_ALERTS_MAX_MESSAGES`: Max emails scanned per cycle (default `300`).

#### Custom Career Pages & RSS Feeds
- `CAREER_PAGES`: Semicolon-separated pairs: `COMPANY|URL;COMPANY|URL`
  - Example: `Canonical|https://canonical.com/careers/all;Instabug|https://instabug.com/careers`
- `RSS_FEEDS`: Semicolon-separated pairs: `LABEL|URL;LABEL|URL`

---

## 3. Candidate Profile Schema (`candidate_profile.json`)

`candidate_profile.json` defines verified facts about the candidate. The automation engine never guesses or hallucinates beyond this file:

```json
{
  "first_name": "Mohamed",
  "last_name": "Ahmed",
  "headline": "Junior Backend / Full-Stack Engineer",
  "email": "candidate@example.com",
  "phone": "+201000000000",
  "location": {
    "city": "Cairo",
    "country": "Egypt",
    "timezone": "Africa/Cairo",
    "remote_preferred": true,
    "willing_to_relocate": true
  },
  "links": {
    "linkedin": "https://www.linkedin.com/in/mohamed-ahmed-mahmoud-766912268/",
    "github": "https://github.com/hazalkoom",
    "portfolio": "https://mohamed-ahmed-five.vercel.app/"
  },
  "work_authorization": {
    "citizen_of": ["Egypt"],
    "requires_us_sponsorship": true,
    "requires_eu_sponsorship": true,
    "authorized_in_egypt": true
  },
  "skills_matrix": {
    "python": 3,
    "django": 2,
    "fastapi": 1,
    "javascript": 3,
    "typescript": 2,
    "angular": 2,
    "react": 1,
    "postgresql": 2,
    "docker": 2,
    "linux": 2,
    "git": 2,
    "qa": 1,
    "kubernetes": 1
  },
  "primary_stacks": [
    "Python", "Django", "FastAPI", "JavaScript", "TypeScript",
    "Angular", "React", "PostgreSQL", "Docker", "Linux", "Git"
  ],
  "excluded_primary_stacks": [
    "Java", "PHP", "Go", "Spring Boot", "Ruby", ".NET", "C++", "C#"
  ],
  "education": {
    "degree": "Bachelor of Science in Computer Science",
    "field_of_study": "Computer Science",
    "graduated": true
  }
}
```

---

## 4. Answer Bank Schema (`application_answers.json`)

The Answer Bank contains structured mappings for question phrases and form fields encountered during ATS interactions:

```json
{
  "exact_mappings": {
    "portfolio": "https://mohamed-ahmed-five.vercel.app/",
    "linkedin": "https://www.linkedin.com/in/mohamed-ahmed-mahmoud-766912268/",
    "github": "https://github.com/hazalkoom",
    "website": "https://mohamed-ahmed-five.vercel.app/",
    "city": "Cairo",
    "country": "Egypt",
    "state": "Cairo"
  },
  "yes_no_questions": {
    "americas_time_zone": "No",
    "us_cet_overlap": "Yes",
    "based_in_cairo_or_relocate": "Yes",
    "authorized_to_work_in_egypt": "Yes",
    "require_sponsorship_us": "Yes",
    "18_years_or_older": "Yes",
    "background_check_consent": "Yes"
  },
  "experience_questions": {
    "years_of_experience_python": "3",
    "years_of_experience_django": "2",
    "years_of_experience_fastapi": "1",
    "years_of_experience_javascript": "3",
    "years_of_experience_typescript": "2",
    "years_of_experience_angular": "2",
    "years_of_experience_react": "1",
    "years_of_experience_postgresql": "2",
    "years_of_experience_docker": "2",
    "years_of_experience_linux": "2",
    "years_of_experience_git": "2",
    "years_of_experience_qa": "1",
    "years_of_experience_kubernetes": "1"
  },
  "generic_free_text": {
    "why_do_you_want_to_work_here": "I am drawn to your mission of building impactful, reliable software. My background in backend development with Python, FastAPI, and Django, coupled with modern frontend experience, aligns well with engineering cultures that value clean architecture, automated testing, and continuous delivery. I am eager to contribute to robust systems and collaborate closely with your engineering team.",
    "additional_information": "Available immediately for remote or Cairo-based positions. Fully equipped home office with high-speed fiber internet and uninterrupted power."
  }
}
```

---

## 5. ATS Company Registry (`data/ats_companies.csv`)

The registry catalogs supported company career boards. Format:

```csv
ats,company,slug
greenhouse,Supabase,supabase
greenhouse,Canonical,canonical
ashby,Linear,linear
ashby,OpenAI,openai
lever,Postman,postman
workable,Foodics,foodics
smartrecruiters,Bosch,bosch
recruitee,TestGorilla,testgorilla
bamboohr,Instabug,instabug
breezy,Vezeeta,vezeeta
```

### Automatic Deduplication
When configured, entries in `data/ats_companies.csv` are automatically merged with any entries defined in the `.env` variables (e.g. `GREENHOUSE_BOARDS`, `ASHBY_BOARDS`), with slugs deduplicated case-insensitively.

---

## 6. Multi-Currency FX Rates (`data/fx_rates.json`)

Standard salary expectations are anchored to 12,000 EGP/month and converted into target figures across currencies:

```json
{
  "base_monthly_egp": 12000,
  "rates": {
    "EGP": {"monthly": 12000, "annual": 144000, "symbol": "EGP"},
    "USD": {"monthly": 222.44, "annual": 2669.28, "symbol": "$"},
    "EUR": {"monthly": 198.20, "annual": 2378.40, "symbol": "€"},
    "GBP": {"monthly": 165.35, "annual": 1984.20, "symbol": "£"},
    "JPY": {"monthly": 35227, "annual": 422724, "symbol": "¥"}
  }
}
```

When an ATS form asks for expected compensation:
- Currency symbol or selector is identified.
- Monthly or annual timeframe is parsed from the question context.
- Exact numeric target is injected without triggering manual reviews or blocking questions.

---

## 7. Encryption & GitHub Actions Secrets

To keep private files safe when pushing code to remote repositories:

```bash
# Encrypt private profile and answers using your passphrase:
bash scripts/prepare_github_autopilot.sh
```

This updates:
- `private/candidate_profile.json.gpg`
- `private/application_answers.json.gpg`
- `private/Mohamed_Ahmed-general.pdf.gpg`

In GitHub Repository Settings -> Secrets and variables -> Actions, configure:
- `JOB_HUNTER_GPG_PASSPHRASE`: Passphrase used for GPG encryption.
- `TELEGRAM_BOT_TOKEN`: Bot token for alerts.
- `TELEGRAM_CHAT_ID`: Telegram chat ID.
- `SERPAPI_API_KEY`: (Optional) SerpApi key.
- `EMAIL_ALERTS_PASSWORD`: (Optional) Gmail App Password.
- `AUTO_APPLY_ENABLED`: Set to `true` to enable GitHub Actions autonomous submissions.
