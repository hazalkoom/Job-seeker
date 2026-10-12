# Personal Job Hunter v2

A personal Python job-search service that collects listings from remote-job APIs and company career systems, filters them against your constraints, stores results in SQLite, and sends confirmed junior developer matches to Telegram. Review candidates are stored but notifications are disabled by default.

## Your matching rules

- **On-site/hybrid:** Cairo or Mansoura only.
- **Remote jobs based in Egypt:** accepted when the listing identifies Egypt as a candidate location.
- **International remote:** confirmed only when the source/listing explicitly indicates worldwide or Egypt eligibility. A country-restricted listing that excludes Egypt is rejected. Ambiguous or regional eligibility (such as EMEA) goes to **REVIEW**, not MATCH.
- **Experience:** internship, junior, graduate, or other clear entry-level language; explicit requirements above one year are rejected. Unclear experience goes to REVIEW.
- **Freshness:** only listings with a parseable date within the last seven days can be MATCH/REVIEW. Missing or stale dates are rejected instead of being assumed fresh. If a source only supplies `updated_at`, the listing is REVIEW because its original posting date is not verified.
- **Target roles:** junior/intern/trainee backend, full-stack, software-development, and frontend roles, with relevant Node.js/Express, Django, FastAPI, Python, Angular, or Java experience.
- **Exclude:** senior/staff/principal/lead/head/manager/architect/mid-level roles; Product Engineer, sales, analyst, recruiting, support, QA, DevOps-only, mobile, PHP, and Go-focused titles; and roles that clearly require existing Spring Boot experience.
- **Strict notifications:** the title itself must clearly identify an entry-level role to be sent as a confirmed MATCH. A generic title with entry-level wording only in the description stays REVIEW and is not sent by default.

No keyword matcher can perfectly understand every job description. Review candidates are deliberately labelled so you can check the original listing before applying.

## Sources included

Enabled out of the box (no API keys required):

1. RemoteOK public API
2. Remotive public API (multiple search terms, deduplicated)
3. Himalayas public remote-jobs API (multiple search terms)
4. Jobicy public API (recent remote postings, cursor pagination)
5. Arbeitnow public job-board API

Configurable company-direct sources:

6. Greenhouse public Job Board API
7. Lever public postings API
8. Ashby public job-posting API
9. Company career pages that publish `schema.org/JobPosting` JSON-LD
10. User-owned mailbox ingestion for subscribed WUZZUF, LinkedIn, Indeed, and Bayt job-alert emails (opt-in)
11. Configurable public RSS/Atom feeds for boards or company career pages that publish one

The three ATS adapters query published job boards using the company's real board/site slug. They are intentionally configurable: board identifiers must be taken from the employer's official careers page rather than guessed. The generic career-page adapter reads structured `JobPosting` data; it will not execute client-side JavaScript or scrape a page that does not expose structured postings.

### Add WUZZUF, LinkedIn, Indeed, and Bayt alerts

The project does **not** scrape logged-in job-board pages. LinkedIn explicitly prohibits third-party scraping and automated access, and Indeed API access is governed by approval and program terms. Instead, the new email-alert collector imports job links from alerts that you choose to subscribe to and receive in your own mailbox. WUZZUF's user agreement also limits use of its materials, so this avoids building a direct scraper against the site.

1. Create job alerts on WUZZUF, LinkedIn, Indeed Egypt, and Bayt for terms such as `junior backend`, `Node.js`, `Python`, `Django`, `FastAPI`, `Angular`, and `full stack`. Use Cairo/Mansoura for local searches and Remote for remote searches. Set LinkedIn alerts to email delivery.
2. For Gmail, enable 2-Step Verification and create an **App Password** for this project. Do not put your normal Gmail password in `.env`. For other providers, use their documented IMAP access and an app-specific password where available.
3. Edit `.env` and set:

   ```dotenv
   ENABLE_EMAIL_ALERTS=true
   EMAIL_ALERTS_IMAP_HOST=imap.gmail.com
   EMAIL_ALERTS_IMAP_PORT=993
   EMAIL_ALERTS_USERNAME=your-alert-mailbox@gmail.com
   EMAIL_ALERTS_PASSWORD=your-16-character-app-password
   EMAIL_ALERTS_MAILBOX=INBOX
   EMAIL_ALERTS_LOOKBACK_DAYS=14
   EMAIL_ALERTS_MAX_MESSAGES=300
   ```

4. Run `python debug_matches.py` first. The collector only accepts links from supported job-board domains and attempts to extract the posting date from the alert card. If the actual posting date is missing from the email, it deliberately leaves the date unknown; the existing matcher then rejects the listing rather than incorrectly treating the email's received date as the job's posting date.
5. Run `python run_once.py` after reviewing the debug output. Repeated alert emails are deduplicated by canonical job URL and the database prevents repeat notifications.

The collector reads recent messages without marking them as read. It searches each supported sender domain separately before checking a small recent-inbox fallback, so a busy Indeed inbox is less likely to crowd out WUZZUF or LinkedIn alerts. `EMAIL_ALERTS_MAX_MESSAGES` is the cap per supported sender domain. Tracking parameters are removed from WUZZUF/LinkedIn/Bayt links and from Indeed links except for the job key, helping repeated digests deduplicate correctly.

### Add public RSS/Atom feeds

If a job board or employer publishes a public RSS/Atom feed, add it to `.env`:

```dotenv
ENABLE_RSS_FEEDS=true
RSS_FEEDS=Board Name|https://example.com/jobs.rss;Company Careers|https://company.example/jobs.xml
```

Use only feed URLs that the site makes available for this purpose. Feed entries must include a real job URL and a parseable publication date to qualify for matching. This source is optional and has no effect until `RSS_FEEDS` is populated.

API references:
- Greenhouse: https://docs.greenhouse.io/job-board.html
- Lever: https://github.com/lever/postings-api
- Ashby: https://developers.ashbyhq.com/docs/public-job-posting-api
- Himalayas: https://himalayas.app/docs/remote-jobs-api
- Jobicy: https://jobicy.com/jobs-rss-feed

### Why the job-board email route is used

This project does not bypass logins, CAPTCHAs, access controls, or scrape private endpoints. LinkedIn explicitly prohibits third-party scraping and automated access; Indeed API access is restricted by its developer terms and approval process. Use official alerts/feeds or a permitted provider for sites without a public API. The alert-email collector is an opt-in way to include these boards without adding direct scraping.

## Setup on Linux

Run these from the extracted `job-hunter-v2` directory.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` and add your existing Telegram bot token and chat ID:

```dotenv
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id
```

Keep `.env` private; it is ignored by Git.

### Updating from your previous project

Extract this release into a **new folder** first. Copy your old `.env` into the new folder so your Telegram credentials are retained. If you want to keep your existing SQLite history, copy the old `jobs.sqlite3` into the new folder or set `DATABASE_PATH` in `.env` to its existing absolute path. The database migration adds the new columns without intentionally deleting existing rows. Back up the database before upgrading.

## Add company career sources

### Greenhouse

Find the employer's official careers URL. If it points to `https://boards.greenhouse.io/COMPANY_SLUG`, add the display name and slug:

```dotenv
GREENHOUSE_BOARDS=Company Name:COMPANY_SLUG;Another Company:ANOTHER_SLUG
```

The collector uses the public endpoint `https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true`.

### Lever

For a company hosted at `https://jobs.lever.co/COMPANY_SLUG`, add:

```dotenv
LEVER_SITES=Company Name:COMPANY_SLUG
```

### Ashby

For a company hosted on an Ashby job board, use the board name shown by its official careers URL:

```dotenv
ASHBY_BOARDS=Company Name:BOARD_NAME
```

### Structured-data career pages

For a public careers page that includes `JobPosting` JSON-LD:

```dotenv
CAREER_PAGES=Company Name|https://company.example/careers;Another Company|https://another.example/jobs
```

Do not put semicolons or pipe characters inside a company name or URL because those delimit the `.env` list. After changing `.env`, rerun the command; settings are loaded at process startup.

**Suggested company targets to check manually:** Vodafone/VOIS, Valeo, Breadfast, Money Fellows, Instabug, MNT-Halan, Giza Systems, ITWorx, Orange Egypt, Raya, Capgemini and IBM. This is a research list, not a claim that every company currently has a matching vacancy or uses one of the supported ATS systems.

## Run it

One search run:

```bash
python run_once.py
```

The JSON report includes source counts, source errors, confirmed matches, review candidates, rejection counts, and the most common rejection reasons.

Inspect sample candidates and rejection reasons without sending Telegram messages:

```bash
python debug_matches.py
```

Run the tests:

```bash
pytest -q
```

Start the optional local API:

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Then open `http://127.0.0.1:8000/health` or `http://127.0.0.1:8000/docs`. The `/run-once` endpoint triggers a search and sends notifications; keep this service bound to localhost and do not expose it to the public internet.

## Telegram behavior

- Confirmed matches are sent as **MATCH**.
- Only confirmed junior matches are sent by default.
- Uncertain candidates are stored as REVIEW but not sent unless `NOTIFY_REVIEW_CANDIDATES=true` is explicitly enabled.
- Each job is stored in SQLite and notified once. If a send fails, it remains eligible to be retried on a later run.

## Database

SQLite defaults to `jobs.sqlite3` in the project directory. Override with `DATABASE_PATH=/absolute/path/jobs.sqlite3`. The database stores jobs, scores, reasons, concerns, first/last seen timestamps, and notification state.

## Automatic scheduling (recommended when your PC is often off)

A Linux cron job only runs while that Linux installation is powered on. Since you often shut down Linux to use Windows, this release includes a GitHub Actions workflow at `.github/workflows/job-hunter.yml`. It runs twice daily on GitHub's hosted runner, so your own PC can be shut down. The workflow restores and saves the SQLite database as an artifact between runs to preserve deduplication and notification history.

### Enable GitHub Actions

1. Create a **private GitHub repository** for this project and push the project code. Do not upload `.env`, `jobs.sqlite3`, Telegram credentials, or your Gmail app password.
2. In that repository, open **Settings → Secrets and variables → Actions → New repository secret** and add these four secrets:
   - `TELEGRAM_BOT_TOKEN` — your existing Telegram bot token.
   - `TELEGRAM_CHAT_ID` — your existing Telegram chat ID.
   - `EMAIL_ALERTS_USERNAME` — the Gmail inbox Job Hunter should read.
   - `EMAIL_ALERTS_PASSWORD` — that inbox's Gmail App Password, not your normal password.
3. Open **Actions**, enable workflows if GitHub prompts you, and select **Job Hunter**.
4. Click **Run workflow** once to test it immediately. Review the run summary for source counts, matches, Telegram sends, and source errors.
5. After the first successful run, the workflow is scheduled for 06:15 and 18:15 UTC (usually 09:15 and 21:15 in Egypt; local times shift with daylight saving time).

GitHub's scheduled runs can occasionally be delayed, so use the **Run workflow** button for an immediate manual run. The workflow requires a successful push of this release to the repository's default branch. Keep the repository private and keep credentials only in GitHub Actions secrets. GitHub-hosted runners are temporary, so the workflow's artifact step is important: it preserves the SQLite history between runs. If artifacts are deleted or expire after 90 days, the next run starts with a fresh database and may resend old matches from the source lookback window.

### Local Linux cron (only if Linux is left on)

If you ever want local scheduling while Linux is running, edit your crontab with `crontab -e` and add a line using absolute paths:

```cron
30 8 * * * cd /absolute/path/job-hunter-v2 && /absolute/path/job-hunter-v2/.venv/bin/python run_once.py >> /absolute/path/job-hunter-v2/job-hunter.log 2>&1
```

Cron cannot run while the computer is shut down or booted into Windows. Do not configure local cron and GitHub Actions at the same time unless you deliberately want both runs.

## Troubleshooting

- `telegram_configured: false`: check `.env`, the token and chat ID, and ensure the bot has received a message from you.
- A source error: inspect the `source_errors` array. Public APIs may rate-limit or change their schema; a failure in one source does not stop the others.
- Zero matches: run `python debug_matches.py`. Review the rejection breakdown before changing requirements.
- ATS source returns zero: verify the board/site slug from the company's official careers page.
- Career page source returns zero: the page may render listings using JavaScript rather than JSON-LD. Use its supported ATS adapter if available.
- No listing date: the system rejects it rather than guessing that it is new. This protects the seven-day rule.

## Project structure

```text
app/
  config.py
  main.py
  matching.py
  models.py
  runner.py
  storage.py
  telegram.py
  sources/
    arbeitnow.py
    remoteok.py
    remotive.py
    himalayas.py
    jobicy.py
    greenhouse.py
    lever.py
    ashby.py
    career_pages.py
    common.py
run_once.py
debug_matches.py
requirements.txt
.env.example
tests/test_matching.py
```
