# myTomatoTimer

A macOS menu-bar study timer. It tracks focus blocks and breaks, shows a live
timer next to the clock (`🍅 24:13`, `🪩 04:32` during a break), and has a stats
window to visualize how much effort you put into studying.

Everything is stored locally in SQLite. The app makes no network calls.

## Features

- **Two phases only**: focus and break (short or long). Only focus time counts
  toward session time and goals; a partially completed block counts for the
  time actually spent.
- **Menu-bar timer** with switchable views: session time, current block, time to
  next break, time to daily goal.
- **Take a break now**: ends the current block early and starts a break; a fresh
  focus block follows (optionally auto-started).
- **Alerts**: macOS notifications and sounds at block ends, plus per-second
  countdown beeps in the last N seconds of a break.
- **Subjects**: pick a subject when starting a session; manage them in the window.
- **Stats window**: today's total, weekly bar chart, calendar heatmap, streak,
  weekly goal progress, time per subject.
- **Session editor and CSV export**: add, edit and delete sessions by hand.
- **Settings**: durations, blocks before a long break, daily/weekly goals,
  auto-start, idle timeout, break display mode, beeps.
- **Launch at login** (in the packaged `.app`).

## Requirements

- macOS (developed on macOS 26, Apple Silicon)
- Python 3.12+
- [uv](https://docs.astral.sh/uv/)

## Setup and run

```sh
uv sync
uv run python -m mytomatotimer          # menu-bar app
uv run python -m mytomatotimer.window   # stats window alone
uv run pytest                           # tests
```

The data lives at `~/Library/Application Support/myTomatoTimer/mytomatotimer.db`.

## Build the .app

py2app needs a Homebrew Python (3.13) in a separate venv, because uv's
standalone Python can't be bundled:

```sh
cd packaging && UV_PROJECT_ENVIRONMENT=../.venv-build uv run --project .. \
  --python /opt/homebrew/bin/python3.13 python setup_app.py py2app \
  && codesign --force --deep -s - dist/myTomatoTimer.app
```

The app is ad-hoc signed and not notarized.

## Architecture

| Path | Role |
| --- | --- |
| `src/mytomatotimer/menubar_app.py` | rumps menu-bar UI (entry point 1) |
| `engine.py` | pure state machine, injectable clock, no UI/DB |
| `notifier.py` | notifications, sounds, beeps |
| `db.py`, `repo.py` | SQLite connection, WAL, migrations, all SQL |
| `export.py` | CSV export |
| `window/` | pywebview + local HTML/JS stats and settings window (entry point 2) |
| `tests/` | pytest for engine, repo, window API |

Design rules: time is derived from UTC epoch timestamps (the 1 s tick only
refreshes the display), and the menu-bar and window processes share only the
SQLite file, never a GUI toolkit.

## Documentation

- [SPEC.md](SPEC.md): requirements, milestone status and the decisions log
- [CLAUDE.md](CLAUDE.md): project instructions for Claude Code

## Dependencies

[rumps](https://github.com/jaredks/rumps) (menu bar),
[pywebview](https://pywebview.flowrl.com/) (window),
pyobjc-framework-ServiceManagement (launch at login),
[Chart.js](https://www.chartjs.org/) (bundled locally), py2app (build only).
