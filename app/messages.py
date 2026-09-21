"""Status and error texts the bridge shows in the web UI.

The backend does not build sentences for the UI: it sends a `Msg` (a key plus parameters and a level),
and the React app translates it (`msg.<key>` in frontend/src/i18n/*.ts). The English text here is what
appears in logs and in API error texts (`curl`); tests/test_messages.py makes sure every key exists in
every language file with the same {placeholders}.
"""
from __future__ import annotations

from typing import Any

# level: "info" (neutral), "ok", "warn" (nothing wrong, but no action taken / simulated), "error"
LEVELS = ("info", "ok", "warn", "error")

EN: dict[str, str] = {
    # controller phase
    "phase.unknown": "SOC/PV unknown",
    "phase.schedule_off": "Schedule off – plain zero feed-in",
    "phase.night_min": "Night: SOC {soc} % ≤ {min} % – no output",
    "phase.night_out": "Night: output up to {w} W (SOC {soc} %)",
    "phase.day_full": "Day: battery full ({soc} %) – PV pass-through only",
    "phase.day_charging": "Day: battery charging (reserve {reserve} W, SOC {soc} %)",
    # last controller action
    "act.params_updated": "Parameters updated",
    "act.enabled": "Enabled (previous output: {w} W)",
    "act.restored": "Output restored to {w} W",
    "act.restore_failed": "FAILED to restore the output to {w} W",
    "act.skip_interval": "skipped: minimum interval",
    "act.skip_output_unknown": "skipped: current output unknown",
    "act.skip_no_inverter": "skipped: no fresh inverter power",
    "act.skip_soc_pv_unknown": "skipped: SOC or PV power unknown",
    "act.ok_deadband": "ok: meter {meter} W within the deadband",
    "act.ok_limit": "ok: meter {meter} W, inverter at its limit ({inv} W)",
    "act.ok_unchanged": "ok: setpoint {w} W unchanged",
    "act.dry_run": "DRY RUN: would set {w} W ({why})",
    "act.set": "set: {w} W ({why})",
    "act.set_failed": "FAILED to set {w} W ({why})",
    "why.control": "meter {meter} W, inverter {inv} W, limit {cap} W",
    "why.failsafe": "meter value stale, failsafe",
    # device limits (main account)
    "dev.guest": "Guest account: NIGHT_MIN_SOC is enforced by the bridge",
    "dev.unreadable": "Device limits not readable",
    "dev.already": "Device: discharge stop already {soc} %",
    "dev.would_write": "Controller off / dry run: would write discharge stop {old} → {new} % to the device",
    "dev.soc_set": "Device: discharge stop {old} → {new} % set",
    "dev.soc_failed": "FAILED to set the discharge stop to {new} %",
    "dev.country_set": "Device: feed-in limit (countryMaxPower) {w} W set",
    "dev.country_failed": "FAILED to set countryMaxPower to {w} W",
    # rejected settings
    "err.unknown_param": "unknown parameter {key}",
    "err.invalid_value": "{key}: invalid value {value}",
    "err.range": "{key}: must be between {lo} and {hi}",
    "err.release_over_full": "CHARGE_RELEASE_SOC must not exceed CHARGE_FULL_SOC",
    "err.unknown_device_param": "unknown device parameter {keys}",
    "err.country_range": "COUNTRY_MAX_POWER: must be a number between 0 and 2000",
    "err.country_main_only": "COUNTRY_MAX_POWER can only be changed with the main account (SUNSHARE_USER_GUEST=FALSE)",
    "err.country_needs_live": "Writing COUNTRY_MAX_POWER needs the controller enabled and out of dry run",
    # Sunshare cloud login
    "login.failed": "Sunshare login failed: {msg}",
    "login.unreachable": "Sunshare login: server not reachable ({reason})",
    "login.no_token": "Sunshare login: no access token in the response",
}


class Msg:
    """A translatable message: `Msg("act.set", "ok", w=150, why=Msg("why.failsafe"))` (key and level are positional)."""

    __slots__ = ("key", "params", "level")

    def __init__(self, key: str, level: str = "info", /, **params: Any) -> None:  # positional-only: params may be named "key"
        if key not in EN:
            raise KeyError(f"unknown message key {key!r}")
        if level not in LEVELS:
            raise ValueError(f"unknown message level {level!r}")
        self.key, self.level, self.params = key, level, params

    def __str__(self) -> str:
        return EN[self.key].format(**{k: str(v) for k, v in self.params.items()})

    def __repr__(self) -> str:
        return f"Msg({self.key!r}, {self.level!r}, {self.params!r})"

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "level": self.level,
            "params": {k: v.to_dict() if isinstance(v, Msg) else v for k, v in self.params.items()},
        }


class MsgError(ValueError):
    """A rejected request whose reason the UI can show in the user's language."""

    def __init__(self, msg: Msg) -> None:
        super().__init__(str(msg))
        self.msg = msg
