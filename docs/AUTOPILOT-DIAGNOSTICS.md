# Job Hunter Autopilot diagnostics

## What is logged

`app/automation_diagnostics.py` creates one-line JSON events in
`logs/application_automation.jsonl` and writes the same `AUTO_APPLY_AUDIT` records
to stderr. This makes them visible in GitHub Actions / systemd logs as well as in a
local JSONL file. Events include the application policy decision, stable reason code,
posting-date and description quality, eligibility metadata, apply-like links and
hosts, HTTP status, detected form shape, preflight blockers, and final outcome.

The logger deliberately does not record answer values, form input values, CV bytes,
profile contents, cookies, raw HTML, or URL query strings. GitHub Actions also writes
a sanitized `run-report.json`; the unsanitized stdout report is kept only in the
runner temporary directory and removed before artifact upload.

## Inspect the current local database and latest cycle

```bash
python scripts/inspect_application_outcomes.py --limit 50
```

For machine-readable JSON:

```bash
python scripts/inspect_application_outcomes.py --json > /tmp/application-outcomes.json
```

The command opens the database read-only. It does not fetch jobs, open a browser,
change queue states, or print `.env` values. It displays both matcher rejection
counts and per-application decision codes, including apply-link hosts and form
structure where the browser reached a listing/application page.

## Create a support bundle

```bash
python scripts/collect_job_hunter_diagnostics.py
```

It creates `job_hunter_diagnostics_YYYYMMDD_HHMMSS.zip` in the project root. If
`gh` is installed and authenticated, it fetches a few recent workflow summaries and
only the deliberately redacted diagnostic artifacts. It does not download the raw
SQLite database artifact.

The bundle contains the relevant application code and tests, test results, Git
status/diff-stat, queue/status/event summaries, sanitized public listing descriptions, the latest matching report
(including top rejection reasons and source effectiveness), structured audit events, and filtered systemd / GitHub Actions logs where available.
It excludes `.env` values, candidate profile and answer bank contents, CVs, raw SQLite
databases, browser state/cookies, encrypted secret files, and raw log files. Inspect
`DIAGNOSTICS.txt` before uploading the ZIP anyway.

To make a smaller bundle without tests or remote GitHub log lookups:

```bash
python scripts/collect_job_hunter_diagnostics.py --no-tests --no-github-logs
```

## One-time diagnostic retry

When a supported ATS link was not found, the item is kept terminal to prevent endless
retries. The GitHub workflow runs `scripts/requeue_auto_skipped.py` for only
`no_supported_ats_form` and `application_form_not_detected` reasons. The script has a
dry-run default and cannot requeue jobs skipped for stale dates, Egypt eligibility,
excessive experience, missing descriptions, CAPTCHAs, or unanswered required
questions. Each queue item is eligible for at most one such diagnostic retry.

## Scheduler

This project is intended to run on GitHub Actions, not a local timer. To turn off the
old Fedora user timer without affecting GitHub Actions, run:

```bash
bash scripts/disable_local_autopilot.sh
```

After installing this update and checking tests, commit/push the workflow and code to
the repository's default branch. Dispatch a workflow run from GitHub Actions to get
the first instrumented results; subsequent scheduled runs use the GitHub schedule.
