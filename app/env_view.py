"""Read-only view of the environment (.env) for the settings page.

Secrets are never sent to the browser: passwords are reported only as set/unset and
the account name is partially masked. The env cannot be changed at runtime, so this is
purely informational (edit .env and restart the container to change it).
"""
from __future__ import annotations

import os
from typing import Any

MASK = "••••••••"

# (group id, English title, [(key, default used by the code when the variable is unset; None = no default)]).
# The UI translates the group by its id (`env.group.<id>`); the title is the fallback for API users.
_GROUPS: list[tuple[str, str, list[tuple[str, str | None]]]] = [
    ("account", "Sunshare account", [
        ("SUNSHARE_USER_ACCOUNT", None), ("SUNSHARE_PASSWORD", None),
        ("SUNSHARE_DEVICE_ID", None), ("SUNSHARE_DEVICE_SN", None), ("SUNSHARE_USER_GUEST", "TRUE"),
    ]),
    ("ui_login", "Web UI login", [("UI_USER", None), ("UI_PASSWORD", None), ("UI_SESSION_SECRET", None)]),
    ("mqtt", "MQTT broker", [
        ("MQTT_HOST", None), ("MQTT_PORT", "1883"), ("MQTT_USERNAME", None),
        ("MQTT_PASSWORD", None), ("MQTT_BASE_TOPIC", "sunshare"), ("MQTT_PUBLISH", "TRUE"),
    ]),
    ("source", "Data source & network", [
        ("DATA_SOURCE", "lan"), ("UI_PORT", "8099"), ("LAN_PORT", "80"), ("TZ", None), ("LOG_LEVEL", "INFO"),
    ]),
    ("intervals", "Intervals & history", [
        ("KEEPALIVE_INTERVAL", "3"), ("CLOUD_POLL_INTERVAL", "2"), ("ENERGY_POLL_INTERVAL", "60"),
        ("HISTORY_RETENTION_DAYS", "30"), ("RAW_LOG_SIZE", "500"),
    ]),
    ("meter", "Meter (MQTT)", [
        ("METER_CONFIG_TOPIC", None),
        ("METER_STATE_TOPIC", None), ("METER_VALUE_PATH", None),
    ]),
    ("controller", "Controller", [
        ("CONTROL_TARGET_W", "20"), ("CONTROL_DEADBAND_W", "25"), ("CONTROL_GAIN", "0.7"),
        ("CONTROL_MIN_W", "0"), ("CONTROL_MAX_W", "800"), ("CONTROL_MIN_INTERVAL", "60"),
    ]),
    ("weather", "Weather forecast (OpenWeatherMap)", [
        ("OWM_API_KEY", None), ("OWM_LAT", None), ("OWM_LON", None), ("WEATHER_POLL_INTERVAL", "1800"),
    ]),
]

_SECRET = ("PASSWORD", "TOKEN", "SECRET", "KEY")  # also covers UI_PASSWORD / UI_SESSION_SECRET / OWM_API_KEY
_PARTIAL = ("SUNSHARE_USER_ACCOUNT",)


def _partial(value: str) -> str:
    """"name@example.com" -> "na•••@example.com"."""
    local, at, domain = value.partition("@")
    return f"{local[:2]}•••{at}{domain}"


def describe_env() -> list[dict[str, Any]]:
    groups = []
    for group_id, title, items in _GROUPS:
        rows = []
        for key, default in items:
            raw = os.environ.get(key)
            is_set = raw not in (None, "")
            secret = any(s in key for s in _SECRET)
            if secret:
                value, shown = (MASK if is_set else ""), is_set
            elif not is_set:
                value, shown = (default or ""), False
            else:
                value, shown = (_partial(raw) if key in _PARTIAL else raw), True
            rows.append({
                "key": key,
                "value": value,
                "secret": secret,
                "source": "env" if shown else ("default" if default is not None else "unset"),
            })
        groups.append({"id": group_id, "title": title, "items": rows})
    return groups
