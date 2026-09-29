import asyncio
import time

import pytest

import app.state as st
from app.debug_log import DEBUG, DebugLog
from app.grid_control import GridController
from app.messages import Msg


class _Client:
    """Just enough of the cloud client for a controller step."""

    def __init__(self):
        self.writes = []

    async def read_ems_settings(self):
        return {"mesSettingUpdatePojo": {"permPower": 100, "emsStrategyType": 1}}

    async def set_output_power(self, watts, ems_strategy_type=1):
        self.writes.append(watts)
        return True


def _controller(client=None):
    return GridController(client or _Client(), "broker", 1883, None, None)


def _kinds():
    return [e["kind"] for e in DEBUG.snapshot()["entries"]]


def _noon():
    return time.mktime((2026, 1, 5, 12, 0, 0, 0, 0, -1))


def test_the_log_is_a_ring_and_since_returns_only_newer_entries():
    log = DebugLog(size=3)
    for w in range(5):
        log.add("meter", Msg("dbg.meter", "info", w=w), meter=w)
    snap = log.snapshot()
    assert [e["ctx"]["meter"] for e in snap["entries"]] == [2, 3, 4] and snap["last_id"] == 5
    assert [e["id"] for e in log.snapshot(since=4)["entries"]] == [5]
    log.clear()
    assert log.snapshot()["entries"] == [] and log.snapshot()["last_id"] == 5  # the counter keeps running


def test_entries_carry_a_translatable_message_and_only_known_numbers():
    log = DebugLog()
    log.add("step", Msg("act.ok_deadband", "ok", meter=12), meter=12, cap=None)
    entry = log.snapshot()["entries"][0]
    assert entry["msg"]["key"] == "act.ok_deadband" and entry["msg"]["level"] == "ok"
    assert entry["ctx"] == {"meter": 12}  # None values are left out


def test_an_unknown_kind_is_rejected():
    with pytest.raises(ValueError):
        DebugLog().add("nonsense", Msg("dbg.meter", "info", w=1))


def test_a_meter_sample_is_logged_with_the_live_device_values(monkeypatch):
    monkeypatch.setattr(st.STATE, "latest", {"pvPow": 320.4, "invPow": 285, "batPow": -20, "soc": 20.0})
    _controller()._on_meter(212.6, time.time())
    entry = DEBUG.snapshot()["entries"][0]
    assert entry["kind"] == "meter" and entry["msg"]["params"] == {"w": 213}
    assert entry["ctx"] == {"meter": 213, "pv": 320, "inv": 285, "bat": -20, "soc": 20}


def test_a_step_that_writes_is_logged_once_with_what_it_worked_from(monkeypatch):
    now = time.time()
    monkeypatch.setattr(st.STATE, "latest", {"soc": 50, "pvPow": 420, "invPow": 100, "batPow": -50, "_power_t": now})
    c = _controller()
    asyncio.run(c.configure(enabled=True, dry_run=False, plan=False))
    DEBUG.clear()
    c.meter_w, c.meter_t = 400.0, now
    c._wrote, c._ctx = False, {}
    asyncio.run(c._step())
    c._log_step()
    entries = DEBUG.snapshot()["entries"]
    writes = [e for e in entries if e["kind"] == "write"]
    assert len(writes) == 1 and not [e for e in entries if e["kind"] == "step"]
    ctx = writes[0]["ctx"]
    assert ctx["meter"] == 400 and ctx["inv"] == 100 and ctx["error"] == 380 and ctx["w"] == c.setpoint


def test_a_step_that_does_not_write_logs_its_decision_and_the_cap_it_used(monkeypatch):
    now = time.time()
    monkeypatch.setattr(st.STATE, "latest", {"soc": 50, "pvPow": 300, "invPow": 100, "batPow": -50, "_power_t": now})
    st.STATE._pv_samples.extend([(now - 20, 300.0), (now - 5, 240.0)])
    c = _controller()
    asyncio.run(c.configure(enabled=True, dry_run=False, plan=True))
    DEBUG.clear()
    c.setpoint = 30  # below the cap of 40 W: nothing to pull down
    c._last_sync_t = now  # no read-back this round
    c.meter_w, c.meter_t = 20.0, now  # on target: inside the dead band
    c._wrote, c._ctx = False, {}
    asyncio.run(c._step())
    c._log_step()
    kinds = _kinds()
    assert kinds.count("step") == 1 and "write" not in kinds
    step = next(e for e in DEBUG.snapshot()["entries"] if e["kind"] == "step")
    assert step["msg"]["key"] == "act.ok_deadband"
    assert step["ctx"]["pvMin"] == 240 and step["ctx"]["cap"] == 240 - c.charge_reserve_w  # sized from the dip


def test_a_phase_change_is_logged_once():
    c = _controller()
    c.enabled = True
    c.phase = Msg("phase.day_full", trickle=5, soc=100)
    c._log_step()
    c._log_step()
    assert _kinds().count("phase") == 1
    c.phase = Msg("phase.day_charging", reserve=200, soc=90)
    c._log_step()
    assert _kinds().count("phase") == 2


def test_settings_changes_and_export_guard_are_logged():
    c = _controller()
    asyncio.run(c.configure(settings={"NIGHT_MAX_W": 180}, cover_load=True))
    config = next(e for e in DEBUG.snapshot()["entries"] if e["kind"] == "config")
    assert "NIGHT_MAX_W=180" in config["msg"]["params"]["what"] and "cover_load=True" in config["msg"]["params"]["what"]
    c._guard_against_export(-50.0, time.time())
    guard = next(e for e in DEBUG.snapshot()["entries"] if e["kind"] == "guard")
    assert guard["msg"]["key"] == "act.export_guard" and guard["ctx"]["meter"] == -50


def test_a_device_output_changed_elsewhere_is_logged_when_adopted():
    c = _controller()
    c.enabled, c.dry_run, c.setpoint = True, False, 150  # the fake client reports 100 W
    asyncio.run(c._resync_setpoint(time.time()))
    sync = next(e for e in DEBUG.snapshot()["entries"] if e["kind"] == "sync")
    assert sync["msg"]["params"] == {"actual": 100, "was": 150}


def test_the_failsafe_is_logged_when_the_meter_goes_missing():
    c = _controller()
    c.enabled, c.dry_run, c.setpoint = True, False, 100
    asyncio.run(c._failsafe())
    assert "failsafe" in _kinds()
