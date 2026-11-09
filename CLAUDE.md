# myTomatoTimer

macOS menu-bar study timer written in Python. It tracks study sessions
(focus blocks and breaks), shows a live timer next to the clock, and has a
stats window. Full requirements: see SPEC.md (source of truth).

## Stack
- Python 3.11+, macOS only
- Menu bar: rumps. Stats/settings window: pywebview + local HTML/JS (separate process)
- Storage: local SQLite (WAL mode), no network calls ever
- Dependencies in pyproject.toml, managed by uv (uv creates .venv/ itself)

## Commands
- Setup: uv sync
- Add a dependency: uv add <package>
- Run menu-bar app: uv run python -m mytomatotimer  (update if the entry point changes)
- Run stats window alone (from milestone 6): uv run python -m mytomatotimer.window
- Tests: uv run pytest
- Build .app (milestone 8): see the decisions log in SPEC.md (needs Homebrew Python 3.13)

## Structure
Source lives in src/mytomatotimer/. Modules are added milestone by milestone.
- __main__.py / menubar_app.py: rumps app, UI only (entry point 1)
- engine.py: pure state machine (focus/break/long_break); no UI, no DB, injectable clock
- notifier.py: notification + sound + beeps, swappable
- db.py: connection, WAL, migrations. repo.py: all SQL (sessions, segments, subjects, settings, stats)
- export.py: CSV export
- window/: separate process (entry point 2): main.py, api.py, web/ (index.html, app.js, style.css, chart.min.js)
- tests/: pytest for engine and db/repo

## Architecture rules
- Only two phases: focus and break (short/long). No pause state.
- Time is derived from UTC epoch timestamps, never from tick counts. The 1 s tick only refreshes the display.
- The menu-bar process and the window process never share a GUI toolkit; they share only the SQLite file.
- All settings come from the settings table; no hard-coded durations outside defaults.

## Working rules
- Build one milestone from SPEC.md at a time. Don't start the next until I confirm.
- Before changing code for a new feature, give a short plan and flag decisions I need to make.
- Run the app or tests after changes and report what actually happened.
- I'm learning: after each change, explain the key parts in a few sentences. Skip basics.
- Keep code simple and readable. Small modules, clear names, comments only where non-obvious.
- Never add a dependency without telling me why.
- If you're unsure about a library's current API or macOS behavior, say so and check, don't guess.
- Update the decisions log in SPEC.md when we make a design decision.

## Gotchas
(Add lines here when Claude gets something wrong twice.)