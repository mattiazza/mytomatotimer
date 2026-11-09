import pytest

from mytomatotimer import db, repo


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "test.db")
    yield c
    c.close()


def test_connect_enables_wal_and_migrates(conn):
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert conn.execute("PRAGMA user_version").fetchone()[0] == len(db.MIGRATIONS)


def test_migrate_is_idempotent(conn):
    db.migrate(conn)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == len(db.MIGRATIONS)


def test_settings_default_and_override(conn):
    assert repo.get_setting(conn, "focus_minutes") == "50"
    repo.set_setting(conn, "focus_minutes", "25")
    repo.set_setting(conn, "focus_minutes", "30")
    assert repo.get_setting(conn, "focus_minutes") == "30"


def test_start_creates_session_and_focus_segment(conn):
    s = repo.start_session(conn, 1000)
    assert repo.get_open_session(conn) == s
    seg = conn.execute("SELECT * FROM segments WHERE session_id = ?", (s.id,)).fetchone()
    assert (seg["kind"], seg["planned_seconds"], seg["started_at"], seg["ended_at"]) == (
        "focus", 50 * 60, 1000, None,
    )


def test_stop_closes_session_and_segment(conn):
    s = repo.start_session(conn, 1000)
    repo.stop_session(conn, s.id, 1600)
    assert repo.get_open_session(conn) is None
    row = conn.execute("SELECT * FROM sessions WHERE id = ?", (s.id,)).fetchone()
    assert (row["ended_at"], row["end_reason"]) == (1600, "user")
    seg = conn.execute("SELECT ended_at FROM segments WHERE session_id = ?", (s.id,)).fetchone()
    assert seg["ended_at"] == 1600


def test_recover_closes_at_last_tick(conn):
    s = repo.start_session(conn, 1000)
    repo.touch(conn, s.id, 1234)
    assert repo.recover_crashed_sessions(conn) == 1
    row = conn.execute("SELECT * FROM sessions WHERE id = ?", (s.id,)).fetchone()
    assert (row["ended_at"], row["end_reason"]) == (1234, "crash")
    assert repo.get_open_session(conn) is None


def test_recover_with_nothing_open(conn):
    assert repo.recover_crashed_sessions(conn) == 0


def test_segments_follow_one_another_in_a_session(conn):
    s = repo.start_session(conn, 1000, planned_seconds=60)
    repo.end_segment(conn, s.id, 1060)
    repo.start_segment(conn, s.id, "break", 600, 1060)
    repo.stop_session(conn, s.id, 1100)
    rows = conn.execute(
        "SELECT kind, planned_seconds, started_at, ended_at FROM segments "
        "WHERE session_id = ? ORDER BY id", (s.id,)
    ).fetchall()
    assert [tuple(r) for r in rows] == [
        ("focus", 60, 1000, 1060), ("break", 600, 1060, 1100),
    ]


def test_focus_seconds_today_counts_focus_only_and_open_segment(conn):
    from datetime import datetime
    midnight = int(datetime(2026, 11, 9).timestamp())
    now = midnight + 10_000
    s = repo.start_session(conn, midnight + 1000)  # open focus segment from +1000
    repo.end_segment(conn, s.id, midnight + 2000)  # focus: 1000 s
    repo.start_segment(conn, s.id, "break", 300, midnight + 2000)
    repo.end_segment(conn, s.id, midnight + 2300)  # break: ignored
    repo.start_segment(conn, s.id, "focus", 3000, midnight + 2300)  # open: until now
    assert repo.focus_seconds_today(conn, now) == 1000 + (10_000 - 2300)


def test_focus_seconds_today_clips_at_midnight(conn):
    from datetime import datetime
    midnight = int(datetime(2026, 11, 9).timestamp())
    s = repo.start_session(conn, midnight - 600)  # started 10 min before midnight
    repo.end_segment(conn, s.id, midnight + 400)
    assert repo.focus_seconds_today(conn, midnight + 1000) == 400


def test_add_and_list_subjects(conn):
    repo.add_subject(conn, "  Math ")
    repo.add_subject(conn, "analysis")
    assert [s.name for s in repo.list_subjects(conn)] == ["analysis", "Math"]


def test_add_subject_rejects_empty_and_duplicate(conn):
    repo.add_subject(conn, "Math")
    with pytest.raises(ValueError):
        repo.add_subject(conn, "Math")
    with pytest.raises(ValueError):
        repo.add_subject(conn, "   ")


def test_list_subjects_hides_archived(conn):
    s = repo.add_subject(conn, "Old")
    conn.execute("UPDATE subjects SET archived = 1 WHERE id = ?", (s.id,))
    assert repo.list_subjects(conn) == []


def test_session_stores_subject_or_null(conn):
    subj = repo.add_subject(conn, "Math")
    a = repo.start_session(conn, 1000, subject_id=subj.id)
    repo.stop_session(conn, a.id, 1100)
    b = repo.start_session(conn, 2000)
    ids = [r[0] for r in conn.execute("SELECT subject_id FROM sessions ORDER BY id")]
    assert ids == [subj.id, None]


# --- stats and subject management (milestone 6) ----------------------------

from datetime import date, datetime, timedelta  # noqa: E402


def _ts(day: date, hour: int, minute: int = 0) -> int:
    return int(datetime(day.year, day.month, day.day, hour, minute).timestamp())


def _focus(conn, start, end, kind="focus", subject_id=None):
    """Insert a finished session with a single segment."""
    with conn:
        sid = conn.execute(
            "INSERT INTO sessions(subject_id, started_at, ended_at) VALUES (?, ?, ?)",
            (subject_id, start, end),
        ).lastrowid
        conn.execute(
            "INSERT INTO segments(session_id, kind, planned_seconds, started_at, ended_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (sid, kind, end - start, start, end),
        )


def test_week_starts_on_monday():
    assert repo.week_start(date(2026, 11, 9)) == date(2026, 11, 9)  # a Monday
    assert repo.week_start(date(2026, 11, 15)) == date(2026, 11, 9)  # Sunday
    assert repo.week_start(date(2026, 11, 8)) == date(2026, 11, 2)  # previous Sunday


def test_focus_by_day_excludes_breaks_and_splits_at_midnight(conn):
    d1, d2 = date(2026, 11, 3), date(2026, 11, 4)
    _focus(conn, _ts(d1, 23), _ts(d2, 1))  # crosses midnight: 1h on each day
    _focus(conn, _ts(d2, 10), _ts(d2, 10, 30), kind="break")  # never counts
    now = _ts(d2, 12)
    by_day = repo.focus_by_day(conn, d1, d2, now)
    assert by_day == {d1: 3600, d2: 3600}


def test_focus_this_week_starts_monday(conn):
    sunday, monday = date(2026, 11, 8), date(2026, 11, 9)
    _focus(conn, _ts(sunday, 9), _ts(sunday, 10))  # last week
    _focus(conn, _ts(monday, 9), _ts(monday, 9, 30))
    assert repo.focus_this_week(conn, _ts(monday, 12)) == 1800


def test_open_segment_counts_up_to_now(conn):
    day = date(2026, 11, 9)
    repo.start_session(conn, _ts(day, 9))
    assert repo.focus_seconds_today(conn, _ts(day, 9, 20)) == 20 * 60


def test_streak_counts_consecutive_days(conn):
    today = date(2026, 11, 9)
    for back in (0, 1, 2, 4):  # gap 3 days ago
        _focus(conn, _ts(today - timedelta(days=back), 9), _ts(today - timedelta(days=back), 10))
    assert repo.streak_days(conn, _ts(today, 12)) == 3


def test_streak_survives_a_day_without_focus_yet(conn):
    today = date(2026, 11, 9)
    _focus(conn, _ts(today - timedelta(days=1), 9), _ts(today - timedelta(days=1), 10))
    assert repo.streak_days(conn, _ts(today, 8)) == 1


def test_streak_zero_when_nothing(conn):
    assert repo.streak_days(conn, _ts(date(2026, 11, 9), 12)) == 0


def test_focus_by_subject_groups_and_orders(conn):
    day = date(2026, 11, 9)
    math = repo.add_subject(conn, "Math")
    _focus(conn, _ts(day, 9), _ts(day, 10), subject_id=math.id)
    _focus(conn, _ts(day, 11), _ts(day, 11, 30))  # no subject
    _focus(conn, _ts(day, 12), _ts(day, 12, 10), kind="break", subject_id=math.id)
    result = repo.focus_by_subject(conn, _ts(day, 0), _ts(day, 23), _ts(day, 23))
    assert result == [("Math", None, 3600), ("No subject", None, 1800)]


def test_subject_rename_archive_color(conn):
    a = repo.add_subject(conn, "A")
    repo.add_subject(conn, "B")
    repo.rename_subject(conn, a.id, " Alpha ")
    with pytest.raises(ValueError):
        repo.rename_subject(conn, a.id, "B")
    with pytest.raises(ValueError):
        repo.rename_subject(conn, a.id, "  ")
    repo.set_subject_color(conn, a.id, "#ff0000")
    repo.set_subject_archived(conn, a.id, True)
    assert [s.name for s in repo.list_subjects(conn)] == ["B"]
    full = repo.list_subjects(conn, include_archived=True)
    assert (full[0].name, full[0].color, full[0].archived) == ("Alpha", "#ff0000", True)


# --- manual editing / export -------------------------------------------------

NOW = 2_000_000_000


def test_add_manual_session_is_session_plus_one_focus_segment(conn):
    sid = repo.add_manual_session(conn, NOW - 3600, NOW - 1800, NOW, note="reading")
    (row,) = repo.list_sessions(conn, NOW)
    assert (row.id, row.source, row.end_reason, row.focus_seconds) == (sid, "manual", "manual", 1800)
    assert repo.focus_seconds_between(conn, NOW - 7200, NOW, NOW) == 1800  # counts in stats


def test_manual_session_rejects_bad_spans(conn):
    with pytest.raises(ValueError):
        repo.add_manual_session(conn, NOW - 100, NOW - 100, NOW)
    with pytest.raises(ValueError):
        repo.add_manual_session(conn, NOW - 100, NOW + 100, NOW)  # future


def test_update_manual_session_changes_times_and_segment(conn):
    sid = repo.add_manual_session(conn, NOW - 3600, NOW - 1800, NOW)
    repo.update_session(conn, sid, NOW, None, "x", NOW - 7200, NOW - 3600)
    (row,) = repo.list_sessions(conn, NOW)
    assert (row.started_at, row.focus_seconds, row.note) == (NOW - 7200, 3600, "x")


def test_timer_session_allows_subject_and_note_but_not_times(conn):
    subject = repo.add_subject(conn, "Math")
    s = repo.start_session(conn, NOW - 1000)
    repo.stop_session(conn, s.id, NOW - 500)
    repo.update_session(conn, s.id, NOW, subject.id, "note")
    assert repo.list_sessions(conn, NOW)[0].subject == "Math"
    with pytest.raises(ValueError):
        repo.update_session(conn, s.id, NOW, None, "", NOW - 900, NOW - 400)


def test_running_session_cannot_be_edited_or_deleted(conn):
    s = repo.start_session(conn, NOW - 100)
    with pytest.raises(ValueError):
        repo.update_session(conn, s.id, NOW, None, "")
    with pytest.raises(ValueError):
        repo.delete_session(conn, s.id)


def test_delete_session_removes_its_segments(conn):
    sid = repo.add_manual_session(conn, NOW - 3600, NOW - 1800, NOW)
    repo.delete_session(conn, sid)
    assert repo.list_sessions(conn, NOW) == []
    assert conn.execute("SELECT COUNT(*) FROM segments").fetchone()[0] == 0


def test_csv_export_has_header_and_one_row_per_session(conn, tmp_path):
    from mytomatotimer import export

    s = repo.start_session(conn, NOW - 4000)
    repo.end_segment(conn, s.id, NOW - 3000)
    repo.start_segment(conn, s.id, "break", 300, NOW - 3000)
    repo.stop_session(conn, s.id, NOW - 2700)
    repo.add_manual_session(conn, NOW - 600, NOW - 300, NOW, note='say "hi", ok')
    path = tmp_path / "out.csv"
    assert export.export_sessions_csv(conn, path, NOW) == 2
    import csv
    rows = list(csv.reader(open(path, encoding="utf-8")))
    assert rows[0] == export.HEADER
    assert rows[1][5:7] == ["16.7", "5.0"]  # focus / break minutes of the timer session
    assert rows[2][2] == "manual" and rows[2][8] == 'say "hi", ok'
