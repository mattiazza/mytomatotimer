import pytest

from mytomatotimer.menubar_app import format_elapsed


@pytest.mark.parametrize(
    "seconds, expected",
    [
        (0, "00:00"),
        (59.9, "00:59"),
        (60, "01:00"),
        (24 * 60 + 13, "24:13"),
        (3599, "59:59"),
        (3600, "1:00:00"),
        (3600 + 5 * 60 + 13, "1:05:13"),
        (-5, "00:00"),
    ],
)
def test_format_elapsed(seconds, expected):
    assert format_elapsed(seconds) == expected


def test_format_goal_counts_overtime_with_plus():
    from mytomatotimer.menubar_app import format_goal
    assert format_goal(90) == "01:30"
    assert format_goal(0) == "00:00"
    assert format_goal(-750) == "+12:30"


def test_window_command_unbundled(monkeypatch):
    import sys

    from mytomatotimer.menubar_app import window_command

    monkeypatch.delattr(sys, "frozen", raising=False)
    assert window_command()[-2:] == ["-m", "mytomatotimer.window"]


def test_window_command_in_bundle(monkeypatch):
    import sys

    from mytomatotimer.menubar_app import window_command

    monkeypatch.setattr(sys, "frozen", "macosx_app", raising=False)
    monkeypatch.setenv("ARGVZERO", "/x/myTomatoTimer.app/Contents/MacOS/myTomatoTimer")
    assert window_command() == ["/x/myTomatoTimer.app/Contents/MacOS/myTomatoTimer", "--window"]
