import asyncio
import json

import app.grid_control as gc
import app.settings_db as sdb
from app.grid_control import GridController
from app.settings_db import SettingsDB


def _controller():
    return GridController(None, "broker", 1883, None, None)


def _configure(c, **settings):
    asyncio.run(c.configure(settings=settings))


def test_values_roundtrip_and_removal(tmp_path):
    db = SettingsDB(tmp_path / "s.db")
    db.save({"a": 1, "b": "x", "c": None, "d": 2.5})
    assert db.load() == {"a": 1, "b": "x", "c": None, "d": 2.5}
    db.save({"a": 2}, remove=["b", "missing"])
    assert db.load() == {"a": 2, "c": None, "d": 2.5}


def test_an_unusable_location_disables_persistence_without_raising(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("not a directory")
    db = SettingsDB(blocker / "s.db")
    assert not db.enabled
    db.save({"a": 1})
    assert db.load() == {}


def test_a_change_made_in_the_ui_survives_a_restart_and_beats_the_env(monkeypatch):
    c = _controller()
    _configure(c, NIGHT_MAX_W=180)
    monkeypatch.setenv("NIGHT_MAX_W", "222")  # the .env of the next start says something else
    assert _controller().night_max_w == 180


def test_only_what_differs_from_the_default_is_stored():
    c = _controller()
    _configure(c, NIGHT_MAX_W=180)
    stored = SettingsDB().load()
    assert stored["setting.NIGHT_MAX_W"] == 180
    assert "setting.NIGHT_START" not in stored and "setting.CHARGE_FULL_SOC" not in stored


def test_a_default_changed_later_still_reaches_settings_never_touched(monkeypatch):
    """The old full snapshot froze every setting at its first save: a later .env edit of anything
    else was silently ignored."""
    _configure(_controller(), CHARGE_RESERVE_W=300)
    monkeypatch.setenv("NIGHT_MAX_W", "222")
    c = _controller()
    assert c.night_max_w == 222 and c.settings()["CHARGE_RESERVE_W"] == 300


def test_setting_a_value_back_to_the_default_hands_it_back_to_the_env(monkeypatch):
    c = _controller()
    _configure(c, NIGHT_MAX_W=180)
    _configure(c, NIGHT_MAX_W=150)  # the default
    assert "setting.NIGHT_MAX_W" not in SettingsDB().load()
    monkeypatch.setenv("NIGHT_MAX_W", "222")
    assert _controller().night_max_w == 222


def test_one_invalid_stored_value_does_not_cost_the_others():
    SettingsDB().save({
        "setting.CONTROL_MIN_INTERVAL": 5,  # below the allowed 60-120 s
        "setting.NIGHT_MAX_W": 180,
        "setting.CHARGE_FULL_SOC": 100,
        "setting.CHARGE_RELEASE_SOC": 98,  # only valid together with the full value above
    })
    c = _controller()
    assert c.min_interval_s == 60  # fell back to the default
    assert c.night_max_w == 180 and c.full_soc == 100 and c.release_soc == 98


def test_the_toggles_and_learned_state_survive_a_restart():
    c = _controller()
    asyncio.run(c.configure(plan=False, cover_load=True, adaptive_gain=True))
    c.learned_gain = 0.9
    c._save()
    again = _controller()
    assert (again.plan_enabled, again.cover_load, again.adaptive_gain, again.learned_gain) == (False, True, True, 0.9)


def test_the_earlier_control_json_is_imported_once(tmp_path):
    gc.CONTROL_FILE.write_text(json.dumps({
        "enabled": True, "dry_run": False, "plan": True, "cover_load": True, "adaptive_gain": False,
        "gain": 0.8, "restore_w": 120,
        "settings": {"NIGHT_MAX_W": 180, "NIGHT_START": "23:00", "CHARGE_RESERVE_W": 614},  # 614: a live export-guard raise
        "reserve_base_w": 210, "charge_reserve_w": 614,
    }))
    c = _controller()
    assert (c.enabled, c.dry_run, c.cover_load, c.learned_gain, c.restore_w) == (True, False, True, 0.8, 120)
    assert c.night_max_w == 180 and c.settings()["CHARGE_RESERVE_W"] == 210 and c.charge_reserve_w == 614
    assert not gc.CONTROL_FILE.exists() and gc.CONTROL_FILE.with_name("control.json.migrated").exists()
    assert "setting.NIGHT_START" not in SettingsDB().load()  # equal to the default: nothing to keep
    assert _controller().night_max_w == 180  # now read from settings.db


def test_an_unreadable_control_json_is_ignored():
    gc.CONTROL_FILE.write_text("{ not json")
    c = _controller()
    assert c.night_max_w == 150 and c.enabled is False


def test_a_broken_settings_location_does_not_stop_the_controller(tmp_path, monkeypatch):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    monkeypatch.setattr(sdb, "SETTINGS_FILE", blocker / "s.db")
    c = _controller()
    _configure(c, NIGHT_MAX_W=180)
    assert c.night_max_w == 180  # applied, just not persisted
