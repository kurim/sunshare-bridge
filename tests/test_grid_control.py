import asyncio

import pytest

from app.grid_control import GridController, _in_window, _parse_hm


def _controller():
    return GridController(None, "broker", 1883, None, None)


def test_defaults_come_from_the_documented_values():
    s = _controller().settings()
    assert s["BATTERY_CAPACITY_WH"] == 1526 and s["CHARGE_FULL_SOC"] == 95 and s["NIGHT_START"] == "23:00"


def test_settings_are_validated_and_persisted(isolated_data):
    c = _controller()
    asyncio.run(c.configure(settings={"NIGHT_MAX_W": 180, "NIGHT_START": "22:30"}))
    assert c.night_max_w == 180 and c.night_start == 22 * 60 + 30
    assert _controller().night_max_w == 180  # a new instance reads control.json


@pytest.mark.parametrize("bad", [
    {"CHARGE_RELEASE_SOC": 99},       # above CHARGE_FULL_SOC (95)
    {"NIGHT_MAX_W": 99999},           # out of range
    {"UNKNOWN_KEY": 1},
    {"NIGHT_END": "not a time"},
    {"CHARGE_RESERVE_W": True},       # bool is not a number
])
def test_invalid_settings_are_rejected_without_changing_anything(bad):
    c = _controller()
    before = c.settings()
    with pytest.raises(ValueError):
        asyncio.run(c.configure(settings=bad))
    assert c.settings() == before


def test_night_window_wraps_midnight():
    start, end = _parse_hm("23:00"), _parse_hm("06:00")
    assert _in_window(_parse_hm("23:30"), start, end)
    assert _in_window(_parse_hm("02:00"), start, end)
    assert not _in_window(_parse_hm("12:00"), start, end)
    assert not _in_window(_parse_hm("06:00"), start, end)  # end is exclusive


def test_no_meter_configured_is_fine():
    c = _controller()
    assert c.config_topic == "" and c.state_topic is None
