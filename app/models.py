"""Normalizes raw Sunshare payloads (cloud AES-channel vs. plaintext LAN push)
into one common reading shape used for MQTT publishing / the live dashboard.

Field meanings confirmed in https://github.com/DelphiXE5/homeassistant-sunshare
(API_DOCUMENTATION.md §3c-FINAL / §3c-CAPTURE) against a live device.
"""
from __future__ import annotations

from typing import Any


def normalize_cloud(d: dict[str, Any], device_id: int) -> dict[str, Any]:
    """From POST app/sysDeviceInfo/systemDiagramUpdate (encchannel:1, AES-decrypted)."""
    return {
        "time": d.get("time"),
        "deviceId": device_id,
        "pvPow": d.get("pvPow"),
        "pv1Pow": d.get("pv1Pow"),
        "pv2Pow": d.get("pv2Pow"),
        "invPow": d.get("invPow"),
        "batPow": d.get("batPow"),
        "loadPow": d.get("loadPow"),
        "gridPow": d.get("gridPow"),
        "soc": d.get("soc"),
        "bhs": d.get("bhs"),
        "source": "cloud",
    }


def normalize_lan(d: dict[str, Any], device_id: int) -> dict[str, Any]:
    """From the device's own plaintext POST to
    .../collect-service/collect/emsRealDataMinute/realTimeElectricFlow.
    No deviceId in this payload (only clientId) — filled in from config.
    """
    return {
        "time": d.get("time"),
        "deviceId": device_id,
        "pvPow": d.get("pvPow"),
        "pv1Pow": d.get("pv1Pow"),
        "pv2Pow": d.get("pv2Pow"),
        "invPow": d.get("invPow"),
        "batPow": d.get("batPow"),
        "loadPow": d.get("loadPow"),
        "gridPow": d.get("gridPow"),
        "offGridPow": d.get("offGridPow"),
        "otherPow": d.get("otherPow"),
        # "Real" (unfiltered) values: shown in the UI next to pvPow/batPow and published to MQTT as
        # separate sensors, but never used for calculations - those stay on pvPow/batPow.
        "pvPreal": d.get("pvPreal"),
        "batPreal": d.get("batPreal"),
        "invPreal": d.get("invPreal"),
        "soc": d.get("soc"),
        "bhs": d.get("bhs"),
        "source": "lan",
    }


def normalize_energy_summary(d: dict[str, Any]) -> dict[str, Any]:
    """From POST app/inveRealDataMinute/selectInveSummary — cumulative PV yield,
    unrelated to the cloud/lan power-flow source so it's kept separate and
    merged alongside whichever of those is currently active (see state.py).
    Omits a field entirely rather than including it as None: state.py's merge
    overwrites on any key present, and these are published as `total_increasing`
    energy sensors - a transient None would show as a HA statistics gap/reset
    instead of just keeping the last known good reading."""
    reading: dict[str, Any] = {}
    if (today := d.get("dayPower")) is not None:
        reading["todayEnergyKwh"] = today
    if (lifetime := d.get("totalAllPower")) is not None:
        reading["lifetimeEnergyKwh"] = lifetime
    return reading
