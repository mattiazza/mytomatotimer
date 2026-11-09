"""Menu-bar UI (rumps). UI only: no timer logic lives here beyond display."""

import os
import subprocess
import sys
import time

import rumps

from mytomatotimer import db, engine, login_item, repo
from mytomatotimer.notifier import MacNotifier, Notifier

FOCUS_EMOJI = "🍅"
BREAK_EMOJI = "🪩"
IDLE_TITLE = FOCUS_EMOJI

# (setting value, menu label), in menu order.
VIEWS = [
    ("session", "Session time"),
    ("block", "Current block"),
    ("next_break", "Time to next break"),
    ("daily_goal", "Time to daily goal"),
]


def format_elapsed(seconds: float) -> str:
    """M:SS under an hour, H:MM:SS from one hour on. Negative values clamp to 0."""
    total = max(0, int(seconds))
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def format_goal(remaining: int) -> str:
    """Time left to the goal; past it, count the overtime up as +MM:SS."""
    return format_elapsed(remaining) if remaining >= 0 else "+" + format_elapsed(-remaining)


def ask_text(message: str, title: str) -> str | None:
    """Ask for a line of text; None if cancelled.

    Uses osascript (a separate process, so macOS gives it keyboard focus): the
    rumps.Window text field never received keystrokes from this unbundled app.
    Both strings are fixed literals, never user input, so no escaping is needed.
    """
    script = (
        f'text returned of (display dialog "{message}" with title "{title}" '
        'default answer "" buttons {"Cancel", "Add"} default button "Add")'
    )
    result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    return result.stdout.rstrip("\n") if result.returncode == 0 else None  # Cancel exits 1


def window_command() -> list[str]:
    """Command that starts the stats window in its own process."""
    if getattr(sys, "frozen", False):
        # Inside the .app: re-run the launcher. py2app overwrites sys.argv[0] with the
        # script path, but keeps the launcher's own path in $ARGVZERO.
        return [os.environ["ARGVZERO"], "--window"]
    return [sys.executable, "-m", "mytomatotimer.window"]


def load_settings(conn) -> engine.Settings:
    """Build engine settings from the settings table (defaults live in repo)."""

    def minutes(key: str) -> int:
        # At least 1 minute: a zero-length block would loop through the cycle forever.
        return max(1, int(repo.get_setting(conn, key))) * 60

    return engine.Settings(
        focus_seconds=minutes("focus_minutes"),
        break_seconds=minutes("break_minutes"),
        long_break_seconds=minutes("long_break_minutes"),
        blocks_before_long_break=max(
            1, int(repo.get_setting(conn, "blocks_before_long_break"))
        ),
        auto_start=repo.get_setting(conn, "auto_start_next_block") == "1",
        idle_timeout_seconds=minutes("idle_timeout_minutes"),
        beep_seconds=max(0, int(repo.get_setting(conn, "beep_seconds"))),
        beeps_at_focus_end=repo.get_setting(conn, "beeps_at_focus_end") == "1",
    )


class MenuBarApp(rumps.App):
    def __init__(self, notifier: Notifier | None = None) -> None:
        super().__init__("myTomatoTimer", title=IDLE_TITLE, quit_button="Quit")
        self._conn = db.connect()
        repo.recover_crashed_sessions(self._conn)
        self._notifier = notifier or MacNotifier()
        self._session: repo.OpenSession | None = None
        self._engine = engine.Engine(load_settings(self._conn))

        # Idle: "Start session" is a submenu (pick a subject). Running: it is hidden
        # and "Stop session" shows instead. A rumps item can't be both submenu and button.
        self._start_menu = rumps.MenuItem("Start session")
        self._stop_item = rumps.MenuItem("Stop session", callback=self._on_stop)
        self._build_start_menu()
        self._break_item = rumps.MenuItem("Take a break now")
        self._next_item = rumps.MenuItem("Start next block")
        self._stats_item = rumps.MenuItem("Open stats…", callback=self._on_open_stats)
        self._window_proc: subprocess.Popen | None = None
        self._view_menu = rumps.MenuItem("View")
        self._view_items = {}
        for key, label in VIEWS:
            item = rumps.MenuItem(label, callback=self._on_view)
            self._view_items[key] = item
            self._view_menu.add(item)
        self.menu = [
            self._start_menu,
            self._stop_item,
            self._break_item,
            self._next_item,
            None,  # separator
            self._view_menu,
            self._stats_item,
        ]
        if login_item.available():
            self._login_item = rumps.MenuItem("Launch at login", callback=self._on_login)
            self._login_item.state = login_item.is_enabled()
            self.menu.add(self._login_item)

        self._timer = rumps.Timer(self._on_tick, 1)
        self._timer.start()
        self._refresh(int(time.time()))

    def _build_start_menu(self) -> None:
        """Submenu: one entry per subject, then Skip and Add subject."""
        if getattr(self._start_menu, "_menu", None) is not None:  # none before first add
            self._start_menu.clear()
        for subject in repo.list_subjects(self._conn):
            self._start_menu.add(
                rumps.MenuItem(
                    subject.name,
                    callback=lambda _s, sid=subject.id: self._start_session(sid),
                )
            )
        self._start_menu.add(None)
        self._start_menu.add(
            rumps.MenuItem("Skip (no subject)", callback=lambda _s: self._start_session(None))
        )
        self._start_menu.add(rumps.MenuItem("Add subject…", callback=self._on_add_subject))

    def _on_add_subject(self, _sender) -> None:
        name = ask_text("Name of the new subject:", "Add subject")
        if name is None:
            return
        try:
            repo.add_subject(self._conn, name)
        except ValueError as err:
            rumps.alert("Could not add subject", str(err))
            return
        self._build_start_menu()

    def _start_session(self, subject_id: int | None) -> None:
        now = int(time.time())
        # Re-read settings so hand edits take effect on the next session.
        self._engine = engine.Engine(load_settings(self._conn))
        self._engine.start(now)
        self._session = repo.start_session(
            self._conn,
            now,
            planned_seconds=self._engine.settings.focus_seconds,
            subject_id=subject_id,
        )
        self._refresh(now)

    def _on_stop(self, _sender) -> None:
        now = int(time.time())
        repo.stop_session(self._conn, self._session.id, now)
        self._engine.stop(now)
        self._session = None
        self._refresh(now)

    def _on_break_now(self, _sender) -> None:
        now = int(time.time())
        self._handle(self._engine.take_break(now))
        self._refresh(now)

    def _on_next_block(self, _sender) -> None:
        now = int(time.time())
        self._handle(self._engine.start_next_block(now))
        self._refresh(now)

    def _on_open_stats(self, _sender) -> None:
        """Launch the window as its own process (it never shares a GUI toolkit with us)."""
        if self._window_proc is not None and self._window_proc.poll() is None:
            return  # already open; one window at a time
        self._window_proc = subprocess.Popen(window_command())

    def _on_login(self, sender) -> None:
        try:
            login_item.set_enabled(not login_item.is_enabled())
        except RuntimeError as err:
            rumps.alert("Launch at login failed", str(err))
        sender.state = login_item.is_enabled()  # show what macOS actually did

    def _on_view(self, sender) -> None:
        key = next(k for k, label in VIEWS if label == sender.title)
        repo.set_setting(self._conn, "menubar_view", key)
        self._refresh(int(time.time()))

    def _focus_seconds_text(self, view: str, now: int) -> str:
        """Title text for a focus block, according to the selected view."""
        eng = self._engine
        if view == "session":
            return format_elapsed(eng.session_focus(now))
        if view == "block":
            return format_elapsed(eng.elapsed(now))
        if view == "daily_goal":
            goal = int(repo.get_setting(self._conn, "daily_goal_minutes")) * 60
            return format_goal(goal - repo.focus_seconds_today(self._conn, now))
        return format_elapsed(eng.remaining(now))  # next_break

    def _on_tick(self, _sender) -> None:
        now = int(time.time())
        self._handle(self._engine.tick(now))
        if self._session is not None:
            repo.touch(self._conn, self._session.id, now)
        self._refresh(now)

    def _handle(self, events: list[engine.Event]) -> None:
        """Apply engine events: persist segments, fire alerts."""
        for event in events:
            match event:
                case engine.SegmentEnded(at=at):
                    repo.end_segment(self._conn, self._session.id, at)
                case engine.SegmentStarted(kind=kind, planned_seconds=planned, at=at):
                    repo.start_segment(
                        self._conn, self._session.id, kind.value, planned, at
                    )
                case engine.SessionEnded(reason=reason, at=at):
                    repo.stop_session(self._conn, self._session.id, at, reason)
                    self._session = None
                case engine.FocusEnded():
                    self._notifier.notify("Focus block done", "Time for a break.")
                    self._notifier.sound()
                case engine.BreakEnded():
                    self._notifier.notify("Break over", "Back to focus.")
                    self._notifier.sound()
                case engine.Beep():
                    self._notifier.beep()

    def _refresh(self, now: int) -> None:
        # Derive from timestamps, never from counting ticks: a delayed or
        # skipped tick can't make the display drift.
        eng = self._engine
        in_focus = eng.phase is engine.Phase.FOCUS
        self._start_menu.hidden = self._session is not None
        self._stop_item.hidden = self._session is None
        # A MenuItem with no callback is greyed out.
        self._break_item.set_callback(self._on_break_now if in_focus else None)
        self._next_item.set_callback(self._on_next_block if eng.waiting else None)
        view = repo.get_setting(self._conn, "menubar_view")
        for key, item in self._view_items.items():
            item.state = key == view

        if self._session is None or eng.phase is None:
            self.title = IDLE_TITLE  # idle, or waiting for the next block
        elif in_focus:
            self.title = f"{FOCUS_EMOJI} {self._focus_seconds_text(view, now)}"
        else:
            shown = (
                eng.elapsed(now)
                if repo.get_setting(self._conn, "break_display_mode") == "elapsed"
                else eng.remaining(now)
            )
            self.title = f"{BREAK_EMOJI} {format_elapsed(shown)}"


def run() -> None:
    MenuBarApp().run()
