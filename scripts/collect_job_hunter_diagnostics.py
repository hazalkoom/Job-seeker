#!/usr/bin/env python3
"""Create a safe Job Hunter diagnostics ZIP for debugging skip/rejection reasons.

Run from repository root:
    python scripts/collect_job_hunter_diagnostics.py

The collector never copies .env, candidate profile/answer-bank files, private CVs,
raw SQLite databases, browser state, encrypted secret files, or raw log files. It
exports a sanitized, read-only summary of job/queue/event rows and filtered logs.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import platform
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SKIP_DIRS = {
    ".git", ".venv", "venv", "env", "__pycache__", ".pytest_cache",
    ".mypy_cache", ".ruff_cache", "node_modules", "dist", "build",
    "site-packages", ".tox", ".nox", "private", "candidate_documents",
    "storage", "browser-profile", "browser_state", ".cache",
}
SKIP_SUFFIXES = {
    ".sqlite", ".sqlite3", ".db", ".log", ".pem", ".key", ".p12",
    ".pfx", ".pyc", ".pyo", ".zip", ".tar", ".gz", ".gpg",
    ".png", ".jpg", ".jpeg", ".webp", ".pdf", ".docx", ".doc",
}
SENSITIVE_NAMES = {
    ".env", "candidate_profile.json", "application_answers.json",
    "storage-state.json", "state.json", "cookies.json", "credentials.json",
    "service-account.json", "id_rsa", "id_ed25519",
}
ROOT_ALLOWLIST = {
    "run_once.py", "main.py", "pyproject.toml", "requirements.txt",
    "requirements-dev.txt", "pytest.ini", "setup.cfg", "tox.ini", "setup.py",
    "Pipfile", "Makefile", "README.md", ".env.example", ".gitignore",
}
INTERESTING_LOG = re.compile(
    r"AUTO_APPLY_AUDIT|auto.?apply|application|submitted|auto_skipped|skipp?ed|"
    r"eligib|reject|reason|source_errors|source error|source_count|timed out|"
    r"captcha|ats|preflight|Playwright|profile.*valid|failed|ERROR|Traceback|pytest",
    re.I,
)


def _sanitize_text(text: str) -> str:
    # Import the same scrubber used by the runtime audit log.
    try:
        from app.automation_diagnostics import sanitize
        return str(sanitize(text))[:2500]
    except Exception:
        text = re.sub(r"\b\d{7,}:[A-Za-z0-9_-]{20,}\b", "<telegram-token-redacted>", text)
        text = re.sub(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", "<email-redacted>", text, flags=re.I)
        text = re.sub(r"(?i)(api[_ -]?key|password|secret|passphrase|token)\s*[:=]\s*([^\s,;]+)", r"\1=<redacted>", text)
        return text[:2500]


def _sanitize_obj(obj: Any) -> Any:
    try:
        from app.automation_diagnostics import sanitize
        return sanitize(obj)
    except Exception:
        if isinstance(obj, dict):
            result = {}
            for key, value in obj.items():
                low = str(key).casefold()
                if any(k in low for k in ("password", "token", "secret", "passphrase", "cookie", "answer_value", "field_value")) or low in {"answer", "value", "profile", "answer_bank", "headers", "html", "body"}:
                    result[str(key)] = "<redacted>"
                else:
                    result[str(key)] = _sanitize_obj(value)
            return result
        if isinstance(obj, list):
            return [_sanitize_obj(item) for item in obj[:100]]
        if isinstance(obj, str):
            return _sanitize_text(obj)
        return obj


def _run(cmd: list[str], timeout: int = 45, cwd: Path = ROOT) -> dict[str, Any]:
    try:
        p = subprocess.run(
            cmd, cwd=cwd, text=True, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, timeout=timeout, check=False,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        output = _sanitize_text(p.stdout or "")
        return {"command": " ".join(cmd), "exit_code": p.returncode, "output": output}
    except FileNotFoundError:
        return {"command": " ".join(cmd), "unavailable": True, "output": "Command not installed."}
    except subprocess.TimeoutExpired as exc:
        out = exc.stdout or ""
        if isinstance(out, bytes):
            out = out.decode("utf-8", errors="replace")
        return {"command": " ".join(cmd), "timed_out": True, "output": _sanitize_text(out)}


def _sensitive_file(path: Path) -> bool:
    if path.name.lower() in SENSITIVE_NAMES:
        return True
    if path.name.lower().startswith(".env") and path.name != ".env.example":
        return True
    if path.suffix.lower() in SKIP_SUFFIXES:
        return True
    if path.name.lower().endswith(".gpg"):
        return True
    if any(part.lower() in SKIP_DIRS for part in path.parts):
        return True
    if any(term in path.name.lower() for term in ("credential", "secret", "token", "password", "resume", "cv_")):
        return True
    return False


def _copy_safe_text(src: Path, dst: Path) -> None:
    if _sensitive_file(src):
        return
    try:
        body = src.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return
    if src.name == ".env.example":
        clean_lines = []
        for line in body.splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                name = line.split("=", 1)[0].strip().upper()
                if any(word in name for word in ("KEY", "TOKEN", "SECRET", "PASSWORD", "PASSWD", "BOT_TOKEN", "API_KEY", "EMAIL_ALERTS_USERNAME")):
                    line = line.split("=", 1)[0] + "=<redacted-by-collector>"
            clean_lines.append(line)
        body = "\n".join(clean_lines) + ("\n" if body.endswith("\n") else "")
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(body, encoding="utf-8")


def _candidate_files(root: Path) -> list[Path]:
    candidates: set[Path] = set()
    for foldername in ("app", "tests", "scripts"):
        folder = root / foldername
        if not folder.is_dir():
            continue
        for current, dirnames, filenames in os.walk(folder):
            dirnames[:] = [name for name in dirnames if name not in SKIP_DIRS]
            for filename in filenames:
                path = Path(current) / filename
                if _sensitive_file(path):
                    continue
                if path.suffix == ".py" or (foldername == "scripts" and path.suffix in {".sh", ".md", ".txt"}):
                    candidates.add(path)
    workflow_dir = root / ".github" / "workflows"
    if workflow_dir.is_dir():
        for path in workflow_dir.glob("*.y*ml"):
            if not _sensitive_file(path):
                candidates.add(path)
    docs_dir = root / "docs"
    if docs_dir.is_dir():
        for path in docs_dir.rglob("*.md"):
            if not _sensitive_file(path):
                candidates.add(path)
    for name in ROOT_ALLOWLIST:
        path = root / name
        if path.is_file() and not _sensitive_file(path):
            candidates.add(path)
    return sorted(candidates)


def _connect_ro(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=5)


def _json_field(value: Any, default: Any) -> Any:
    try:
        return json.loads(str(value or ""))
    except (TypeError, json.JSONDecodeError):
        return default


def _database_snapshot(root: Path) -> dict[str, Any]:
    from app.config import settings
    from app.automation_diagnostics import reason_code_for_reason, safe_url

    db_path = Path(settings.database_path).expanduser()
    if not db_path.is_absolute():
        db_path = root / db_path
    report: dict[str, Any] = {
        "exists": db_path.is_file(),
        "file_name": db_path.name,
        "raw_database_included": False,
        "tables": {},
        "job_status_counts": {},
        "job_source_status_counts": [],
        "queue_status_counts": {},
        "queue_qualification_counts": {},
        "event_counts": {},
        "application_records": [],
        "job_records": [],
        "event_records": [],
        "event_reason_counts": {},
    }
    if not db_path.is_file():
        return report
    try:
        with _connect_ro(db_path) as conn:
            conn.row_factory = sqlite3.Row
            tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            report["tables"] = {name: name in tables for name in ("jobs", "application_queue", "application_events")}
            if "jobs" in tables:
                report["job_status_counts"] = {str(r[0]): int(r[1]) for r in conn.execute("SELECT status,COUNT(*) FROM jobs GROUP BY status")}
                report["job_source_status_counts"] = [dict(r) for r in conn.execute("SELECT source,status,COUNT(*) AS count FROM jobs GROUP BY source,status ORDER BY source,status")]
                rows = conn.execute(
                    "SELECT id,source,source_id,title,company,location,url,description,posted_at,date_kind,remote,"
                    "workplace_type,employment_type,eligibility,description_quality,status,score,reasons,concerns,"
                    "first_seen_at,last_seen_at FROM jobs ORDER BY last_seen_at DESC LIMIT 300"
                )
                for row in rows:
                    item = dict(row)
                    item["url"] = safe_url(item.get("url"))
                    item["source_id"] = safe_url(item.get("source_id")) if str(item.get("source_id", "")).startswith(("http://", "https://")) else _sanitize_text(str(item.get("source_id") or ""))[:300]
                    item["description"] = _sanitize_text(str(item.get("description") or "")[:3500])
                    item["reasons"] = _json_field(item.get("reasons"), [])
                    item["concerns"] = _json_field(item.get("concerns"), [])
                    report["job_records"].append(_sanitize_obj(item))
            if "application_queue" in tables:
                report["queue_status_counts"] = {str(r[0]): int(r[1]) for r in conn.execute("SELECT status,COUNT(*) FROM application_queue GROUP BY status")}
                report["queue_qualification_counts"] = {str(r[0]): int(r[1]) for r in conn.execute("SELECT qualification_status,COUNT(*) FROM application_queue GROUP BY qualification_status")}
                rows = conn.execute(
                    "SELECT q.id AS queue_id,q.job_id,q.canonical_url,q.status,q.qualification_status,q.score,"
                    "q.reasons,q.concerns,q.preflight_status,q.preflight_blockers,q.preflight_warnings,"
                    "q.sightings_count,q.first_seen_at,q.last_seen_at,q.updated_at,q.reviewed_at,q.ready_at,"
                    "q.submitted_at,q.submission_reference,q.notes,j.source,j.source_id,j.title,j.company,j.location,"
                    "j.url,j.posted_at,j.date_kind,j.description_quality,j.workplace_type,j.employment_type,j.remote,"
                    "j.eligibility,j.description FROM application_queue q JOIN jobs j ON j.id=q.job_id "
                    "ORDER BY q.updated_at DESC LIMIT 500"
                )
                for row in rows:
                    item = dict(row)
                    item["canonical_url"] = safe_url(item.get("canonical_url"))
                    item["url"] = safe_url(item.get("url"))
                    item["submission_reference"] = safe_url(item.get("submission_reference"))
                    item["reasons"] = _json_field(item.get("reasons"), [])
                    item["concerns"] = _json_field(item.get("concerns"), [])
                    item["preflight_blockers"] = _json_field(item.get("preflight_blockers"), [])
                    item["preflight_warnings"] = _json_field(item.get("preflight_warnings"), [])
                    item["description"] = _sanitize_text(str(item.get("description") or "")[:4500])
                    item["reason_code"] = reason_code_for_reason(str(item.get("notes") or ""), stage="stored_outcome")
                    report["application_records"].append(_sanitize_obj(item))
            if "application_events" in tables:
                report["event_counts"] = {str(r[0]): int(r[1]) for r in conn.execute("SELECT event_type,COUNT(*) FROM application_events GROUP BY event_type ORDER BY COUNT(*) DESC,event_type")}
                rows = conn.execute("SELECT id,queue_id,event_type,details,created_at FROM application_events ORDER BY id DESC LIMIT 1500")
                reason_counts: Counter[str] = Counter()
                for row in rows:
                    details = _json_field(row["details"], {})
                    if not isinstance(details, dict):
                        details = {}
                    reason = str(details.get("reason") or "")
                    code = str(details.get("reason_code") or reason_code_for_reason(reason, stage=str(row["event_type"])))
                    if row["event_type"] in {"application_auto_skipped", "application_failed"}:
                        reason_counts[code] += 1
                    details["reason_code"] = code
                    report["event_records"].append(_sanitize_obj({
                        "event_id": row["id"], "queue_id": row["queue_id"],
                        "event_type": row["event_type"], "created_at": row["created_at"], "details": details,
                    }))
                report["event_reason_counts"] = dict(reason_counts.most_common())
    except sqlite3.Error as exc:
        report["read_error_type"] = type(exc).__name__
    return report


def _settings_snapshot(root: Path) -> dict[str, Any]:
    from app.config import settings
    env_names: list[str] = []
    env_path = root / ".env"
    if env_path.is_file():
        try:
            for line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
                raw = line.strip()
                if raw and not raw.startswith("#") and "=" in raw:
                    env_names.append(raw.split("=", 1)[0].strip())
        except OSError:
            pass
    sensitive_names = [
        "TELEGRAM_BOT_TOKEN", "SERPAPI_API_KEY", "EMAIL_ALERTS_USERNAME",
        "EMAIL_ALERTS_PASSWORD", "AUTOPILOT_DECRYPTION_PASSPHRASE",
    ]
    boolean_settings = {}
    for key in (
        "auto_apply_enabled", "auto_apply_max_per_day", "auto_apply_min_score",
        "auto_apply_delay_seconds", "auto_apply_headless", "auto_apply_timeout_seconds",
        "max_required_experience_years", "max_posting_age_days", "min_match_score",
        "enable_google_jobs", "enable_himalayas", "enable_arbeitnow", "enable_remoteok",
        "enable_remotive", "enable_jobicy", "enable_european_tech_opportunities",
        "enable_nomado24", "enable_rss_feeds", "enable_email_alerts",
        "enable_greenhouse", "enable_lever", "enable_ashby", "enable_career_pages",
        "notify_review_candidates",
    ):
        boolean_settings[key] = getattr(settings, key, None)
    resume_candidate = Path(settings.auto_apply_resume_path).expanduser()
    if not resume_candidate.is_absolute():
        resume_candidate = root / resume_candidate
    return {
        "nonsecret_runtime_settings": boolean_settings,
        "credential_presence_only": {
            "telegram_configured": bool(settings.telegram_bot_token and settings.telegram_chat_id),
            "serpapi_configured": bool(settings.serpapi_api_key),
            "email_alerts_configured": bool(settings.email_alerts_username and settings.email_alerts_password),
            "github_decryption_key_env_name_present_in_dotenv": "AUTOPILOT_DECRYPTION_PASSPHRASE" in env_names,
        },
        "dotenv_variable_names_only": sorted(set(env_names)),
        "candidate_profile_file_exists": (root / "candidate_profile.json").is_file(),
        "answer_bank_file_exists": (root / "application_answers.json").is_file(),
        "configured_resume_exists": resume_candidate.is_file(),
        "configured_resume_basename": resume_candidate.name if resume_candidate.is_file() else None,
        "database_name": Path(settings.database_path).name,
    }


def _log_tails(root: Path, include_github_logs: bool) -> dict[str, Any]:
    output: dict[str, Any] = {"latest_run_report": None, "application_audit_jsonl": [], "systemd_service_log": [], "systemd_timer_status": "", "github_workflow_runs": [], "github_workflow_log_excerpt": [], "github_run_reports": [], "github_artifact_audit_jsonl": []}
    report_path = root / "logs" / "latest_run_report.json"
    if report_path.is_file():
        try:
            output["latest_run_report"] = _sanitize_obj(json.loads(report_path.read_text(encoding="utf-8", errors="replace")))
        except (OSError, json.JSONDecodeError):
            output["latest_run_report"] = {"error": "latest run report could not be parsed"}
    app_log = root / "logs" / "application_automation.jsonl"
    if app_log.is_file():
        for line in app_log.read_text(encoding="utf-8", errors="replace").splitlines()[-1500:]:
            try:
                output["application_audit_jsonl"].append(_sanitize_obj(json.loads(line)))
            except json.JSONDecodeError:
                output["application_audit_jsonl"].append({"unparsed": _sanitize_text(line)})
    for name, command in (
        ("systemd_service_log", ["journalctl", "--user", "-u", "job-hunter-autopilot.service", "-n", "1800", "--no-pager", "-o", "cat"]),
        ("systemd_timer_status", ["systemctl", "--user", "--no-pager", "status", "job-hunter-autopilot.timer"]),
    ):
        result = _run(command, timeout=30)
        if name == "systemd_timer_status":
            output[name] = result.get("output", "")[:5000]
        else:
            lines = result.get("output", "").splitlines()
            filtered = [line for line in lines if INTERESTING_LOG.search(line)]
            output[name] = [_sanitize_text(line) for line in filtered[-700:]]
    if include_github_logs and shutil.which("gh"):
        run_result = _run(["gh", "run", "list", "--workflow", "job-hunter.yml", "--limit", "4", "--json", "databaseId,status,conclusion,createdAt,displayTitle,headBranch,url"], timeout=45)
        try:
            runs = json.loads(run_result.get("output", "[]")) if run_result.get("exit_code") == 0 else []
        except json.JSONDecodeError:
            runs = []
        if isinstance(runs, list):
            output["github_workflow_runs"] = _sanitize_obj(runs[:4])
            for run in runs[:3]:
                run_id = run.get("databaseId")
                if not run_id:
                    continue
                log_result = _run(["gh", "run", "view", str(run_id), "--log"], timeout=75)
                lines = log_result.get("output", "").splitlines()
                filtered = [line for line in lines if INTERESTING_LOG.search(line)]
                output["github_workflow_log_excerpt"].append({
                    "run_id": run_id,
                    "log_available": bool(log_result.get("exit_code") == 0),
                    "excerpt": [_sanitize_text(line) for line in filtered[-450:]],
                    "error": None if log_result.get("exit_code") == 0 else "GitHub Actions logs unavailable through gh CLI.",
                })
                # Download only the deliberately redacted diagnostic artifact, never the DB artifact.
                with tempfile.TemporaryDirectory(prefix="job-hunter-gh-diag-") as tmpdir:
                    outdir = Path(tmpdir) / "artifact"
                    download = _run([
                        "gh", "run", "download", str(run_id),
                        "--name", f"job-hunter-diagnostics-{run_id}",
                        "--dir", str(outdir),
                    ], timeout=75)
                    report_path = outdir / "run-report.json"
                    if download.get("exit_code") == 0 and report_path.is_file():
                        try:
                            raw_report = json.loads(report_path.read_text(encoding="utf-8", errors="replace"))
                        except (OSError, json.JSONDecodeError):
                            raw_report = {}
                        if isinstance(raw_report, dict):
                            auto = raw_report.get("auto_apply") or {}
                            picked_results = []
                            if isinstance(auto, dict):
                                for entry in auto.get("results", [])[:200]:
                                    if isinstance(entry, dict):
                                        picked_results.append({key: entry.get(key) for key in (
                                            "queue_id", "title", "company", "source", "outcome",
                                            "reason_code", "reason", "ats_host", "apply_links",
                                            "diagnostics", "form_diagnostics",
                                        ) if key in entry})
                            output["github_run_reports"].append(_sanitize_obj({
                                "run": run,
                                "overall": {key: raw_report.get(key) for key in (
                                    "seen_after_cross_source_dedup", "newly_stored", "confirmed_matches",
                                    "review_candidates", "rejected", "source_counts", "source_effectiveness",
                                    "source_errors", "top_rejection_reasons",
                                ) if key in raw_report},
                                "auto_apply": {
                                    key: auto.get(key) for key in (
                                        "enabled", "processed", "submitted", "skipped", "failed",
                                        "reason", "error", "reason_breakdown", "daily_cap",
                                    ) if isinstance(auto, dict) and key in auto
                                },
                                "application_results": picked_results,
                            }))
                    artifact_log = outdir / "logs" / "application_automation.jsonl"
                    if download.get("exit_code") == 0 and artifact_log.is_file():
                        for line in artifact_log.read_text(encoding="utf-8", errors="replace").splitlines()[-900:]:
                            try:
                                output["github_artifact_audit_jsonl"].append(_sanitize_obj(json.loads(line)))
                            except json.JSONDecodeError:
                                continue
        elif run_result.get("output"):
            output["github_workflow_runs_error"] = _sanitize_text(run_result["output"][:500])
    elif include_github_logs:
        output["github_workflow_runs_error"] = "GitHub CLI (gh) is not installed; local diagnostics were still collected."
    return output


def _git_snapshot(root: Path) -> dict[str, Any]:
    results = {}
    for key, command in (
        ("status", ["git", "status", "--short"]),
        ("diff_stat", ["git", "diff", "--stat"]),
        ("recent_commits", ["git", "log", "-5", "--oneline"]),
        ("branch", ["git", "branch", "--show-current"]),
    ):
        result = _run(command, timeout=20, cwd=root)
        results[key] = result.get("output", "")[:10000]
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--no-tests", action="store_true", help="Do not run compileall/pytest")
    parser.add_argument("--no-github-logs", action="store_true", help="Skip gh workflow run listing/log excerpts")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    if not (root / "app" / "sources" / "__init__.py").is_file():
        print("ERROR: run from the Job Hunter project root (app/sources/__init__.py not found).", file=sys.stderr)
        return 2

    now = dt.datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")
    output_zip = root / f"job_hunter_diagnostics_{now}.zip"
    tmp_parent = tempfile.mkdtemp(prefix="job-hunter-diagnostics-")
    try:
        staging = Path(tmp_parent) / "job_hunter_diagnostics"
        project_dir = staging / "project_files"
        files = _candidate_files(root)
        for src in files:
            try:
                relative = src.relative_to(root)
            except ValueError:
                continue
            _copy_safe_text(src, project_dir / relative)

        try:
            from app.config import settings
            root_metadata = {
                "generated_at": dt.datetime.now().astimezone().isoformat(),
                "python_version": sys.version,
                "python_executable_basename": Path(sys.executable).name,
                "platform": platform.platform(),
                "project_directory_name": root.name,
                "project_file_count": len(list(project_dir.rglob("*"))),
                "settings": _settings_snapshot(root),
                "database": _database_snapshot(root),
                "git": _git_snapshot(root),
                "logs": _log_tails(root, include_github_logs=not args.no_github_logs),
            }
        except Exception as exc:
            root_metadata = {
                "generated_at": dt.datetime.now().astimezone().isoformat(),
                "python_version": sys.version,
                "platform": platform.platform(),
                "collector_error_type": type(exc).__name__,
                "collector_error": _sanitize_text(str(exc)),
                "git": _git_snapshot(root),
                "logs": _log_tails(root, include_github_logs=not args.no_github_logs),
            }

        if not args.no_tests:
            root_metadata["compile_check"] = _run([sys.executable, "-m", "compileall", "-q", "app", "scripts", "tests"], timeout=120)
            root_metadata["pytest"] = _run([sys.executable, "-m", "pytest", "-q"], timeout=240)
        else:
            root_metadata["tests"] = "Not run (--no-tests supplied)."

        root_metadata = _sanitize_obj(root_metadata)
        (staging / "DIAGNOSTICS.json").write_text(json.dumps(root_metadata, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        summary = [
            "JOB HUNTER DIAGNOSTIC BUNDLE",
            "",
            f"Generated: {root_metadata.get('generated_at', '')}",
            f"Project name: {root.name}",
            "",
            "PRIVACY",
            "- .env values, candidate_profile.json, application_answers.json, CV/PDFs, browser cookies, GPG files, raw SQLite databases and raw log files were not copied.",
            "- Database contents are represented only by sanitized job/queue/event summaries and public listing descriptions.",
            "- Logs are filtered and redacted; verify this file before sharing it.",
            "",
            "QUEUE STATUS COUNTS",
        ]
        summary += [f"- {k}: {v}" for k, v in root_metadata.get("database", {}).get("queue_status_counts", {}).items()] or ["- No queue table/records were found."]
        summary += ["", "MOST COMMON AUTOMATION REASON CODES"]
        summary += [f"- {k}: {v}" for k, v in root_metadata.get("database", {}).get("event_reason_counts", {}).items()][:20] or ["- No automation events found yet."]
        summary += ["", "Files included:"]
        summary += [f"- {p.relative_to(project_dir)}" for p in sorted(project_dir.rglob("*")) if p.is_file()]
        (staging / "DIAGNOSTICS.txt").write_text("\n".join(summary) + "\n", encoding="utf-8")

        with zipfile.ZipFile(output_zip, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in staging.rglob("*"):
                if path.is_file():
                    archive.write(path, path.relative_to(staging))
    finally:
        shutil.rmtree(tmp_parent, ignore_errors=True)

    print(f"Created: {output_zip}")
    print("Raw database, .env values, candidate profile, answer bank, CV, browser state and encrypted secrets were excluded.")
    print("Included sanitized queue/event summaries, filtered local/GitHub logs where available, code, tests and test results.")
    print("Please inspect DIAGNOSTICS.txt in the ZIP before uploading; no file collector can guarantee perfect redaction.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
