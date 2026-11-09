# myTomatoTimer - Spec

Goal: visualize how much effort I put into studying.

Target: macOS Tahoe 26.x, Apple Silicon (M1 Pro). Python 3.11+ from Homebrew, managed with uv.

## Timer flow
- Two phases only: focus and break (a break is short or long).
- Break is timed too. It can be displayed as a countdown (time remaining) or as time elapsed (setting: break display mode).
- Breaks do NOT count toward session time or the daily/weekly goal. Only focus time counts. A partially completed block counts for the time actually spent.
- "Take a break now" (menu action): ends the current focus block early (the time spent counts) and starts a break immediately. When that break ends, a fresh full focus block starts (subject to the auto-start setting below). The interrupted block is not resumed.
- After a break ends, the next focus block either starts automatically or waits for a click (setting: auto-start next block, on/off). The timer should also be usable for non-study activities such as workouts: same cycle, durations changed by hand in settings (no profiles in v1; to be discussed once the app is running).
- Auto-start off: if the next focus block is not started within 5 minutes after the break ended (setting: idle timeout, default 5 min), the session is closed and the keep-awake hold is released, so macOS can sleep on its normal schedule (the app does not force sleep). This applies only when auto-start is off.

## Alerts
- macOS notification + sound when focus block ends and when break ends.
- Countdown beeps: one beep per second during the last N seconds before the end of a break (setting: beep seconds, default 5; 0 = visual only, no beeps). Same behavior whether auto-start is on or off: beeps only in those last N seconds, nothing after the break has ended.
- Beeps at the end of a focus block are optional (setting, default off; useful for workouts). They use the same N seconds.
- If a break ends while the display is asleep, play the audio signal by default (setting: on/off, so I can compare audio vs silence).

## Sleep / lid behavior
- Display sleep: nothing changes, timers keep running (timestamps, not tick counts).
- Lid closed (system sleep): the session is considered ended, at the moment of sleep.
- While a session is running (focus and break alike), hold a "prevent idle sleep" power assertion so the Mac doesn't sleep on its own and the break-end alert can fire (setting: on/off, default on). Held for the whole session so the app never has to check display state. Released when the session ends, including via the idle timeout above.

## Subject tags
- Pick a subject when starting a session; manage the subject list.

## Menu bar (next to clock)
- Live timer in the macOS menu bar, prefixed with a tomato emoji, e.g. `🍅 24:13`.
- Click menu to switch the displayed view: current session time / current block time / time to next break / time to daily goal. Break display as above.
- Start/stop and "Take a break now" from that menu.
- Break state: show a different emoji (e.g. `🪩 04:32`) so I can tell focus from break at a glance. Long break uses the same emoji. Idle (no session): plain `🍅` with no time.

## Stats window
- Today's total, weekly bar chart, calendar heatmap, streak counter, weekly goal progress, time per subject.
- Also hosts: session editor, subject manager, settings (tabs).
- Weeks start on Monday.

## Data
- Local SQLite. CSV export. Never send data anywhere.
- Manual edit: add, edit, delete sessions.
- Goals (daily, weekly) configurable in hours/minutes, stored in minutes.

## Architecture (agreed direction)
- Menu bar: rumps. Stats/settings window: separate process (pywebview + local HTML/JS, Chart.js bundled locally). Processes share only the SQLite file (WAL mode). Avoids GUI toolkit conflicts. Future option: switch window to pure Python.
- engine.py is a pure state machine (no UI, no DB, injectable clock), unit-tested. Time is derived from timestamps (UTC epoch ints), never from tick counts.
- Schema:
  - subjects(id, name, color, archived)
  - sessions(id, subject_id, started_at, ended_at, source timer|manual, end_reason user|sleep|idle_timeout|crash|manual, note)
  - segments(id, session_id, kind focus|break|long_break, planned_seconds, started_at, ended_at, last_tick_at)  -- a block cut short has actual duration < planned_seconds
  - settings(key, value)
  - Manual sessions = session + one focus segment. Crash recovery: close open segments at last_tick_at on launch.
- Settings: focus/break/long-break minutes, blocks before long break, daily/weekly goal, auto-start next block, idle timeout after break (auto-start off), break display mode, beep seconds, beeps at block end, alert if display asleep, prevent idle sleep.
- Tests: pytest across engine and DB layers.

## Milestones
0 skeleton (uv, layout, pytest) / 1 menu bar clock / 2 start-stop + SQLite / 3 focus-break cycle, "take a break now", notifications and sounds / 4 view switching / 5 subjects / 6 window (stats, subjects, settings) / 7 manual edit + CSV / 8 .app packaging + launch at login.

### Status
- Done: milestone 0 (uv project, src layout, pytest smoke test passing). Milestone 1 (menu bar clock with rumps, 1 s tick from timestamps, `format_elapsed` tested; 9 tests passing).
- Done: milestone 2 (start/stop + SQLite; 16 tests passing; Start/Stop confirmed working by hand).
- Done: milestone 3 (focus-break cycle, "take a break now", notifications and sounds; 32 tests passing; cycle confirmed working by hand).
- Done: milestone 4 (view switching; 37 tests passing; View switching confirmed working by hand).
- Done: milestone 5 (subjects; 41 tests passing; confirmed working by hand).
- Done: milestone 6 (window: stats, subjects, settings; 55 tests passing; confirmed working by hand after a quick look). 
- Done: milestone 7 (manual edit + CSV; 63 tests passing; confirmed working by hand).
- Done: milestone 8 (.app packaging + launch at login; 65 tests passing; confirmed working by hand). All milestones complete.

## Open items (future)
- Timer profiles (e.g. workouts with different durations): v1 has none, settings are changed by hand. Revisit now that the app is running.
- `ask_text` (osascript dialog for "Add subject…"): try `rumps.Window` inside the bundle; switch only if the text field gets keyboard input.
- Not implemented yet from the spec: keep-awake power assertion (prevent idle sleep), lid-close/system-sleep ends the session, alert if display asleep. Their settings are hidden in the window until they exist.
- Custom app icon (.icns): the bundle uses the default py2app icon.
- Rebuild is manual (command in the decisions log); the app was copied to /Applications by hand, so a rebuild must be copied over again.
- Nothing is committed to git yet.

## Decisions log
- 2026-11-08: rumps for menu bar; separate-process pywebview window (option A); SQLite with epoch-UTC timestamps.
- 2026-11-08: Breaks excluded from session time and goals; partial blocks count.
- 2026-11-08: Auto-start of next block after a break is a setting.
- 2026-11-08: Display sleep keeps timers running; break-end audio while asleep is a setting (default on); lid closed / system sleep ends the session.
- 2026-11-08: Weeks start Monday; goals in minutes, shown as h/min.
- 2026-11-08: pytest everywhere.
- 2026-11-08: Beeps in last N seconds of a break (configurable, 0 = visual only), with auto-start on or off; optional at end of focus block.
- 2026-11-08: Prevent idle sleep for the whole running session (setting, default on).
- 2026-11-08: Auto-start off: close session 5 min after break end if no block started, then release the hold (no forced sleep).
- 2026-11-08: No timer profiles in v1; settings changed by hand. Revisit after the app is running.
- 2026-11-09: App name: myTomatoTimer (package: mytomatotimer).
- 2026-11-09: Only two phases, focus and break (short/long). No separate pause state: "pause" is "Take a break now", which ends the current block early and starts a break; afterwards a new full focus block starts (no resume). Pause table, pause length and pause emoji dropped; "pause display mode" became "break display mode" (countdown or elapsed).
- 2026-11-09: Menu bar emojis: focus 🍅, break and long break 🪩, idle plain 🍅.
- 2026-11-09: A block cut short by "Take a break now" counts toward the long-break counter.
- 2026-11-09: Milestone 0 done: src layout built with uv_build (so the package is installed editable); pytest is a uv dev dependency; requires-python >=3.12 (the uv init default, within the 3.11+ target). Nothing committed yet.
- 2026-11-09: Milestone 1 is next: menu bar clock with rumps.
- 2026-11-09: Milestone 1 done: rumps added as a dependency (menu-bar wrapper over AppKit). The clock is a throwaway demo counting up from app launch as `🍅 MM:SS` (`H:MM:SS` from one hour), derived from time.time() each 1 s tick. Dock icon left as is until milestone 8 (LSUIElement).
- 2026-11-09: Milestone 2 done: DB at ~/Library/Application Support/myTomatoTimer/mytomatotimer.db. Migration 1 creates the full SPEC schema; versioning via PRAGMA user_version. Start creates a session plus one open focus segment (planned = focus setting); the 1 s tick updates the segment's last_tick_at; on launch, open sessions are closed at last_tick_at with end_reason `crash`. Default durations live only in repo.DEFAULT_SETTINGS.
- 2026-11-09: Milestone 3: engine.py takes `now` as an argument (that is the injectable clock) and returns events (SegmentEnded/Started, SessionEnded, FocusEnded, BreakEnded, Beep); the app persists and alerts. Late ticks process every due transition at its own end time. Waiting after a break (auto-start off) is not a phase: the session stays open with `waiting_since` set. Notifications via `osascript`, sounds via `afplay` (system Glass/Tink), because rumps.notification needs an app bundle. New settings defaults in repo: auto_start_next_block, idle_timeout_minutes, break_display_mode, beep_seconds, beeps_at_focus_end. Not yet in: keep-awake assertion, lid-close, display-asleep alert. Until milestone 4, the focus title shows time remaining in the block; breaks follow break_display_mode.
- 2026-11-09: Milestone 4: a "View" submenu (checkmark on the active one) switches focus-block title between session time (focus only, from engine.session_focus), current block (elapsed), time to next break (remaining) and time to daily goal. Choice stored in settings as `menubar_view`. Breaks ignore the view and always follow break_display_mode. Daily goal default 240 min (`daily_goal_minutes`); today's focus comes from repo.focus_seconds_today (local midnight, open segment counts up to now). Past the goal the view counts overtime as `+MM:SS`. While waiting for the next block (auto-start off) the title stays a plain 🍅.
- 2026-11-09: Milestone 5: "Start session" is a submenu listing subjects, then "Skip (no subject)" (subject_id NULL) and "Add subject…" (rumps.Window prompt). While a session runs the submenu is hidden and "Stop session" shows instead (a rumps item can't be both submenu and button). One subject per session, fixed at start; the title shows only the timer. Subject names are unique even when archived. Rename/archive/colors wait for the milestone 6 window.
- 2026-11-09: "Add subject…" uses an osascript `display dialog` (helper `ask_text`), not rumps.Window: the rumps text field got no keystrokes from this unbundled app (they went to the terminal). Revisit after .app packaging in milestone 8.
- 2026-11-09: Milestone 6: pywebview 6.2.1 added (window toolkit, as agreed). Chart.js 4.4.7 UMD build saved once as window/web/chart.min.js (no network at runtime). Window opened from the menu bar via "Open stats…" as a subprocess (`python -m mytomatotimer.window`), one at a time. Each js_api call opens its own SQLite connection (pywebview uses worker threads). Bad input returns `{ok: false, error}` instead of raising. Weekly goal setting `weekly_goal_minutes`, default 1200 (20 h). Heatmap: last 10 weeks, Monday-first columns, shade by share of the daily goal. Streak = consecutive local days with any focus time; today without focus yet doesn't break it. Time per subject: toggle this week / 10 weeks; sessions without a subject show as "No subject". Settings tab only lists settings that exist (alert-if-display-asleep and prevent-idle-sleep come with their features). Settings changed in the window apply from the next session (menu bar reads them at session start). Subject rename/archive/color live in the Subjects tab; archived subjects keep history.
- 2026-11-09: Milestone 7: new "Sessions" tab (list newest first, add/edit/delete, Export CSV). Manual sessions = one session + one focus segment and are fully editable. Timer sessions keep recorded times (several segments): only subject and note editable, delete allowed. Running sessions can't be edited or deleted from the window. Overlapping sessions are allowed (not checked); end can't be in the future. Delete asks by turning the button into "Sure?" (no confirm() in pywebview). CSV (export.py): one row per session, oldest first, local times, focus/break minutes, saved via a native save dialog.
- 2026-11-09: Milestone 8: py2app 0.28.10 (dev dependency, build only) builds dist/myTomatoTimer.app (LSUIElement, id local.mytomatotimer), ad-hoc signed, no notarization. Build script is packaging/setup_app.py, run from packaging/ because setuptools reads pyproject dependencies as install_requires, which py2app rejects. The build needs a Homebrew Python (3.13) in a separate venv (.venv-build): uv's standalone Python has zlib built in and py2app can't copy it. Command: `cd packaging && UV_PROJECT_ENVIRONMENT=../.venv-build uv run --project .. --python /opt/homebrew/bin/python3.13 python setup_app.py py2app && codesign --force --deep -s - dist/myTomatoTimer.app`.
- 2026-11-09: In the bundle there is no `python -m`, so `__main__` takes `--window` and the menu bar spawns `$ARGVZERO --window` (py2app overwrites sys.argv[0] with the script path; the launcher path stays in $ARGVZERO). Still two processes, sharing only SQLite.
- 2026-11-09: Launch at login uses SMAppService (pyobjc-framework-ServiceManagement); the OS stores the state, not the settings table. The menu item only shows in the bundle (`sys.frozen`), because unbundled macOS would register the Python interpreter instead.
- 2026-11-09: myTomatoTimer.app installed by hand in /Applications (so the login item survives rebuilds in packaging/dist). Remaining ideas are listed under Open items.
