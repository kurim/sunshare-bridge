"""Shared in-process state: which data source is active (cloud/lan, fixed via
the DATA_SOURCE env var, default "lan") and the most recent normalized reading.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from collections import deque
from pathlib import Path
from typing import Any

from .history_db import HistoryDB

_LOGGER = logging.getLogger("sunshare.state")

ENERGY_FILE = Path("/data/battery_energy.json")
HISTORY_FILE = Path("/data/history.db")
METER_MAX_AGE_S = 180  # default; overridden at runtime by the controller's CONTROL_METER_MAX_AGE setting
DEFAULT_RETENTION_DAYS = 30
VALID_MODES = ("cloud", "lan")
DEFAULT_MODE = "lan"
MAX_INTEGRATION_GAP_S = 30  # longer silences (device off, bridge restarted) are not integrated
HISTORY_MAXLEN = 600  # ~30-50min at the default 3-5s publish cadence


def _derive_battery_flow(reading: dict[str, Any]) -> dict[str, Any]:
    """Splits the signed `batPow` (negative = charging, per API_DOCUMENTATION.md
    §3c) into two always-positive-or-None power sensors. Home Assistant's Energy
    dashboard wants separate charge/discharge *energy* series, which there's no
    device-side counter for — so this is the power source you feed into two
    "Integration - Riemann sum" helpers in HA to get there."""
    bat_pow = reading.get("batPow")
    if bat_pow is None:
        return {}
    return {
        "batChargePow": -bat_pow if bat_pow < 0 else 0,
        "batDischargePow": bat_pow if bat_pow > 0 else 0,
    }


def _derive_export(reading: dict[str, Any]) -> dict[str, Any]:
    """Feed-in to the house grid: the inverter's total output (invPow) minus what its own socket
    draws (offGridPow). Verified against a capture with a test feed-in (113 W out, 33 W socket)."""
    inv, socket = reading.get("invPow"), reading.get("offGridPow")
    if inv is None or socket is None:
        return {}
    diff = inv - socket
    return {"exportPow": round(diff, 1) if diff > 3 else 0}  # <= 3 W is measurement noise


class SharedState:
    def __init__(self) -> None:
        self.mode = self._load_mode()
        self.latest: dict[str, Any] | None = None
        self.history: deque[dict[str, Any]] = deque(maxlen=HISTORY_MAXLEN)
        self.lock = asyncio.Lock()
        self.meter_w: float | None = None  # external grid meter (set by the grid controller), + = import
        self.meter_t: float | None = None
        self.meter_max_age_s: float = METER_MAX_AGE_S  # kept in sync with the controller's setting
        # Long-term history: one averaged value per minute (kept HISTORY_RETENTION_DAYS days).
        try:
            retention = max(1, int(os.environ.get("HISTORY_RETENTION_DAYS", DEFAULT_RETENTION_DAYS)))
        except ValueError:
            retention = DEFAULT_RETENTION_DAYS
        self.db = HistoryDB(HISTORY_FILE, retention)
        self._subscribers: set[asyncio.Queue] = set()
        saved = self._load_energy()
        self._bat_charge_kwh = float(saved.get("charge_kwh", 0.0))
        self._bat_discharge_kwh = float(saved.get("discharge_kwh", 0.0))
        self._pv_total_kwh = float(saved.get("pv_total_kwh", 0.0))
        self._pv_today_kwh = float(saved.get("pv_today_kwh", 0.0))
        self._pv_peak_today_w = float(saved.get("pv_peak_today_w", 0.0))
        self._pv_day = saved.get("pv_day") or time.strftime("%Y-%m-%d")
        # Reference point for the battery efficiency: SOC + counter readings when recording
        # began. Stored energy changes with SOC, so efficiency is only meaningful relative to it.
        self._eff_base: dict[str, float] | None = saved.get("eff_base")
        self._last_t: float | None = None
        self._last_charge_pow: float | None = None
        self._last_discharge_pow: float | None = None
        self._last_pv_pow: float | None = None

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue()
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self._subscribers.discard(queue)

    def _broadcast(self) -> None:
        payload = {"mode": self.mode, "reading": self.latest}
        for queue in list(self._subscribers):
            queue.put_nowait(payload)

    def _load_energy(self) -> dict[str, Any]:
        try:
            return json.loads(ENERGY_FILE.read_text())
        except Exception:
            return {}

    def _save_energy(self) -> None:
        try:
            ENERGY_FILE.parent.mkdir(parents=True, exist_ok=True)
            ENERGY_FILE.write_text(
                json.dumps(
                    {
                        "charge_kwh": self._bat_charge_kwh,
                        "discharge_kwh": self._bat_discharge_kwh,
                        "pv_total_kwh": self._pv_total_kwh,
                        "pv_today_kwh": self._pv_today_kwh,
                        "pv_peak_today_w": self._pv_peak_today_w,
                        "pv_day": self._pv_day,
                        "eff_base": self._eff_base,
                    }
                )
            )
        except OSError:
            _LOGGER.warning("Could not persist energy counters to %s (non-fatal)", ENERGY_FILE)

    def _integrate_energy(
        self,
        now: float,
        charge_pow: float | None,
        discharge_pow: float | None,
        pv_pow: float | None,
    ) -> None:
        """Trapezoidal integration of the power sensors into cumulative kWh — the
        device has no such counters of its own (see `_derive_battery_flow`;
        selectInveSummary's PV yield turned out to stay at 0 for this device),
        and this replaces needing "Integration - Riemann sum" helpers in HA.
        PV also gets a per-day counter and peak power, both resetting at local midnight (TZ env)."""
        today = time.strftime("%Y-%m-%d", time.localtime(now))
        if today != self._pv_day:
            self._pv_day = today
            self._pv_today_kwh = 0.0
            self._pv_peak_today_w = 0.0
        if pv_pow is not None and pv_pow > self._pv_peak_today_w:
            self._pv_peak_today_w = pv_pow
        if self._last_t is not None:
            gap_s = now - self._last_t
            if 0 < gap_s <= MAX_INTEGRATION_GAP_S:
                dt_h = gap_s / 3600.0
                if self._last_charge_pow is not None and charge_pow is not None:
                    self._bat_charge_kwh += (self._last_charge_pow + charge_pow) / 2 / 1000 * dt_h
                if self._last_discharge_pow is not None and discharge_pow is not None:
                    self._bat_discharge_kwh += (self._last_discharge_pow + discharge_pow) / 2 / 1000 * dt_h
                if self._last_pv_pow is not None and pv_pow is not None:
                    pv_kwh = (self._last_pv_pow + pv_pow) / 2 / 1000 * dt_h
                    self._pv_total_kwh += pv_kwh
                    self._pv_today_kwh += pv_kwh
            self._save_energy()
        self._last_t = now
        self._last_charge_pow = charge_pow
        self._last_discharge_pow = discharge_pow
        self._last_pv_pow = pv_pow

    @staticmethod
    def _load_mode() -> str:
        mode = os.environ.get("DATA_SOURCE", DEFAULT_MODE).strip().lower()
        if mode not in VALID_MODES:
            _LOGGER.warning("Invalid DATA_SOURCE=%r, falling back to %r", mode, DEFAULT_MODE)
            return DEFAULT_MODE
        return mode

    async def publish(self, reading: dict[str, Any], mqtt_pub) -> None:
        """Merges `reading` into the last-known state rather than replacing it,
        so fields updated on different cadences (e.g. power every few seconds,
        energy totals every minute) don't wipe each other out on the retained
        MQTT state topic."""
        async with self.lock:
            merged = {**(self.latest or {}), **reading}
            merged.update(_derive_battery_flow(merged))
            merged.update(_derive_export(merged))
            now = time.time()
            # Only integrate on fresh power readings — the minute-cadence energy
            # poll republishes the merged (stale) power values, which must not
            # be counted again.
            if "pvPow" in reading or "batPow" in reading:
                merged["_power_t"] = now
                self._integrate_energy(
                    now, merged.get("batChargePow"), merged.get("batDischargePow"), merged.get("pvPow")
                )
            merged["_t"] = now
            # The grid meter typically reports much less often than pvPow/batPow: carry its last value
            # along (up to meter_max_age_s) so the live chart and the history have a grid line (the
            # device's own gridPow is always 0). _meterT lets the UI show how stale that value is.
            if self.meter_w is not None and self.meter_t is not None and now - self.meter_t < self.meter_max_age_s:
                merged["meterPow"] = self.meter_w
                merged["_meterT"] = self.meter_t
            else:
                merged.pop("meterPow", None)
                merged.pop("_meterT", None)
            if "pvPow" in reading or "batPow" in reading:
                self.db.add(now, merged)
            if self._eff_base is None and merged.get("soc") is not None and "pvPow" in reading:
                self._eff_base = {
                    "soc": float(merged["soc"]),
                    "charge_kwh": self._bat_charge_kwh,
                    "discharge_kwh": self._bat_discharge_kwh,
                    "t": now,
                }
                self._save_energy()
            if self._eff_base:
                # Raw reference values; the UI combines them with the (editable) battery capacity.
                merged["_effBaseSoc"] = self._eff_base["soc"]
                merged["_effBaseChargeKwh"] = round(self._eff_base["charge_kwh"], 4)
                merged["_effBaseDischargeKwh"] = round(self._eff_base["discharge_kwh"], 4)
                merged["_effBaseT"] = self._eff_base["t"]
            merged["pvEnergyTodayKwh"] = round(self._pv_today_kwh, 4)
            merged["pvEnergyTotalKwh"] = round(self._pv_total_kwh, 4)
            merged["pvPeakTodayW"] = round(self._pv_peak_today_w, 1)
            merged["batChargeEnergyKwh"] = round(self._bat_charge_kwh, 4)
            merged["batDischargeEnergyKwh"] = round(self._bat_discharge_kwh, 4)
            self.latest = merged
            self.history.append(merged)
        mqtt_pub.publish_state(merged)
        self._broadcast()

    async def get_history(self) -> list[dict[str, Any]]:
        async with self.lock:
            return list(self.history)


STATE = SharedState()
