"""Build myTomatoTimer.app:  cd packaging && uv run python setup_app.py py2app

Not the package build (that is pyproject.toml / uv_build); this only wraps the
app in a macOS bundle. Add `-A` after py2app for a quick alias build while developing.
"""

from setuptools import setup

setup(
    name="myTomatoTimer",
    app=["../src/mytomatotimer/__main__.py"],
    options={
        "py2app": {
            "packages": ["mytomatotimer", "webview", "rumps"],
            "includes": ["ServiceManagement"],
            "plist": {
                "CFBundleName": "myTomatoTimer",
                "CFBundleIdentifier": "local.mytomatotimer",
                "CFBundleShortVersionString": "0.1.0",
                "LSUIElement": True,  # menu-bar only, no Dock icon
                "LSMinimumSystemVersion": "13.0",  # SMAppService
            },
        }
    },
)
