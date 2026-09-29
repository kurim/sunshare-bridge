"""Zero-feed-in controller: follows an external grid-power meter (a Home Assistant
MQTT sensor, positive = import from grid) and steers the inverter's constant
output wattage (`permPower`, via updateEmsParaById) so the meter reads ~0.

The device has no smart meter of its own here (`meterList: null`), so its own
the device's gridPow/loadPow only describe its own socket (grid pass-through resp. the load
hanging on it), not the household — this is the closest thing to a meter-driven mode. That also
means PV/battery power (which the bridge does see continuously) say nothing about the household
load between two external meter samples - they aren't a usable feed-forward signal for it.

Safety defaults: disabled and in dry-run (only logs what it would set). The meter
only reports about once a minute and the command goes cloud -> MQTT -> device, so
this is a slow, damped controller: one decision per fresh meter sample. CONTROL_GAIN can
optionally be tuned online from that decision cadence itself (see _adapt_gain).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import socket
import time
from pathlib import Path
from typing import Any

import paho.mqtt.client as mqtt

from .debug_log import DEBUG
from .messages import Msg, MsgError
from .settings_db import SettingsDB
from .state import STATE, pv_supply
from .sunshare_cloud import DEVICE_SOC_MIN_MAX, SunshareCloudClient

_LOGGER = logging.getLogger("sunshare.control")

CONTROL_FILE = Path("/data/control.json")  # the earlier storage: only read once, to import it into settings.db
SETTING_PREFIX = "setting."  # settings.db key prefix of the plan settings (the rest is controller state)
INV_MAX_AGE_S = 120  # inverter reading older than this is not trusted as the control base
EXPORT_GUARD_DECAY_INTERVAL_S = 600  # how rarely the export guard's charge-reserve raise may step back down
EXPORT_GUARD_DECAY_STEP_W = 10  # ... and by how little each time, so it settles rather than hunts
REDUCE_LOCKOUT_S = 20  # after a write, a meter sample this much later may already pull the output down (see _step)
PV_FLOOR_WINDOW_S = 20  # look-back of the lowest-PV filter the day cap is sized from (see _pv_floor)
LIMIT_RECHECK_S = 300  # how long "inverter delivers less than commanded" is trusted before the setpoint is re-sent
LIMIT_UNEXPLAINED_S = 120  # ... when nothing in PV/battery explains it (see _limit_plausible): just a device-lag grace
LIMIT_CHARGING_W = 20  # battery charging harder than this counts as "the device serves the battery first"
LIMIT_SOC_MARGIN = 3  # % above the discharge stop from which the battery could supply the setpoint
DEVICE_SYNC_INTERVAL_S = 300  # how often the device's own output setpoint is read back (see _resync_setpoint)
DEVICE_SYNC_SETTLE_S = 120  # ... and how long after a write of ours it may still be taking effect

# Adaptive CONTROL_GAIN (see _adapt_gain): bounded so a bad run can't wind gain up to something that
# oscillates the real device output, or down to something that never converges. Grow slowly, shrink
# fast (like TCP's AIMD) - overshoot on a real output is worse than a slightly slow approach.
GAIN_MIN = 0.3
GAIN_MAX = 1.2
GAIN_GROW = 1.05
GAIN_SHRINK = 0.85
GAIN_UNDERSHOOT_RATIO = 0.9  # the new error must have shrunk below this fraction of the old one to count as progress


def _extract_value(payload: str, path: str | None) -> float | None:
    """`path` is a dotted key path into a JSON payload (e.g. "ENERGY.Power"),
    or None for a plain numeric payload."""
    try:
        if not path:
            return float(payload)
        value: Any = json.loads(payload)
        for part in path.split("."):
            value = value[part]
        return float(value)
    except (ValueError, KeyError, TypeError, IndexError, json.JSONDecodeError):
        return None


def _path_from_template(template: str | None) -> str | None:
    """Pulls the key path out of simple HA templates: `{{ value_json.a.b | float }}`
    and the bracket form `{{ value_json['power'] }}` (also nested inside `{% if %}`)."""
    if not template:
        return None
    m = re.search(r"value_json((?:\.\w+|\[['\"][^'\"]+['\"]\])+)", template)
    if not m:
        return None
    keys = re.findall(r"\.(\w+)|\[['\"]([^'\"]+)['\"]\]", m.group(1))
    return ".".join(a or b for a, b in keys)


def _discovery_field(cfg: dict[str, Any], long: str, short: str) -> Any:
    """HA discovery allows abbreviated keys (stat_t, val_tpl, ...)."""
    return cfg.get(long) if cfg.get(long) is not None else cfg.get(short)


def _expand_base(topic: str | None, cfg: dict[str, Any]) -> str | None:
    """Resolves the `~` base-topic placeholder used in discovery payloads."""
    base = _discovery_field(cfg, "base_topic", "~")
    if topic and base and topic.startswith("~"):
        return base + topic[1:]
    return topic


def _parse_hm(text: str) -> int:
    """"23:00" -> minutes since midnight."""
    h, m = text.split(":")
    return int(h) * 60 + int(m)


def _r(value: Any) -> int | None:
    """Whole watts/percent for the debug log; None stays None."""
    return None if value is None else round(value)


def _in_window(minute: int, start: int, end: int) -> bool:
    """True if `minute` lies in [start, end), also when the window wraps midnight."""
    return start <= minute < end if start <= end else minute >= start or minute < end


# Settings editable in the web UI: key -> (attribute, kind, min, max).
# The env vars (same names, upper case) only provide the defaults; UI changes are
# persisted in settings.db and win over the env on the next start.
PLAN_SETTINGS: dict[str, tuple[str, str, float, float]] = {
    "BATTERY_CAPACITY_WH": ("battery_wh", "float", 100, 100000),
    "CHARGE_RESERVE_W": ("charge_reserve_w", "int", 0, 2000),
    "CHARGE_TRICKLE_W": ("trickle_w", "int", 0, 200),
    "CHARGE_FULL_SOC": ("full_soc", "float", 50, 100),
    "CHARGE_RELEASE_SOC": ("release_soc", "float", 50, 100),
    "NIGHT_START": ("night_start", "time", 0, 1439),
    "NIGHT_END": ("night_end", "time", 0, 1439),
    "NIGHT_MAX_W": ("night_max_w", "int", 0, 2000),
    "NIGHT_MIN_SOC": ("night_min_soc", "float", 0, 100),
    # How long a meter sample stays valid (failsafe trigger and the UI's "still fresh?" cutoff);
    # depends on how often the user's own meter reports, so it isn't a fixed default for everyone.
    "CONTROL_METER_MAX_AGE": ("meter_max_age_s", "float", 5, 3600),
    # Minimum time between writes. Bounded to the meter's own reporting lag (most HA grid-meter
    # integrations report once every 60-120s): reacting faster just means steering on a sample
    # that hasn't caught up with the last write yet, which winds the loop up instead of damping it.
    "CONTROL_MIN_INTERVAL": ("min_interval_s", "float", 60, 120),
    # Ceiling for the output while the meter is stale (see _failsafe): 0 is only ever "safe" for a
    # house with no baseline load of its own. Still subject to the battery plan's phase cap (PV
    # minus charge reserve by day, the night SOC floor/ceiling) when the plan is on - a fixed value
    # here is a ceiling for what the house may need, not a guarantee that PV/grid actually cover it.
    "CONTROL_FALLBACK_W": ("fallback_w", "int", 0, 2000),
    # Poll rates of the background loops in main.py (read again while they wait, so a change applies
    # within seconds, without a restart): the cumulative PV yield from the cloud, and - cloud mode only - the live values. Not the
    # grid meter: how often that reports is up to the meter itself.
    "ENERGY_POLL_INTERVAL": ("energy_poll_s", "float", 5, 3600),
    "CLOUD_POLL_INTERVAL": ("cloud_poll_s", "float", 0.5, 60),
}


def _n(value: float) -> float | int:
    """Numbers in messages: 63.0 -> 63, 63.46 -> 63.5."""
    return int(value) if float(value).is_integer() else round(float(value), 1)


def _fmt_hm(minute: int) -> str:
    return f"{minute // 60:02d}:{minute % 60:02d}"


class GridController:
    def __init__(
        self,
        client: SunshareCloudClient,
        mqtt_host: str | None,
        mqtt_port: int,
        mqtt_username: str | None,
        mqtt_password: str | None,
    ) -> None:
        env = os.environ.get
        self._client = client
        self._mqtt_conn = (mqtt_host, mqtt_port, mqtt_username, mqtt_password)

        # Where the meter value comes from: either an explicit state topic, or the
        # HA discovery config topic (whose payload names the state topic).
        self.config_topic = env("METER_CONFIG_TOPIC", "")  # e.g. homeassistant/sensor/<meter>/power/config
        self.state_topic: str | None = env("METER_STATE_TOPIC") or None
        self.value_path: str | None = env("METER_VALUE_PATH") or None
        self._path_forced = bool(self.value_path)

        self.target_w = float(env("CONTROL_TARGET_W", "20"))  # small import buffer -> avoids export
        self.deadband_w = float(env("CONTROL_DEADBAND_W", "25"))
        self.gain_base = float(env("CONTROL_GAIN", "0.7"))  # the user's own configured value; see _adapt_gain
        self.min_w = int(env("CONTROL_MIN_W", "0"))
        self.max_w = int(env("CONTROL_MAX_W", "800"))
        # Default at the low end of the meter-delay window (see CONTROL_MIN_INTERVAL in PLAN_SETTINGS);
        # a user whose meter reports slower can raise it in the UI, up to that window's other end.
        self.min_interval_s = float(env("CONTROL_MIN_INTERVAL", "60"))
        self.meter_max_age_s = float(env("CONTROL_METER_MAX_AGE", "180"))
        self.fallback_w = int(env("CONTROL_FALLBACK_W", "0"))
        self.energy_poll_s = float(env("ENERGY_POLL_INTERVAL", "60"))
        self.cloud_poll_s = float(env("CLOUD_POLL_INTERVAL", "2"))

        # Battery plan (day: keep `charge_reserve_w` for charging until full, feed only
        # the PV above that; night: discharge up to `night_max_w` down to `night_min_soc`).
        self.battery_wh = float(env("BATTERY_CAPACITY_WH", "1526"))
        self.charge_reserve_w = int(env("CHARGE_RESERVE_W", "200"))
        # Placeholder until the authoritative value is loaded below (saved.get("reserve_base_w", ...))
        # - settings() (called right below, for default_settings) needs it to already exist.
        self._reserve_base_w = float(self.charge_reserve_w)
        # Held back from output even once "full" (below), so the battery keeps getting a trickle
        # instead of the device's own standby draw slowly running it down before nightfall.
        self.trickle_w = int(env("CHARGE_TRICKLE_W", "5"))
        self.full_soc = float(env("CHARGE_FULL_SOC", "95"))
        self.release_soc = float(env("CHARGE_RELEASE_SOC", "90"))  # hysteresis: "full" ends below this
        self.night_start = _parse_hm(env("NIGHT_START", "23:00"))
        self.night_end = _parse_hm(env("NIGHT_END", "06:00"))
        self.night_max_w = int(env("NIGHT_MAX_W", "150"))
        self.night_min_soc = float(env("NIGHT_MIN_SOC", "25"))
        self._battery_full = False
        self.phase: Msg | None = None
        self.default_settings = self.settings()

        # Main account: NIGHT_MIN_SOC is written to the device (`socMin`, capped at
        # DEVICE_SOC_MIN_MAX) and the device enforces it. Guest account: bridge logic only.
        self.guest = bool(getattr(client, "guest", True))
        self.device_limits: dict[str, Any] | None = None  # last emsModeAdvan read (main account)
        self.device_note: Msg | None = None
        self._device_soc_ok = False  # device `socMin` currently equals what NIGHT_MIN_SOC asks for

        self._db = SettingsDB()
        saved = self._load()
        self._apply_stored_settings(saved.get("settings") or {})
        # settings()["CHARGE_RESERVE_W"] (just applied above) is the baseline, not a live export-guard
        # raise (see settings()'s docstring) - restore that live value separately, so an active raise
        # still survives a restart instead of snapping back to the baseline.
        self.charge_reserve_w = int(saved.get("charge_reserve_w", self.charge_reserve_w))
        self.plan_enabled = bool(saved.get("plan", True))
        # Battery-plan day phase, alternative to the fixed CHARGE_RESERVE_W: cover the household's
        # grid draw first and only divert PV the export guard actually had to claim back, so real
        # surplus - not a fixed reserve - is what ends up in the battery. See _plan_cap.
        self.cover_load = bool(saved.get("cover_load", False))
        # Online-tuned CONTROL_GAIN (see _adapt_gain), off by default: existing installs keep the
        # fixed gain they already have until they opt in. `learned_gain` survives toggling the
        # switch on and off (and restarts) - only the control loop's *use* of it depends on the
        # switch, via the `gain` property below.
        self.adaptive_gain = bool(saved.get("adaptive_gain", False))
        self.learned_gain = float(saved.get("gain", self.gain_base))
        self._prev_error: float | None = None
        self.enabled = bool(saved.get("enabled", False))
        self.dry_run = bool(saved.get("dry_run", True))
        self.restore_w: int | None = saved.get("restore_w")
        # What the export guard (see _guard_against_export) decays CHARGE_RESERVE_W back down
        # to - the user's own configured value, remembered separately from any auto-raise so a
        # restart doesn't mistake a raised reserve for the new baseline.
        self._reserve_base_w = float(saved.get("reserve_base_w", self.charge_reserve_w))

        self.meter_w: float | None = None
        self.meter_t: float | None = None
        self._setpoint: int | None = None
        self.setpoint = None  # property: mirrors into STATE for the history (see _sync_state_setpoint)
        self.strategy_type = 1
        self.last_action: Msg | None = None
        self._last_write_t = 0.0
        self._last_export_guard_t = 0.0
        self._failsafe_active = False
        self._failsafe_w: int | None = None  # last failsafe target that actually went out
        self._last_sync_t = 0.0
        self._ctx: dict[str, float | int | None] = {}  # what the current step works from (debug log)
        self._wrote = False  # this step already logged its decision as a write
        self._dbg_phase: str | None = None
        self._limit_since: float | None = None  # since when the loop has been holding back for a supposed limit
        self._mqtt_connected = False
        self._config_seen = False
        self._last_payload: str | None = None  # raw text of the last message on the state topic
        self._new_meter = asyncio.Event()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._mqtt: mqtt.Client | None = None

    @property
    def setpoint(self) -> int | None:
        return self._setpoint

    @setpoint.setter
    def setpoint(self, value: int | None) -> None:
        self._setpoint = value
        self._sync_state_setpoint()

    def _sync_state_setpoint(self) -> None:
        """The output the bridge is holding, for the live/long-term charts - only while it actually
        steers the device (a stale value from a disabled or dry-run controller would mislead)."""
        STATE.setpoint_w = self._setpoint if self.enabled and not self.dry_run else None

    @property
    def gain(self) -> float:
        """The gain the control loop actually applies right now: the online-learned value while
        adaptive gain is on, the user's own configured CONTROL_GAIN while it's off. Switching the
        UI toggle off only stops applying/updating `learned_gain` - it never discards it."""
        return self.learned_gain if self.adaptive_gain else self.gain_base

    # ---- persistence / UI ------------------------------------------------
    def _load(self) -> dict[str, Any]:
        """What the user saved (settings.db), as {"enabled": ..., "settings": {KEY: value, ...}, ...}:
        the plan settings live under a "setting." key prefix there, only those differing from the defaults."""
        stored = self._db.load()
        if not stored and self._db.enabled:
            stored = self._import_control_json()
        out = {k: v for k, v in stored.items() if not k.startswith(SETTING_PREFIX)}
        out["settings"] = {k[len(SETTING_PREFIX):]: v for k, v in stored.items() if k.startswith(SETTING_PREFIX)}
        return out

    def _import_control_json(self) -> dict[str, Any]:
        """First start with settings.db: take over what the earlier control.json held, then set that
        file aside (renamed, not deleted) so it is not imported twice."""
        try:
            old = json.loads(CONTROL_FILE.read_text())
        except (OSError, ValueError):
            return {}
        settings = dict(old.get("settings") or {})
        if old.get("reserve_base_w") is not None:  # the user's own value, not a live export-guard raise
            settings["CHARGE_RESERVE_W"] = old["reserve_base_w"]
        flat = {k: v for k, v in old.items() if k != "settings"}
        flat.update({SETTING_PREFIX + k: v for k, v in settings.items() if v != self.default_settings.get(k)})
        self._db.save(flat)
        try:
            CONTROL_FILE.rename(CONTROL_FILE.with_name(CONTROL_FILE.name + ".migrated"))
        except OSError:
            _LOGGER.warning("Imported %s but could not rename it", CONTROL_FILE)
        _LOGGER.info("Imported the earlier %s into %s", CONTROL_FILE, self._db.path)
        return flat

    def _apply_stored_settings(self, values: dict[str, Any]) -> None:
        """Applies the saved plan settings; one that no longer validates (a range narrowed by an update, say)
        is skipped with a warning instead of costing the user all the others."""
        try:
            self._apply_settings(values)
            return
        except ValueError:
            pass
        for key in sorted(values, key=lambda k: k != "CHARGE_FULL_SOC"):  # full before release: they are checked together
            try:
                self._apply_settings({key: values[key]})
            except ValueError as err:
                _LOGGER.warning("Ignoring stored setting %s=%r: %s", key, values[key], err)

    def _save(self) -> None:
        """Persists the state; of the plan settings only what differs from the .env/option default."""
        values: dict[str, Any] = {
            "enabled": self.enabled,
            "dry_run": self.dry_run,
            "plan": self.plan_enabled,
            "cover_load": self.cover_load,
            "adaptive_gain": self.adaptive_gain,
            "gain": self.learned_gain,
            "restore_w": self.restore_w,
            "reserve_base_w": self._reserve_base_w,
            "charge_reserve_w": self.charge_reserve_w,
        }
        remove = []
        for key, value in self.settings().items():
            if value == self.default_settings[key]:
                remove.append(SETTING_PREFIX + key)
            else:
                values[SETTING_PREFIX + key] = value
        self._db.save(values, remove)

    def settings(self) -> dict[str, Any]:
        """Current battery-plan settings under their env-var names (times as "HH:MM"). CHARGE_RESERVE_W
        reports the user's own configured baseline (`_reserve_base_w`), not the live value while the
        export guard has temporarily raised it (see _guard_against_export) - otherwise the settings
        form would show that transient raise as if it were the user's setting, and saving any other
        field alongside it (the form submits the whole thing) would silently lock it in as the new
        baseline, permanently, instead of letting it decay back down."""
        out: dict[str, Any] = {}
        for key, (attr, kind, _lo, _hi) in PLAN_SETTINGS.items():
            value = self._reserve_base_w if key == "CHARGE_RESERVE_W" else getattr(self, attr)
            out[key] = _fmt_hm(value) if kind == "time" else value
        return out

    def _apply_settings(self, values: dict[str, Any]) -> None:
        """Validates `values` (a subset of PLAN_SETTINGS) and applies them all-or-nothing."""
        parsed: dict[str, Any] = {}
        for key, raw in values.items():
            if key not in PLAN_SETTINGS:
                raise MsgError(Msg("err.unknown_param", "error", key=key))
            attr, kind, lo, hi = PLAN_SETTINGS[key]
            try:
                if kind == "time":
                    if not isinstance(raw, str):
                        raise ValueError
                    value: float = _parse_hm(raw)
                else:
                    if isinstance(raw, bool):
                        raise ValueError
                    value = float(raw)
                    if kind == "int":
                        value = int(round(value))
            except (ValueError, TypeError):
                raise MsgError(Msg("err.invalid_value", "error", key=key, value=repr(raw))) from None
            if not lo <= value <= hi:
                raise MsgError(Msg("err.range", "error", key=key, lo=f"{lo:g}", hi=f"{hi:g}"))
            parsed[attr] = value
        full = parsed.get("full_soc", self.full_soc)
        release = parsed.get("release_soc", self.release_soc)
        if release > full:
            raise MsgError(Msg("err.release_over_full", "error"))
        for attr, value in parsed.items():
            setattr(self, attr, value)
        STATE.meter_max_age_s = self.meter_max_age_s

    def _writes_allowed(self) -> bool:
        return self.enabled and not self.dry_run

    def _device_soc_min_target(self) -> int:
        return max(0, min(int(round(self.night_min_soc)), DEVICE_SOC_MIN_MAX))

    def _bridge_min_soc(self) -> float | None:
        """SOC at/below which the bridge itself cuts the output at night, or None if the
        device's own `socMin` covers it (main account, value within the device's range)."""
        if self.guest or not self._device_soc_ok or self.night_min_soc > DEVICE_SOC_MIN_MAX:
            return self.night_min_soc
        return None

    async def sync_device_limits(self) -> None:
        """Main account only: bring the device's `socMin` in line with NIGHT_MIN_SOC.
        Like every real write it needs the controller enabled and out of dry-run."""
        if self.guest:
            self.device_note = Msg("dev.guest")
            return
        settings = await self._client.read_ems_settings()
        adv = (settings or {}).get("emsModeAdvan") or {}
        if not adv:
            self._device_soc_ok = False
            self.device_note = Msg("dev.unreadable", "warn")
            return
        self.device_limits = {
            "soc_min": adv.get("socMin"), "soc_max": adv.get("socMax"),
            "country_max_power": adv.get("countryMaxPower"),
        }
        want = self._device_soc_min_target()
        if adv.get("socMin") == want:
            self._device_soc_ok = True
            self.device_note = Msg("dev.already", "ok", soc=want)
            return
        self._device_soc_ok = False
        if not self._writes_allowed():
            self.device_note = Msg("dev.would_write", "warn", old=adv.get("socMin"), new=want)
            return
        ok = await self._client.set_device_limits(soc_min=want)
        self._device_soc_ok = ok
        if ok:
            self.device_limits["soc_min"] = want
        self.device_note = (
            Msg("dev.soc_set", "ok", old=adv.get("socMin"), new=want) if ok else Msg("dev.soc_failed", "error", new=want)
        )
        _LOGGER.info("%s", self.device_note)

    async def _set_country_max_power(self, watts: int) -> None:
        ok = await self._client.set_device_limits(country_max_power=watts)
        if ok and self.device_limits is not None:
            self.device_limits["country_max_power"] = watts
        self.device_note = Msg("dev.country_set", "ok", w=watts) if ok else Msg("dev.country_failed", "error", w=watts)
        _LOGGER.info("%s", self.device_note)

    def status(self) -> dict[str, Any]:
        latest = STATE.latest or {}
        soc = latest.get("soc")
        est_full_h = est_night_h = None
        if soc is not None:
            if soc < self.full_soc and self.charge_reserve_w > 0:
                est_full_h = round((self.full_soc - soc) / 100 * self.battery_wh / 0.9 / self.charge_reserve_w, 1)
            if soc > self.night_min_soc and self.night_max_w > 0:
                est_night_h = round((soc - self.night_min_soc) / 100 * self.battery_wh / self.night_max_w, 1)
        return {
            "plan": self.plan_enabled,
            "cover_load": self.cover_load,
            "adaptive_gain": self.adaptive_gain,
            "gain": round(self.gain, 3),
            "learned_gain": round(self.learned_gain, 3),
            "phase": self.phase.to_dict() if self.phase else None,
            "est_full_h": est_full_h,
            "est_night_h": est_night_h,
            "enabled": self.enabled,
            "dry_run": self.dry_run,
            "meter_w": self.meter_w,
            "meter_age_s": round(time.time() - self.meter_t) if self.meter_t else None,
            "inverter_w": latest.get("invPow"),
            "setpoint_w": self.setpoint,
            "restore_w": self.restore_w,
            "target_w": self.target_w,
            "state_topic": self.state_topic,
            "mqtt_connected": self._mqtt_connected,
            "config_seen": self._config_seen,
            "value_path": self.value_path,
            "last_payload": self._last_payload,
            "last_action": self.last_action.to_dict() if self.last_action else None,
            "settings": self.settings(),
            "defaults": self.default_settings,
            "battery_full": self._battery_full,
            "control_max_w": self.max_w,
            "cloud_login": self._client.login_status() if hasattr(self._client, "login_status") else None,
            "account": "guest" if self.guest else "main",
            "min_soc_source": "bridge" if self._bridge_min_soc() is not None else "device",
            "device_limits": self.device_limits,
            "device_note": self.device_note.to_dict() if self.device_note else None,
        }

    async def configure(
        self,
        enabled: bool | None = None,
        dry_run: bool | None = None,
        plan: bool | None = None,
        cover_load: bool | None = None,
        adaptive_gain: bool | None = None,
        settings: dict[str, Any] | None = None,
        device: dict[str, Any] | None = None,
    ) -> None:
        """Raises MsgError, a ValueError (before changing anything) if `settings` or `device` is invalid.
        `device` holds device-side limits (only COUNTRY_MAX_POWER, main account only)."""
        country_max: int | None = None
        if device:
            if set(device) - {"COUNTRY_MAX_POWER"}:
                raise MsgError(Msg("err.unknown_device_param", "error", keys=", ".join(sorted(set(device) - {"COUNTRY_MAX_POWER"}))))
            raw = device["COUNTRY_MAX_POWER"]
            if isinstance(raw, bool) or not isinstance(raw, (int, float)) or not 0 <= raw <= 2000:
                raise MsgError(Msg("err.country_range", "error"))
            if self.guest:
                raise MsgError(Msg("err.country_main_only", "error"))
            now_enabled = self.enabled if enabled is None else enabled
            now_dry = self.dry_run if dry_run is None else dry_run
            if not (now_enabled and not now_dry):
                raise MsgError(Msg("err.country_needs_live", "error"))
            country_max = int(round(raw))
        changed = [f"{name}={value}" for name, value in (
            ("enabled", enabled), ("dry_run", dry_run), ("plan", plan), ("cover_load", cover_load),
            ("adaptive_gain", adaptive_gain)) if value is not None]
        changed += [f"{key}={value}" for key, value in (settings or {}).items()]
        changed += [f"{key}={value}" for key, value in (device or {}).items()]
        if settings:
            self._apply_settings(settings)
            self._battery_full = False  # re-evaluate "full" against the new thresholds
            if "CHARGE_RESERVE_W" in settings:
                self._reserve_base_w = self.charge_reserve_w  # a deliberate edit is the new baseline
            self.last_action = Msg("act.params_updated", "ok")
        was_active = self.enabled and not self.dry_run
        if enabled is True and not self.enabled:
            settings = await self._client.read_ems_settings()
            pojo = (settings or {}).get("mesSettingUpdatePojo") or {}
            if pojo.get("permPower") is not None:
                self.restore_w = int(pojo["permPower"])
                self.setpoint = self.restore_w
                self.strategy_type = int(pojo.get("emsStrategyType") or 1)
            self.last_action = Msg("act.enabled", "ok", w="?" if self.restore_w is None else self.restore_w)
        if enabled is not None:
            self.enabled = enabled
        if dry_run is not None:
            self.dry_run = dry_run
        if plan is not None:
            self.plan_enabled = plan
        if cover_load is not None:
            self.cover_load = cover_load
        if adaptive_gain is not None:
            self.adaptive_gain = adaptive_gain  # learned_gain is untouched: it survives the toggle
        self._sync_state_setpoint()  # enabled / dry_run may just have changed
        if was_active and not (self.enabled and not self.dry_run) and self.restore_w is not None:
            ok = await self._client.set_output_power(self.restore_w, self.strategy_type)
            self.last_action = (
                Msg("act.restored", "ok", w=self.restore_w) if ok else Msg("act.restore_failed", "error", w=self.restore_w)
            )
            if ok:
                self.setpoint = self.restore_w
        if not self.guest and (settings or enabled is not None or dry_run is not None):
            await self.sync_device_limits()
        if country_max is not None:
            await self._set_country_max_power(country_max)
        self._save()
        if changed:
            DEBUG.add("config", Msg("dbg.config", "info", what=", ".join(changed)))
        _LOGGER.info("Control config: enabled=%s dry_run=%s (%s)", self.enabled, self.dry_run, self.last_action)

    # ---- MQTT (paho thread -> event loop) ---------------------------------
    def _on_connect(self, client: mqtt.Client, userdata: Any, flags: dict, rc: int) -> None:
        if rc != 0:
            _LOGGER.warning("Meter MQTT connect failed rc=%s (check MQTT_HOST/USERNAME/PASSWORD)", rc)
            return
        self._mqtt_connected = True
        _LOGGER.info("Meter MQTT connected, subscribing (config=%s, state=%s)", self.config_topic, self.state_topic)
        if self.state_topic:
            client.subscribe(self.state_topic)
        if self.config_topic and (not self._path_forced or not self.state_topic):
            client.subscribe(self.config_topic)
        if not self.config_topic and not self.state_topic:
            _LOGGER.warning("No grid meter configured (set METER_CONFIG_TOPIC or METER_STATE_TOPIC): the controller stays idle")

    def _on_disconnect(self, client: mqtt.Client, userdata: Any, rc: int) -> None:
        self._mqtt_connected = False
        _LOGGER.warning("Meter MQTT disconnected rc=%s (paho reconnects automatically)", rc)

    def _on_message(self, client: mqtt.Client, userdata: Any, msg: mqtt.MQTTMessage) -> None:
        payload = msg.payload.decode("utf-8", errors="replace")
        if msg.topic == self.config_topic:
            try:
                cfg = json.loads(payload)
            except json.JSONDecodeError:
                _LOGGER.warning("Meter config payload is not JSON: %r", payload[:200])
                return
            self._config_seen = True
            topic = _expand_base(_discovery_field(cfg, "state_topic", "stat_t"), cfg)
            if not topic:
                _LOGGER.warning("Meter discovery payload has no state topic; keys=%s", sorted(cfg))
            elif not self.state_topic:
                self.state_topic = topic
                client.subscribe(self.state_topic)
                _LOGGER.info("Meter state topic from discovery: %s", self.state_topic)
            if not self._path_forced:
                self.value_path = _path_from_template(_discovery_field(cfg, "value_template", "val_tpl"))
                _LOGGER.info("Meter value path: %s", self.value_path or "(plain number)")
            return
        if msg.topic == self.state_topic:
            self._last_payload = payload[:300]
            value = _extract_value(payload, self.value_path)
            if value is None:
                _LOGGER.warning("Could not read a number from meter payload %r (path=%s)", payload[:200], self.value_path)
                return
            assert self._loop is not None
            self._loop.call_soon_threadsafe(self._on_meter, value, time.time())

    def _on_meter(self, value: float, t: float) -> None:
        self.meter_w = value
        self.meter_t = t
        DEBUG.add("meter", Msg("dbg.meter", "info", w=round(value)), meter=round(value), **self._live())
        STATE.meter_w, STATE.meter_t = value, t
        self._failsafe_active = False
        self._failsafe_w = None
        self._new_meter.set()

    # ---- debug trail ------------------------------------------------------
    @staticmethod
    def _live() -> dict[str, float | None]:
        """The device values a decision at this moment would be based on (for the debug log)."""
        latest = STATE.latest or {}
        supply, booked = _r(pv_supply(latest)), _r(latest.get("pvPow"))
        return {
            "pv": supply, "pvPow": booked if booked != supply else None,  # booked PV only when it differs
            "inv": _r(latest.get("invPow")), "bat": _r(latest.get("batPow")), "soc": _r(latest.get("soc")),
        }

    def _log_step(self) -> None:
        """One debug entry per meter-driven step: the phase when it changed, and the decision unless the
        step wrote (that entry, from `_apply`, already carries it)."""
        if self.enabled and self.phase is not None and self.phase.key != self._dbg_phase:
            self._dbg_phase = self.phase.key
            DEBUG.add("phase", self.phase, soc=_r(self._ctx.get("soc")), pv=_r(self._ctx.get("pv")))
        if self.enabled and not self._wrote and self.last_action is not None:
            DEBUG.add("step", self.last_action, **self._ctx)

    # ---- control loop -----------------------------------------------------
    async def run(self) -> None:
        self._loop = asyncio.get_running_loop()
        host, port, user, password = self._mqtt_conn
        if host:
            # Suffixed with the container hostname (Docker assigns one per container, unique between
            # e.g. a docker-compose deployment and the HA add-on pointed at the same broker) - a
            # fixed client ID collides and the broker repeatedly kicks whichever connected first
            # ("session taken over"), which then reconnects and kicks the other, forever.
            self._mqtt = mqtt.Client(client_id=f"sunshare-bridge-gridctl-{socket.gethostname()}")
            if user:
                self._mqtt.username_pw_set(user, password)
            self._mqtt.on_connect = self._on_connect
            self._mqtt.on_message = self._on_message
            self._mqtt.on_disconnect = self._on_disconnect
            self._mqtt.connect_async(host, port)
            self._mqtt.loop_start()
        else:
            # No broker at all (dashboard-only use, see MQTT_HOST in .env.example): the meter-
            # driven controller can never do anything without it - same as "stays idle" when a
            # broker is configured but no meter topic is, just one level up.
            _LOGGER.info("No MQTT broker configured (MQTT_HOST unset): the grid controller stays idle")
        try:
            await self.sync_device_limits()
        except Exception:
            _LOGGER.exception("Device limit sync failed")
        _LOGGER.info(
            "Grid controller started (enabled=%s dry_run=%s, config topic %s)",
            self.enabled, self.dry_run, self.config_topic,
        )
        while True:
            try:
                await asyncio.wait_for(self._new_meter.wait(), timeout=self.meter_max_age_s)
            except asyncio.TimeoutError:
                await self._failsafe()
                continue
            self._new_meter.clear()
            self._wrote = False
            self._ctx = {}
            try:
                await self._step()
                self._log_step()
            except Exception:
                _LOGGER.exception("Grid control step failed")

    def _night_cap(self, soc: float, now: float) -> tuple[Msg, int] | None:
        """(phase message, max output watts) if `now` falls in the night window, else None. Split out of
        `_plan_cap` so the failsafe (no live PV to size a day cap from) can still apply the SOC floor and
        the night ceiling - the one part of the plan that's a hard safety/battery-health rule, not just
        headroom bookkeeping for the closed loop."""
        lt = time.localtime(now)
        if not _in_window(lt.tm_hour * 60 + lt.tm_min, self.night_start, self.night_end):
            return None
        floor = self._bridge_min_soc()
        if floor is not None and soc <= floor:
            return Msg("phase.night_min", soc=_n(soc), min=_n(floor)), 0
        return Msg("phase.night_out", w=self.night_max_w, soc=_n(soc)), self.night_max_w

    def _pv_floor(self, pv: float, now: float) -> float:
        """PV the day cap is sized from: the lowest value of the last PV_FLOOR_WINDOW_S, not just the latest.
        The setpoint stays as written until the next meter sample, while the PV moves every few seconds;
        a dip below it in between is covered by the battery, which is exactly what the day phases keep
        it from doing. The window is short on purpose: it only filters that second-by-second jitter. A
        window as long as the write interval lagged behind a rising PV (the setpoint then trailed it by
        up to a minute and the difference went into the battery even with the house drawing from the grid)."""
        low = STATE.pv_min(PV_FLOOR_WINDOW_S, now)
        return pv if low is None else min(pv, low)

    def _plan_cap(self, latest: dict[str, Any], now: float) -> tuple[Msg, int] | None:
        """(phase message, max output watts) for the current time/SOC/PV, or None if
        SOC or PV power are unknown (then nothing is changed)."""
        soc, pv = latest.get("soc"), pv_supply(latest)
        if soc is None or pv is None:
            return None
        night = self._night_cap(soc, now)
        if night is not None:
            return night
        pv = self._pv_floor(pv, now)
        if soc >= self.full_soc:
            self._battery_full = True
        elif soc < self.release_soc:
            self._battery_full = False
        if self._battery_full:
            # Battery is otherwise untouched here: output tracks PV, minus a small trickle always
            # held back (even at very low PV) so the device's own standby draw doesn't slowly drain
            # it before nightfall, between reaching CHARGE_FULL_SOC and the device's own cutoff.
            return Msg("phase.day_full", trickle=self.trickle_w, soc=_n(soc)), max(round(pv - self.trickle_w), 0)
        if self.cover_load:
            # Cover the household's grid draw first; only PV the export guard has actually had to
            # claim back (charge_reserve_w's raise above the user's own baseline - see
            # _guard_against_export) is withheld from output, so real surplus, not a fixed
            # reserve, is what ends up in the battery.
            guard_w = max(round(self.charge_reserve_w - self._reserve_base_w), 0)
            return (
                Msg("phase.day_cover_load", guard=guard_w, soc=_n(soc)),
                max(round(pv - guard_w), 0),
            )
        return (
            Msg("phase.day_charging", reserve=self.charge_reserve_w, soc=_n(soc)),
            max(round(pv - self.charge_reserve_w), 0),
        )

    def _guard_against_export(self, meter_w: float, now: float) -> None:
        """Feed-in at the meter (negative reading) means the day's charge reserve is too low: too much
        PV is left over for output instead of charging. Raise the reserve right away, by exactly the
        export seen, so `_plan_cap` leaves that much less headroom for output next cycle. This runs
        before the write-rate-limit below since it only changes the bridge's own plan, not the device.

        Without export, slowly relax any such raise back toward the user's own configured reserve
        (`_reserve_base_w`), one small step at a time and never faster than once per
        EXPORT_GUARD_DECAY_INTERVAL_S - a quick decay would just re-trigger the raise above on the next
        PV dip. It never goes below that baseline, so it settles exactly where export last needed it."""
        if meter_w < 0:
            reserve_max = PLAN_SETTINGS["CHARGE_RESERVE_W"][3]
            new_reserve = min(round(self.charge_reserve_w - meter_w), int(reserve_max))
            if new_reserve == self.charge_reserve_w:
                return
            old = self.charge_reserve_w
            self.charge_reserve_w = new_reserve
            self._last_export_guard_t = now
            self._save()
            self.last_action = Msg("act.export_guard", "warn", meter=round(meter_w), old=old, new=new_reserve)
            DEBUG.add("guard", self.last_action, meter=round(meter_w), reserve=new_reserve)
            _LOGGER.warning("%s", self.last_action)
            return
        if self.charge_reserve_w <= self._reserve_base_w or now - self._last_export_guard_t < EXPORT_GUARD_DECAY_INTERVAL_S:
            return
        old = self.charge_reserve_w
        new_reserve = max(self.charge_reserve_w - EXPORT_GUARD_DECAY_STEP_W, self._reserve_base_w)
        self.charge_reserve_w = new_reserve
        self._last_export_guard_t = now
        self._save()
        self.last_action = Msg("act.export_guard_relax", "info", old=old, new=new_reserve)
        DEBUG.add("guard", self.last_action, meter=round(meter_w), reserve=new_reserve)
        _LOGGER.info("%s", self.last_action)

    def _adapt_gain(self, error: float) -> None:
        """Online-tunes CONTROL_GAIN from how the *previous* correction actually played out - the
        same idea as Better Thermostat's thermal_learning, aimed at the meter's own responsiveness
        instead of a room's. There is no faster signal to feed forward from: the device has no meter
        of its own, and PV/battery power say nothing about the household load between two external
        meter samples (see the module docstring) - so this tunes how hard the existing meter-driven
        correction should push, not what to do between samples.

        `error` here is the one just measured, `_prev_error` the one the last correction was based
        on. If the sign flipped, that correction overshot past the target - back off quickly. If the
        sign held and the error barely shrank, it undershot - ease the gain up a little. Close to
        converged (previous error already inside the deadband) there is nothing to grade."""
        prev = self._prev_error
        if prev is None or abs(prev) <= self.deadband_w:
            return
        old = self.learned_gain
        if prev * error < 0:  # crossed the target: overshoot
            self.learned_gain = max(self.learned_gain * GAIN_SHRINK, GAIN_MIN)
        elif abs(error) >= abs(prev) * GAIN_UNDERSHOOT_RATIO:  # barely moved: undershoot
            self.learned_gain = min(self.learned_gain * GAIN_GROW, GAIN_MAX)
        if self.learned_gain != old:
            self._save()
            _LOGGER.info("Adaptive gain: %.3f -> %.3f (prev error %.0f W, now %.0f W)", old, self.learned_gain, prev, error)

    async def _step(self) -> None:
        if not self.enabled or self.meter_w is None:
            return
        now = time.time()
        self._guard_against_export(self.meter_w, now)
        await self._resync_setpoint(now)
        self._ctx = {"meter": round(self.meter_w), "setpoint": self.setpoint, **self._live()}

        if self.setpoint is None:
            settings = await self._client.read_ems_settings()
            pojo = (settings or {}).get("mesSettingUpdatePojo") or {}
            if pojo.get("permPower") is None:
                self.last_action = Msg("act.skip_output_unknown", "warn")
                return
            self.setpoint = int(pojo["permPower"])
            self.strategy_type = int(pojo.get("emsStrategyType") or 1)

        latest = STATE.latest or {}
        inv = latest.get("invPow")
        if inv is None or now - latest.get("_power_t", 0) > INV_MAX_AGE_S:
            self.last_action = Msg("act.skip_no_inverter", "warn")
            return

        cap = self.max_w
        if self.plan_enabled:
            plan = self._plan_cap(latest, now)
            if plan is None:
                self.phase = Msg("phase.unknown", "warn")
                self.last_action = Msg("act.skip_soc_pv_unknown", "warn")
                return
            self.phase, cap = plan[0], min(plan[1], self.max_w)
            self._ctx["pvMin"] = _r(STATE.pv_min(self.min_interval_s, now))
            self._ctx["cap"] = cap
        else:
            self.phase = Msg("phase.schedule_off")

        error = self.meter_w - self.target_w
        self._ctx["error"] = round(error)
        # The plan's cap can drop quickly (PV falls, night starts): pull down at once, bypassing
        # the write-rate limit below - waiting out the interval here would keep over-charging or
        # exporting until it happens to elapse.
        over_cap = self.setpoint > cap and (cap == 0 or self.setpoint > cap + self.deadband_w)
        recheck = False
        fast = False  # a reduction that went ahead of the write interval
        if over_cap:
            self._limit_since = None
        else:
            if abs(error) <= self.deadband_w:
                self._limit_since = None
                self.last_action = Msg("act.ok_deadband", "ok", meter=round(self.meter_w))
                return
            # Needs more, but the inverter already delivers less than commanded (PV/battery-limited):
            # raising the setpoint would only wind up. That is a guess, though - the device may deliver
            # nothing for a reason that has nothing to do with its supply (and only takes up the value
            # again once it is written anew), while the house keeps drawing from the grid. So it only
            # holds for LIMIT_RECHECK_S (only LIMIT_UNEXPLAINED_S if PV/battery could supply more, see
            # _limit_plausible); after that the setpoint is re-sent (recomputed from what the inverter
            # really delivers) and the wait starts over.
            if error > 0 and inv < self.setpoint - self.deadband_w:
                plausible = self._limit_plausible(latest)
                if self._limit_since is None:
                    self._limit_since = now
                if now - self._limit_since < (LIMIT_RECHECK_S if plausible else LIMIT_UNEXPLAINED_S):
                    self.last_action = (
                        Msg("act.ok_limit", "ok", meter=round(self.meter_w), inv=round(inv)) if plausible
                        else Msg("act.wait_output", "warn", inv=round(inv), w=self.setpoint)
                    )
                    return
                recheck = True
            else:
                self._limit_since = None
            # Only now, once a correction is actually due, does the write-rate limit apply - checking
            # it any earlier (e.g. before the deadband/limit checks above) would report "skipped:
            # minimum interval" even while already converged, which is misleading: nothing was ever
            # going to be written regardless of the interval. The same goes for a correction the cap
            # (or the inverter's own output) leaves at the current setpoint: the interval only held
            # something back if a different value would have gone out.
            if now - self._last_write_t < self.min_interval_s:
                # Reducing does not wait for the interval: output above what the house draws feeds the
                # grid or charges the battery for nothing, while too little output only costs a moment of
                # import. It needs a meter sample that arrived after the last write (an older one cannot
                # show its effect) and a short lockout, so a lagging meter cannot make it reduce twice.
                fast = error < 0 and now - self._last_write_t >= REDUCE_LOCKOUT_S and (self.meter_t or 0) > self._last_write_t
                if not fast:
                    would = round(min(max(inv + self.gain * error, self.min_w), cap))
                    if would == self.setpoint and not recheck:
                        self.last_action = Msg("act.ok_unchanged", "ok", w=would)
                    else:
                        self.last_action = Msg("act.skip_interval", "warn")
                    return

        if fast:
            self._prev_error = None  # taken ahead of the interval: its effect is not a clean grade for the gain
        elif recheck:
            self._limit_since = now  # re-arm: the next test comes after another full LIMIT_RECHECK_S
            self._prev_error = None  # a re-send is not a correction whose effect could be graded
        else:
            if self.adaptive_gain:
                self._adapt_gain(error)
            self._prev_error = error

        new = round(min(max(inv + self.gain * error, self.min_w), cap))
        if new == self.setpoint and not recheck:
            self.last_action = Msg("act.ok_unchanged", "ok", w=new)
            return
        why = "why.control_fast" if fast else "why.control"
        await self._apply(new, Msg(why, meter=round(self.meter_w), inv=round(inv), cap=cap))

    def _limit_plausible(self, latest: dict[str, Any]) -> bool:
        """Could the supply explain an inverter that delivers less than commanded? Yes if the battery is
        charging (the device serves it first), or neither the PV covers the setpoint nor the battery has
        energy above its discharge stop. If PV or battery could supply it and the device still delivers
        less, the "limit" is more likely something else (a setpoint the device has not taken up) - the
        loop then waits only a short grace instead of LIMIT_RECHECK_S. Unknown values count as plausible."""
        soc, pv, bat = latest.get("soc"), pv_supply(latest), latest.get("batPow")
        if soc is None or pv is None or bat is None or self.setpoint is None:
            return True
        if bat < -LIMIT_CHARGING_W:
            return True
        floor = (self.device_limits or {}).get("soc_min")
        if floor is None:
            floor = DEVICE_SOC_MIN_MAX
        could_supply = pv >= self.setpoint - self.deadband_w or soc > float(floor) + LIMIT_SOC_MARGIN
        return not could_supply

    async def _resync_setpoint(self, now: float) -> None:
        """The bridge only knows the output it wrote itself; a change made elsewhere (the official app)
        would otherwise go unnoticed - e.g. the loop computing the same value again would see "unchanged"
        and leave the device on the other one. So every DEVICE_SYNC_INTERVAL_S the device's own setpoint is
        read back and adopted when it differs; the next step then works from what the device really has
        (and the failsafe re-asserts its own target). Skipped in dry-run (nothing is ever written, so
        there is nothing to keep in step) and while a write of ours may still be taking effect."""
        if self.dry_run or self.setpoint is None:
            return
        if now - self._last_sync_t < DEVICE_SYNC_INTERVAL_S or now - self._last_write_t < DEVICE_SYNC_SETTLE_S:
            return
        self._last_sync_t = now
        settings = await self._client.read_ems_settings()
        actual = ((settings or {}).get("mesSettingUpdatePojo") or {}).get("permPower")
        if actual is None or int(actual) == self.setpoint:
            return
        _LOGGER.info("Device output is %s W, not the %s W last set here (changed elsewhere?) - adopting it", actual, self.setpoint)
        DEBUG.add("sync", Msg("dbg.adopted", "warn", actual=int(actual), was=self.setpoint), setpoint=int(actual))
        self.setpoint = int(actual)
        self._failsafe_w = None

    async def _apply(self, watts: int, why: Msg) -> bool:
        """True if the value went out (or, in dry-run, would have)."""
        if self.dry_run:
            self.last_action = Msg("act.dry_run", "warn", w=watts, why=why)
            _LOGGER.info("%s", self.last_action)
            self._last_write_t = time.time()
            self._log_write(watts)
            return True
        ok = await self._client.set_output_power(watts, self.strategy_type)
        self._last_write_t = time.time()
        if ok:
            self.setpoint = watts
            self.last_action = Msg("act.set", "ok", w=watts, why=why)
        else:
            self.last_action = Msg("act.set_failed", "error", w=watts, why=why)
        _LOGGER.info("%s", self.last_action)
        self._log_write(watts)
        return ok

    def _log_write(self, watts: int) -> None:
        self._wrote = True
        if self.last_action is not None:
            DEBUG.add("write", self.last_action, **{**self._ctx, "w": watts})

    async def _failsafe(self) -> None:
        """No meter sample for `meter_max_age_s`: drive to a safe output. Runs again every
        `meter_max_age_s` for as long as the meter stays away (see `run`), so the value follows the plan
        as it changes - the evening's 0 W (no PV, still day) must not stick through the night window, and
        the night's value must not stick into the morning - but only writes when the target actually
        differs from the last one that went out (a failed write is retried on the next round).
        `fallback_w` (UI-editable, default 0) is the ceiling for it, but only ever a ceiling - with the battery plan on, it is
        additionally capped by the exact same phase logic the closed loop uses (`_plan_cap`, from the
        last known SOC/PV - independent of the meter, so still fresh): during the day charging phase or
        once full that means never drawing more from the battery than PV actually covers, at night the
        usual SOC floor/ceiling. A configured fallback is a guess at what the house's own baseline load
        needs, not a guarantee that PV/grid cover it - the plan's reserve exists precisely so a blind
        fallback can't eat into it. If the plan is on but even the last known SOC/PV is missing, there is
        nothing to size a safe cap from, so it defaults to 0 rather than trusting the raw fallback."""
        if not self.enabled:
            return
        now = time.time()
        await self._resync_setpoint(now)
        first = not self._failsafe_active
        if not first and now - self._last_write_t < self.min_interval_s:
            return  # a short CONTROL_METER_MAX_AGE must not turn the re-check into a write storm
        self._ctx = {"setpoint": self.setpoint}
        if first:
            DEBUG.add("failsafe", Msg("dbg.meter_missing", "warn", s=round(self.meter_max_age_s)))
            self._failsafe_active = True
            _LOGGER.warning(
                "No meter sample for %.0fs: mqtt_connected=%s config_seen=%s state_topic=%s value_path=%s",
                self.meter_max_age_s, self._mqtt_connected, self._config_seen, self.state_topic, self.value_path,
            )
        watts = self.fallback_w
        if self.plan_enabled:
            cap = self._plan_cap(STATE.latest or {}, now)
            if cap is not None:
                self.phase, watts = cap[0], min(watts, cap[1])
                self._ctx.update(self._live(), cap=cap[1])
            else:
                watts = 0
        if watts == self._failsafe_w:
            return
        if await self._apply(watts, Msg("why.failsafe")):
            self._failsafe_w = watts
