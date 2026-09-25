"""MQTT publisher with Home Assistant MQTT-discovery, so sensors show up in
HA automatically — no need to install the custom_components/sunshare
integration from the reverse-engineering repo.
"""
from __future__ import annotations

import json
import logging
import socket
from typing import Any

import paho.mqtt.client as mqtt

_LOGGER = logging.getLogger("sunshare.mqtt")

_SENSORS: list[tuple[str, str, str, str | None, str | None, str | None]] = [
    # (key, friendly name, json field, unit, device_class, state_class)
    ("pv_power", "PV Power", "pvPow", "W", "power", "measurement"),
    ("pv1_power", "PV1 Power", "pv1Pow", "W", "power", "measurement"),
    ("pv2_power", "PV2 Power", "pv2Pow", "W", "power", "measurement"),
    ("inverter_power", "Inverter Output Power", "invPow", "W", "power", "measurement"),
    ("battery_power", "Battery Power", "batPow", "W", "power", "measurement"),
    ("battery_charge_power", "Battery Charge Power", "batChargePow", "W", "power", "measurement"),
    ("battery_discharge_power", "Battery Discharge Power", "batDischargePow", "W", "power", "measurement"),
    ("load_power", "Load Power", "loadPow", "W", "power", "measurement"),
    ("offgrid_power", "Off-Grid Socket Power", "offGridPow", "W", "power", "measurement"),
    ("house_feedin_power", "Feed-in to House Grid (derived)", "exportPow", "W", "power", "measurement"),
    ("grid_power", "Grid Power", "gridPow", "W", "power", "measurement"),
    # Unfiltered "real" values of the device. pvPow/batPow read 0 below some threshold, these keep
    # the small values (same sign convention: battery + = discharging, - = charging).
    ("pv_power_real", "PV Power (real)", "pvPreal", "W", "power", "measurement"),
    ("battery_power_real", "Battery Power (real)", "batPreal", "W", "power", "measurement"),
    ("inverter_power_real", "Inverter Output Power (real)", "invPreal", "W", "power", "measurement"),
    ("battery_soc", "Battery SOC", "soc", "%", "battery", "measurement"),
    ("pv_energy_today", "PV Energy Today", "todayEnergyKwh", "kWh", "energy", "total_increasing"),
    ("pv_energy_lifetime", "PV Energy Lifetime", "lifetimeEnergyKwh", "kWh", "energy", "total_increasing"),
    ("pv_power_peak_today", "PV Power Peak Today", "pvPeakTodayW", "W", "power", "measurement"),
    ("pv_energy_today_bridge", "PV Energy Today (Bridge)", "pvEnergyTodayKwh", "kWh", "energy", "total_increasing"),
    ("pv_energy_total_bridge", "PV Energy Total (Bridge)", "pvEnergyTotalKwh", "kWh", "energy", "total_increasing"),
    ("battery_charge_energy", "Battery Charge Energy", "batChargeEnergyKwh", "kWh", "energy", "total_increasing"),
    ("battery_discharge_energy", "Battery Discharge Energy", "batDischargeEnergyKwh", "kWh", "energy", "total_increasing"),
    ("data_source", "Data Source", "source", None, None, None),
]


class MqttPublisher:
    def __init__(
        self,
        host: str,
        port: int,
        username: str | None,
        password: str | None,
        base_topic: str,
        device_id: int,
    ) -> None:
        self.base_topic = base_topic
        self.device_id = device_id
        self._discovery_sent = False
        # Hostname suffix: same device_id can be bridged by two containers at once (e.g. the HA
        # add-on and a separate docker-compose install both publishing) - without it they'd fight
        # over the client ID and the broker would keep disconnecting one for the other.
        self._client = mqtt.Client(client_id=f"sunshare-bridge-{device_id}-{socket.gethostname()}")
        if username:
            self._client.username_pw_set(username, password)
        self._client.connect_async(host, port)
        self._client.loop_start()

    def _state_topic(self) -> str:
        return f"{self.base_topic}/{self.device_id}/state"

    def _publish_discovery(self) -> None:
        device = {
            "identifiers": [f"sunshare_{self.device_id}"],
            "name": "Sunshare Inverter",
            "manufacturer": "Sunshare",
        }
        for key, name, field, unit, device_class, state_class in _SENSORS:
            uid = f"sunshare_{self.device_id}_{key}"
            payload: dict[str, Any] = {
                "name": name,
                "unique_id": uid,
                "state_topic": self._state_topic(),
                "value_template": f"{{{{ value_json.{field} }}}}",
                "device": device,
            }
            if unit:
                payload["unit_of_measurement"] = unit
            if device_class:
                payload["device_class"] = device_class
            if state_class:
                payload["state_class"] = state_class
            self._client.publish(f"homeassistant/sensor/{uid}/config", json.dumps(payload), retain=True)
        self._discovery_sent = True
        _LOGGER.info("Published HA MQTT discovery for device %s", self.device_id)

    def publish_state(self, reading: dict[str, Any]) -> None:
        if not self._discovery_sent:
            self._publish_discovery()
        self._client.publish(self._state_topic(), json.dumps(reading), retain=True)
