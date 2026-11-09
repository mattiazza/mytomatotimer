"""Entry point: `uv run python -m mytomatotimer`, and the script inside the .app.

`--window` starts the stats window instead of the menu bar. The menu bar uses it to
spawn the window as a separate process; in the bundle there is no `python -m`.
"""

import sys

if __name__ == "__main__":
    if "--window" in sys.argv:
        from mytomatotimer.window.main import run
    else:
        from mytomatotimer.menubar_app import run
    run()
