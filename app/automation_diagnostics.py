"""Privacy-conscious structured audit logging for automatic applications.

The logger intentionally never stores form input values, profile answers, cookies,
full page HTML, query strings, or credential values. It writes JSONL locally and
emits AUTO_APPLY_AUDIT records to stderr so GitHub Actions/systemd collect them.
"""
from __future__ import annotations

import json
import os
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parent.parent
_EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
_TELEGRAM_TOKEN_RE = re.compile(r"\b\d{7,}:[A-Za-z0-9_-]{20,}\b")
_BEARER_RE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/-]+=*")
_SECRET_ASSIGN_RE = re.compile(
    r"(?i)\b(api[_ -]?key|access[_ -]?token|refresh[_ -]?token|token|password|passphrase|secret)\b\s*[:=]\s*([^\s,;]+)"
)
_SENSITIVE_KEYS = {
    "answer", "resolved_answer", "field_value", "input_value", "value",
    "password", "token", "secret", "passphrase", "cookie", "cookies",
    "authorization", "headers", "body", "html", "page_html", "raw_body",
    "profile", "answer_bank", "resume_contents", "cv_contents", "email_value",
}


def new_run_id() -> str:
    return uuid.uuid4().hex[:12]


def safe_url(value: Any) -> str:
    """Return an HTTP URL without credentials, query parameters, or fragments."""
    raw = str(value or "")
    try:
        p = urlsplit(raw)
        if p.scheme not in {"http", "https"} or not p.hostname:
            return _scrub_text(raw)[:500]
        host = p.hostname
        if p.port:
            host = f"{host}:{p.port}"
        return urlunsplit((p.scheme, host, p.path[:500], "", ""))[:800]
    except Exception:
        return _scrub_text(raw)[:500]


def _scrub_text(value: str) -> str:
    value = _TELEGRAM_TOKEN_RE.sub("<telegram-token-redacted>", value)
    value = _BEARER_RE.sub("Bearer <redacted>", value)
    value = _SECRET_ASSIGN_RE.sub(r"\1=<redacted>", value)
    value = _EMAIL_RE.sub("<email-redacted>", value)
    value = re.sub(r"(?i)(https?://[^\s?#]+)\?[^\s#]*", r"\1?<query-redacted>", value)
    # Scrub common long API key/token shapes without destroying normal URLs/IDs.
    value = re.sub(r"\b(?=[A-Za-z0-9_-]{32,}\b)(?=.*[A-Za-z])(?=.*\d)[A-Za-z0-9_-]+\b", "<long-token-redacted>", value)
    return value[:2500]


def sanitize(value: Any, key: str = "") -> Any:
    key_l = key.casefold()
    if key_l in _SENSITIVE_KEYS or any(marker in key_l for marker in ("password", "token", "secret", "passphrase", "cookie", "answer_value", "field_value")):
        return "<redacted>"
    if isinstance(value, dict):
        clean: dict[str, Any] = {}
        for k, v in value.items():
            k_s = str(k)
            if k_s.casefold() in _SENSITIVE_KEYS or any(marker in k_s.casefold() for marker in ("password", "token", "secret", "passphrase", "cookie", "answer_value", "field_value")):
                clean[k_s] = "<redacted>"
            elif k_s.casefold() in {"url", "href", "reference", "application_url", "listing_url"}:
                clean[k_s] = safe_url(v)
            else:
                clean[k_s] = sanitize(v, k_s)
        return clean
    if isinstance(value, (list, tuple, set)):
        return [sanitize(v, key) for v in list(value)[:100]]
    if isinstance(value, str):
        return _scrub_text(value)
    if value is None or isinstance(value, (int, float, bool)):
        return value
    return _scrub_text(str(value))


def reason_code_for_reason(reason: str, stage: str = "") -> str:
    text = str(reason or "").casefold()
    if "captcha" in text or "anti-bot" in text or "security challenge" in text:
        return "captcha_or_antibot"
    if "original publication date" in text or "posting date" in text or "stale" in text:
        return "posting_date_unverified_or_stale"
    if "full employer description" in text or "snippet" in text or "description" in text and "unavailable" in text:
        return "description_unavailable"
    if "egypt" in text or "eligibility" in text or "country restriction" in text or "location" in text and "outside" in text:
        return "egypt_eligibility_unconfirmed"
    if "experience" in text and ("exceed" in text or "year" in text):
        return "experience_above_limit"
    if "score threshold" in text or "below automatic" in text:
        return "score_below_threshold"
    if "qualification filter rejected" in text:
        return "qualification_rejected"
    if "no supported public ats" in text or "supported ats application form" in text:
        return "no_supported_ats_form"
    if "unsupported application host" in text or "unsupported ats" in text:
        return "unsupported_ats_host"
    if "no recognizable public application form" in text or "no application form" in text:
        return "application_form_not_detected"
    if "required fields" in text or "required question" in text or "required dropdown" in text or "required checkbox" in text or "required radio" in text:
        return "required_field_unanswered"
    if "no application fields" in text or "no application fields were confidently filled" in text:
        return "no_fields_confidently_filled"
    if "preflight" in text:
        return "preflight_failed"
    if "timed out" in text or "timeout" in text:
        return "site_timeout"
    if "validation/error" in text or "validation state" in text:
        return "site_validation_error"
    if "employer identity is missing" in text:
        return "employer_identity_missing"
    if "already has a submission or an unresolved attempt" in text:
        return "duplicate_or_unresolved_attempt"
    if "http 403" in text:
        return "listing_access_denied"
    if "not confirmed" in text or "uncertain" in text:
        return "submission_uncertain"
    if "browser automation error" in text or "browser could not start" in text:
        return "browser_error"
    if "submit" in text and "confirmation" in text:
        return "submission_confirmed"
    if "company" in text and ("missing" in text or "uncertain" in text):
        return "employer_identity_missing"
    if "valid title" in text or "job url" in text:
        return "job_metadata_missing"
    if ("job-board" in text or "aggregator" in text) and ("account" in text or "login" in text):
        return "aggregator_account_required"
    if "login/password" in text:
        return "login_required"
    if "form" in text and "field" in text:
        return "form_mapping_blocked"
    if stage:
        return f"{re.sub(r'[^a-z0-9]+', '_', stage.casefold()).strip('_')}_other"
    return "other"


def log_auto_apply_event(run_id: str, event: str, **fields: Any) -> dict[str, Any]:
    """Write one redacted JSONL event, emitting the same record to stderr."""
    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "run_id": run_id,
        "event": event,
        **fields,
    }
    safe = sanitize(payload)
    line = json.dumps(safe, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    log_path_value = os.getenv("AUTO_APPLY_AUDIT_LOG_PATH", "logs/application_automation.jsonl").strip()
    log_path = Path(log_path_value).expanduser()
    if not log_path.is_absolute():
        log_path = ROOT / log_path
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
        fd = os.open(log_path, flags, 0o600)
        try:
            os.write(fd, (line + "\n").encode("utf-8", errors="replace"))
            os.fchmod(fd, 0o600)
        finally:
            os.close(fd)
    except OSError:
        # Audit I/O failure must not turn into a potentially duplicated application.
        pass
    print("AUTO_APPLY_AUDIT " + line, file=sys.stderr, flush=True)
    return safe
