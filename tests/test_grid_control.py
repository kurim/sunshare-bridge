import asyncio
from unittest import mock

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
    c._guard_against_export(-50.0, 1000.0)
    assert c.charge_reserve_w == before + 50
    assert _controller().charge_reserve_w == before + 50  # a new instance reads control.json
    assert _controller()._reserve_base_w == before  # the baseline itself is untouched by an auto-raise


def test_export_guard_is_capped_and_a_no_op_without_export():
    c = _controller()
    c.charge_reserve_w = 1980
    c._guard_against_export(-500.0, 1000.0)
    assert c.charge_reserve_w == 2000  # PLAN_SETTINGS' own CHARGE_RESERVE_W ceiling

    unchanged = _controller()
    unchanged._guard_against_export(0.0, 1000.0)
    unchanged._guard_against_export(5.0, 1000.0)
    assert unchanged.charge_reserve_w == unchanged.settings()["CHARGE_RESERVE_W"]


def test_export_guard_relaxes_slowly_and_never_below_the_baseline():
    from app.grid_control import EXPORT_GUARD_DECAY_INTERVAL_S, EXPORT_GUARD_DECAY_STEP_W

    c = _controller()
    base = c.charge_reserve_w
    c._guard_against_export(-25.0, 1000.0)  # raise to base + 25
    assert c.charge_reserve_w == base + 25

    c._guard_against_export(5.0, 1000.0 + EXPORT_GUARD_DECAY_INTERVAL_S - 1)  # too soon
    assert c.charge_reserve_w == base + 25

    c._guard_against_export(5.0, 1000.0 + EXPORT_GUARD_DECAY_INTERVAL_S)  # cooldown elapsed
    assert c.charge_reserve_w == base + 25 - EXPORT_GUARD_DECAY_STEP_W

    # Repeated relaxing settles exactly at the baseline, never below it.
    t = 1000.0 + EXPORT_GUARD_DECAY_INTERVAL_S
    for _ in range(10):
        t += EXPORT_GUARD_DECAY_INTERVAL_S
        c._guard_against_export(5.0, t)
    assert c.charge_reserve_w == base


def test_manually_editing_the_reserve_resets_the_auto_raise_baseline(isolated_data):
    c = _controller()
    c._guard_against_export(-50.0, 1000.0)
    assert c.charge_reserve_w != c._reserve_base_w
    asyncio.run(c.configure(settings={"CHARGE_RESERVE_W": 300}))
    assert c.charge_reserve_w == 300 and c._reserve_base_w == 300


def test_control_min_interval_is_bounded_to_the_meter_delay_window():
    c = _controller()
    assert c.settings()["CONTROL_MIN_INTERVAL"] == 60  # default: low end of the 60-120s window
    with pytest.raises(ValueError):
        asyncio.run(c.configure(settings={"CONTROL_MIN_INTERVAL": 30}))  # faster than any real meter delay
    asyncio.run(c.configure(settings={"CONTROL_MIN_INTERVAL": 90}))
    assert c.min_interval_s == 90


def test_cover_load_defaults_off_and_persists(isolated_data):
    c = _controller()
    assert c.cover_load is False
    asyncio.run(c.configure(cover_load=True))
    assert c.cover_load is True
    assert _controller().cover_load is True  # a new instance reads control.json


def test_cover_load_covers_the_full_pv_without_export():
    """No export guard active (fresh reserve == the configured baseline): cover_load lets the whole
    PV through instead of always withholding CHARGE_RESERVE_W, unlike the default day_charging phase."""
    c = _controller()
    c.cover_load = True
    latest, now = _day(soc=50, pv=420)
    phase, cap = c._plan_cap(latest, now)
    assert (phase.key, phase.params, cap) == ("phase.day_cover_load", {"guard": 0, "soc": 50}, 420)


def test_cover_load_withholds_exactly_what_the_export_guard_has_claimed():
    c = _controller()
    c.cover_load = True
    c._guard_against_export(-50.0, 1000.0)  # export seen -> reserve raised by 50 W over the baseline
    latest, now = _day(soc=50, pv=420)
    phase, cap = c._plan_cap(latest, now)
    assert (phase.key, phase.params, cap) == ("phase.day_cover_load", {"guard": 50, "soc": 50}, 370)


def test_cover_load_does_not_change_the_night_or_battery_full_phases():
    c = _controller()
    c.cover_load = True
    latest, now = _night(soc=80)
    assert c._plan_cap(latest, now)[0].key == "phase.night_out"  # unaffected by cover_load
    latest, now = _day(soc=c.full_soc, pv=300)
    phase, cap = c._plan_cap(latest, now)
    assert (phase.key, cap) == ("phase.day_full", 300)


def test_adaptive_gain_off_by_default():
    c = _controller()
    assert c.adaptive_gain is False
    assert c.gain == c.gain_base == 0.7  # effective gain while off is the configured base
    assert c.learned_gain == c.gain_base  # nothing learned yet


def test_adaptive_gain_backs_off_after_a_sign_flip():
    c = _controller()
    c._prev_error = 100.0  # was importing too much, corrected...
    old = c.learned_gain
    c._adapt_gain(-40.0)  # ...and overshot into export: sign flipped
    assert c.learned_gain == pytest.approx(old * 0.85)


def test_adaptive_gain_eases_up_when_the_error_barely_moved():
    c = _controller()
    c._prev_error = 100.0
    old = c.learned_gain
    c._adapt_gain(95.0)  # same sign, barely smaller: still undershooting
    assert c.learned_gain == pytest.approx(old * 1.05)


def test_adaptive_gain_holds_steady_once_converging_well():
    c = _controller()
    c._prev_error = 100.0
    old = c.learned_gain
    c._adapt_gain(50.0)  # same sign, clearly shrunk: no reason to change
    assert c.learned_gain == old


def test_adaptive_gain_ignores_a_missing_or_tiny_previous_error():
    c = _controller()
    old = c.learned_gain
    c._adapt_gain(500.0)  # no _prev_error yet: nothing to grade
    assert c.learned_gain == old
    c._prev_error = 5.0  # within the deadband: already converged, nothing to grade
    c._adapt_gain(200.0)
    assert c.learned_gain == old


def test_adaptive_gain_is_bounded():
    from app.grid_control import GAIN_MAX, GAIN_MIN

    c = _controller()
    c.learned_gain = GAIN_MIN
    c._prev_error = 100.0
    c._adapt_gain(-40.0)  # would shrink further
    assert c.learned_gain == GAIN_MIN
    c.learned_gain = GAIN_MAX
    c._prev_error = 100.0
    c._adapt_gain(95.0)  # would grow further
    assert c.learned_gain == GAIN_MAX


def test_adaptive_gain_toggle_switches_the_effective_value_but_never_discards_the_learned_one(isolated_data):
    c = _controller()
    base = c.gain_base
    asyncio.run(c.configure(adaptive_gain=True))
    assert _controller().adaptive_gain is True  # a new instance reads control.json
    c.learned_gain = base * 1.2  # simulate some learning having happened, then persist it
    c._save()
    assert c.gain == pytest.approx(base * 1.2)  # effective gain follows the learned value while on
    assert _controller().learned_gain == pytest.approx(base * 1.2)

    asyncio.run(c.configure(adaptive_gain=False))
    assert c.gain == base  # off: the control loop falls back to the configured base...
    assert c.learned_gain == pytest.approx(base * 1.2)  # ...but the learned value is not discarded
    assert _controller().learned_gain == pytest.approx(base * 1.2)  # ...and survives a restart

    asyncio.run(c.configure(adaptive_gain=True))
    assert c.gain == pytest.approx(base * 1.2)  # re-enabling resumes from where it left off


def test_night_window_wraps_midnight():
    start, end = _parse_hm("23:00"), _parse_hm("06:00")
    assert _in_window(_parse_hm("23:30"), start, end)
    assert _in_window(_parse_hm("02:00"), start, end)
    assert not _in_window(_parse_hm("12:00"), start, end)
    assert not _in_window(_parse_hm("06:00"), start, end)  # end is exclusive


def test_no_meter_configured_is_fine():
    c = _controller()
    assert c.config_topic == "" and c.state_topic is None


def test_run_stays_idle_without_a_configured_broker():
    """MQTT_HOST unset (dashboard-only use, see .env.example): run() must not try to build an MQTT
    client at all - no host to connect to."""
    c = GridController(None, None, 1883, None, None)
    with pytest.raises(asyncio.TimeoutError):
        asyncio.run(asyncio.wait_for(c.run(), timeout=0.05))
    assert c._mqtt is None


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


def _day(soc, pv):
    latest = {"soc": soc, "pvPow": pv}
    return latest, time.mktime((2026, 1, 5, 12, 0, 0, 0, 0, -1))  # 12:00, outside 23:00-06:00


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


def test_failsafe_clamps_the_fallback_to_the_night_soc_floor(monkeypatch):
    client = FakeClient(guest=True)
    c = _ctl(client)
    asyncio.run(c.configure(enabled=True, dry_run=False, settings={"CONTROL_FALLBACK_W": 500}))
    assert _controller().fallback_w == 500  # persisted like any other plan setting
    latest, now = _night(soc=10)  # below the default NIGHT_MIN_SOC floor -> night cap is 0
    monkeypatch.setattr(st.STATE, "latest", latest)
    with mock.patch("time.time", return_value=now):
        asyncio.run(c._failsafe())
    assert c.setpoint == 0 and c.last_action.key == "act.set" and c.last_action.params["w"] == 0


def test_failsafe_clamps_the_fallback_to_the_night_ceiling(monkeypatch):
    client = FakeClient(guest=True)
    c = _ctl(client)
    asyncio.run(c.configure(enabled=True, dry_run=False, settings={"CONTROL_FALLBACK_W": 500}))
    latest, now = _night(soc=80)  # well above the floor -> night cap is night_max_w (150 default)
    monkeypatch.setattr(st.STATE, "latest", latest)
    with mock.patch("time.time", return_value=now):
        asyncio.run(c._failsafe())
    assert c.setpoint == 150


def test_failsafe_clamps_the_fallback_to_the_day_charging_cap(monkeypatch):
    """Regression: a stale meter with no PV (e.g. dusk, before the night window starts) used to still
    apply the full configured fallback - with no PV to cover it, that came entirely out of the battery
    during what's supposed to be the day's charging-reserve lockout. The day cap (PV minus charge
    reserve) now applies to the failsafe fallback exactly like it does to the closed loop."""
    client = FakeClient(guest=True)
    c = _ctl(client)
    asyncio.run(c.configure(enabled=True, dry_run=False, settings={"CONTROL_FALLBACK_W": 200, "CHARGE_RESERVE_W": 300}))
    latest, now = _day(soc=50, pv=420)  # day_charging cap = max(420-300, 0) = 120
    monkeypatch.setattr(st.STATE, "latest", latest)
    with mock.patch("time.time", return_value=now):
        asyncio.run(c._failsafe())
    assert c.setpoint == 120


def test_failsafe_never_drains_the_battery_with_no_pv_during_the_day(monkeypatch):
    client = FakeClient(guest=True)
    c = _ctl(client)
    asyncio.run(c.configure(enabled=True, dry_run=False, settings={"CONTROL_FALLBACK_W": 200}))
    latest, now = _day(soc=89, pv=0)  # dusk: still before the night window, no PV to cover any output
    monkeypatch.setattr(st.STATE, "latest", latest)
    with mock.patch("time.time", return_value=now):
        asyncio.run(c._failsafe())
    assert c.setpoint == 0


def test_failsafe_defaults_to_0_when_the_plan_is_on_but_soc_and_pv_are_unknown(monkeypatch):
    client = FakeClient(guest=True)
    c = _ctl(client)
    asyncio.run(c.configure(enabled=True, dry_run=False, settings={"CONTROL_FALLBACK_W": 200}))
    monkeypatch.setattr(st.STATE, "latest", {})
    asyncio.run(c._failsafe())
    assert c.setpoint == 0


def test_failsafe_uses_the_fallback_as_is_when_it_is_within_the_night_cap(monkeypatch):
    client = FakeClient(guest=True)
    c = _ctl(client)
    asyncio.run(c.configure(enabled=True, dry_run=False, settings={"CONTROL_FALLBACK_W": 50}))
    latest, now = _night(soc=80)  # well above the floor -> night cap is night_max_w (150 default)
    monkeypatch.setattr(st.STATE, "latest", latest)
    with mock.patch("time.time", return_value=now):
        asyncio.run(c._failsafe())
    assert c.setpoint == 50


def test_failsafe_ignores_the_plan_cap_when_the_plan_is_disabled(monkeypatch):
    client = FakeClient(guest=True)
    c = _ctl(client)
    asyncio.run(c.configure(enabled=True, dry_run=False, plan=False, settings={"CONTROL_FALLBACK_W": 500}))
    latest, now = _night(soc=10)
    monkeypatch.setattr(st.STATE, "latest", latest)
    with mock.patch("time.time", return_value=now):
        asyncio.run(c._failsafe())
    assert c.setpoint == 500


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
