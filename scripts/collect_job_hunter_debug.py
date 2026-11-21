#!/usr/bin/env python3
"""Create a privacy-conscious diagnostic ZIP for Job Hunter development support.

Run from the project root:
    python scripts/collect_job_hunter_debug.py

The collector does NOT read .env, database files, logs, caches, or virtualenvs.
It includes application Python source, test source, selected project metadata,
and command outputs needed to debug source registration/integration issues.
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import platform
import re
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

SENSITIVE_NAMES = {
    ".env", ".env.local", ".env.production", "credentials.json",
    "service-account.json", "id_rsa", "id_ed25519",
}
SKIP_DIRS = {
    ".git", ".venv", "venv", "env", "__pycache__", ".pytest_cache",
    ".mypy_cache", ".ruff_cache", "node_modules", "dist", "build",
    "site-packages", ".tox", ".nox",
}
SKIP_SUFFIXES = {
    ".sqlite", ".sqlite3", ".db", ".log", ".pem", ".key", ".p12",
    ".pfx", ".pyc", ".pyo", ".zip", ".tar", ".gz",
}
SAFE_ROOT_FILES = {
    "run_once.py", "main.py", "pyproject.toml", "requirements.txt",
    "requirements-dev.txt", "pytest.ini", "setup.cfg", "tox.ini",
    "setup.py", "Pipfile", "Makefile", "README.md", ".env.example", "VERSION",
    ".gitignore", "company_targets.csv", ".python-version",
}


def run_cmd(cmd: list[str], cwd: Path, timeout: int = 120) -> str:
    try:
        p = subprocess.run(
            cmd, cwd=cwd, text=True, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, timeout=timeout, check=False,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        return f"$ {' '.join(cmd)}\n(exit code {p.returncode})\n{p.stdout}\n"
    except FileNotFoundError as exc:
        return f"$ {' '.join(cmd)}\nCommand unavailable: {exc}\n"
    except subprocess.TimeoutExpired as exc:
        output = exc.stdout or ""
        if isinstance(output, bytes):
            output = output.decode("utf-8", errors="replace")
        return f"$ {' '.join(cmd)}\nTIMED OUT after {timeout}s\n{output}\n"


def is_sensitive(path: Path) -> bool:
    lower_name = path.name.lower()
    if lower_name in SENSITIVE_NAMES:
        return True
    if lower_name.startswith(".env") and lower_name != ".env.example":
        return True
    if any(part.lower() in {"secrets", "credentials", "private", "tokens"} for part in path.parts):
        return True
    if path.suffix.lower() in SKIP_SUFFIXES:
        return True
    if any(term in lower_name for term in ("secret", "credential", "token", "password")):
        return True
    return False


def safe_copy(src: Path, dst: Path) -> None:
    """Copy text files; redact secret-like assignments in .env.example."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        text = src.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return
    if src.name == ".env.example":
        redacted = []
        for line in text.splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key = line.split("=", 1)[0].strip().upper()
                sensitive_exact = {
                    "TELEGRAM_CHAT_ID", "EMAIL_ALERTS_USERNAME", "CANDIDATE_DISPLAY_NAME",
                    "CANDIDATE_SUMMARY", "CANDIDATE_PORTFOLIO_URL", "CANDIDATE_CV_URL",
                }
                if key in sensitive_exact or any(
                    word in key for word in (
                        "KEY", "TOKEN", "SECRET", "PASSWORD", "PASSWD", "BOT_TOKEN", "API_KEY"
                    )
                ):
                    line = line.split("=", 1)[0] + "=<redacted-by-collector>"
            redacted.append(line)
        text = "\n".join(redacted) + ("\n" if text.endswith("\n") else "")
    dst.write_text(text, encoding="utf-8")


def candidate_files(root: Path) -> list[Path]:
    files: set[Path] = set()
    for folder in (root / "app", root / "tests", root / "scripts", root / ".github"):
        if not folder.is_dir():
            continue
        for current, dirnames, filenames in os.walk(folder):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for filename in filenames:
                path = Path(current) / filename
                if is_sensitive(path):
                    continue
                path.relative_to(folder)
                if (
                    path.suffix == ".py"
                    or (folder.name == "scripts" and path.suffix in {".sh", ".md", ".txt"})
                    or (folder.name == ".github" and path.suffix.lower() in {".yml", ".yaml", ".md", ".json", ".js", ".ts", ".sh"})
                ):
                    files.add(path)
    for filename in SAFE_ROOT_FILES:
        path = root / filename
        if path.is_file() and not is_sensitive(path):
            files.add(path)
    return sorted(files)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="Project root (defaults to current directory)")
    parser.add_argument("--no-tests", action="store_true", help="Do not run compileall/pytest diagnostics")
    args = parser.parse_args()
    root = args.root.resolve()

    if not (root / "app" / "sources" / "__init__.py").is_file():
        print("ERROR: Run this from the Job Hunter project root (app/sources/__init__.py not found).", file=sys.stderr)
        return 2

    now = dt.datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")
    zip_path = root / f"job_hunter_debug_{now}.zip"

    with tempfile.TemporaryDirectory(prefix="job-hunter-debug-") as tmp_name:
        staging = Path(tmp_name) / "job_hunter_debug"
        files_dir = staging / "project_files"
        for src in candidate_files(root):
            try:
                rel = src.relative_to(root)
            except ValueError:
                continue
            safe_copy(src, files_dir / rel)

        files_list = sorted(
            str(p.relative_to(files_dir)) for p in files_dir.rglob("*") if p.is_file()
        )

        sections = [
            "JOB HUNTER DIAGNOSTIC BUNDLE",
            f"Generated: {dt.datetime.now().astimezone().isoformat()}",
            f"Project root: {root}",
            f"Python executable: {sys.executable}",
            f"Python version: {sys.version}",
            f"Platform: {platform.platform()}",
            "",
            "SAFETY NOTES",
            "The collector does not include .env, database files, logs, virtualenvs, caches, or binary files.",
            "Review this ZIP before uploading; it contains application code and tests.",
            "",
            "FILES INCLUDED",
            *files_list,
            "",
        ]
        git_commands = [
            ("GIT STATUS", ["git", "status", "--short"]),
            ("GIT BRANCH", ["git", "branch", "--show-current"]),
            ("GIT DIFF STAT", ["git", "diff", "--stat"]),
            ("GIT CACHED DIFF STAT", ["git", "diff", "--cached", "--stat"]),
            ("RECENT COMMITS", ["git", "log", "-5", "--oneline"]),
        ]
        for heading, cmd in git_commands:
            sections.extend([heading, run_cmd(cmd, root)])

        remote_text = run_cmd(["git", "remote", "-v"], root)
        remote_text = re.sub(r"(https?://)[^/@\s]+(:[^/@\s]*)?@", r"\1[REDACTED]@", remote_text)
        sections.extend(["GIT REMOTES (credentials redacted)", remote_text])

        if not args.no_tests:
            sections.extend([
                "COMPILE CHECK",
                run_cmd([sys.executable, "-m", "compileall", "-q", "app", "tests"], root, timeout=120),
                "PYTEST RESULTS",
                run_cmd([sys.executable, "-m", "pytest", "-q"], root, timeout=180),
            ])
        else:
            sections.append("Tests not run: --no-tests was specified.\n")

        # Summarize relevant identifiers without reading environment values.
        registry = root / "app" / "sources" / "__init__.py"
        config = root / "app" / "config.py"
        sections.extend(["REGISTRY/CONFIG QUICK SCAN", ""])
        for path in (registry, config):
            sections.append(f"--- {path.relative_to(root)} ---")
            try:
                body = path.read_text(encoding="utf-8")
                for i, line in enumerate(body.splitlines(), 1):
                    if re.search(r"enabled_sources|fetch_jobs|rss_feeds|greenhouse|lever_sites|ashby_boards|career_pages|WORLDWIDE|eligibility", line, re.I):
                        sections.append(f"{i}: {line[:240]}")
            except OSError as exc:
                sections.append(f"Could not read file: {exc}")
            sections.append("")

        (staging / "DIAGNOSTICS.txt").write_text("\n".join(sections), encoding="utf-8")
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for path in staging.rglob("*"):
                if path.is_file():
                    zf.write(path, path.relative_to(staging))

    print(f"Created: {zip_path}")
    print("Included app/test/script source, GitHub workflows/actions, root config, company_targets.csv, Git metadata, and compile/test diagnostics.")
    print("Please inspect the ZIP before uploading it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
