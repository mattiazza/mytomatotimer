"""Notifications and sounds. Swappable: the app only calls the Notifier methods.

macOS tools are used instead of a Python API because `rumps.notification` needs an
app bundle (milestone 8). Both commands run detached so the 1 s tick never blocks.
"""

import subprocess

SOUND_DIR = "/System/Library/Sounds"


class Notifier:
    def notify(self, title: str, message: str) -> None:
        raise NotImplementedError

    def sound(self) -> None:
        """The alert sound for the end of a block or break."""
        raise NotImplementedError

    def beep(self) -> None:
        raise NotImplementedError


class MacNotifier(Notifier):
    def notify(self, title: str, message: str) -> None:
        # Pass text as argv, not interpolated into the script, so quotes can't break it.
        script = "on run argv\ndisplay notification (item 2 of argv) with title (item 1 of argv)\nend run"
        self._spawn(["osascript", "-e", script, title, message])

    def sound(self) -> None:
        self._spawn(["afplay", f"{SOUND_DIR}/Glass.aiff"])

    def beep(self) -> None:
        self._spawn(["afplay", f"{SOUND_DIR}/Tink.aiff"])

    @staticmethod
    def _spawn(cmd: list[str]) -> None:
        try:
            subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            pass  # an alert failing must never break the timer


class SilentNotifier(Notifier):
    """For tests: records calls instead of making noise."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def notify(self, title: str, message: str) -> None:
        self.calls.append(("notify", title, message))

    def sound(self) -> None:
        self.calls.append(("sound",))

    def beep(self) -> None:
        self.calls.append(("beep",))
