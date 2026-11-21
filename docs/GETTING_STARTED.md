# Getting Started with Job Hunter

This guide explains how to install, configure, test, and deploy **Job Hunter 4.0 Autopilot** on your local machine and on GitHub Actions.

---

## 1. Prerequisites

Before setting up, ensure you have the following installed:

- **Python 3.11 or 3.12** (Python 3.13+ is also supported)
- **Git**
- **GnuPG (`gpg`)** (for candidate profile encryption)
- **GitHub CLI (`gh`)** (authenticated via `gh auth login`, needed for GitHub Actions secrets)
- **Google Chrome / Chromium dependencies** (for Playwright headless automation)

---

## 2. Local Installation

### Step 1: Clone & Create Virtual Environment

```bash
# Clone the repository
git clone https://github.com/hazalkoom/Job-seeker.git
cd Job-seeker

# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Upgrade pip and install all required dependencies
pip install --upgrade pip
pip install -r requirements.txt

# Install Playwright browser binaries
playwright install chromium
```

*(On Linux systems, if Playwright complains of missing system libraries, run `playwright install-deps chromium`).*

---

## 3. Configuration Setup

### Step 2: Initialize Environment Variables

Copy the example configuration file:
```bash
cp .env.example .env
```

Open `.env` in your text editor and configure your credentials:

```dotenv
# Telegram Bot Notifications (Optional for offline tests, recommended for autopilot)
TELEGRAM_BOT_TOKEN=123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ
TELEGRAM_CHAT_ID=123456789

# Autonomous Application Settings
AUTO_APPLY_ENABLED=true
AUTO_APPLY_MAX_PER_DAY=50
AUTO_APPLY_MIN_SCORE=60
AUTO_APPLY_HEADLESS=true
AUTO_APPLY_DELAY_SECONDS=8

# Experience & Description Gates
MAX_REQUIRED_EXPERIENCE_YEARS=2
REQUIRE_FULL_DESCRIPTION_FOR_MATCH=true
MIN_MATCH_SCORE=70
MAX_POSTING_AGE_DAYS=7

# SerpAPI for Google Jobs & Deep ATS Discovery (Optional)
SERPAPI_API_KEY=your_serpapi_key_here

# Gmail IMAP for Alert Ingestion & Confirmation Reconciliation (Optional)
ENABLE_EMAIL_ALERTS=true
EMAIL_ALERTS_USERNAME=your_email@gmail.com
EMAIL_ALERTS_PASSWORD=your_16_char_google_app_password
EMAIL_ALERTS_IMAP_HOST=imap.gmail.com
EMAIL_ALERTS_IMAP_PORT=993
```

> [!WARNING]
> `.env` contains private secrets and is listed in `.gitignore`. **Never commit `.env` to git.**

---

## 4. Candidate Profile & Answer Bank Setup

Job Hunter uses two JSON configuration files to answer employer questionnaires truthfully:

1. **[`candidate_profile.json`](../candidate_profile.json)**:
   Contains your personal facts (full name, email, phone, city, country, education history, portfolio, GitHub, LinkedIn URLs, and per-skill years table).

2. **[`application_answers.json`](../application_answers.json)**:
   Contains verified answer mappings (salary targets, military exemption, relocation preferences, work authorization, first degree completion, why this company/role drafts).

3. **CV Files (`cvs/`)**:
   Place your tailored PDFs in the `cvs/` directory. The engine automatically matches the best CV according to the job's title and description:
   - `cvs/Mohamed_Ahmed-Backend.pdf`
   - `cvs/Mohamed_Ahmed-Full_Stack.pdf`
   - `cvs/Mohamed_Ahmed-QA_Testing.pdf`
   - `cvs/Mohamed_Ahmed-Frontend.pdf`
   - `cvs/Mohamed_Ahmed-IT_Support.pdf`
   - `cvs/Mohamed_Ahmed-general.pdf` (fallback default)

---

## 5. Running Job Hunter Locally

### Mode A: Dry-Run Search & Telemetry (No Submissions)
To run a complete search across all enabled sources without submitting applications, set `AUTO_APPLY_ENABLED=false` in `.env` and run:

```bash
python run_once.py
```
This will:
- Ingest postings from all 17+ enabled sources.
- Deduplicate listings and classify them as `match`, `review`, or `reject`.
- Resolve aggregator and alert jobs to public ATS endpoints.
- Save eligible items to `jobs.sqlite3`.
- Send Telegram digests (if configured).

### Mode B: Local Autonomous Apply Run
With `AUTO_APPLY_ENABLED=true` in `.env`:

```bash
python run_once.py
```
This executes the full autopilot loop: ingestion $\to$ qualification $\to$ queue prioritization $\to$ Playwright form filling $\to$ submission $\to$ Gmail reconciliation $\to$ Telegram summary.

### Mode C: Diagnostic CLI Inspection
Use the `jobhunter` command line tool to inspect and test parts of the system:

```bash
# 1. Audit the 7-stage conversion funnel and database queue
python -m jobhunter audit funnel

# 2. Check live connectivity of your ATS company database
python -m jobhunter sources health --limit 10

# 3. Safely preview form fields and answer mappings on any job URL
python -m jobhunter form inspect "https://boards.greenhouse.io/canonical/jobs/12345"

# 4. View pending unanswered questions from the Question Ledger
python -m jobhunter questions gaps

# 5. Check Gmail application confirmations and interviews
python -m jobhunter inbox status --days 7

# 6. Generate an interactive HTML dashboard
python -m jobhunter report html
```

---

## 6. GitHub Actions Autopilot Deployment

Job Hunter is engineered to run unattended on GitHub Actions (**4 times daily at 03:17, 09:17, 15:17, and 21:17 Africa/Cairo time**).

### How to Encrypt & Stage Secrets for GitHub Actions:

Run the automated preparation script:
```bash
bash scripts/prepare_github_autopilot.sh
```

This script:
1. Generates a cryptographically strong 256-bit passphrase.
2. Encrypts `candidate_profile.json`, `application_answers.json`, and `private/Mohamed_Ahmed-general.pdf` into `.gpg` files under `private/`.
3. Automatically sets the `AUTOPILOT_DECRYPTION_PASSPHRASE` secret in your GitHub repository via `gh secret set`.
4. Stages only the encrypted `.gpg` files.

### Deploying to GitHub:

```bash
# Ensure git status only shows encrypted .gpg files and code
git status -s

# Commit and push to main
git commit -m "Deploy Job Hunter Autopilot"
git push origin main

# Trigger an immediate run on GitHub Actions
gh workflow run job-hunter.yml
```

### Inspecting Runs on GitHub Actions:
1. Navigate to **Actions** in your GitHub repository.
2. Select the latest run of **Job Hunter Autopilot**.
3. View the job summary table (submitted count, auto-skipped count, funnel breakdown).
4. Download the `job-hunter-diagnostics-<run_id>` artifact containing redacted audit logs and screenshots.
