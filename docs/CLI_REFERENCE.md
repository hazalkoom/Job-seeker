# Job Hunter CLI Reference Manual

The `jobhunter` command-line interface (`python -m jobhunter <command>`) provides diagnostic, inspection, and operations utilities for managing your autonomous job search pipeline.

---

## Command Overview

```
jobhunter [-h] {audit,sources,ats,form,questions,inbox,report,replay} ...
```

| Command Group | Subcommand | Purpose |
|---|---|---|
| `audit` | `funnel` | Displays 7-stage conversion funnel and queue status distribution |
| `sources` | `health` | Probes configured ATS endpoints and validates live status |
| `ats` | `probe <company>` | Discovers if a company is hosted on any supported ATS |
| `ats` | `discover <url>` | Scrapes career pages to extract and probe embedded ATS links |
| `form` | `inspect <url>` | Headlessly loads an application page and previews field mappings |
| `questions` | `gaps` | Inspects pending unanswered required questions in the Question Ledger |
| `inbox` | `status` | Checks recent Gmail application receipts, interviews, and rejections |
| `report` | `html` | Generates a standalone interactive HTML dashboard |
| `replay` | `--queue-id N` | Dry-runs a specific application queue item |

---

## Detailed Command Specifications

### 1. `audit funnel`
Audits the end-to-end conversion funnel using metrics from the most recent run report and SQLite database.

```bash
python -m jobhunter audit funnel
```

**Output Example:**
```
=== Job Hunter 7-Stage Funnel Audit ===
Deduped jobs seen:   3568
Confirmed matches:   5
Review candidates:   69
Rejected:            3494
ATS resolved:        18
Manual apply cards:  14
Auto-apply cycle:    processed=9 submitted=0 skipped=7 failed=2

Queue Status Breakdown:
  pending_review     109
  submitted          4
  auto_skipped       67
  failed             2

Queue Apply-Path Classification:
  direct_ats             34
  aggregator_redirect    94
  login_gated            22
```

---

### 2. `sources health`
Tests network connectivity and endpoint validity across all companies listed in `data/ats_companies.csv`.

```bash
python -m jobhunter sources health [--limit N]
```

**Options:**
- `--limit N`: Limit health check to the first `N` companies (useful for quick connectivity checks).

**Output Example:**
```
Probing 10 ATS endpoints...
  [OK]   greenhouse      canonical          (Canonical) -> 82 jobs
  [OK]   ashby           supabase           (Supabase) -> 12 jobs
  [OK]   workable        instabug           (Instabug) -> 6 jobs
  [OK]   smartrecruiters valu               (valU) -> 4 jobs
  [OK]   lever           kraken             (Kraken) -> 28 jobs
```

---

### 3. `ats probe`
Discovers whether a target company is hosted on a supported public ATS by checking known registries and live API endpoints.

```bash
python -m jobhunter ats probe <company>
```

**Example:**
```bash
python -m jobhunter ats probe "Thndr"
```

**Output Example:**
```
Found ATS for 'Thndr': ats=ashby, slug=thndr, company=Thndr, jobs=8
```

---

### 4. `ats discover`
Crawls a public careers landing page, searches for embedded ATS iframe URLs or links (Greenhouse, Ashby, Lever, Workable, SmartRecruiters, Recruitee, BambooHR, Breezy), verifies them against live ATS APIs, and appends live endpoints to `data/proposed_companies.csv`.

```bash
python -m jobhunter ats discover <url>
```

**Example:**
```bash
python -m jobhunter ats discover "https://example.com/careers"
```

---

### 5. `form inspect`
Opens an ATS job URL in a headless browser, inspects all form fields, detects required tags, and previews resolved candidate answers without submitting anything.

```bash
python -m jobhunter form inspect <url>
```

**Example:**
```bash
python -m jobhunter form inspect "https://jobs.ashbyhq.com/supabase/12345"
```

**Output Example:**
```
=== Form Inspection for https://jobs.ashbyhq.com/supabase/12345 (14 controls) ===
  [REQ] (input/text)     Full Name                     -> 'Mohamed Ahmed Mahmoud' (saved candidate identity)
  [REQ] (input/email)    Email                         -> 'mohamed@example.com' (saved candidate email)
  [REQ] (input/tel)      Phone                         -> '+201000000000' (saved candidate phone)
  [REQ] (input/file)     Resume                        -> 'Mohamed_Ahmed-Backend.pdf' (tailored CV)
  [REQ] (select/select)  In which country do you work? -> 'Egypt (Cairo)' (saved candidate location)
  [REQ] (button/yesno)   Americas time zone?           -> 'No' (saved timezone answer)
  [OPT] (input/url)      GitHub Profile                -> 'https://github.com/hazalkoom' (saved profile link)
```

---

### 6. `questions gaps`
Lists pending unanswered required questions that caused applications to be skipped.

```bash
python -m jobhunter questions gaps
```

**Output Example:**
```
=== Pending Unanswered Questions (3) ===
1. [4x] (select) In which country do you currently work?
   Company/Host: Canonical (boards.greenhouse.io)
   Options: Egypt (Cairo), United Kingdom, United States, Germany
   HTML: <select id="question_991" required>...</select>

2. [2x] (radio) Are you legally authorized to work remotely from Egypt?
   Company/Host: Supabase (jobs.ashbyhq.com)
   Options: Yes, No
```

---

### 7. `inbox status`
Reconciles recent application confirmation emails, interview invitations, and rejection receipts from your configured Gmail account via SSL IMAP.

```bash
python -m jobhunter inbox status [--days N]
```

**Options:**
- `--days N`: Lookback period in days (default: `7`).

**Output Example:**
```
=== Application Inbox Status (last 7 days) ===
Confirmed queue IDs: [30, 42]
Confirmations seen:  5
Interviews seen:     1
Rejections seen:     2
```

---

### 8. `report html`
Generates a standalone, dependency-free HTML dashboard displaying recent queue activity, qualification statistics, and unanswered questions.

```bash
python -m jobhunter report html [--output PATH]
```

**Default Output:** `logs/dashboard.html`

Open `logs/dashboard.html` in any web browser to view the interactive table.

---

### 9. `replay`
Dry-runs a specific application queue record by ID to inspect its form fields and evaluate why it was previously skipped or failed.

```bash
python -m jobhunter replay --queue-id <ID> [--dry-run]
```
