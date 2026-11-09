"""SQLite connection, WAL mode and migrations. No queries for features here: see repo.py."""

import sqlite3
from pathlib import Path

APP_DIR = Path.home() / "Library" / "Application Support" / "myTomatoTimer"
DB_PATH = APP_DIR / "mytomatotimer.db"

# Each entry is one migration; the schema version is the number of entries applied
# (stored in PRAGMA user_version). Never edit an applied migration: append a new one.
MIGRATIONS = [
    """
    CREATE TABLE subjects (
        id       INTEGER PRIMARY KEY,
        name     TEXT NOT NULL UNIQUE,
        color    TEXT,
        archived INTEGER NOT NULL DEFAULT 0
    );
    CREATE TABLE sessions (
        id         INTEGER PRIMARY KEY,
        subject_id INTEGER REFERENCES subjects(id),
        started_at INTEGER NOT NULL,
        ended_at   INTEGER,
        source     TEXT NOT NULL DEFAULT 'timer' CHECK (source IN ('timer', 'manual')),
        end_reason TEXT CHECK (end_reason IN ('user', 'sleep', 'idle_timeout', 'crash', 'manual')),
        note       TEXT
    );
    CREATE TABLE segments (
        id              INTEGER PRIMARY KEY,
        session_id      INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
        kind            TEXT NOT NULL CHECK (kind IN ('focus', 'break', 'long_break')),
        planned_seconds INTEGER NOT NULL,
        started_at      INTEGER NOT NULL,
        ended_at        INTEGER,
        last_tick_at    INTEGER
    );
    CREATE TABLE settings (
        key   TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );
    CREATE INDEX idx_sessions_started ON sessions(started_at);
    CREATE INDEX idx_segments_session ON segments(session_id);
    """,
]


def connect(path: Path | str = DB_PATH) -> sqlite3.Connection:
    """Open the DB (creating the folder if needed), enable WAL, and migrate."""
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    # Two processes share this file: wait briefly instead of failing on a lock.
    conn.execute("PRAGMA busy_timeout=5000")
    migrate(conn)
    return conn


def migrate(conn: sqlite3.Connection) -> None:
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    for number, script in enumerate(MIGRATIONS[version:], start=version + 1):
        # executescript commits first, so run the script and the version bump together
        # in one explicit transaction to avoid a half-migrated DB.
        conn.executescript(f"BEGIN;\n{script}\nPRAGMA user_version = {number};\nCOMMIT;")
