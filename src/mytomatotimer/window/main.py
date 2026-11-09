"""Entry point 2: the stats/settings window. Run with `python -m mytomatotimer.window`.

A separate process from the menu bar on purpose: the two never share a GUI toolkit,
only the SQLite file.
"""

from pathlib import Path

import webview

from mytomatotimer.window.api import Api

WEB_DIR = Path(__file__).parent / "web"


def run() -> None:
    webview.create_window(
        "myTomatoTimer",
        str(WEB_DIR / "index.html"),
        js_api=Api(),
        width=960,
        height=720,
        min_size=(720, 520),
    )
    webview.start()


if __name__ == "__main__":
    run()
