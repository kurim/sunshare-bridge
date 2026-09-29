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
    assert _controller().night_max_w == 180  # a new instance reads settings.db


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
    assert _controller().meter_max_age_s == 30  # a new instance reads settings.db


def test_export_raises_the_charge_reserve_and_persists_it(isolated_data):
    c = _controller()
    before = c.charge_reserve_w
    c._guard_against_export(-50.0, 1000.0)
    assert c.charge_reserve_w == before + 50
    assert _controller().charge_reserve_w == before + 50  # a new instance reads settings.db
    assert _controller()._reserve_base_w == before  # the baseline itself is untouched by an auto-raise


def test_settings_report_the_baseline_not_a_live_export_guard_raise(isolated_data):
    """Regression: settings() used to report the live (possibly export-guard-raised) charge reserve -
    so the settings form pre-filled with e.g. 424 instead of the user's own configured 210, and since
    it submits every field together, saving any unrelated change would silently resubmit that transient
    raise as the new permanent baseline (see grid_control.py's settings() docstring)."""
    c = _controller()
    asyncio.run(c.configure(settings={"CHARGE_RESERVE_W": 210}))
    c._guard_against_export(-400.0, 1000.0)  # export seen -> live reserve raised well above 210
    assert c.charge_reserve_w == 610 and c._reserve_base_w == 210
    assert c.settings()["CHARGE_RESERVE_W"] == 210  # the form must show the baseline, not 610


def test_export_guard_is_capped_and_a_no_op_without_export(tmp_path, monkeypatch):
    c = _controller()
    c.charge_reserve_w = 1980
    c._guard_against_export(-500.0, 1000.0)
    assert c.charge_reserve_w == 2000  # PLAN_SETTINGS' own CHARGE_RESERVE_W ceiling

    # A settings.db of its own - `c`'s raise above just persisted to the shared isolated_data
    # path, and this instance must start genuinely fresh, not inherit it.
    import app.settings_db as sdb
    monkeypatch.setattr(sdb, "SETTINGS_FILE", tmp_path / "other-settings.db")
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
    assert _controller().cover_load is True  # a new instance reads settings.db


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
    assert (phase.key, cap) == ("phase.day_full", 300 - c.trickle_w)


def test_day_full_withholds_the_trickle_charge_from_output():
    """Once "full" (>= CHARGE_FULL_SOC), output used to track PV exactly - so as PV faded toward
    dusk, 100 % of even a tiny remaining trickle went to the AC output instead of the battery,
    which could then slowly drain from the device's own standby draw. CHARGE_TRICKLE_W (default
    5 W) is now always withheld here too, on top of the plain PV pass-through."""
    c = _controller()
    assert c.trickle_w == 5  # documented default
    latest, now = _day(soc=c.full_soc, pv=95)
    phase, cap = c._plan_cap(latest, now)
    assert (phase.key, phase.params, cap) == ("phase.day_full", {"trickle": 5, "soc": c.full_soc}, 90)


def test_day_full_trickle_never_pushes_the_cap_negative():
    """Below the trickle amount, all of the (already tiny) PV should go to the battery - the cap
    must clamp at 0, not go negative."""
    c = _controller()
    latest, now = _day(soc=c.full_soc, pv=2)
    assert c._plan_cap(latest, now)[1] == 0


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
    assert _controller().adaptive_gain is True  # a new instance reads settings.db
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


class RecordingClient(FakeClient):
    """Remembers every output written, and reports the device's setpoint like the real one would: the
    last thing written - unless `device_output` says somebody else (the app) changed it."""

    def __init__(self, guest=True):
        super().__init__(guest)
        self.outputs = []
        self.reads = 0
        self.device_output = None

    async def read_ems_settings(self):
        self.reads += 1
        shown = self.device_output if self.device_output is not None else (self.outputs[-1] if self.outputs else 100)
        return {"mesSettingUpdatePojo": {"permPower": shown, "emsStrategyType": 1}, "emsModeAdvan": dict(self.adv)}

    async def set_output_power(self, watts, ems_strategy_type=1):
        self.outputs.append(watts)
        self.device_output = None
        return self.ok


def test_failsafe_follows_the_plan_from_the_evening_into_the_night(monkeypatch):
    """Regression: the failsafe ran once per outage. A meter that dropped out at dusk (day phase, no
    PV -> cap 0) left the output at 0 W for the whole night, although the night window would have
    allowed CONTROL_FALLBACK_W (up to NIGHT_MAX_W) - it must be re-evaluated while the meter is away."""
    client = RecordingClient()
    c = _ctl(client)
    asyncio.run(c.configure(enabled=True, dry_run=False, settings={"CONTROL_FALLBACK_W": 210, "NIGHT_MAX_W": 200}))
    latest, dusk = _day(soc=40, pv=0)
    monkeypatch.setattr(st.STATE, "latest", latest)
    with mock.patch("time.time", return_value=dusk):
        asyncio.run(c._failsafe())
    assert client.outputs == [0]

    _, night = _night(soc=40)
    night += 24 * 3600  # 02:00 of the following day
    with mock.patch("time.time", return_value=night):
        asyncio.run(c._failsafe())
    assert client.outputs == [0, 200] and c.setpoint == 200  # min(fallback 210, NIGHT_MAX_W 200)


def test_failsafe_only_writes_when_the_target_changes(monkeypatch):
    client = RecordingClient()
    c = _ctl(client)
    asyncio.run(c.configure(enabled=True, dry_run=False, settings={"CONTROL_FALLBACK_W": 100}))
    latest, now = _night(soc=80)
    monkeypatch.setattr(st.STATE, "latest", latest)
    for step in range(3):
        with mock.patch("time.time", return_value=now + step * 600):
            asyncio.run(c._failsafe())
    assert client.outputs == [100]  # later rounds found nothing new to send


def test_failsafe_retries_a_failed_write_on_the_next_round(monkeypatch):
    client = RecordingClient()
    client.ok = False
    c = _ctl(client)
    asyncio.run(c.configure(enabled=True, dry_run=False, settings={"CONTROL_FALLBACK_W": 100}))
    latest, now = _night(soc=80)
    monkeypatch.setattr(st.STATE, "latest", latest)
    with mock.patch("time.time", return_value=now):
        asyncio.run(c._failsafe())
    assert c.last_action.key == "act.set_failed"
    client.ok = True
    with mock.patch("time.time", return_value=now + 600):
        asyncio.run(c._failsafe())
    assert client.outputs == [100, 100] and c.last_action.key == "act.set"


def test_failsafe_recheck_respects_the_write_rate_limit(monkeypatch):
    """A very short CONTROL_METER_MAX_AGE re-runs the failsafe every few seconds - repeat rounds must
    not write faster than CONTROL_MIN_INTERVAL even when PV keeps moving the day cap."""
    client = RecordingClient()
    c = _ctl(client)
    asyncio.run(c.configure(enabled=True, dry_run=False, settings={"CONTROL_FALLBACK_W": 500}))
    latest, now = _day(soc=50, pv=420)
    monkeypatch.setattr(st.STATE, "latest", latest)
    with mock.patch("time.time", return_value=now):
        asyncio.run(c._failsafe())
    first = list(client.outputs)
    monkeypatch.setattr(st.STATE, "latest", {"soc": 50, "pvPow": 480})
    with mock.patch("time.time", return_value=now + 10):  # inside min_interval_s (60 s default)
        asyncio.run(c._failsafe())
    assert client.outputs == first
    with mock.patch("time.time", return_value=now + 70):
        asyncio.run(c._failsafe())
    assert len(client.outputs) == len(first) + 1


def test_failsafe_ignores_the_plan_cap_when_the_plan_is_disabled(monkeypatch):
    client = FakeClient(guest=True)
    c = _ctl(client)
    asyncio.run(c.configure(enabled=True, dry_run=False, plan=False, settings={"CONTROL_FALLBACK_W": 500}))
    latest, now = _night(soc=10)
    monkeypatch.setattr(st.STATE, "latest", latest)
    with mock.patch("time.time", return_value=now):
        asyncio.run(c._failsafe())
    assert c.setpoint == 500


# ---- closed loop step: the write-rate limit must not hide an already-converged state ----

def test_step_reports_deadband_even_right_after_a_write_instead_of_the_rate_limit(monkeypatch):
    """Regression: the write-rate limit used to be checked before the deadband, so an already-
    converged controller reported "skipped: minimum interval" (a warning) almost permanently -
    nothing was ever going to be written anyway, rate limit or not."""
    client = FakeClient(guest=True)
    c = _ctl(client)
    asyncio.run(c.configure(enabled=True, dry_run=False, plan=False))
    c.meter_w = c.target_w  # error == 0: squarely inside the deadband
    c._last_write_t = time.time()  # a write "just happened" - well inside min_interval_s
    monkeypatch.setattr(st.STATE, "latest", {"invPow": 100, "_power_t": time.time()})
    asyncio.run(c._step())
    assert c.last_action.key == "act.ok_deadband"


def test_step_pulls_an_over_cap_setpoint_down_at_once_despite_the_rate_limit(monkeypatch):
    """The plan cap can drop sharply (PV falls, battery just reached full) - per the code's own
    intent ("pull down at once"), that correction must not wait out the write-rate limit."""
    client = FakeClient(guest=True)
    c = _ctl(client)
    asyncio.run(c.configure(enabled=True, dry_run=False))  # plan stays on; setpoint fetched as 100
    c.meter_w = c.target_w  # error == 0: only the cap, not the meter error, should drive this
    _, noon = _day(soc=96, pv=20)  # a fixed daytime: the real clock may sit inside the night window
    c._last_write_t = noon  # inside min_interval_s
    # soc >= CHARGE_FULL_SOC (95 by default) -> phase.day_full, cap = pv - trickle (20 - 5 = 15), well
    # below setpoint (100)
    monkeypatch.setattr(st.STATE, "latest", {"soc": 96, "pvPow": 20, "invPow": 90, "_power_t": noon})
    with mock.patch("time.time", return_value=noon):
        asyncio.run(c._step())
    assert c.setpoint == 15 and c.last_action.key == "act.set"


# ---- an output changed outside the bridge (the official app) ----------------------------

def _live_step_controller(client, monkeypatch, now):
    c = _ctl(client)
    asyncio.run(c.configure(enabled=True, dry_run=False, plan=False))  # setpoint 100 read from the device
    c.meter_w = c.target_w  # inside the deadband: _step itself writes nothing
    monkeypatch.setattr(st.STATE, "latest", {"invPow": 100, "_power_t": now})
    return c


def test_step_adopts_an_output_changed_outside_the_bridge(monkeypatch):
    """The loop only knew what it wrote itself: a value set in the app went unnoticed, and computing the
    same target again read as "unchanged", leaving the device on the app's value."""
    client = RecordingClient()
    now = time.time()
    c = _live_step_controller(client, monkeypatch, now)
    client.device_output = 210
    asyncio.run(c._step())
    assert c.setpoint == 210 and client.reads == 2  # once when enabling, once for the read-back


def test_readback_leaves_a_matching_device_value_alone_and_is_rate_limited(monkeypatch):
    client = RecordingClient()
    now = time.time()
    c = _live_step_controller(client, monkeypatch, now)
    reads_before = client.reads
    with mock.patch("time.time", return_value=now):
        asyncio.run(c._step())
        asyncio.run(c._step())
    assert client.reads == reads_before + 1 and c.setpoint == 100  # second call is inside the interval
    with mock.patch("time.time", return_value=now + 301):
        monkeypatch.setattr(st.STATE, "latest", {"invPow": 100, "_power_t": now + 301})
        asyncio.run(c._step())
    assert client.reads == reads_before + 2


def test_readback_waits_while_our_own_write_may_still_be_taking_effect(monkeypatch):
    client = RecordingClient()
    now = time.time()
    c = _live_step_controller(client, monkeypatch, now)
    reads_before = client.reads
    c._last_write_t = now - 10  # just wrote: the device may still show the old value
    client.device_output = 999
    asyncio.run(c._step())
    assert client.reads == reads_before and c.setpoint == 100


def test_readback_is_skipped_in_dry_run():
    client = RecordingClient()
    c = _ctl(client)  # dry run is the default: nothing is ever written, nothing to keep in step
    c.setpoint = 100
    asyncio.run(c._resync_setpoint(time.time()))
    assert client.reads == 0


def test_failsafe_reasserts_its_target_after_an_outside_change(monkeypatch):
    client = RecordingClient()
    c = _ctl(client)
    asyncio.run(c.configure(enabled=True, dry_run=False, settings={"CONTROL_FALLBACK_W": 100}))
    latest, now = _night(soc=80)
    monkeypatch.setattr(st.STATE, "latest", latest)
    with mock.patch("time.time", return_value=now):
        asyncio.run(c._failsafe())
    assert client.outputs == [100]
    client.device_output = 210  # changed in the app while the meter is away
    with mock.patch("time.time", return_value=now + 600):
        asyncio.run(c._failsafe())
    assert client.outputs == [100, 100]  # unchanged target, but the device no longer had it


# ---- "inverter at its limit" must not hold forever (issue #26) -----------------------------

def _stuck_controller(client, monkeypatch, now):
    """The issue's rebuild: plan off, deadband 10, setpoint 16 W, the device delivers 0 W, the grid 112 W."""
    monkeypatch.setenv("CONTROL_DEADBAND_W", "10")
    c = _ctl(client)
    asyncio.run(c.configure(enabled=True, dry_run=False, plan=False))
    c.setpoint = 16
    client.device_output = 16
    c.meter_w = 112.0
    return c


def _step_at(c, monkeypatch, t, inv=0, **supply):
    monkeypatch.setattr(st.STATE, "latest", {"invPow": inv, "_power_t": t, **supply})
    with mock.patch("time.time", return_value=t):
        asyncio.run(c._step())


def test_a_supposed_limit_is_retested_instead_of_holding_forever(monkeypatch):
    """Regression (issue #26): "inverter delivers less than commanded" was trusted for good - if the
    device delivered nothing for another reason, the loop never wrote again while the house drew from
    the grid for hours (only toggling the dry-run, which re-sends the old value, got it out)."""
    from app.grid_control import LIMIT_RECHECK_S

    client = RecordingClient()
    t0 = 1_000_000.0
    c = _stuck_controller(client, monkeypatch, t0)
    _step_at(c, monkeypatch, t0)
    assert c.last_action.key == "act.ok_limit" and client.outputs == []
    _step_at(c, monkeypatch, t0 + LIMIT_RECHECK_S - 10)
    assert c.last_action.key == "act.ok_limit" and client.outputs == []  # still trusted inside the window

    _step_at(c, monkeypatch, t0 + LIMIT_RECHECK_S)
    assert client.outputs == [64] and c.setpoint == 64  # 0 W delivered + 0.7 * (112 - 20 W target)

    _step_at(c, monkeypatch, t0 + LIMIT_RECHECK_S + 30)  # the wait starts over after the re-send
    assert c.last_action.key == "act.ok_limit" and client.outputs == [64]
    _step_at(c, monkeypatch, t0 + 2 * LIMIT_RECHECK_S)
    assert client.outputs == [64, 64]  # same value, but re-sent: the device may need it written anew


def test_a_retest_does_not_train_the_adaptive_gain(monkeypatch):
    from app.grid_control import LIMIT_RECHECK_S

    client = RecordingClient()
    t0 = 1_000_000.0
    c = _stuck_controller(client, monkeypatch, t0)
    c.adaptive_gain = True
    gain = c.learned_gain
    for k in range(4):
        _step_at(c, monkeypatch, t0 + k * LIMIT_RECHECK_S)
    assert len(client.outputs) >= 2 and c.learned_gain == gain  # a re-send is no correction to grade


def test_a_real_limit_that_ends_resets_the_wait(monkeypatch):
    from app.grid_control import LIMIT_RECHECK_S

    client = RecordingClient()
    t0 = 1_000_000.0
    c = _stuck_controller(client, monkeypatch, t0)
    _step_at(c, monkeypatch, t0)
    assert c._limit_since == t0
    _step_at(c, monkeypatch, t0 + LIMIT_RECHECK_S - 10, inv=16)  # the inverter delivers again
    assert c._limit_since is None


def test_an_unexplained_shortfall_is_retested_after_a_short_grace_only(monkeypatch):
    """Battery well above its discharge stop and not charging, yet the inverter delivers 0 W of a
    16 W setpoint while the grid supplies the house: the supply can't be the reason (issue #26)."""
    from app.grid_control import LIMIT_UNEXPLAINED_S

    client = RecordingClient()
    t0 = 1_000_000.0
    c = _stuck_controller(client, monkeypatch, t0)
    full_but_silent = {"soc": 98, "pvPow": 0, "batPow": 0}
    _step_at(c, monkeypatch, t0, **full_but_silent)
    assert c.last_action.key == "act.wait_output" and c.last_action.level == "warn"
    assert c.last_action.params == {"inv": 0, "w": 16}
    _step_at(c, monkeypatch, t0 + LIMIT_UNEXPLAINED_S - 10, **full_but_silent)
    assert client.outputs == []
    _step_at(c, monkeypatch, t0 + LIMIT_UNEXPLAINED_S, **full_but_silent)
    assert client.outputs == [64]


def test_a_shortfall_while_the_battery_charges_still_counts_as_a_limit(monkeypatch):
    from app.grid_control import LIMIT_UNEXPLAINED_S

    client = RecordingClient()
    t0 = 1_000_000.0
    c = _stuck_controller(client, monkeypatch, t0)
    charging = {"soc": 40, "pvPow": 300, "batPow": -280}  # the device serves the battery first
    _step_at(c, monkeypatch, t0, **charging)
    _step_at(c, monkeypatch, t0 + LIMIT_UNEXPLAINED_S + 30, **charging)
    assert c.last_action.key == "act.ok_limit" and client.outputs == []


@pytest.mark.parametrize("supply, plausible", [
    ({"soc": 98, "pvPow": 0, "batPow": 0}, False),      # battery could supply it
    ({"soc": 50, "pvPow": 0, "batPow": 5}, False),      # discharging a little, plenty left
    ({"soc": 22, "pvPow": 500, "batPow": 0}, False),    # battery at its stop, but PV alone covers it
    ({"soc": 21, "pvPow": 0, "batPow": 0}, True),       # at the device's discharge stop (20 %) + margin, no PV
    ({"soc": 40, "pvPow": 300, "batPow": -280}, True),  # charging first
    ({"soc": None, "pvPow": 0, "batPow": 0}, True),     # unknown -> keep the old trust
])
def test_limit_plausibility(supply, plausible):
    c = _controller()
    c.setpoint = 100
    assert c._limit_plausible(supply) is plausible


def test_the_setpoint_reaches_the_shared_state_only_while_steering(monkeypatch):
    """History and charts show the commanded output - not a stale value of a disabled/dry-run controller."""
    client = RecordingClient()
    c = _ctl(client)
    assert st.STATE.setpoint_w is None
    asyncio.run(c.configure(enabled=True, dry_run=True))  # setpoint is read (100) but nothing is steered
    assert c.setpoint == 100 and st.STATE.setpoint_w is None
    asyncio.run(c.configure(dry_run=False))
    assert st.STATE.setpoint_w == 100
    asyncio.run(c._apply(64, Msg("why.control", meter=0, inv=0, cap=800)))
    assert st.STATE.setpoint_w == 64
    asyncio.run(c.configure(enabled=False))
    assert st.STATE.setpoint_w is None


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


# --- day cap sized from the lowest recent PV -------------------------------------------------

def _pv_seen(now, *values_ago):
    """PV samples as the state would have recorded them: (seconds ago, watts)."""
    for ago, w in values_ago:
        st.STATE._pv_samples.append((now - ago, float(w)))


def test_the_day_cap_follows_the_lowest_recent_pv():
    c = _controller()
    latest, now = _day(soc=50, pv=320)
    _pv_seen(now, (50, 330), (15, 240), (5, 300))  # a dip to 240 W within the last 20 s
    _, cap = c._plan_cap(latest, now)
    assert cap == 240 - c.charge_reserve_w  # sized from the dip, not from the 320 W right now


def test_a_rising_pv_is_followed_within_seconds_not_a_write_interval_later():
    """The old look-back (a whole write interval) trailed a ramp by up to a minute, and the difference went
    into the battery even though the house was drawing from the grid."""
    c = _controller()
    latest, now = _day(soc=50, pv=400)
    _pv_seen(now, (55, 160), (40, 200), (25, 260), (12, 380))
    assert c._plan_cap(latest, now)[1] == 380 - c.charge_reserve_w  # not 160 - reserve


def test_a_pv_dip_older_than_the_look_back_no_longer_counts():
    c = _controller()
    latest, now = _day(soc=50, pv=320)
    _pv_seen(now, (30, 240), (10, 330))
    assert c._plan_cap(latest, now)[1] == 320 - c.charge_reserve_w


def test_the_current_pv_still_counts_when_it_is_the_lowest():
    c = _controller()
    latest, now = _day(soc=50, pv=250)
    _pv_seen(now, (20, 330))
    assert c._plan_cap(latest, now)[1] == 250 - c.charge_reserve_w


def test_the_lowest_pv_applies_to_full_and_cover_load_phases_too():
    c = _controller()
    latest, now = _day(soc=c.full_soc, pv=300)
    _pv_seen(now, (15, 200))
    assert c._plan_cap(latest, now)[1] == 200 - c.trickle_w  # PV pass-through when full
    asyncio.run(c.configure(cover_load=True))
    latest, now = _day(soc=50, pv=300)
    _pv_seen(now, (5, 200))
    assert c._plan_cap(latest, now)[1] == 200  # cover-load: guard 0 -> the lowest PV itself


def test_the_night_cap_ignores_pv_samples():
    c = _controller()
    latest, now = _night(soc=60)
    _pv_seen(now, (10, 0))
    assert c._plan_cap(latest, now)[1] == c.night_max_w


def test_state_keeps_only_recent_pv_samples_and_reports_the_minimum():
    s = st.SharedState()
    asyncio.run(s.publish({"pvPow": 100, "batPow": 0}, None))
    asyncio.run(s.publish({"pvPow": 60, "batPow": 0}, None))
    asyncio.run(s.publish({"soc": 50}, None))  # no fresh power reading: not a sample
    assert len(s._pv_samples) == 2 and s.pv_min(60) == 60
    assert s.pv_min(60, now=time.time() + 300) is None  # everything is older than the window


# --- "minimum interval" is only reported when a write was really held back ---------------------

def _step_within_the_interval(monkeypatch, *, cap_pv, inv, setpoint):
    """One step shortly after a write, meter far above the target, day phase with the given PV."""
    _, noon = _day(soc=50, pv=cap_pv)
    c = _ctl(FakeClient(guest=True))
    asyncio.run(c.configure(enabled=True, dry_run=False, plan=True))
    asyncio.run(c.configure(cover_load=True))  # cap == PV, as in the field report
    c.setpoint, c.meter_w = setpoint, 225.0
    c._last_sync_t = noon  # no read-back this round
    c._last_write_t = noon - 6  # 6 s ago: inside min_interval_s
    monkeypatch.setattr(st.STATE, "latest", {"soc": 50, "pvPow": cap_pv, "batPow": 0, "invPow": inv, "_power_t": noon})
    with mock.patch("time.time", return_value=noon):
        asyncio.run(c._step())
    return c


def test_within_the_interval_a_setpoint_the_cap_already_holds_is_unchanged_not_skipped(monkeypatch):
    c = _step_within_the_interval(monkeypatch, cap_pv=110, inv=110, setpoint=110)
    assert c.last_action.key == "act.ok_unchanged" and c.last_action.params == {"w": 110}


def test_within_the_interval_a_correction_that_would_go_out_is_still_skipped(monkeypatch):
    c = _step_within_the_interval(monkeypatch, cap_pv=500, inv=110, setpoint=110)  # room to raise it
    assert c.last_action.key == "act.skip_interval" and c.setpoint == 110


# --- the cap is sized from the real PV, not from the booked pvPow ------------------------------

def test_the_cap_uses_the_real_pv_not_the_booked_value_that_only_mirrors_the_output():
    """Field report: pvPow 110 = the inverter's own output (the battery took no surplus) while the real PV
    was 135 W - a cap from pvPow could never rise above the setpoint and pinned the output at 110 W."""
    c = _controller()
    latest, now = _day(soc=50, pv=110)
    latest["pvPreal"] = 135
    _pv_seen(now, (10, 135))
    asyncio.run(c.configure(cover_load=True))
    assert c._plan_cap(latest, now)[1] == 135  # not 110


def test_without_a_real_value_the_pv_strings_are_summed_and_then_the_booked_value_is_used():
    from app.state import pv_supply

    assert pv_supply({"pvPreal": 150, "pv1Pow": 1, "pv2Pow": 2, "pvPow": 110}) == 150  # LAN
    assert pv_supply({"pv1Pow": 40, "pv2Pow": 95, "pvPow": 110}) == 135  # cloud: PV1 + PV2
    assert pv_supply({"pv1Pow": None, "pv2Pow": 95, "pvPow": 110}) == 110  # incomplete strings: booked
    assert pv_supply({"pvPow": 110}) == 110
    assert pv_supply({}) is None


def test_the_pv_samples_and_the_debug_context_use_the_same_supply(monkeypatch):
    s = st.SharedState()
    asyncio.run(s.publish({"pvPow": 110, "pvPreal": 135, "batPow": 0}, None))
    assert s.pv_min(20) == 135
    monkeypatch.setattr(st.STATE, "latest", {"pvPow": 110, "pvPreal": 135})
    live = GridController._live()
    assert live["pv"] == 135 and live["pvPow"] == 110  # the booked value is shown when it differs


def test_a_stale_real_value_from_the_other_source_is_dropped_when_a_reading_has_none():
    s = st.SharedState()
    asyncio.run(s.publish({"pvPow": 110, "pvPreal": 135, "batPow": 0}, None))
    asyncio.run(s.publish({"pvPow": 90, "batPow": 0}, None))  # e.g. cloud mode after a switch
    assert "pvPreal" not in s.latest


# --- reducing does not wait for the write interval ------------------------------------------

def _reduction_step(monkeypatch, *, since_write, sample_after_write=True, meter=-100.0, adaptive=False):
    """A step `since_write` s after the last write, the meter showing feed-in (output above the house's draw)."""
    _, noon = _day(soc=50, pv=500)
    c = _ctl(FakeClient(guest=True))
    asyncio.run(c.configure(enabled=True, dry_run=False, plan=True, cover_load=True, adaptive_gain=adaptive))
    c.setpoint, c.meter_w = 300, meter
    c._last_sync_t = noon  # no read-back this round
    c._last_write_t = noon - since_write
    c.meter_t = noon - (since_write - 2 if sample_after_write else since_write + 5)
    monkeypatch.setattr(st.STATE, "latest", {"soc": 50, "pvPow": 500, "batPow": 0, "invPow": 300, "_power_t": noon})
    with mock.patch("time.time", return_value=noon):
        asyncio.run(c._step())
    return c


def test_a_reduction_goes_out_without_waiting_for_the_interval(monkeypatch):
    c = _reduction_step(monkeypatch, since_write=30)  # 30 s < CONTROL_MIN_INTERVAL (60 s)
    assert c.last_action.key == "act.set" and c.setpoint == round(300 + c.gain * (-100.0 - c.target_w))
    assert c.last_action.params["why"].key == "why.control_fast"


def test_a_reduction_still_respects_the_short_lockout_after_a_write(monkeypatch):
    c = _reduction_step(monkeypatch, since_write=10)  # inside REDUCE_LOCKOUT_S
    assert c.last_action.key == "act.skip_interval" and c.setpoint == 300


def test_a_reduction_needs_a_meter_sample_that_arrived_after_the_last_write(monkeypatch):
    c = _reduction_step(monkeypatch, since_write=30, sample_after_write=False)  # cannot show the write's effect yet
    assert c.last_action.key == "act.skip_interval" and c.setpoint == 300


def test_an_increase_still_waits_for_the_interval(monkeypatch):
    c = _reduction_step(monkeypatch, since_write=30, meter=400.0)  # house draws more than the output
    assert c.last_action.key == "act.skip_interval" and c.setpoint == 300


def test_a_reduction_ahead_of_the_interval_does_not_train_the_adaptive_gain(monkeypatch):
    c = _reduction_step(monkeypatch, since_write=30, adaptive=True)
    assert c.last_action.key == "act.set" and c._prev_error is None
