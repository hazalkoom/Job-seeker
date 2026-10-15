#!/usr/bin/env python3
"""Create a privacy-conscious Job Hunter diagnostic ZIP.

Run from the project root:
    python scripts/collect_job_hunter_debug.py

Includes application/test source, GitHub Actions workflow definitions, selected
project configuration, Git metadata, and local compile/test results. It never
copies .env files, databases, logs, archives, virtual environments, or caches.
Review the archive before uploading it.
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
    "site-packages", ".tox", ".nox", ".phase2-backup", ".workflow-debug-backups",
}
SKIP_SUFFIXES = {
    ".sqlite", ".sqlite3", ".db", ".log", ".pem", ".key", ".p12",
    ".pfx", ".pyc", ".pyo", ".zip", ".tar", ".gz", ".whl", ".bak",
}
SAFE_ROOT_FILES = {
    "run_once.py", "main.py", "pyproject.toml", "requirements.txt",
    "requirements-dev.txt", "requirements.lock", "pytest.ini", "setup.cfg",
    "tox.ini", "setup.py", "Pipfile", "Pipfile.lock", "Makefile", "README.md",
    ".env.example", ".gitignore", ".dockerignore", ".python-version",
    "company_targets.csv", "Dockerfile", "compose.yaml", "docker-compose.yml",
    "uv.lock", "poetry.lock", "ruff.toml", ".coveragerc", "mypy.ini",
}
SOURCE_SUFFIXES = {".py"}
SCRIPT_SUFFIXES = {".py", ".sh", ".md", ".txt"}
WORKFLOW_SUFFIXES = {".yml", ".yaml"}
ACTION_SUFFIXES = {".yml", ".yaml", ".py", ".sh", ".js", ".md", ".json"}
SENSITIVE_KEY_RE = re.compile(
    r"(TOKEN|PASSWORD|PASSWD|SECRET|PRIVATE[_ -]?KEY|CREDENTIAL|API[_ -]?KEY)",
    re.IGNORECASE,
)


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


def _redact_assignment(line: str, file_name: str) -> str:
    """Redact literal secret-like assignments but preserve GitHub secret refs."""
    if not line.strip() or line.lstrip().startswith(("#", "//")):
        return line

    # .env.example uses KEY=value. Keep the key and redact values that can be secret.
    if file_name == ".env.example" and "=" in line:
        key, value = line.split("=", 1)
        if SENSITIVE_KEY_RE.search(key):
            return f"{key}=<redacted-by-collector>"
        return line

    # GitHub workflow/action YAML can contain either safe secret references or a
    # mistakenly hard-coded value. Preserve expressions but redact literals.
    if file_name.endswith((".yml", ".yaml", ".json")):
        match = re.match(r"^(\s*[^:#\n]+?\s*:\s*)(.*?)(\s+#.*)?$", line)
        if match and SENSITIVE_KEY_RE.search(match.group(1)):
            value = match.group(2).strip()
            if "${{" in value and ("secrets." in value or "vars." in value or "env." in value):
                return line
            if value and value.lower() not in {"null", "none", "''", '""'}:
                comment = match.group(3) or ""
                return f"{match.group(1)}<redacted-by-collector>{comment}"
    return line


def safe_copy(src: Path, dst: Path) -> None:
    """Copy UTF-8 source while redacting common secret assignments."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        text = src.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return
    text = "\n".join(_redact_assignment(line, src.name) for line in text.splitlines())
    if src.read_text(encoding="utf-8").endswith("\n"):
        text += "\n"
    dst.write_text(text, encoding="utf-8")


def candidate_files(root: Path) -> list[Path]:
    files: set[Path] = set()
    source_roots = [
        (root / "app", SOURCE_SUFFIXES),
        (root / "tests", SOURCE_SUFFIXES),
        (root / "scripts", SCRIPT_SUFFIXES),
        # Workflow definitions are essential when diagnosing scheduled runs.
        (root / ".github" / "workflows", WORKFLOW_SUFFIXES),
        # Include custom composite action definitions/code, if this repo uses them.
        (root / ".github" / "actions", ACTION_SUFFIXES),
    ]
    for folder, suffixes in source_roots:
        if not folder.is_dir():
            continue
        for current, dirnames, filenames in os.walk(folder):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for filename in filenames:
                path = Path(current) / filename
                if is_sensitive(path) or path.suffix.lower() not in suffixes:
                    continue
                files.add(path)

    for filename in SAFE_ROOT_FILES:
        path = root / filename
        if path.is_file() and not is_sensitive(path):
            files.add(path)

    # Include the .github/dependabot config if present; no credential files are scanned.
    for path in (root / ".github" / "dependabot.yml", root / ".github" / "dependabot.yaml"):
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
            "The collector excludes .env files, databases, logs, archives, virtual environments, caches, and common credential filenames.",
            "GitHub workflow/action YAML is included with literal secret-like assignments redacted; references such as ${{ secrets.X }} are preserved.",
            "No live job hunt is run by the collector. Compile/test commands are run unless --no-tests is supplied.",
            "Review this ZIP before uploading; it contains application code and project configuration.",
            "",
            "FILES INCLUDED",
            *files_list,
            "",
        ]

        commands = [
            ("CURRENT BRANCH", ["git", "branch", "--show-current"]),
            ("CURRENT UPSTREAM", ["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"]),
            ("GIT STATUS", ["git", "status", "--short"]),
            ("GIT DIFF STAT", ["git", "diff", "--stat"]),
            ("STAGED DIFF STAT", ["git", "diff", "--cached", "--stat"]),
            ("UNTRACKED FILE NAMES", ["git", "ls-files", "--others", "--exclude-standard"]),
            ("RECENT COMMITS", ["git", "log", "-5", "--oneline"]),
        ]
        for heading, cmd in commands:
            sections.extend([heading, run_cmd(cmd, root)])

        if not args.no_tests:
            sections.extend([
                "COMPILE CHECK",
                run_cmd([sys.executable, "-m", "compileall", "-q", "app", "tests"], root, timeout=120),
                "PYTEST RESULTS",
                run_cmd([sys.executable, "-m", "pytest", "-q"], root, timeout=180),
            ])
        else:
            sections.append("Tests not run: --no-tests was specified.\n")

        sections.extend(["WORKFLOW / CONFIG QUICK SCAN", ""])
        scan_paths = [
            root / ".github" / "workflows" / "job-hunter.yml",
            root / "app" / "sources" / "__init__.py",
            root / "app" / "config.py",
        ]
        scan_pattern = re.compile(
            r"schedule:|cron:|timezone:|workflow_dispatch|NOTIFY_REVIEW_CANDIDATES|"
            r"REVIEW_DIGEST_SIZE|ENABLE_EUROPEAN|ENABLE_NOMADO|RSS_FEEDS|"
            r"enabled_sources|fetch_jobs|greenhouse|lever_sites|ashby_boards|"
            r"career_pages|WORLDWIDE|eligibility|NOMADO24_MAX_PAGES|EUROPEAN_TECH_OPPORTUNITIES_MAX_PAGES",
            re.I,
        )
        for path in scan_paths:
            if not path.is_file():
                continue
            sections.append(f"--- {path.relative_to(root)} ---")
            try:
                body = path.read_text(encoding="utf-8")
                for i, line in enumerate(body.splitlines(), 1):
                    if scan_pattern.search(line):
                        sections.append(f"{i}: {_redact_assignment(line, path.name)[:240]}")
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
    print("Excluded .env files, databases, logs, archives, virtualenvs, and caches. Inspect the ZIP before uploading it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
