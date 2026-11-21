"""Encrypted SQLite checkpoints for GitHub Actions."""
from __future__ import annotations

import argparse
from contextlib import closing
from pathlib import Path
import os
import sqlite3
import subprocess
from tempfile import TemporaryDirectory

from app.application_queue import _event, _has_attempt_history, record_automation_outcome
from app.config import settings
from app.storage import _connect, init_db


def _read_only(path: Path):
    return sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)


def validate_database(path: Path, *, run_id: str = "", kind: str = "") -> None:
    with closing(_read_only(path)) as db:
        if db.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise ValueError("SQLite integrity check failed")
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {"jobs", "application_queue", "application_events"} <= tables:
            raise ValueError("Application history schema missing")
        if run_id and db.execute("SELECT run_id,kind FROM workflow_checkpoint").fetchall() != [(run_id, kind)]:
            raise ValueError("State belongs to a different workflow run or step")


def _gpg(*arguments: str) -> None:
    passphrase = os.getenv("JOBHUNTER_STATE_KEY", "")
    if not passphrase or "\n" in passphrase or "\r" in passphrase:
        raise ValueError("JOBHUNTER_STATE_KEY must be set to a single line")
    subprocess.run(
        ["gpg", "--batch", "--quiet", "--no-symkey-cache", "--pinentry-mode", "loopback",
         "--passphrase-fd", "0", *arguments],
        input=passphrase + "\n", text=True, check=True,
    )


def snapshot(target: Path, run_id: str, kind: str) -> None:
    if target.exists():
        raise FileExistsError(target)
    source_path = Path(settings.database_path)
    with TemporaryDirectory() as work:
        backup = Path(work) / "history.sqlite3"
        with closing(_read_only(source_path)) as source, closing(sqlite3.connect(backup)) as dest:
            source.backup(dest)
            with dest:
                dest.execute("CREATE TABLE IF NOT EXISTS workflow_checkpoint(run_id TEXT,kind TEXT)")
                dest.execute("DELETE FROM workflow_checkpoint")
                dest.execute("INSERT INTO workflow_checkpoint VALUES(?,?)", (run_id, kind))
        validate_database(backup, run_id=run_id, kind=kind)
        _gpg("--output", str(target), "--cipher-algo", "AES256", "--symmetric", str(backup))


def restore(source: Path, run_id: str, kind: str) -> None:
    destination = Path(settings.database_path)
    if destination.exists():
        raise FileExistsError(destination)
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with TemporaryDirectory(dir=destination.parent) as work:
        restored = Path(work) / "history.sqlite3"
        if kind == "legacy":
            with closing(_read_only(source)) as db, closing(sqlite3.connect(restored)) as copy:
                db.backup(copy)
        else:
            _gpg("--output", str(restored), "--decrypt", str(source))
        validate_database(restored, run_id=run_id if kind != "legacy" else "", kind=kind)
        restored.chmod(0o600)
        restored.replace(destination)
    init_db()
    if kind == "reserved":
        hold_unresolved(run_id)


def reserve(queue_ids: list[int], run_id: str) -> list[int]:
    if not run_id:
        raise ValueError("Missing workflow run ID")
    reserved = []
    with closing(_connect()) as db, db:
        db.execute("BEGIN IMMEDIATE")
        for queue_id in queue_ids:
            row = db.execute("SELECT status FROM application_queue WHERE id=?", (queue_id,)).fetchone()
            if (row and row["status"] in {"pending_review", "approved", "ready"}
                    and not _has_attempt_history(db, queue_id)):
                _event(db, queue_id, "workflow_submit_reserved", {"run_id": run_id})
                reserved.append(queue_id)
    return reserved


def reserved_ids(run_id: str) -> list[int]:
    with closing(_connect()) as db:
        return [row[0] for row in db.execute("""
            SELECT queue_id FROM application_events
            WHERE event_type='workflow_submit_reserved' AND json_extract(details,'$.run_id')=?
            ORDER BY id
        """, (run_id,))]


def hold_unresolved(run_id: str) -> None:
    with closing(_connect()) as db:
        rows = db.execute("""
            SELECT q.id FROM application_queue q JOIN application_events e ON e.queue_id=q.id
            WHERE q.status IN ('pending_review','approved','ready','applying')
              AND e.event_type='workflow_submit_reserved' AND json_extract(e.details,'$.run_id')=?
        """, (run_id,)).fetchall()
    for row in rows:
        record_automation_outcome(row["id"], "failed",
                                  reason="Reserved in an interrupted run. Review employer confirmation before retry.",
                                  details={"reason_code": "submission_uncertain", "run_id": run_id})


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("snapshot", "restore"))
    parser.add_argument("path", type=Path)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--kind", choices=("reserved", "final", "legacy"), required=True)
    args = parser.parse_args()
    os.umask(0o077)
    (snapshot if args.operation == "snapshot" else restore)(args.path, args.run_id, args.kind)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
