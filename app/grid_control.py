"""Zero-feed-in controller: follows an external grid-power meter (a Home Assistant
MQTT sensor, positive = import from grid) and steers the inverter's constant
output wattage (`permPower`, via updateEmsParaById) so the meter reads ~0.

The device has no smart meter of its own here (`meterList: null`), so its own
the device's gridPow/loadPow only describe its own socket (grid pass-through resp. the load
hanging on it), not the household — this is the closest thing to a meter-driven mode.

Safety defaults: disabled and in dry-run (only logs what it would set). The meter
only reports about once a minute and the command goes cloud -> MQTT -> device, so
this is a slow, damped controller: one decision per fresh meter sample.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any

import paho.mqtt.client as mqtt

from .state import STATE
from .sunshare_cloud import SunshareCloudClient

_LOGGER = logging.getLogger("sunshare.control")

CONTROL_FILE = Path("/data/control.json")
INV_MAX_AGE_S = 120  # inverter reading older than this is not trusted as the control base


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


def _in_window(minute: int, start: int, end: int) -> bool:
    """True if `minute` lies in [start, end), also when the window wraps midnight."""
    return start <= minute < end if start <= end else minute >= start or minute < end


# Battery-plan settings editable in the web UI: key -> (attribute, kind, min, max).
# The env vars (same names, upper case) only provide the defaults; UI changes are
# persisted in control.json and win over the env on the next start.
PLAN_SETTINGS: dict[str, tuple[str, str, float, float]] = {
    "BATTERY_CAPACITY_WH": ("battery_wh", "float", 100, 100000),
    "CHARGE_RESERVE_W": ("charge_reserve_w", "int", 0, 2000),
    "CHARGE_FULL_SOC": ("full_soc", "float", 50, 100),
    "CHARGE_RELEASE_SOC": ("release_soc", "float", 50, 100),
    "NIGHT_START": ("night_start", "time", 0, 1439),
    "NIGHT_END": ("night_end", "time", 0, 1439),
    "NIGHT_MAX_W": ("night_max_w", "int", 0, 2000),
    "NIGHT_MIN_SOC": ("night_min_soc", "float", 0, 100),
}


def _fmt_hm(minute: int) -> str:
    return f"{minute // 60:02d}:{minute % 60:02d}"


class GridController:
    def __init__(
        self,
        client: SunshareCloudClient,
        mqtt_host: str,
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
        self.gain = float(env("CONTROL_GAIN", "0.7"))
        self.min_w = int(env("CONTROL_MIN_W", "0"))
        self.max_w = int(env("CONTROL_MAX_W", "800"))
        self.min_interval_s = float(env("CONTROL_MIN_INTERVAL", "45"))
        self.meter_max_age_s = float(env("CONTROL_METER_MAX_AGE", "180"))
        self.fallback_w = int(env("CONTROL_FALLBACK_W", "0"))

        # Battery plan (day: keep `charge_reserve_w` for charging until full, feed only
        # the PV above that; night: discharge up to `night_max_w` down to `night_min_soc`).
        self.battery_wh = float(env("BATTERY_CAPACITY_WH", "1526"))
        self.charge_reserve_w = int(env("CHARGE_RESERVE_W", "200"))
        self.full_soc = float(env("CHARGE_FULL_SOC", "95"))
        self.release_soc = float(env("CHARGE_RELEASE_SOC", "90"))  # hysteresis: "full" ends below this
        self.night_start = _parse_hm(env("NIGHT_START", "23:00"))
        self.night_end = _parse_hm(env("NIGHT_END", "06:00"))
        self.night_max_w = int(env("NIGHT_MAX_W", "150"))
        self.night_min_soc = float(env("NIGHT_MIN_SOC", "25"))
        self._battery_full = False
        self.phase = "–"
        self.default_settings = self.settings()

        saved = self._load()
        try:
            self._apply_settings(saved.get("settings") or {})
        except ValueError as err:
            _LOGGER.warning("Ignoring invalid saved plan settings: %s", err)
        self.plan_enabled = bool(saved.get("plan", True))
        self.enabled = bool(saved.get("enabled", False))
        self.dry_run = bool(saved.get("dry_run", True))
        self.restore_w: int | None = saved.get("restore_w")

        self.meter_w: float | None = None
        self.meter_t: float | None = None
        self.setpoint: int | None = None
        self.strategy_type = 1
        self.last_action = "–"
        self._last_write_t = 0.0
        self._failsafe_active = False
        self._mqtt_connected = False
        self._config_seen = False
        self._last_payload: str | None = None  # raw text of the last message on the state topic
        self._new_meter = asyncio.Event()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._mqtt: mqtt.Client | None = None

    # ---- persistence / UI ------------------------------------------------
    def _load(self) -> dict[str, Any]:
        try:
            return json.loads(CONTROL_FILE.read_text())
        except Exception:
            return {}

    def _save(self) -> None:
        try:
            CONTROL_FILE.parent.mkdir(parents=True, exist_ok=True)
            CONTROL_FILE.write_text(
                json.dumps(
                    {
                        "enabled": self.enabled,
                        "dry_run": self.dry_run,
                        "plan": self.plan_enabled,
                        "restore_w": self.restore_w,
                        "settings": self.settings(),
                    }
                )
            )
        except OSError:
            _LOGGER.warning("Could not persist control state to %s (non-fatal)", CONTROL_FILE)

    def settings(self) -> dict[str, Any]:
        """Current battery-plan settings under their env-var names (times as "HH:MM")."""
        out: dict[str, Any] = {}
        for key, (attr, kind, _lo, _hi) in PLAN_SETTINGS.items():
            value = getattr(self, attr)
            out[key] = _fmt_hm(value) if kind == "time" else value
        return out

    def _apply_settings(self, values: dict[str, Any]) -> None:
        """Validates `values` (a subset of PLAN_SETTINGS) and applies them all-or-nothing."""
        parsed: dict[str, Any] = {}
        for key, raw in values.items():
            if key not in PLAN_SETTINGS:
                raise ValueError(f"unbekannter Parameter {key}")
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
                raise ValueError(f"{key}: ungültiger Wert {raw!r}") from None
            if not lo <= value <= hi:
                raise ValueError(f"{key}: muss zwischen {lo:g} und {hi:g} liegen")
            parsed[attr] = value
        full = parsed.get("full_soc", self.full_soc)
        release = parsed.get("release_soc", self.release_soc)
        if release > full:
            raise ValueError("CHARGE_RELEASE_SOC darf nicht über CHARGE_FULL_SOC liegen")
        for attr, value in parsed.items():
            setattr(self, attr, value)

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
            "phase": self.phase,
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
            "last_action": self.last_action,
            "settings": self.settings(),
            "defaults": self.default_settings,
            "battery_full": self._battery_full,
            "control_max_w": self.max_w,
        }

    async def configure(
        self,
        enabled: bool | None = None,
        dry_run: bool | None = None,
        plan: bool | None = None,
        settings: dict[str, Any] | None = None,
    ) -> None:
        """Raises ValueError (before changing anything) if `settings` is invalid."""
        if settings:
            self._apply_settings(settings)
            self._battery_full = False  # re-evaluate "full" against the new thresholds
            self.last_action = "Parameter aktualisiert"
        was_active = self.enabled and not self.dry_run
        if enabled is True and not self.enabled:
            settings = await self._client.read_ems_settings()
            pojo = (settings or {}).get("mesSettingUpdatePojo") or {}
            if pojo.get("permPower") is not None:
                self.restore_w = int(pojo["permPower"])
                self.setpoint = self.restore_w
                self.strategy_type = int(pojo.get("emsStrategyType") or 1)
            self.last_action = f"aktiviert (Ausgangswert vorher: {self.restore_w} W)"
        if enabled is not None:
            self.enabled = enabled
        if dry_run is not None:
            self.dry_run = dry_run
        if plan is not None:
            self.plan_enabled = plan
        if was_active and not (self.enabled and not self.dry_run) and self.restore_w is not None:
            ok = await self._client.set_output_power(self.restore_w, self.strategy_type)
            self.last_action = f"Ausgangswert zurück auf {self.restore_w} W ({'ok' if ok else 'FEHLER'})"
            if ok:
                self.setpoint = self.restore_w
        self._save()
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
        STATE.meter_w, STATE.meter_t = value, t
        self._failsafe_active = False
        self._new_meter.set()

    # ---- control loop -----------------------------------------------------
    async def run(self) -> None:
        self._loop = asyncio.get_running_loop()
        host, port, user, password = self._mqtt_conn
        self._mqtt = mqtt.Client(client_id="sunshare-bridge-gridctl")
        if user:
            self._mqtt.username_pw_set(user, password)
        self._mqtt.on_connect = self._on_connect
        self._mqtt.on_message = self._on_message
        self._mqtt.on_disconnect = self._on_disconnect
        self._mqtt.connect_async(host, port)
        self._mqtt.loop_start()
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
            try:
                await self._step()
            except Exception:
                _LOGGER.exception("Grid control step failed")

    def _plan_cap(self, latest: dict[str, Any], now: float) -> tuple[str, int] | None:
        """(phase text, max output watts) for the current time/SOC/PV, or None if
        SOC or PV power are unknown (then nothing is changed)."""
        soc, pv = latest.get("soc"), latest.get("pvPow")
        if soc is None or pv is None:
            return None
        lt = time.localtime(now)
        if _in_window(lt.tm_hour * 60 + lt.tm_min, self.night_start, self.night_end):
            if soc <= self.night_min_soc:
                return f"Nacht: SOC {soc} % ≤ {self.night_min_soc:.0f} % – keine Abgabe", 0
            return f"Nacht: Abgabe bis {self.night_max_w} W (SOC {soc} %)", self.night_max_w
        if soc >= self.full_soc:
            self._battery_full = True
        elif soc < self.release_soc:
            self._battery_full = False
        if self._battery_full:
            # Battery stays untouched for the night: output never exceeds what PV delivers.
            return f"Tag: Batterie voll ({soc} %) – nur PV-Durchleitung", max(round(pv), 0)
        return (
            f"Tag: Batterie lädt (Reserve {self.charge_reserve_w} W, SOC {soc} %)",
            max(round(pv - self.charge_reserve_w), 0),
        )

    async def _step(self) -> None:
        if not self.enabled or self.meter_w is None:
            return
        now = time.time()
        if now - self._last_write_t < self.min_interval_s:
            self.last_action = "übersprungen: Mindestabstand"
            return

        if self.setpoint is None:
            settings = await self._client.read_ems_settings()
            pojo = (settings or {}).get("mesSettingUpdatePojo") or {}
            if pojo.get("permPower") is None:
                self.last_action = "übersprungen: aktueller Ausgangswert unbekannt"
                return
            self.setpoint = int(pojo["permPower"])
            self.strategy_type = int(pojo.get("emsStrategyType") or 1)

        latest = STATE.latest or {}
        inv = latest.get("invPow")
        if inv is None or now - latest.get("_power_t", 0) > INV_MAX_AGE_S:
            self.last_action = "übersprungen: keine frische Wechselrichter-Leistung"
            return

        cap = self.max_w
        if self.plan_enabled:
            plan = self._plan_cap(latest, now)
            if plan is None:
                self.phase = "SOC/PV unbekannt"
                self.last_action = "übersprungen: SOC oder PV-Leistung unbekannt"
                return
            self.phase, cap = plan[0], min(plan[1], self.max_w)
        else:
            self.phase = "Zeitplan aus – reine Nulleinspeisung"

        error = self.meter_w - self.target_w
        # The plan's cap can drop quickly (PV falls, night starts): pull down at once.
        over_cap = self.setpoint > cap and (cap == 0 or self.setpoint > cap + self.deadband_w)
        if not over_cap:
            if abs(error) <= self.deadband_w:
                self.last_action = f"ok: Zähler {self.meter_w:.0f} W im Totband"
                return
            # Needs more, but the inverter already delivers less than commanded
            # (PV/battery-limited): raising the setpoint would only wind up.
            if error > 0 and inv < self.setpoint - self.deadband_w:
                self.last_action = f"ok: Zähler {self.meter_w:.0f} W, Wechselrichter am Limit ({inv:.0f} W)"
                return

        new = round(min(max(inv + self.gain * error, self.min_w), cap))
        if new == self.setpoint:
            self.last_action = f"ok: Sollwert {new} W unverändert"
            return
        await self._apply(new, f"Zähler {self.meter_w:.0f} W, WR {inv:.0f} W, Grenze {cap} W")

    async def _apply(self, watts: int, why: str) -> None:
        if self.dry_run:
            self.last_action = f"TROCKENLAUF: würde {watts} W setzen ({why})"
            _LOGGER.info(self.last_action)
            self._last_write_t = time.time()
            return
        ok = await self._client.set_output_power(watts, self.strategy_type)
        self._last_write_t = time.time()
        if ok:
            self.setpoint = watts
            self.last_action = f"gesetzt: {watts} W ({why})"
        else:
            self.last_action = f"FEHLER beim Setzen von {watts} W ({why})"
        _LOGGER.info(self.last_action)

    async def _failsafe(self) -> None:
        """No meter sample for `meter_max_age_s`: drive to a safe output once."""
        if not self.enabled or self._failsafe_active:
            return
        self._failsafe_active = True
        _LOGGER.warning(
            "No meter sample for %.0fs: mqtt_connected=%s config_seen=%s state_topic=%s value_path=%s",
            self.meter_max_age_s, self._mqtt_connected, self._config_seen, self.state_topic, self.value_path,
        )
        await self._apply(self.fallback_w, "Zählerwert veraltet, Failsafe")
