# Role-Tailored CV Generation (`scripts/generate_tailored_cvs.py`)

Job Hunter automatically selects the best matching 1-page CV PDF from `cvs/` for every job application based on the job title, company, and description (`_select_cv_for_job` in `app/application_automation.py`).

## How It Works

1. **Base CV & Fallback**:
   - Locally, `scripts/generate_tailored_cvs.py` copies `Mohamed_Ahmed-general2.pdf` to `cvs/Mohamed_Ahmed-General.pdf` (and updates `private/Mohamed_Ahmed-general.pdf`).
   - In CI/CD (GitHub Actions), where `Mohamed_Ahmed-general2.pdf` is git-ignored, it falls back to the decrypted `private/Mohamed_Ahmed-general.pdf` and generates all 28 specialized PDFs into `cvs/`.

2. **Verified Hyperlinks**:
   Every generated 1-page PDF embeds clickable hyperlinks for:
   - **Contact & Profiles**: Email, Portfolio, LinkedIn, GitHub
   - **Open-Source Contributions**: [Cantera Merged PRs](https://github.com/Cantera/cantera/pulls?q=author:hazalkoom)
   - **Projects**: Direct GitHub repository links (`smartCart`, `AeroLock`, `real-estate-platform`, `Job-seeker`)
   - **Certificates**: Direct verification URLs (`https://coursera.org/verify/...`, `https://aws.amazon.com/verification`, `https://www.freecodecamp.org/`)

3. **29 Role-Tailored CVs**:
   Includes dedicated 1-page CVs for:
   - General / Software Engineer / Junior Software Engineer / Software Developer
   - Backend (Node.js, Python, Django, FastAPI, General, API & Integrations, PostgreSQL/Database)
   - Full Stack (Angular, React, Python, TypeScript)
   - Frontend (General, React/Next.js, Angular, Web Developer)
   - AI Applications & Workflow Automation
   - QA & Test Automation (SDET, QA Engineer)
   - Linux, Open Source, & Junior Cloud/DevOps
   - Application Support, Developer Support, & IT Support

## Running Manually

```bash
python3 scripts/generate_tailored_cvs.py
```

Playwright Chromium renders each HTML specification in `CV_SPECS` to a 1-page Letter PDF in `cvs/`.
