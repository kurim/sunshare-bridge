import asyncio

import pytest

import app.state as st
from app.grid_control import GridController, _in_window, _parse_hm
from app.messages import Msg, MsgError


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


def test_meter_max_age_is_settable_and_kept_in_sync_with_state(isolated_data):
    c = _controller()
    assert c.meter_max_age_s == 180 and st.STATE.meter_max_age_s == 180
    asyncio.run(c.configure(settings={"CONTROL_METER_MAX_AGE": 30}))
    assert c.meter_max_age_s == 30 and st.STATE.meter_max_age_s == 30
    assert _controller().meter_max_age_s == 30  # a new instance reads control.json


def test_export_raises_the_charge_reserve_and_persists_it(isolated_data):
    c = _controller()
    before = c.charge_reserve_w
    c._guard_against_export(-50.0)
    assert c.charge_reserve_w == before + 50
    assert _controller().charge_reserve_w == before + 50  # a new instance reads control.json


def test_export_guard_is_capped_and_a_no_op_without_export():
    c = _controller()
    c.charge_reserve_w = 1980
    c._guard_against_export(-500.0)
    assert c.charge_reserve_w == 2000  # PLAN_SETTINGS' own CHARGE_RESERVE_W ceiling

    unchanged = _controller()
    unchanged._guard_against_export(0.0)
    unchanged._guard_against_export(5.0)
    assert unchanged.charge_reserve_w == unchanged.settings()["CHARGE_RESERVE_W"]


def test_night_window_wraps_midnight():
    start, end = _parse_hm("23:00"), _parse_hm("06:00")
    assert _in_window(_parse_hm("23:30"), start, end)
    assert _in_window(_parse_hm("02:00"), start, end)
    assert not _in_window(_parse_hm("12:00"), start, end)
    assert not _in_window(_parse_hm("06:00"), start, end)  # end is exclusive


def test_no_meter_configured_is_fine():
    c = _controller()
    assert c.config_topic == "" and c.state_topic is None


# ---- main account (device-side limits) vs. guest account (bridge logic) ----------------

import time

from app import sunshare_cloud
from app.sunshare_cloud import SunshareCloudClient, guest_from_env


class FakeClient:
    """Stands in for SunshareCloudClient; records device-limit writes."""

    def __init__(self, guest, soc_min=20, country_max=800):
        self.guest = guest
        self.adv = {"socMin": soc_min, "socMax": 100, "countryMaxPower": country_max}
        self.writes = []
        self.ok = True

    async def read_ems_settings(self):
        return {"mesSettingUpdatePojo": {"permPower": 100, "emsStrategyType": 1}, "emsModeAdvan": dict(self.adv)}

    async def set_device_limits(self, soc_min=None, soc_max=None, country_max_power=None):
        self.writes.append({"soc_min": soc_min, "soc_max": soc_max, "country_max_power": country_max_power})
        if self.ok:
            for key, value in (("socMin", soc_min), ("socMax", soc_max), ("countryMaxPower", country_max_power)):
                if value is not None:
                    self.adv[key] = value
        return self.ok

    async def set_output_power(self, watts, ems_strategy_type=1):
        return True


def _ctl(client):
    return GridController(client, "broker", 1883, None, None)


def _night(soc):
    latest = {"soc": soc, "pvPow": 0}
    return latest, time.mktime((2026, 1, 5, 2, 0, 0, 0, 0, -1))  # 02:00, inside 23:00-06:00


@pytest.mark.parametrize("raw, expected", [
    (None, True), ("", True), ("TRUE", True), ("true", True), ("1", True),
    ("FALSE", False), ("false", False), (" False ", False), ("0", False),
])
def test_guest_flag_parsing_defaults_to_the_safe_guest_mode(raw, expected):
    assert guest_from_env(raw) is expected


def test_guest_keeps_night_min_soc_in_the_bridge_and_never_writes_the_device():
    client = FakeClient(guest=True)
    c = _ctl(client)
    asyncio.run(c.configure(enabled=True, dry_run=False, settings={"NIGHT_MIN_SOC": 15}))
    assert client.writes == []
    assert c.status()["account"] == "guest" and c.status()["min_soc_source"] == "bridge"
    latest, now = _night(soc=14)
    assert c._plan_cap(latest, now)[1] == 0  # bridge cuts the output


def test_main_account_dry_run_does_not_write_and_keeps_the_bridge_fallback():
    client = FakeClient(guest=False, soc_min=20)
    c = _ctl(client)
    asyncio.run(c.configure(settings={"NIGHT_MIN_SOC": 15}))  # still disabled + dry-run
    assert client.writes == []
    assert c.device_note.key == "dev.would_write" and c.device_note.level == "warn"
    latest, now = _night(soc=14)
    assert c._plan_cap(latest, now)[1] == 0  # device not synced yet -> bridge still protects


def test_main_account_writes_socmin_and_hands_enforcement_to_the_device():
    client = FakeClient(guest=False, soc_min=20)
    c = _ctl(client)
    asyncio.run(c.configure(enabled=True, dry_run=False, settings={"NIGHT_MIN_SOC": 15}))
    assert client.writes == [{"soc_min": 15, "soc_max": None, "country_max_power": None}]
    assert c.status()["min_soc_source"] == "device" and c.device_limits["soc_min"] == 15
    latest, now = _night(soc=14)
    assert c._plan_cap(latest, now)[1] == c.night_max_w  # no bridge cut, the device stops at 15 %
    asyncio.run(c.sync_device_limits())
    assert len(client.writes) == 1  # already in sync: nothing written again


def test_main_account_above_device_range_writes_the_maximum_and_keeps_the_bridge_cut():
    client = FakeClient(guest=False, soc_min=10)
    c = _ctl(client)
    asyncio.run(c.configure(enabled=True, dry_run=False, settings={"NIGHT_MIN_SOC": 25}))
    assert client.writes == [{"soc_min": 20, "soc_max": None, "country_max_power": None}]
    assert c.status()["min_soc_source"] == "bridge"
    latest, now = _night(soc=24)
    assert c._plan_cap(latest, now)[1] == 0


def test_failed_device_write_falls_back_to_the_bridge_logic():
    client = FakeClient(guest=False, soc_min=20)
    client.ok = False
    c = _ctl(client)
    asyncio.run(c.configure(enabled=True, dry_run=False, settings={"NIGHT_MIN_SOC": 15}))
    assert c.device_note.key == "dev.soc_failed" and c.device_note.level == "error"
    assert c.status()["min_soc_source"] == "bridge"


def test_country_max_power_is_main_account_only():
    guest = _ctl(FakeClient(guest=True))
    with pytest.raises(MsgError) as guest_err:
        asyncio.run(guest.configure(enabled=True, dry_run=False, device={"COUNTRY_MAX_POWER": 600}))

    client = FakeClient(guest=False)
    main = _ctl(client)
    with pytest.raises(MsgError) as dry_err:  # dry-run is still on
        asyncio.run(main.configure(device={"COUNTRY_MAX_POWER": 600}))
    assert client.writes == [] and main.enabled is False  # nothing changed
    assert guest_err.value.msg.key == "err.country_main_only" and dry_err.value.msg.key == "err.country_needs_live"

    asyncio.run(main.configure(enabled=True, dry_run=False, device={"COUNTRY_MAX_POWER": 600}))
    assert {"soc_min": None, "soc_max": None, "country_max_power": 600} in client.writes
    assert main.device_limits["country_max_power"] == 600


@pytest.mark.parametrize("bad", [{"COUNTRY_MAX_POWER": 5000}, {"COUNTRY_MAX_POWER": True}, {"SOC_MIN": 10}])
def test_invalid_device_values_are_rejected(bad):
    with pytest.raises(ValueError):
        asyncio.run(_ctl(FakeClient(guest=False)).configure(enabled=True, dry_run=False, device=bad))


def test_set_device_limits_sends_the_whole_object_in_emsadvanstagepojo():
    """Body shape found by disassembling the app: wrapper key emsAdvanStagePojo, complete
    object with only the requested field replaced."""
    sent = {}

    class Resp:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def json(self, content_type=None):
            return {"code": 200, "msg": None, "data": True}

    client = SunshareCloudClient(None, "u", "p", 4711, "SN", guest=False)

    async def read_ems_settings():
        return {"emsModeAdvan": {"adVanSetType": 1, "socMin": 20, "socMax": 100, "countryMaxPower": 800,
                                 "zeroNetworkButton": 0, "deviceId": 4711, "isOnlySave": 0}}

    async def post(path, body, extra_headers=None):
        sent.update(path=path, body=body)
        return Resp()

    client.read_ems_settings, client._post = read_ems_settings, post
    assert asyncio.run(client.set_device_limits(soc_min=15)) is True
    assert sent["path"] == "app/sysDeviceInfo/updateEmsModeAdvanById"
    assert sent["body"] == {"emsAdvanStagePojo": {
        "adVanSetType": 1, "socMin": 15, "socMax": 100, "countryMaxPower": 800,
        "zeroNetworkButton": 0, "deviceId": 4711, "isOnlySave": 0}}
    assert sunshare_cloud.DEVICE_SOC_MIN_MAX == 20


# ---- translatable messages -------------------------------------------------------------

def test_status_reports_messages_as_key_level_and_params(isolated_data):
    c = _ctl(FakeClient(guest=True))
    status = c.status()
    assert status["phase"] is None and status["last_action"] is None and status["device_note"] is None
    asyncio.run(c.configure(settings={"NIGHT_MAX_W": 180}))
    assert c.status()["last_action"] == {"key": "act.params_updated", "level": "ok", "params": {}}
    asyncio.run(c.sync_device_limits())
    assert c.status()["device_note"] == {"key": "dev.guest", "level": "info", "params": {}}


def test_dry_run_message_nests_its_reason_and_reads_well_in_logs():
    c = _ctl(FakeClient(guest=True))  # dry run is the default
    asyncio.run(c._apply(140, Msg("why.control", meter=35, inv=150, cap=800)))
    d = c.last_action.to_dict()
    assert d["key"] == "act.dry_run" and d["level"] == "warn" and d["params"]["w"] == 140
    assert d["params"]["why"] == {"key": "why.control", "level": "info", "params": {"meter": 35, "inv": 150, "cap": 800}}
    assert str(c.last_action) == "DRY RUN: would set 140 W (meter 35 W, inverter 150 W, limit 800 W)"


def test_plan_phase_is_a_message():
    import time
    c = _ctl(FakeClient(guest=True))
    night = time.mktime((2026, 1, 5, 2, 0, 0, 0, 0, -1))
    phase, cap = c._plan_cap({"soc": 15.0, "pvPow": 0}, night)
    assert (phase.key, phase.params, cap) == ("phase.night_min", {"soc": 15, "min": 25}, 0)


def test_rejected_settings_carry_key_and_params():
    c = _ctl(None)
    with pytest.raises(MsgError) as err:
        asyncio.run(c.configure(settings={"NIGHT_MAX_W": 99999}))
    assert err.value.msg.key == "err.range" and err.value.msg.params["key"] == "NIGHT_MAX_W"
    assert "NIGHT_MAX_W" in str(err.value)  # the plain (English) text for logs and curl
