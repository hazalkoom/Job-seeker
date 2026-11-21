"""Funnel telemetry and unanswered-question ledger for Job Hunter."""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Any

from app.storage import _connect, init_db

ROOT = Path(__file__).resolve().parent.parent
PENDING_QUESTIONS_PATH = ROOT / "data" / "pending_questions.json"
PENDING_QUESTIONS_JSON = PENDING_QUESTIONS_PATH

FUNNEL_STAGES = (
    "fetched",
    "title_ok",
    "qualified",
    "apply_path_known",
    "resolved_to_ats",
    "form_found",
    "fields_filled",
    "submit_attempted",
    "submitted",
    "email_confirmed",
)


class FunnelTracker:
    """Tracks per-stage and per-source conversion counts and drop-off reasons."""

    def __init__(self, *, fetched_total: int = 0, deduped_total: int = 0) -> None:
        self.stage_counts: Counter[str] = Counter()
        if fetched_total or deduped_total:
            self.stage_counts["fetched"] = int(deduped_total or fetched_total)
        self.by_source: dict[str, Counter[str]] = defaultdict(Counter)
        self.stage_dropoffs: dict[str, Counter[str]] = defaultdict(Counter)
        self.path_counts: Counter[str] = Counter()
        self.matched_total: int = 0
        self.rejected_total: int = 0
        self.submitted_total: int = 0

    def record_stage(self, stage: str, *, source: str = "", count: int = 1) -> None:
        self.stage_counts[stage] += count
        if source:
            self.by_source[source][stage] += count

    def record_dropoff(self, stage: str, reason: str, *, source: str = "", count: int = 1) -> None:
        clean_reason = (reason or "unknown").strip()[:160]
        self.stage_dropoffs[stage][clean_reason] += count
        if source:
            self.by_source[source][f"drop_{stage}"] += count

    def record_classification(self, source: str, status: str, concerns: list[str] | None = None) -> None:
        if status == "reject":
            self.rejected_total += 1
            for c in (concerns or [])[:2]:
                self.record_dropoff("qualified", c, source=source)
        else:
            self.matched_total += 1
            self.record_stage("qualified", source=source)

    def record_apply_path(self, source: str, apply_path: str, *, resolved: bool = False) -> None:
        self.path_counts[apply_path] += 1
        if apply_path == "direct_ats":
            self.record_stage("apply_path_known", source=source)
        if resolved:
            self.record_stage("resolved_to_ats", source=source)

    def ingest_auto_apply_report(self, report: dict[str, Any] | None) -> None:
        if not isinstance(report, dict):
            return
        self.submitted_total = int(report.get("submitted", 0) or 0)
        self.stage_counts["submitted"] += self.submitted_total
        for res in report.get("results", []) or []:
            if not isinstance(res, dict):
                continue
            src = str(res.get("source") or "")
            filled = int(res.get("filled_count") or 0) > 0
            if filled or (res.get("form_diagnostics") or {}).get("forms_found"):
                self.record_stage("form_found", source=src)
                if filled:
                    self.record_stage("fields_filled", source=src)
            elif res.get("outcome") != "submitted":
                self.record_dropoff("form_found", str(res.get("reason") or "skipped"), source=src)
            if res.get("attempted"):
                self.record_stage("submit_attempted", source=src)

    def to_dict(self) -> dict[str, Any]:
        return {
            "stages": {stage: int(self.stage_counts.get(stage, 0)) for stage in FUNNEL_STAGES},
            "matched_total": self.matched_total,
            "rejected_total": self.rejected_total,
            "submitted_total": self.submitted_total,
            "path_counts": dict(self.path_counts),
            "top_dropoffs": {
                stage: reasons.most_common(8)
                for stage, reasons in self.stage_dropoffs.items()
                if reasons
            },
            "by_source": {
                src: dict(counts)
                for src, counts in sorted(self.by_source.items())
            },
        }

    def format_telegram_summary_lines(self) -> list[str]:
        s = self.stage_counts
        line = (
            f"📊 <b>Funnel:</b> {s['fetched']} fetched → "
            f"{s['qualified']} qualified ({s['apply_path_known']} direct_ats, "
            f"{s['resolved_to_ats']} ATS-resolved) → {s['form_found']} form_found → "
            f"{s['fields_filled']} filled → <b>{s['submitted']} submitted</b>"
        )
        lines = [line]
        if self.path_counts:
            parts = [f"{k}={v}" for k, v in self.path_counts.most_common()]
            lines.append("🛤 <b>Path breakdown:</b> " + ", ".join(parts))
        top_blockers: list[str] = []
        for stage in ("apply_path_known", "form_found", "fields_filled", "qualified"):
            for reason, count in self.stage_dropoffs.get(stage, Counter()).most_common(3):
                top_blockers.append(f"{count}× {escape(reason[:70])}")
        if top_blockers:
            lines.append("⚠️ <b>Top blockers:</b> " + "; ".join(top_blockers[:5]))
        return lines


def _normalize_question_key(question_text: str, field_type: str = "", html_snippet: str = "") -> str:
    clean_q = re.sub(r"[^a-z0-9]+", " ", (question_text or "").lower()).strip()
    if clean_q and clean_q not in {"required question needs an exact saved answer", "unlabeled", "unknown"}:
        return f"{field_type.lower() or 'text'}:{clean_q[:120]}"
    snippet_key = re.sub(r"[^a-z0-9]+", " ", (html_snippet or "").lower()).strip()[:100]
    return f"unlabeled:{field_type.lower() or 'field'}:{snippet_key or 'empty'}"


def record_unanswered_question(
    question_text: str,
    *,
    field_type: str = "text",
    field_name: str = "",
    options: list[str] | None = None,
    html_snippet: str = "",
    company: str = "",
    ats_host: str = "",
    example_url: str = "",
    job_url: str = "",
    queue_id: int | None = None,
    json_path: Path | None = None,
) -> dict[str, Any]:
    """Record an unanswered required question in SQLite `question_ledger` and `data/pending_questions.json`."""
    init_db()
    target_json = json_path or PENDING_QUESTIONS_JSON
    url_val = example_url or job_url
    now = datetime.now(timezone.utc).isoformat()
    q_clean = (question_text or "").strip() or (field_name or "").strip() or "[Unlabeled required field]"
    key = _normalize_question_key(q_clean, field_type, html_snippet)
    opts = [str(o).strip() for o in (options or []) if str(o).strip()][:25]
    opts_json = json.dumps(opts, ensure_ascii=False)
    snippet_clean = re.sub(r"\s+", " ", (html_snippet or "").strip())[:500]

    with _connect() as conn:
        existing = conn.execute(
            "SELECT id, seen_count FROM question_ledger WHERE normalized_key=?",
            (key,),
        ).fetchone()
        if existing:
            seen_count = int(existing["seen_count"]) + 1
            conn.execute(
                """UPDATE question_ledger
                   SET seen_count=?, last_seen_at=?,
                       options_json=CASE WHEN ? != '[]' THEN ? ELSE options_json END,
                       html_snippet=CASE WHEN ? != '' THEN ? ELSE html_snippet END,
                       company=CASE WHEN ? != '' THEN ? ELSE company END,
                       ats_host=CASE WHEN ? != '' THEN ? ELSE ats_host END,
                       example_url=CASE WHEN ? != '' THEN ? ELSE example_url END
                   WHERE id=?""",
                (
                    seen_count,
                    now,
                    opts_json, opts_json,
                    snippet_clean, snippet_clean,
                    company, company,
                    ats_host, ats_host,
                    url_val, url_val,
                    existing["id"],
                ),
            )
        else:
            seen_count = 1
            conn.execute(
                """INSERT INTO question_ledger (
                    normalized_key, question_text, field_type, options_json,
                    html_snippet, company, ats_host, example_url,
                    seen_count, first_seen_at, last_seen_at, resolved
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, 0)""",
                (
                    key,
                    q_clean[:300],
                    (field_type or "text")[:40],
                    opts_json,
                    snippet_clean,
                    (company or "")[:120],
                    (ats_host or "")[:120],
                    (url_val or "")[:400],
                    now,
                    now,
                ),
            )

    _sync_pending_questions_json(json_path=target_json)
    return {
        "normalized_key": key,
        "question_text": q_clean,
        "field_type": field_type,
        "options": opts,
        "html_snippet": snippet_clean,
        "company": company,
        "ats_host": ats_host,
        "seen_count": seen_count,
        "occurrences": seen_count,
    }


def list_pending_questions(*, limit: int = 50, include_resolved: bool = False) -> list[dict[str, Any]]:
    init_db()
    query = "SELECT * FROM question_ledger"
    if not include_resolved:
        query += " WHERE resolved = 0"
    query += " ORDER BY seen_count DESC, last_seen_at DESC LIMIT ?"
    with _connect() as conn:
        rows = conn.execute(query, (int(limit),)).fetchall()
    result: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item["occurrences"] = int(item.get("seen_count") or 1)
        try:
            item["options"] = json.loads(item.get("options_json") or "[]")
        except Exception:
            item["options"] = []
        result.append(item)
    return result


def _sync_pending_questions_json(*, json_path: Path = PENDING_QUESTIONS_PATH) -> None:
    try:
        items = list_pending_questions(limit=100, include_resolved=False)
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(
            json.dumps({"updated_at": datetime.now(timezone.utc).isoformat(), "questions": items}, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    except Exception:
        pass


def format_pending_questions_telegram_digest(questions: list[dict[str, Any]] | None = None, *, limit: int = 8) -> str:
    """Build a Telegram digest of unanswered required questions so the user can answer them once."""
    items = questions if questions is not None else list_pending_questions(limit=limit)
    if not items:
        return ""
    shown = items[:limit]
    lines = [
        "❓ <b>Job Hunter — Questions Needed to Unlock Skipped Forms</b>",
        "These required fields blocked auto-submission. Reply with your answers so they auto-fill next time:",
    ]
    for idx, q in enumerate(shown, 1):
        q_text = escape(str(q.get("question_text") or "[Unlabeled field]")[:160])
        f_type = escape(str(q.get("field_type") or "text"))
        co = escape(str(q.get("company") or q.get("ats_host") or "Unknown")[:60])
        seen = int(q.get("seen_count") or 1)
        lines.append("")
        lines.append(f"<b>{idx}. {q_text}</b> (<i>{f_type}</i>, {co}, seen {seen}×)")
        opts = q.get("options") or []
        if opts:
            opts_str = ", ".join(escape(str(o)[:40]) for o in opts[:8])
            lines.append(f"   Options: <code>{opts_str}</code>")
        snippet = str(q.get("html_snippet") or "").strip()
        if snippet and ("[Unlabeled" in q_text or len(q_text) < 4):
            lines.append(f"   HTML: <code>{escape(snippet[:160])}</code>")
    return "\n".join(lines)[:3900]
