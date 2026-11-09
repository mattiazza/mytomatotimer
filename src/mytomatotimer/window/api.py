"""Python side of the window: methods JS calls through pywebview's `js_api`.

pywebview runs these on worker threads, and a sqlite3 connection must stay on the
thread that made it, so every call opens its own short-lived connection.
Everything returned is plain JSON-able data. Expected problems (bad input) come back
as {"ok": False, "error": ...} so the JS side can show them.
"""

import time
from contextlib import closing
from datetime import date, datetime, timedelta

from mytomatotimer import db, export, repo

HEATMAP_WEEKS = 10

# key -> (minimum value, kind). These are the settings the window edits; the rest
# (menubar_view) is owned by the menu bar.
INT_SETTINGS = {
    "focus_minutes": 1,
    "break_minutes": 1,
    "long_break_minutes": 1,
    "blocks_before_long_break": 1,
    "idle_timeout_minutes": 1,
    "beep_seconds": 0,
    "daily_goal_minutes": 0,
    "weekly_goal_minutes": 0,
}
BOOL_SETTINGS = ["auto_start_next_block", "beeps_at_focus_end"]
CHOICE_SETTINGS = {"break_display_mode": ("countdown", "elapsed")}


def _connect():
    return closing(db.connect())


def _parse_local(text: str) -> int:
    """'2026-11-09T14:30' (from <input type=datetime-local>, local time) -> epoch seconds."""
    try:
        return int(datetime.fromisoformat(text).timestamp())
    except (TypeError, ValueError):
        raise ValueError("Enter a valid date and time") from None


def _fail(message: str) -> dict:
    return {"ok": False, "error": message}


class Api:
    # --- stats ---------------------------------------------------------------

    def get_stats(self, subject_range: str = "week") -> dict:
        now = int(time.time())
        today = datetime.fromtimestamp(now).date()
        monday = repo.week_start(today)
        heat_first = monday - timedelta(weeks=HEATMAP_WEEKS - 1)
        with _connect() as conn:
            by_day = repo.focus_by_day(conn, heat_first, today, now)
            if subject_range == "week":
                sub_start = repo.day_start(monday)
            else:
                sub_start = repo.day_start(heat_first)
            subjects = repo.focus_by_subject(conn, sub_start, now + 1, now)
            return {
                "today_seconds": by_day[today],
                "week_seconds": repo.focus_this_week(conn, now),
                "streak_days": repo.streak_days(conn, now),
                "daily_goal_seconds": int(repo.get_setting(conn, "daily_goal_minutes")) * 60,
                "weekly_goal_seconds": int(repo.get_setting(conn, "weekly_goal_minutes")) * 60,
                # Mon..Sun of this week; days still to come are 0.
                "week_days": [
                    {"date": (monday + timedelta(days=i)).isoformat(),
                     "seconds": by_day.get(monday + timedelta(days=i), 0)}
                    for i in range(7)
                ],
                # Heatmap in reading order (week by week, Monday first); future days null.
                "heatmap": [
                    {"date": d.isoformat(), "seconds": by_day.get(d)}
                    for d in (heat_first + timedelta(days=i) for i in range(HEATMAP_WEEKS * 7))
                ],
                "subjects": [
                    {"name": n, "color": c, "seconds": s} for n, c, s in subjects
                ],
            }

    # --- subjects ------------------------------------------------------------

    def get_subjects(self) -> list[dict]:
        with _connect() as conn:
            return [
                {"id": s.id, "name": s.name, "color": s.color, "archived": s.archived}
                for s in repo.list_subjects(conn, include_archived=True)
            ]

    def add_subject(self, name: str) -> dict:
        with _connect() as conn:
            try:
                repo.add_subject(conn, name)
            except ValueError as err:
                return _fail(str(err))
        return {"ok": True}

    def rename_subject(self, subject_id: int, name: str) -> dict:
        with _connect() as conn:
            try:
                repo.rename_subject(conn, subject_id, name)
            except ValueError as err:
                return _fail(str(err))
        return {"ok": True}

    def set_subject_archived(self, subject_id: int, archived: bool) -> dict:
        with _connect() as conn:
            repo.set_subject_archived(conn, subject_id, bool(archived))
        return {"ok": True}

    def set_subject_color(self, subject_id: int, color: str | None) -> dict:
        with _connect() as conn:
            repo.set_subject_color(conn, subject_id, color or None)
        return {"ok": True}

    # --- sessions (manual edit) -----------------------------------------------

    def get_sessions(self, limit: int = 200) -> list[dict]:
        with _connect() as conn:
            return [
                {
                    "id": r.id, "subject_id": r.subject_id, "subject": r.subject,
                    "started_at": datetime.fromtimestamp(r.started_at).strftime("%Y-%m-%dT%H:%M"),
                    "ended_at": (datetime.fromtimestamp(r.ended_at).strftime("%Y-%m-%dT%H:%M")
                                 if r.ended_at else None),
                    "source": r.source, "note": r.note or "",
                    "focus_seconds": r.focus_seconds,
                    "running": r.ended_at is None,
                }
                for r in repo.list_sessions(conn, int(time.time()), limit)
            ]

    def add_session(self, subject_id, start: str, end: str, note: str = "") -> dict:
        try:
            with _connect() as conn:
                repo.add_manual_session(
                    conn, _parse_local(start), _parse_local(end), int(time.time()),
                    subject_id or None, note.strip(),
                )
        except ValueError as err:
            return _fail(str(err))
        return {"ok": True}

    def update_session(self, session_id: int, subject_id, note: str,
                       start: str | None = None, end: str | None = None) -> dict:
        """start/end are sent for manual sessions only; omit them to edit subject/note."""
        try:
            with _connect() as conn:
                repo.update_session(
                    conn, session_id, int(time.time()), subject_id or None, note.strip(),
                    _parse_local(start) if start else None,
                    _parse_local(end) if end else None,
                )
        except ValueError as err:
            return _fail(str(err))
        return {"ok": True}

    def delete_session(self, session_id: int) -> dict:
        try:
            with _connect() as conn:
                repo.delete_session(conn, session_id)
        except ValueError as err:
            return _fail(str(err))
        return {"ok": True}

    def export_csv(self) -> dict:
        """Ask where to save (native dialog), then write all sessions there."""
        import webview  # only the real window has one; keeps the API importable in tests

        chosen = webview.windows[0].create_file_dialog(
            webview.FileDialog.SAVE,
            save_filename=f"mytomatotimer-{date.today().isoformat()}.csv",
            file_types=("CSV files (*.csv)",),
        )
        if not chosen:
            return {"ok": True, "cancelled": True}
        path = chosen if isinstance(chosen, str) else chosen[0]
        with _connect() as conn:
            count = export.export_sessions_csv(conn, path, int(time.time()))
        return {"ok": True, "count": count, "path": str(path)}

    # --- settings ------------------------------------------------------------

    def get_settings(self) -> dict:
        keys = [*INT_SETTINGS, *BOOL_SETTINGS, *CHOICE_SETTINGS]
        with _connect() as conn:
            return {k: repo.get_setting(conn, k) for k in keys}

    def save_settings(self, values: dict) -> dict:
        """Validate everything first, then write, so a bad field saves nothing."""
        clean = {}
        for key, value in values.items():
            if key in INT_SETTINGS:
                try:
                    number = int(value)
                except (TypeError, ValueError):
                    return _fail(f"{key}: not a whole number")
                if number < INT_SETTINGS[key]:
                    return _fail(f"{key}: must be at least {INT_SETTINGS[key]}")
                clean[key] = str(number)
            elif key in BOOL_SETTINGS:
                clean[key] = "1" if value in (True, "1", 1) else "0"
            elif key in CHOICE_SETTINGS:
                if value not in CHOICE_SETTINGS[key]:
                    return _fail(f"{key}: unknown choice '{value}'")
                clean[key] = value
            else:
                return _fail(f"Unknown setting '{key}'")
        with _connect() as conn:
            for key, value in clean.items():
                repo.set_setting(conn, key, value)
        return {"ok": True}
