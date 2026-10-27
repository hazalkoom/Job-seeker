JOB HUNTER GITHUB AUTOPILOT MIGRATION

This package moves scheduling from local systemd to GitHub Actions. It does not contain your .env, candidate profile, answer bank, or PDF.

1. Stop the local timer on Fedora:
   systemctl --user disable --now job-hunter-autopilot.timer
   systemctl --user stop job-hunter-autopilot.service

2. Unzip this package at the root of your existing Job Hunter repository, replacing .github/workflows/job-hunter.yml and adding scripts/prepare_github_autopilot.sh.

3. From the project root, run:
   bash scripts/prepare_github_autopilot.sh
   It will encrypt candidate_profile.json, application_answers.json, and private/Mohamed_Ahmed-general.pdf, set the repository Actions secret AUTOPILOT_DECRYPTION_PASSPHRASE using gh, and stage only the encrypted files. It does not commit or push.

   Requires gpg, openssl, GitHub CLI (gh), and an authenticated `gh auth login` session.

4. Inspect `git status --short`. The plaintext .env, candidate_profile.json, application_answers.json, and PDF must NOT be staged or tracked. Only the three `.gpg` ciphertexts should be added from private/.

5. Check repository Actions secrets by NAME only in GitHub Settings > Secrets and variables > Actions. Existing source/notification secrets should include SERPAPI_API_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, EMAIL_ALERTS_USERNAME, and EMAIL_ALERTS_PASSWORD if you want those integrations enabled. Never paste secret values in a commit or log.

6. The package workflow enables AUTO_APPLY_ENABLED=true and runs on GitHub Actions at 03:17, 09:17, 15:17, and 21:17 Africa/Cairo. It restores/saves the SQLite database artifact between runs and reports confirmed submissions, skipped jobs, failures, and source errors in the GitHub Actions run summary. It also uses Telegram for an application summary if configured.

7. Stage your local code changes plus the workflow and ciphertext files, review `git status --short`, run tests, commit, and push to the repository's default branch. GitHub scheduled workflows run from the default branch. Run the workflow manually from Actions once after pushing if desired; that first run may submit eligible applications.

Important limits: it only submits when the job passes strict freshness, full-description, experience, Egypt eligibility, supported ATS host, and truthful-answer checks. Unsupported forms/CAPTCHAs/unanswerable required questions are skipped. This is not a guarantee that every listing can be submitted.
