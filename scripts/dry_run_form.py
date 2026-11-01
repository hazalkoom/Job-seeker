#!/usr/bin/env python3
"""Dry-run form filler: tests navigation, link discovery, and field mapping without submitting."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from playwright.sync_api import sync_playwright
from app.application_profile import load_profile_bundle
from app.application_automation import (
    _choose_application_form,
    _fill_form,
    _find_apply_url,
    _resume_path,
)


def dry_run(url: str):
    bundle = load_profile_bundle()
    resume_path = _resume_path(bundle.profile)
    item = {"url": url, "company": "Test Company", "title": "Software Engineer"}

    print(f"Testing URL: {url}")
    print(f"Resume path exists: {resume_path.is_file()} ({resume_path})")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=25000)
            page.wait_for_timeout(1000)

            apply_url = _find_apply_url(page)
            print(f"Apply target URL: {apply_url}")
            if apply_url and apply_url != page.url:
                page.goto(apply_url, wait_until="domcontentloaded", timeout=25000)
                page.wait_for_timeout(1000)

            form = _choose_application_form(page)
            if not form:
                print("❌ No application form found on page.")
                return

            print("✅ Application form detected. Attempting field mapping...")
            blockers, filled = _fill_form(form, bundle.profile, bundle.answer_bank, item, resume_path)
            print(f"Filled fields ({len(filled)}):")
            for f in filled:
                print(f"  ✓ {f}")
            if blockers:
                print(f"\nBlockers ({len(blockers)}):")
                for b in blockers:
                    print(f"  ✗ {b}")
            else:
                print("\n🎉 Zero blockers! Form would be successfully submitted / ready for review.")
        finally:
            browser.close()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/dry_run_form.py <job_or_ats_url>")
        sys.exit(1)
    dry_run(sys.argv[1])
