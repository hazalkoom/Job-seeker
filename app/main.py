from __future__ import annotations

from fastapi import FastAPI, HTTPException, Query

from app.config import settings
from app.runner import run_once
from app.storage import init_db, list_jobs

app = FastAPI(title="Personal Job Hunter", version="2.3.0")


@app.on_event("startup")
def startup() -> None:
    init_db()


@app.get("/health")
def health() -> dict:
    return {"ok": True, "telegram_configured": bool(settings.telegram_bot_token and settings.telegram_chat_id)}


@app.get("/jobs")
def jobs(status: str | None = Query(default=None, pattern="^(match|review|reject)$"), limit: int = 100) -> dict:
    return {"jobs": list_jobs(status=status, limit=limit)}


@app.post("/run-once")
def run_jobs() -> dict:
    # Local personal tool only. Do not expose this endpoint to the public internet.
    return run_once()
