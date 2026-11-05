# Job Hunter Operations Runbook

This runbook provides step-by-step operational guidance for maintaining, troubleshooting, and operating **Job Hunter 4.0 Autopilot**.

---

## 1. Daily Autopilot Lifecycle

Job Hunter runs autonomously via GitHub Actions on a 4-times-daily cron schedule in the **`Africa/Cairo`** timezone:

| Scheduled Run | Time (Cairo) | Purpose |
|---|---|---|
| **Early Morning** | `03:17` | Collects overnight US/European postings, runs auto-apply, sends morning digest |
| **Mid-Morning** | `09:17` | Captures fresh morning listings from Egyptian and European companies |
| **Afternoon** | `15:17` | Captures midday listings and afternoon US rollouts |
| **Evening** | `21:17` | Reconciles end-of-day application confirmations via Gmail |

Each run:
1. Restores the SQLite database artifact (`job-hunter-db`).
2. Decrypts candidate credentials and tailored CVs in an ephemeral runner memory space.
3. Fetches from all 17+ enabled sources and deduplicates listings.
4. Executes autonomous submissions for qualified direct-ATS applications.
5. Reconciles application confirmations from your Gmail inbox.
6. Delivers Telegram summary notifications and 1-tap manual cards.
7. Saves the updated SQLite database artifact for the next scheduled run.

---

## 2. Understanding Telegram Notifications

Job Hunter sends bounded, formatted Telegram alerts to your configured chat:

### 1. Application Submitted Alert
Delivered in real-time when an application is successfully submitted to an employer's ATS:
```
🚀 APPLICATION SUBMITTED AUTOMATICALLY
Junior Backend Engineer
🏢 Canonical
📍 Remote (Worldwide)
📄 CV Used: Mohamed_Ahmed-Backend.pdf
🔗 View Job Listing: https://boards.greenhouse.io/canonical/jobs/...
```

### 2. Run Summary Message
Delivered at the conclusion of each autopilot cycle:
```
Job Hunter — automatic application cycle
Applications confirmed submitted: 3 (including 1 confirmed via Gmail inbox)
Automatically skipped: 14
Submission errors/uncertain outcomes: 0
Funnel: 350 fetched → 42 qualified (12 ATS-resolved) → 4 manual cards
• Canonical (Junior Backend) — submitted [CV: Mohamed_Ahmed-Backend.pdf]
• Supabase (Software Engineer - Tooling) — submitted [CV: Mohamed_Ahmed-Full_Stack.pdf]
```

### 3. 1-Tap Manual Apply Cards (LinkedIn / Wuzzuf / Indeed)
Delivered when a high-scoring job is found on a login-gated board without an external ATS:
```
📲 Job Hunter — 1-Tap Manual Apply Cards
These roles matched your profile on login-gated boards:
1. Full Stack Developer — Fawry
Score: 88/100 | 📍 Smart Village, Giza | 📄 CV: Mohamed_Ahmed-Full_Stack.pdf
🔗 Tap to Apply on Wuzzuf: https://wuzzuf.net/jobs/p/...

Quick-copy links:
• Portfolio: https://mohamed-ahmed-five.vercel.app/
• GitHub: https://github.com/hazalkoom
• LinkedIn: https://www.linkedin.com/in/mohamed-ahmed-mahmoud-766912268/
```

### 4. Questions Needed Digest
Delivered when required questions blocked form submissions:
```
❓ Job Hunter — Questions Needed to Unlock Skipped Forms
These required fields blocked auto-submission:
1. In which country do you currently work? (select, Canonical, seen 3×)
   Options: Egypt (Cairo), United Kingdom, United States
2. What is your expected start date? (text, Vezeeta, seen 1×)
```

---

## 3. Managing the Question Ledger

When you receive a `❓ Questions Needed` digest on Telegram:

1. **Open `application_answers.json`**:
   Add the question key and your verified answer under `"answers"`:
   ```json
   "expected_start_date": {
     "type": "factual",
     "answer": "Available immediately with no notice period",
     "auto_fill": true
   }
   ```
2. **Re-encrypt and Stage for GitHub Actions**:
   ```bash
   bash scripts/prepare_github_autopilot.sh
   git add -u
   git commit -m "Add expected_start_date answer"
   git push origin main
   ```
3. Subsequent autopilot runs will automatically auto-fill that field.

---

## 4. Expanding the Company Registry (`data/ats_companies.csv`)

To add new target companies for automated monitoring:

1. Discover their ATS endpoint:
   ```bash
   python -m jobhunter ats probe "Company Name"
   # or crawl their careers page:
   python -m jobhunter ats discover "https://company.com/careers"
   ```
2. Add the verified row to [`data/ats_companies.csv`](file:///run/media/hazalkoom/FD16124010E85459/job-hunter/Job-Seeker-push-20261019-121011/data/ats_companies.csv):
   ```csv
   ats,slug,company,remote_friendly,egypt_presence
   ashby,mycompany,My Company,true,true
   ```
3. Commit and push to `main`.

---

## 5. Troubleshooting & FAQ

### Issue: GitHub Actions run reports `Playwright TimeoutError`
- **Cause**: An employer's site took longer than 30 seconds to load or had heavy client-side scripts.
- **Handling**: The runner logs the timeout, marks the queue item as `failed` (or skips it), and continues to the remaining queue items. If an employer consistently times out, raise `AUTO_APPLY_TIMEOUT_SECONDS=45` in `.env`.

### Issue: Page presented a CAPTCHA or Cloudflare challenge
- **Handling**: Job Hunter **strictly adheres to zero-evasion ethics**. It never attempts automated solving. It captures a screenshot to `logs/challenge_<id>.png`, skips the item, and generates a 1-tap manual apply card on Telegram so you can complete the application manually in your personal browser.

### Issue: Gmail IMAP fails with `AUTHENTICATIONFAILED`
- **Cause**: Google disabled legacy passwords.
- **Resolution**: Generate a new **16-character Google App Password**:
  1. Go to Google Account > Security > 2-Step Verification.
  2. Select **App Passwords** at the bottom.
  3. Create an app password for "Job Hunter" and paste the 16 characters into `EMAIL_ALERTS_PASSWORD`.
  4. Update the GitHub Actions secret: `gh secret set EMAIL_ALERTS_PASSWORD`.

### Issue: Resetting or Re-evaluating a Failed Queue Record
- Use the CLI tool to dry-run and inspect:
  ```bash
  python -m jobhunter replay --queue-id 42 --dry-run
  ```
- To requeue previously skipped applications:
  ```bash
  python scripts/requeue_auto_skipped.py
  ```
