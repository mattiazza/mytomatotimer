import pytest

from mytomatotimer import db, repo
from mytomatotimer.window import api as api_module


@pytest.fixture
def api(tmp_path, monkeypatch):
    path = tmp_path / "test.db"
    monkeypatch.setattr(db, "DB_PATH", path)
    monkeypatch.setattr(db, "connect", lambda p=path: _real_connect(p))
    return api_module.Api()


_real_connect = db.connect


def test_save_settings_validates_before_writing(api):
    bad = api.save_settings({"focus_minutes": "25", "break_minutes": "0"})
    assert bad["ok"] is False
    assert api.get_settings()["focus_minutes"] == "50"  # nothing was saved


def test_save_settings_roundtrip(api):
    r = api.save_settings(
        {"focus_minutes": 25, "auto_start_next_block": False, "break_display_mode": "elapsed",
         "weekly_goal_minutes": 600}
    )
    assert r == {"ok": True}
    s = api.get_settings()
    assert (s["focus_minutes"], s["auto_start_next_block"], s["break_display_mode"]) == ("25", "0", "elapsed")
    assert s["weekly_goal_minutes"] == "600"


def test_save_settings_rejects_unknown_key_and_choice(api):
    assert api.save_settings({"nope": 1})["ok"] is False
    assert api.save_settings({"break_display_mode": "sideways"})["ok"] is False


def test_get_stats_shape(api):
    stats = api.get_stats()
    assert len(stats["week_days"]) == 7
    assert len(stats["heatmap"]) == 70
    assert stats["weekly_goal_seconds"] == 1200 * 60
    assert stats["streak_days"] == 0


def test_subject_errors_come_back_as_data(api):
    assert api.add_subject("Math") == {"ok": True}
    assert api.add_subject("Math")["ok"] is False


def test_session_api_add_edit_delete_and_errors(api):
    assert api.add_session(None, "2020-01-01T10:00", "2020-01-01T11:00", "n") == {"ok": True}
    (s,) = api.get_sessions()
    assert (s["started_at"], s["focus_seconds"], s["note"]) == ("2020-01-01T10:00", 3600, "n")
    assert api.add_session(None, "2020-01-01T11:00", "2020-01-01T10:00")["ok"] is False
    assert api.add_session(None, "garbage", "2020-01-01T10:00")["ok"] is False
    assert api.update_session(s["id"], None, "", "2020-01-01T10:00", "2020-01-01T12:00")["ok"]
    assert api.get_sessions()[0]["focus_seconds"] == 7200
    assert api.delete_session(s["id"]) == {"ok": True}
    assert api.get_sessions() == []
