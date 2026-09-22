import asyncio
import json
import time
from unittest import mock

import app.state as st
from app.models import normalize_lan


class FakeMqtt:
    def __init__(self):
        self.published = []

    def publish_state(self, reading):
        self.published.append(reading)


def _publish(state, reading, t):
    async def go():
        with mock.patch("time.time", return_value=t):
            await state.publish(reading, FakeMqtt())

    asyncio.run(go())


def test_export_is_inverter_output_minus_socket_load():
    assert st._derive_export({"invPow": 113, "offGridPow": 33}) == {"exportPow": 80}
    assert st._derive_export({"invPow": 34, "offGridPow": 34}) == {"exportPow": 0}
    assert st._derive_export({"invPow": 36, "offGridPow": 34}) == {"exportPow": 0}  # <= 3 W is noise
    assert st._derive_export({"invPow": 50}) == {}  # cloud source has no offGridPow


def test_battery_power_is_split_into_charge_and_discharge():
    assert st._derive_battery_flow({"batPow": -40}) == {"batChargePow": 40, "batDischargePow": 0}
    assert st._derive_battery_flow({"batPow": 25}) == {"batChargePow": 0, "batDischargePow": 25}


def test_publish_attaches_fresh_meter_value_and_drops_stale_one():
    s = st.SharedState()
    t = time.time()
    s.meter_w, s.meter_t = 450.0, t
    _publish(s, {"pvPow": 10, "soc": 30}, t + 5)
    assert s.latest["meterPow"] == 450.0
    _publish(s, {"pvPow": 10, "soc": 30}, t + st.METER_MAX_AGE_S + 10)
    assert "meterPow" not in s.latest


def test_energy_is_integrated_and_persisted(isolated_data):
    s = st.SharedState()
    t = time.time()
    for i in range(3):  # 1000 W discharge for 2 x 10 s
        _publish(s, {"pvPow": 0, "batPow": 1000, "soc": 50}, t + i * 10)
    assert abs(s.latest["batDischargeEnergyKwh"] - 1000 / 1000 * 20 / 3600) < 1e-3
    saved = json.loads((isolated_data / "battery_energy.json").read_text())
    assert saved["discharge_kwh"] > 0 and saved["eff_base"]["soc"] == 50


def test_pv_peak_today_tracks_max_and_resets_at_midnight(isolated_data):
    s = st.SharedState()
    t = time.time()
    _publish(s, {"pvPow": 500, "batPow": 0, "soc": 50}, t)
    _publish(s, {"pvPow": 800, "batPow": 0, "soc": 50}, t + 10)
    _publish(s, {"pvPow": 300, "batPow": 0, "soc": 50}, t + 20)
    assert s.latest["pvPeakTodayW"] == 800
    saved = json.loads((isolated_data / "battery_energy.json").read_text())
    assert saved["pv_peak_today_w"] == 800
    s._pv_day = "2000-01-01"  # force a day change on the next publish
    _publish(s, {"pvPow": 120, "batPow": 0, "soc": 50}, t + 30)
    assert s.latest["pvPeakTodayW"] == 120


def test_lan_payload_is_normalised_including_real_values():
    raw = {"pvPow": 0, "pv2Pow": 24, "pvPreal": 24, "batPreal": -3, "invPreal": -1, "offGridPow": 5, "soc": 18, "extra": 1}
    r = normalize_lan(raw, 7)
    assert r["pvPreal"] == 24 and r["batPreal"] == -3 and r["invPreal"] == -1 and r["offGridPow"] == 5
    assert r["deviceId"] == 7 and r["source"] == "lan" and "extra" not in r
