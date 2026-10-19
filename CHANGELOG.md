# Changelog

## 2.3.1

- Raised the default maximum mandatory professional-experience requirement from one year to two years; requirements of two years or less can qualify, while more than two mandatory years are rejected.
- Updated the shipped `.env.example` and GitHub Actions workflow to use a two-year limit. The update installer changes only `MAX_REQUIRED_EXPERIENCE_YEARS` and adds an empty LinkedIn URL variable in an existing `.env`, preserving other secrets and preferences.
- Added `CANDIDATE_LINKEDIN_URL` separately from portfolio and CV URLs, and included it in referral message drafts.
- Made experience-rejection evidence and source-quality metrics use the configured threshold rather than hardcoding a one-year limit.

## 2.3.0

- Added an explainable experience-requirement extractor, preserving employer wording for mandatory and preferred years of experience.
- Requires full-description quality for a confirmed match by default; snippet/metadata-only listings remain review candidates unless explicit hard requirements already justify rejection.
- Tightened international remote eligibility checks so global customers/offices don't prove a candidate can work remotely from Egypt.
- Added description-quality labels to stored jobs and a safe reclassification command for existing databases.
- Added source-effectiveness metrics, richer cross-source deduplication, and a privacy-conscious diagnostic bundle that includes GitHub workflows.
- Added a local feedback log for poor fit, experience mismatches, Egypt eligibility, stale/closed listings, and outcomes.
- Added a human-reviewed referral assistant: public contact-search links, contact registry, tailored message drafts, outreach tracking, and follow-up dates. It does not send messages automatically.
- Added Linux setup helper and a four-times-daily Cairo-time GitHub Actions workflow.
