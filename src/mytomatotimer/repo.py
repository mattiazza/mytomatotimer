"""All SQL lives here. Timestamps are UTC epoch ints (seconds)."""

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

# The only place default durations are defined (minutes unless noted).
DEFAULT_SETTINGS = {
    "focus_minutes": "50",
    "break_minutes": "5",
    "long_break_minutes": "30",
    "blocks_before_long_break": "4",
    "auto_start_next_block": "1",  # booleans are "1" / "0"
    "idle_timeout_minutes": "5",
    "break_display_mode": "countdown",  # or "elapsed"
    "beep_seconds": "5",  # 0 = visual only
    "beeps_at_focus_end": "0",
    "daily_goal_minutes": "240",
    "weekly_goal_minutes": "1200",
    "menubar_view": "session",  # session | block | next_break | daily_goal
}


@dataclass(frozen=True)
class OpenSession:
    id: int
    started_at: int


# --- settings ---------------------------------------------------------------


def get_setting(conn: sqlite3.Connection, key: str) -> str:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else DEFAULT_SETTINGS[key]


def set_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
    with conn:
        conn.execute(
            "INSERT INTO settings(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )


# --- subjects ---------------------------------------------------------------


@dataclass(frozen=True)
class Subject:
    id: int
    name: str
    color: str | None = None
    archived: bool = False


def add_subject(conn: sqlite3.Connection, name: str) -> Subject:
    """Add a subject. Raises ValueError if the name is empty or already taken.

    Names stay unique even when archived, so history never gets ambiguous.
    """
    name = name.strip()
    if not name:
        raise ValueError("Subject name is empty")
    try:
        with conn:
            cur = conn.execute("INSERT INTO subjects(name) VALUES (?)", (name,))
    except sqlite3.IntegrityError:
        raise ValueError(f"Subject '{name}' already exists") from None
    return Subject(cur.lastrowid, name)


def list_subjects(conn: sqlite3.Connection, include_archived: bool = False) -> list[Subject]:
    """Subjects, alphabetical. Archived ones only when asked (the window manages them)."""
    where = "" if include_archived else "WHERE archived = 0"
    rows = conn.execute(
        f"SELECT id, name, color, archived FROM subjects {where} ORDER BY name COLLATE NOCASE"
    ).fetchall()
    return [Subject(r["id"], r["name"], r["color"], bool(r["archived"])) for r in rows]


def rename_subject(conn: sqlite3.Connection, subject_id: int, name: str) -> None:
    """Rename a subject. Raises ValueError if the name is empty or already taken."""
    name = name.strip()
    if not name:
        raise ValueError("Subject name is empty")
    try:
        with conn:
            conn.execute("UPDATE subjects SET name = ? WHERE id = ?", (name, subject_id))
    except sqlite3.IntegrityError:
        raise ValueError(f"Subject '{name}' already exists") from None


def set_subject_archived(conn: sqlite3.Connection, subject_id: int, archived: bool) -> None:
    with conn:
        conn.execute(
            "UPDATE subjects SET archived = ? WHERE id = ?", (int(archived), subject_id)
        )


def set_subject_color(conn: sqlite3.Connection, subject_id: int, color: str | None) -> None:
    with conn:
        conn.execute("UPDATE subjects SET color = ? WHERE id = ?", (color, subject_id))


# --- sessions ---------------------------------------------------------------


def start_session(
    conn: sqlite3.Connection,
    now: int,
    planned_seconds: int | None = None,
    subject_id: int | None = None,
) -> OpenSession:
    """Create a timer session with one open focus segment (subject_id None = no subject)."""
    planned = planned_seconds or int(get_setting(conn, "focus_minutes")) * 60
    with conn:
        cur = conn.execute(
            "INSERT INTO sessions(subject_id, started_at, source) VALUES (?, ?, 'timer')",
            (subject_id, now),
        )
        session_id = cur.lastrowid
        conn.execute(
            "INSERT INTO segments(session_id, kind, planned_seconds, started_at, last_tick_at) "
            "VALUES (?, 'focus', ?, ?, ?)",
            (session_id, planned, now, now),
        )
    return OpenSession(session_id, now)


def get_open_session(conn: sqlite3.Connection) -> OpenSession | None:
    row = conn.execute(
        "SELECT id, started_at FROM sessions WHERE ended_at IS NULL "
        "ORDER BY started_at DESC LIMIT 1"
    ).fetchone()
    return OpenSession(row["id"], row["started_at"]) if row else None


def touch(conn: sqlite3.Connection, session_id: int, now: int) -> None:
    """Record 'the app was alive at now' on the open segment (used for crash recovery)."""
    with conn:
        conn.execute(
            "UPDATE segments SET last_tick_at = ? WHERE session_id = ? AND ended_at IS NULL",
            (now, session_id),
        )


def end_segment(conn: sqlite3.Connection, session_id: int, at: int) -> None:
    with conn:
        conn.execute(
            "UPDATE segments SET ended_at = ? WHERE session_id = ? AND ended_at IS NULL",
            (at, session_id),
        )


def start_segment(
    conn: sqlite3.Connection, session_id: int, kind: str, planned_seconds: int, at: int
) -> None:
    with conn:
        conn.execute(
            "INSERT INTO segments(session_id, kind, planned_seconds, started_at, last_tick_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (session_id, kind, planned_seconds, at, at),
        )


def stop_session(
    conn: sqlite3.Connection, session_id: int, now: int, reason: str = "user"
) -> None:
    """Close the open segment(s) and the session at `now`."""
    with conn:
        conn.execute(
            "UPDATE segments SET ended_at = ? WHERE session_id = ? AND ended_at IS NULL",
            (now, session_id),
        )
        conn.execute(
            "UPDATE sessions SET ended_at = ?, end_reason = ? WHERE id = ?",
            (now, reason, session_id),
        )


def recover_crashed_sessions(conn: sqlite3.Connection) -> int:
    """Close sessions left open by a crash, ending them at the last recorded tick.

    Returns how many sessions were closed.
    """
    rows = conn.execute(
        "SELECT s.id, s.started_at, MAX(g.last_tick_at) AS last_tick "
        "FROM sessions s LEFT JOIN segments g ON g.session_id = s.id "
        "WHERE s.ended_at IS NULL GROUP BY s.id"
    ).fetchall()
    with conn:
        for row in rows:
            end = max(row["last_tick"] or row["started_at"], row["started_at"])
            conn.execute(
                "UPDATE segments SET ended_at = ? WHERE session_id = ? AND ended_at IS NULL",
                (end, row["id"]),
            )
            conn.execute(
                "UPDATE sessions SET ended_at = ?, end_reason = 'crash' WHERE id = ?",
                (end, row["id"]),
            )
    return len(rows)


# --- manual editing ---------------------------------------------------------
# Manual sessions are one session + one focus segment covering the whole span.
# Timer sessions have several segments (focus and breaks), so only their subject and
# note can be edited: changing times would mean guessing how to reshape the segments.


@dataclass(frozen=True)
class SessionRow:
    id: int
    subject_id: int | None
    subject: str | None
    started_at: int
    ended_at: int | None
    source: str
    end_reason: str | None
    note: str | None
    focus_seconds: int
    break_seconds: int


def _check_span(started_at: int, ended_at: int, now: int) -> None:
    if ended_at <= started_at:
        raise ValueError("End must be after start")
    if ended_at > now:
        raise ValueError("A session can't end in the future")


def add_manual_session(
    conn: sqlite3.Connection,
    started_at: int,
    ended_at: int,
    now: int,
    subject_id: int | None = None,
    note: str | None = None,
) -> int:
    """Insert a finished manual session. Raises ValueError for a bad time span."""
    _check_span(started_at, ended_at, now)
    with conn:
        cur = conn.execute(
            "INSERT INTO sessions(subject_id, started_at, ended_at, source, end_reason, note) "
            "VALUES (?, ?, ?, 'manual', 'manual', ?)",
            (subject_id, started_at, ended_at, note or None),
        )
        conn.execute(
            "INSERT INTO segments(session_id, kind, planned_seconds, started_at, ended_at) "
            "VALUES (?, 'focus', ?, ?, ?)",
            (cur.lastrowid, ended_at - started_at, started_at, ended_at),
        )
    return cur.lastrowid


def update_session(
    conn: sqlite3.Connection,
    session_id: int,
    now: int,
    subject_id: int | None,
    note: str | None,
    started_at: int | None = None,
    ended_at: int | None = None,
) -> None:
    """Edit a finished session. Times apply to manual sessions only (see above).

    Raises ValueError for a missing/running session, a bad span, or times on a timer session.
    """
    row = conn.execute(
        "SELECT source, ended_at FROM sessions WHERE id = ?", (session_id,)
    ).fetchone()
    if row is None:
        raise ValueError("Session not found")
    if row["ended_at"] is None:
        raise ValueError("Stop the running session before editing it")
    with conn:
        if started_at is not None and ended_at is not None:
            if row["source"] != "manual":
                raise ValueError("Times of timer sessions can't be edited")
            _check_span(started_at, ended_at, now)
            conn.execute(
                "UPDATE sessions SET started_at = ?, ended_at = ? WHERE id = ?",
                (started_at, ended_at, session_id),
            )
            conn.execute(
                "UPDATE segments SET started_at = ?, ended_at = ?, planned_seconds = ? "
                "WHERE session_id = ?",
                (started_at, ended_at, ended_at - started_at, session_id),
            )
        conn.execute(
            "UPDATE sessions SET subject_id = ?, note = ? WHERE id = ?",
            (subject_id, note or None, session_id),
        )


def delete_session(conn: sqlite3.Connection, session_id: int) -> None:
    """Delete a finished session and its segments (ON DELETE CASCADE).

    Raises ValueError for a running session: the menu bar still owns it.
    """
    row = conn.execute("SELECT ended_at FROM sessions WHERE id = ?", (session_id,)).fetchone()
    if row is None:
        raise ValueError("Session not found")
    if row["ended_at"] is None:
        raise ValueError("Stop the running session before deleting it")
    with conn:
        conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))


def list_sessions(
    conn: sqlite3.Connection, now: int, limit: int | None = None
) -> list[SessionRow]:
    """Sessions, newest first, with focus/break totals (open segments count up to now)."""
    rows = conn.execute(
        "SELECT s.id, s.subject_id, sub.name AS subject, s.started_at, s.ended_at, s.source, "
        "s.end_reason, s.note, "
        "COALESCE(SUM(CASE WHEN g.kind = 'focus' "
        "  THEN COALESCE(g.ended_at, :now) - g.started_at END), 0) AS focus, "
        "COALESCE(SUM(CASE WHEN g.kind != 'focus' "
        "  THEN COALESCE(g.ended_at, :now) - g.started_at END), 0) AS brk "
        "FROM sessions s LEFT JOIN subjects sub ON sub.id = s.subject_id "
        "LEFT JOIN segments g ON g.session_id = s.id "
        "GROUP BY s.id ORDER BY s.started_at DESC, s.id DESC LIMIT :limit",
        {"now": now, "limit": -1 if limit is None else limit},
    ).fetchall()
    return [
        SessionRow(r["id"], r["subject_id"], r["subject"], r["started_at"], r["ended_at"],
                   r["source"], r["end_reason"], r["note"], r["focus"], r["brk"])
        for r in rows
    ]


# --- stats ------------------------------------------------------------------
# Only focus segments count. Open segments count up to `now`. Days are local days.


def day_start(day: date) -> int:
    """Epoch seconds of local midnight (DST-safe: built from the date, not +86400)."""
    return int(datetime.combine(day, time.min).timestamp())


def week_start(day: date) -> date:
    """The Monday of the week containing `day`."""
    return day - timedelta(days=day.weekday())


def focus_seconds_between(conn: sqlite3.Connection, start: int, end: int, now: int) -> int:
    """Focus seconds inside [start, end), clipping segments that cross the edges."""
    row = conn.execute(
        "SELECT COALESCE(SUM(MIN(COALESCE(ended_at, :now), :end) - MAX(started_at, :start)), 0) "
        "FROM segments WHERE kind = 'focus' "
        "AND started_at < :end AND COALESCE(ended_at, :now) > :start",
        {"now": now, "start": start, "end": end},
    ).fetchone()
    return max(0, row[0])


def focus_seconds_today(conn: sqlite3.Connection, now: int) -> int:
    today = datetime.fromtimestamp(now).date()
    return focus_seconds_between(conn, day_start(today), now, now)


def focus_by_day(conn: sqlite3.Connection, first: date, last: date, now: int) -> dict[date, int]:
    """Focus seconds for each local day from `first` to `last` inclusive."""
    result = {}
    day = first
    while day <= last:
        nxt = day + timedelta(days=1)
        result[day] = focus_seconds_between(conn, day_start(day), day_start(nxt), now)
        day = nxt
    return result


def focus_this_week(conn: sqlite3.Connection, now: int) -> int:
    """Focus seconds since Monday 00:00 (local)."""
    monday = week_start(datetime.fromtimestamp(now).date())
    return focus_seconds_between(conn, day_start(monday), now, now)


def focus_by_subject(
    conn: sqlite3.Connection, start: int, end: int, now: int
) -> list[tuple[str, str | None, int]]:
    """(subject name, color, focus seconds) in [start, end), biggest first.

    Sessions without a subject are grouped as "No subject".
    """
    rows = conn.execute(
        "SELECT COALESCE(sub.name, 'No subject') AS name, sub.color AS color, "
        "SUM(MIN(COALESCE(g.ended_at, :now), :end) - MAX(g.started_at, :start)) AS secs "
        "FROM segments g JOIN sessions s ON s.id = g.session_id "
        "LEFT JOIN subjects sub ON sub.id = s.subject_id "
        "WHERE g.kind = 'focus' AND g.started_at < :end AND COALESCE(g.ended_at, :now) > :start "
        "GROUP BY s.subject_id ORDER BY secs DESC",
        {"now": now, "start": start, "end": end},
    ).fetchall()
    return [(r["name"], r["color"], r["secs"]) for r in rows if r["secs"] > 0]


def streak_days(conn: sqlite3.Connection, now: int) -> int:
    """Consecutive local days with any focus time, ending today.

    Today not having focus yet doesn't break the streak: counting then starts yesterday.
    """
    day = datetime.fromtimestamp(now).date()
    nxt = day + timedelta(days=1)
    if focus_seconds_between(conn, day_start(day), day_start(nxt), now) == 0:
        day -= timedelta(days=1)
    count = 0
    while True:
        nxt = day + timedelta(days=1)
        if focus_seconds_between(conn, day_start(day), day_start(nxt), now) == 0:
            return count
        count += 1
        day -= timedelta(days=1)
