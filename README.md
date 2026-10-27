# Job Hunter 2.3.1

A personal job-search assistant focused on junior and early-career backend, full-stack, software, and AI-application roles. It collects public listings, removes duplicates, checks experience and location eligibility using explainable rules, sends bounded Telegram digests, and helps you prepare and track referral outreach.

**The goal is fewer misleading alerts, not the largest possible listing count.** A job title saying “Junior” is not enough if the description requires more experience than your configured limit (two years by default). Likewise, “remote” does not mean that a person living in Egypt can necessarily do the job.

## What's new in 2.3

- Experience requirement extraction with saved evidence from the job description. Mandatory requirements above `MAX_REQUIRED_EXPERIENCE_YEARS` are rejected; above-target items described as preferred go to review.
- A job cannot become a confirmed match when only a summary, metadata/tags, or unknown-quality description is available if `REQUIRE_FULL_DESCRIPTION_FOR_MATCH=true`.
- Bachelor's/Computer Science degree wording is not a rejection rule. This app treats that requirement as satisfied, as requested by its owner.
- Remote eligibility checks distinguish explicit permission for Egypt/worldwide applicants from generic mentions of global customers or offices. Unknown eligibility remains review, not confirmed match.
- Cross-source deduplication chooses the copy with stronger description/date/eligibility evidence and removes common tracking parameters from URLs.
- Run reports include per-source effectiveness and description-quality counts.
- Local feedback labels for bad fits, experience mismatch, Egypt eligibility, stale jobs, applications, and interview outcomes. Feedback is recorded for later analysis; it does not automatically change rules.
- Referral contact registry, manually opened contact-search links, personalized referral message drafts, outreach status tracking, and follow-up dates. Messages are **never sent automatically**.
- Public source integrations include RemoteOK, Remotive, Himalayas, Jobicy, Arbeitnow, Google Jobs via SerpApi, Greenhouse, Lever, Ashby, public structured-data career pages, email alerts, RSS/Atom feeds, European Tech Opportunities, and Nomado24. See the provider documentation for [European Tech Opportunities](https://docs.techopportunities.eu/docs/users/data/api.html) and [Nomado24](https://www.nomado24.de/en/developers), including their data limitations and attribution requirements.
- GitHub Actions workflow runs four times daily in the `Africa/Cairo` timezone and supports manual runs.

## Requirements

- Python 3.11 or 3.12 recommended.
- Internet connection for job-source fetching and Telegram messages.
- Telegram bot token and chat ID for notifications (optional for local offline tests).
- SerpApi key is optional but required for Google Jobs.
- Email alerts are optional and need an IMAP-enabled mailbox. For Gmail, use an App Password, not your normal password.

## Fresh-folder install

Extract this ZIP into a new directory, then open a terminal in that directory.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
cp .env.example .env
```

Or run `bash scripts/setup_linux.sh` to create the virtual environment, install dependencies, and copy `.env.example` to `.env` when no `.env` already exists.

Edit `.env` and add your own credentials only if you want those integrations:

```dotenv
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id
SERPAPI_API_KEY=
```

`.env` is private configuration. Never upload it, commit it, or include it in a diagnostic ZIP.

### Starting in a new folder vs retaining old history

The safest initial setup is to start with a **fresh** `jobs.sqlite3`; leave the old application's database untouched while you validate this version. The database is created automatically on first run.

If you explicitly want to carry over history, first back up the previous `jobs.sqlite3`, then copy it into this folder before running the application. This version performs non-destructive schema migrations, but old rows may have `description_quality=unknown` because an earlier version didn't record that field. Reclassify them with the current rules and inspect the counts:

```bash
cp /path/to/old/jobs.sqlite3 ./jobs.sqlite3
cp ./jobs.sqlite3 ./jobs.sqlite3.before-2.3.bak
python scripts/reclassify_stored_jobs.py
python scripts/report_quality.py
```

Reclassification is local only: it performs no network requests and sends no Telegram messages. It preserves historical `notified_at` values and referral records. Since unknown-description jobs should not be considered verified, some previously confirmed matches may move to review. Existing notification history is not reset, so reclassifying doesn't resend old alerts.

## Recommended configuration

The bundled `.env.example` is tuned for early-career matching with a maximum of **two mandatory professional-experience years**. Review these values in your `.env`:

```dotenv
MAX_REQUIRED_EXPERIENCE_YEARS=2
REQUIRE_FULL_DESCRIPTION_FOR_MATCH=true
MIN_MATCH_SCORE=70
MAX_POSTING_AGE_DAYS=7
NOTIFY_REVIEW_CANDIDATES=true
REVIEW_DIGEST_SIZE=5
NOMADO24_MAX_PAGES=1
NOMADO24_SEARCH_TERMS=junior;entry level;graduate;internship;trainee;no experience;junior backend;junior python
```

If you copy an older `.env` rather than starting from `.env.example`, update these settings yourself; old values may override the bundled defaults. The app loads only `.env`, not `.env.example`.

Degree wording is not used to reject a job. The default experience limit concerns **mandatory professional-experience requirements**, not years of company history, skill list mentions, a degree's duration, or a preference that is clearly labelled optional.

## How qualification works

Each listing is classified as one of three states:

- **MATCH**: meets the strict rules with enough evidence; eligible for a direct job alert.
- **REVIEW**: potentially useful, but experience level, full description, remote eligibility, regional restrictions, or date semantics need checking. Review alerts are capped into a short Telegram digest.
- **REJECT**: a definite mismatch, such as mandatory experience exceeding the configured limit, a senior title, irrelevant role, unsupported primary stack, explicit country exclusion, or stale/missing posting date.

The experience extractor saves the actual sentence as evidence. It interprets a mandatory range conservatively: `1–3 years required` exceeds a one-year limit. `4 years preferred` is review rather than automatic rejection. If the provider only supplies a short summary, explicit evidence of a 4-year mandatory requirement still causes rejection, but a summary alone cannot become a confirmed match.

The parser is explainable pattern-based logic, not a guarantee that every employer's wording is understood perfectly. Check the evidence excerpt before applying. The employer's full listing remains authoritative.

### Remote eligibility

- “Applicants in Egypt accepted” or an explicit “remote worldwide” statement may support confirmation when it is connected to the job/applicant eligibility.
- “Our product is used worldwide,” “global customers,” or “we have an Egypt office” are not eligibility evidence.
- “Remote” with no allowed countries is review.
- “EMEA” or “Europe” without a clear country list is review unless the employer's own terms clarify it.
- A confirmed country restriction excluding Egypt is rejected.

The matcher's evidence is not legal advice and cannot guarantee the employer will accept an applicant from Egypt. Always verify the application page before investing time.

### Description completeness and source provenance

Every listing has a `description_quality` value:

- `full`: a source provides the full job description or a comprehensive employer-posted body.
- `summary`: a search/email/RSS summary only.
- `metadata`: tags/category/location with no employer description.
- `unknown`: completeness wasn't established.

Source adapters label this field based on what they actually receive, but different providers can still omit text. Treat a suspiciously short “full” description as worth checking manually. `REQUIRE_FULL_DESCRIPTION_FOR_MATCH=true` prevents only non-full-labeled records from entering MATCH; it is not a semantic verifier of every sentence in the employer's page. The current European Tech Opportunities and Nomado24 adapters intentionally label their returned records as `metadata`, because those API responses do not provide the full job body to this app. They are useful for discovery, but their candidates remain REVIEW until a full description is available from another reliable source; do not lower this safeguard just to increase the MATCH count.

## Run it

Run a full source fetch, classify new candidates, update SQLite, and potentially send Telegram alerts:

```bash
python run_once.py
```

This makes network requests. It does not apply for jobs or contact people for you. The JSON report includes fetched source counts, unique/deduplicated listings, confirmed matches, reviews, rejections, source errors, Telegram delivery counts, and source-effectiveness metrics.

Run an independent debug pass that fetches and classifies jobs but does **not** write the job database or send Telegram messages:

```bash
python scripts/debug_candidates.py
# optional machine-readable output:
python scripts/debug_candidates.py --json
```

Inspect the stored database quality and notification state:

```bash
python scripts/report_quality.py
```

Run tests and syntax checks:

```bash
python -m compileall -q app tests scripts
pytest -q
```

### Optional local API

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Then open `http://127.0.0.1:8000/health` or `http://127.0.0.1:8000/docs`. Keep it bound to localhost. `/run-once` triggers a real collection run, so do not expose it publicly without adding authentication.

## Source setup

### Public feeds

Three public programming/engineering RSS feeds are included in `.env.example`:

```dotenv
ENABLE_RSS_FEEDS=true
RSS_FEEDS=We Work Remotely Backend|https://weworkremotely.com/categories/remote-back-end-programming-jobs.rss;We Work Remotely Full Stack|https://weworkremotely.com/categories/remote-full-stack-programming-jobs.rss;Startup Jobs Remote Engineering|https://startup.jobs/feeds/jobs?role=engineering&workplace=remote
```

Keep source attribution and the original listing link in notifications. Feed failures are isolated; one broken feed shouldn't prevent other feeds from being consumed.

### Public ATS boards

Only configure confirmed official board slugs. Do not guess slugs: an incorrect board often returns 404.

```dotenv
GREENHOUSE_BOARDS=Company Name:greenhouse_slug
LEVER_SITES=Company Name:lever_site
ASHBY_BOARDS=Company Name:ashby_board
CAREER_PAGES=Company Name|https://company.example/careers
```

The generic career-page adapter needs publicly available Schema.org `JobPosting` structured data; it won't execute browser JavaScript. For dynamic pages, prefer a documented public ATS/API/feed.

### Email alerts

The project can import alerts you intentionally subscribed to from supported email providers/boards. It does not scrape logged-in job sites. For Gmail use an App Password and set:

```dotenv
ENABLE_EMAIL_ALERTS=true
EMAIL_ALERTS_IMAP_HOST=imap.gmail.com
EMAIL_ALERTS_IMAP_PORT=993
EMAIL_ALERTS_USERNAME=your-alert-mailbox@gmail.com
EMAIL_ALERTS_PASSWORD=your-gmail-app-password
EMAIL_ALERTS_MAILBOX=INBOX
EMAIL_ALERTS_LOOKBACK_DAYS=14
EMAIL_ALERTS_MAX_MESSAGES=300
```

Use email alerts from WUZZUF, LinkedIn, Indeed, Bayt, or other supported senders. The source can't reliably infer an employer's eligibility from the fact an alert email was received.

## Feedback to improve future matching

When a stored match or review candidate turns out to be a poor fit, record the reason while it is fresh. This builds a small local feedback log we can use to adjust and regression-test the rules. Feedback does **not** automatically change classifier behavior; that prevents one mistaken rating from silently changing every future match.

List current candidates and their database IDs:

```bash
python scripts/job_feedback.py list --status review --limit 30
python scripts/job_feedback.py list --status match --limit 30
```

Record a reason after checking the actual employer listing:

```bash
python scripts/job_feedback.py mark --job-id 42 --type too_experienced --notes "Employer page explicitly requires 4+ years"
python scripts/job_feedback.py mark --job-id 43 --type not_eligible_from_egypt --notes "Role restricted to German residents"
python scripts/job_feedback.py mark --job-id 44 --type stale_or_closed
```

Supported labels: `good_fit`, `too_experienced`, `not_eligible_from_egypt`, `stale_or_closed`, `irrelevant`, `applied`, `interview`, and `rejected_by_employer`. Inspect your feedback history with `python scripts/job_feedback.py report`. It stays in the local SQLite database and is not included in diagnostic ZIPs.

## Application queue v1 (review-first)

Every non-rejected `match` or `review` discovered by a search run is recorded in a persistent application queue, separately from the original job-classification status. Queue entries deduplicate by canonical job URL, survive repeated sightings without resetting a human decision, and keep an audit trail for review, preflight and manual submission records.

List the queue and review a listing by its queue ID:

```bash
python scripts/application_queue.py list --status pending_review --limit 30
python scripts/application_queue.py approve 12 --notes "Checked the employer listing and Egypt eligibility"
python scripts/application_queue.py preflight 12
```

Preflight validates the local `candidate_profile.json`, `application_answers.json`, and essential job details. It only marks an approved item `ready` for the candidate to prepare manually. Review-classified jobs retain that warning even if approved. Missing/invalid private files or an unreviewed item block readiness. Resolve a specific application-form question using the existing answer resolver:

```bash
python scripts/application_queue.py answer 12 "What is your email address?"
python scripts/application_queue.py answer 12 "Why are you interested in this role?" --skill Node.js --skill Express
```

The CLI may print private profile answers locally, so do not paste its output into public issues or commit it. Answer-resolution audit events record only category/status/source, never the answer text. To record completion, first apply manually and then use `python scripts/application_queue.py mark-submitted 12 --reference "confirmation-id"`; this command records a submission that already happened elsewhere and **does not submit anything**. Reject a listing with `python scripts/application_queue.py reject 12 --notes "Not eligible from Egypt"`.

This version deliberately does not automate website forms, bypass logins/CAPTCHAs, or submit applications. `auto_submit_allowed` is always false.

## Referral assistant

The referral workflow helps you organize contact research and draft tailored requests. It does not scrape logged-in networks or send any referral messages automatically. Verify people and personalize messages before contacting them.

List stored companies and jobs:

```bash
python scripts/referral_assistant.py companies
python scripts/referral_assistant.py jobs --status match,review
```

Generate public search links for possible contacts at a relevant employer:

```bash
python scripts/referral_assistant.py suggest-contacts --company "Example Company"
```

After manually finding and verifying a person, save the contact:

```bash
python scripts/referral_assistant.py add-contact \
  --name "Contact Name" \
  --company "Exact Company Name" \
  --role "Software Engineer" \
  --profile-url "https://www.linkedin.com/in/public-profile/"
```

You can customize the drafted note in `.env` with `CANDIDATE_DISPLAY_NAME`, `CANDIDATE_SUMMARY`, `CANDIDATE_LINKEDIN_URL`, `CANDIDATE_PORTFOLIO_URL`, and `CANDIDATE_CV_URL`. Use the LinkedIn variable for your profile; reserve the portfolio variable for your personal site or project portfolio. A LinkedIn profile is useful, but it should not silently stand in for a portfolio link. For a CV PDF that changes often, Google Drive is a simple option: share the existing file as “Anyone with the link” / Viewer, then update that same file through **Manage versions → Upload new version** rather than making a new file each time. Don't include private data you wouldn't want in a message.

Create the draft using the database IDs shown by the commands:

```bash
python scripts/referral_assistant.py contacts --company "Exact Company Name"
python scripts/referral_assistant.py jobs --status match,review
python scripts/referral_assistant.py draft --job-id 12 --contact-id 3
```

The draft is printed and stored, but not sent. Update outreach after you manually send a message:

```bash
python scripts/referral_assistant.py update --outreach-id 1 --status contacted --followup-days 5
python scripts/referral_assistant.py outreach
python scripts/referral_assistant.py followups
```

Available outreach states are `draft`, `contacted`, `replied`, `referred`, and `declined`.

## Telegram

Set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`. Confirmed matches are sent individually when newly eligible for notification; review candidates are bundled into a digest capped by `REVIEW_DIGEST_SIZE`. A successful send is marked notified. Failed sends should remain eligible for a later retry. Run summaries expose source errors. This app doesn't send applications or referral outreach automatically.

## GitHub Actions

The workflow at `.github/workflows/job-hunter.yml` is configured for four runs daily at 03:17, 09:17, 15:17 and 21:17 in `Africa/Cairo`, with a manual `workflow_dispatch`. A run can be delayed by GitHub; use the Actions tab to trigger a manual run.

To deploy it in your own repository:

1. Keep the repository private if it contains personal project context; never commit `.env` or a database with personal notes.
2. Add secrets under **Settings → Secrets and variables → Actions → Secrets**: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `SERPAPI_API_KEY` (optional), `EMAIL_ALERTS_USERNAME` and `EMAIL_ALERTS_PASSWORD` (optional).
3. Optional repository variables: `GREENHOUSE_BOARDS`, `LEVER_SITES`, `ASHBY_BOARDS`, `CAREER_PAGES`, and `RSS_FEEDS`. The workflow has a fallback RSS list if `RSS_FEEDS` is unset.
4. Push the code to the default branch, enable Actions, and trigger one manual run. Inspect the run summary and Telegram before relying on the schedule.

SQLite history is restored/saved via workflow artifacts for deduplication and notification state. Artifacts expire; if database history is lost, old jobs may become eligible for notifications again. Scheduled runs depend on the workflow file being on the repository's default branch.

## Diagnostics and privacy

A diagnostic ZIP collector is available:

```bash
bash scripts/collect_job_hunter_debug.sh
```

It excludes `.env`, databases, logs, virtual environments, caches and archives, but always inspect the ZIP before sharing it. Review `git status` before committing. Never commit credentials, Gmail app passwords, Telegram tokens, CV files, or contact notes.

## Known limitations

- Public aggregator descriptions and dates are not always the employer's full source of truth; automatic mode skips entries whose original posting date or full description cannot be verified.
- Experience-language rules are pattern-based, so unusual wording may be skipped conservatively.
- Job boards may restrict their APIs/feeds or change their schema; individual source failures are recorded without stopping the other sources.
- Automatic submission is a best-effort browser worker, not a legal eligibility verifier or a guarantee of successful submission to every employer platform. Unsupported forms and required questions without verified answers are skipped and recorded.

### Autonomous applications (local machine only)

Job Hunter can optionally apply without manual approval to a bounded subset of fresh jobs. Enable `AUTO_APPLY_ENABLED=true` only after validating the private candidate profile, answer bank, and resume path. The worker automatically skips roles with unverified Egypt eligibility, non-original/unknown posting dates, summaries instead of full descriptions, above-target experience, unsupported ATS sites, CAPTCHA challenges, required logins, unknown required questions, or required legal/consent answers. It does not bypass anti-bot controls or invent candidate facts.

The worker supports generic public application forms on known ATS hosts (Greenhouse, Lever, Ashby, Workable, SmartRecruiters, Jobvite, iCIMS, BambooHR, Recruitee, Personio, Teamtailor, and Workday). It cannot submit through every custom site, and the employer page must provide a recognisable supported form. Submission is recorded only when the form gives a clear success signal; uncertain submissions are not retried automatically to avoid duplicate applications.

To configure local autopilot, run `bash scripts/enable_autopilot.sh` once from this project. It validates local private files, installs dependencies in a home-directory virtual environment, installs Chromium, enables a maximum of 10 confirmed submissions per Cairo day, installs a user systemd timer for four daily runs, and starts the first cycle immediately. The computer must be online and the project drive mounted for a run to complete. This local worker does not send your candidate profile/CV to GitHub Actions.

Required `.env` settings:

```dotenv
AUTO_APPLY_ENABLED=true
AUTO_APPLY_MAX_PER_DAY=10
AUTO_APPLY_MIN_SCORE=60
AUTO_APPLY_DELAY_SECONDS=8
AUTO_APPLY_HEADLESS=true
AUTO_APPLY_RESUME_PATH=private/Mohamed_Ahmed_CV.pdf
```

If the profile or answer bank needs a personal fact that is not saved, the form is skipped instead of asking you to make up an answer. Sensitive/legal declarations and company-specific consent checkboxes remain blockers.
