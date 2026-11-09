"""CSV export of all sessions. Local file only, nothing leaves the machine."""

import csv
from datetime import datetime
from pathlib import Path

from mytomatotimer import repo

HEADER = [
    "session_id", "subject", "source", "start", "end",
    "focus_minutes", "break_minutes", "end_reason", "note",
]


def _local(ts: int | None) -> str:
    """Local time, ISO-like, so spreadsheets parse it."""
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S") if ts else ""


def export_sessions_csv(conn, path: Path | str, now: int) -> int:
    """Write one row per session, oldest first. Returns the number of rows written."""
    sessions = list(reversed(repo.list_sessions(conn, now)))
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(HEADER)
        for s in sessions:
            writer.writerow([
                s.id, s.subject or "", s.source, _local(s.started_at), _local(s.ended_at),
                round(s.focus_seconds / 60, 1), round(s.break_seconds / 60, 1),
                s.end_reason or "", s.note or "",
            ])
    return len(sessions)
