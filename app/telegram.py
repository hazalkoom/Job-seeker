from __future__ import annotations

import httpx

from app.config import settings
from app.models import Job


def format_message(job: Job, status: str, score: int, reasons: list[str], concerns: list[str]) -> str:
    tag = "MATCH" if status == "match" else "REVIEW — verify before applying"
    mode = job.workplace_type.replace("_", " ").title()
    posted = job.posted_at or "Date unavailable"
    lines = [
        f"{'✅' if status == 'match' else '🔎'} {tag}",
        f"<b>{_escape(job.title)}</b>",
        f"🏢 {_escape(job.company)}",
        f"📍 {_escape(job.location)}",
        f"💼 {_escape(mode)} | {_escape(job.employment_type or 'Type not listed')}",
        f"🗓 {_escape(posted)} ({_escape(job.date_kind)}) | Score: {score}/100",
        f"🔗 <a href=\"{_escape(job.url)}\">Open original listing / apply</a>",
    ]
    if reasons:
        lines.append("\n<b>Why it matched</b>")
        lines.extend(f"• {_escape(reason)}" for reason in reasons[:5])
    if concerns:
        lines.append("\n<b>Check before applying</b>")
        lines.extend(f"• {_escape(concern)}" for concern in concerns[:5])
    description = (job.description or "").strip()
    if description:
        excerpt = description[:500] + ("…" if len(description) > 500 else "")
        lines.extend(["\n<b>Description excerpt</b>", _escape(excerpt)])
    lines.append("\nSource: " + _escape(job.source))
    return "\n".join(lines)[:3900]


def _escape(value: str) -> str:
    return str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def send_message(message: str) -> bool:
    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        return False
    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
    try:
        with httpx.Client(timeout=15) as client:
            response = client.post(
                url,
                json={
                    "chat_id": settings.telegram_chat_id,
                    "text": message,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                },
            )
            response.raise_for_status()
            return bool(response.json().get("ok"))
    except (httpx.HTTPError, ValueError):
        return False
