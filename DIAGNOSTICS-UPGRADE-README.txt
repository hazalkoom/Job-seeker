JOB HUNTER DIAGNOSTICS + GITHUB AUTOPILOT UPDATE

This update adds detailed per-job auto-application diagnostics, a read-only inspector,
a privacy-conscious diagnostic ZIP collector, and a bounded one-time retry for jobs
previously skipped only because an ATS form was not detected. It updates the GitHub
Actions workflow to sanitize the run report before artifact upload. It does not itself
run a search or submit an application during installation.

INSTALL
1. Extract this ZIP at the Job Hunter repository root, preserving paths.
2. Run: python -m compileall -q app scripts tests
3. Run: python -m pytest -q
4. Run: git diff --check
5. Run: bash scripts/disable_local_autopilot.sh (the user's preferred scheduler is GitHub Actions).
6. Run: python scripts/inspect_application_outcomes.py --limit 50
7. Run: python scripts/collect_job_hunter_diagnostics.py
8. Inspect DIAGNOSTICS.txt inside the resulting job_hunter_diagnostics_*.zip before uploading.

The diagnostic collector excludes .env contents, candidate_profile.json, application_answers.json,
CV/PDFs, encrypted .gpg files, raw SQLite databases and raw logs. It includes relevant code,
tests, a sanitized database summary, sanitized latest report, filtered logs, and test results.
Inspect the resulting archive before sharing anyway.

GITHUB ACTIONS
The workflow is set for GitHub Actions at 03:17, 09:17, 15:17 and 21:17 Africa/Cairo time.
It will not run automatically until these code/workflow changes and the encrypted private
files/secrets required by README-GitHub-Autopilot.txt are committed/pushed to the default
branch. If encrypted private files have not yet been prepared, review the guide and run
scripts/prepare_github_autopilot.sh after verifying your current .gitignore and repository.
Never commit or upload plaintext .env, candidate profile, answer bank, or CV.

LOGGING
The application worker writes logs/application_automation.jsonl and
logs/latest_run_report.json. GitHub Actions uploads the sanitized report and JSONL audit
log as job-hunter-diagnostics-<run_id>. To inspect a run on GitHub, open Actions, select
the run, inspect the summary, then download that diagnostic artifact.

This update does not bypass CAPTCHA/anti-bot controls, invent answers, or treat an
unconfirmed submission as successful. The one-time retry only targets prior public-ATS
link discovery skips. Stale/old, ineligible, incomplete-description, unanswered-required
question, and CAPTCHA cases remain skipped with explicit reason codes.
