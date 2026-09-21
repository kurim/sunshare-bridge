"""Cloud-side Sunshare client: login, keepalive (openRealTime) and the
AES-encrypted live-flow read (systemDiagramUpdate).

Endpoints/crypto confirmed in
https://github.com/DelphiXE5/homeassistant-sunshare (API_DOCUMENTATION.md §3c-FINAL).

The keepalive loop runs regardless of the active display mode (cloud/lan) —
it's what makes the device push telemetry in the first place, whether you
then read it back from the cloud or tap it locally on the LAN. Sunshare allows
one active session per account, so log in with a dedicated invited-user account:
with the main account this login and the mobile app would kick each other out.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import math
import re
import time
from typing import Any

import aiohttp
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.padding import PKCS7

from .messages import Msg

_LOGGER = logging.getLogger("sunshare.cloud")

BASE_URL = "https://web.sunsharetek.com/app/"
AES_KEY = b"sunsharesunshare"
CLIENT_ID_PREFIX = "GID_sun@@@"
COMMON_HEADERS = {
    "Content-Type": "application/json",
    "language": "en",
    "localeName": "en",
}
TIMEOUT = aiohttp.ClientTimeout(total=15)
_NETWORK_ERRORS = (aiohttp.ClientError, asyncio.TimeoutError)
# The app only lets the battery's discharge stop (`socMin`) go up to this value.
DEVICE_SOC_MIN_MAX = 20


# After a failed login the client does NOT try again for a while: hammering the login endpoint
# locks the account ("Account locked, try again in 5 minutes") and, worse, restarting the
# container in a crash loop would keep doing exactly that.
LOGIN_MIN_BACKOFF_S = 300
LOGIN_MAX_BACKOFF_S = 1800
LOGIN_NETWORK_BACKOFF_S = 15  # unreachable backend: a short pause is enough, nothing was rejected
_TRY_AGAIN = re.compile(r"try again in\s+(\d+)\s*(second|sec|minute|min|hour)", re.IGNORECASE)


class SunshareLoginError(RuntimeError):
    """The Sunshare login was rejected, or is paused after a rejection (no request was sent)."""


def _server_wait_s(msg: str) -> int | None:
    """"Account locked Please try again in 5 minutes" -> 300."""
    m = _TRY_AGAIN.search(msg or "")
    if not m:
        return None
    unit = m.group(2).lower()
    return int(m.group(1)) * (3600 if unit.startswith("hour") else 60 if unit.startswith("min") else 1)


def guest_from_env(value: str | None) -> bool:
    """SUNSHARE_USER_GUEST: TRUE = invited/guest account (default when unset, the safe
    mode: no device-side battery/feed-in limits are written), FALSE = main account."""
    if value is None or not value.strip():
        return True
    return value.strip().lower() not in ("false", "0", "no", "off")


class SunshareCloudClient:
    def __init__(
        self,
        session: aiohttp.ClientSession,
        user_account: str,
        password: str,
        device_id: int | None = None,
        device_sn: str | None = None,
        guest: bool = True,
    ) -> None:
        self._session = session
        self.guest = guest
        self._user_account = user_account
        self._password = password
        self.device_id = device_id
        self.sn = device_sn
        self._token: str | None = None
        self.login_error: Msg | None = None  # last login failure, shown in the UI; None = fine
        self._login_blocked_until = 0.0
        self._login_failures = 0

    def login_status(self) -> dict[str, Any]:
        wait = max(0, math.ceil(self._login_blocked_until - time.time()))
        return {
            "ok": self.login_error is None,
            "error": self.login_error.to_dict() if self.login_error else None,
            "retry_in_s": wait if self.login_error else None,
        }

    def _login_failed(self, message: Msg, wait_s: float) -> SunshareLoginError:
        self._token = None
        self.login_error = message
        self._login_blocked_until = time.time() + wait_s
        _LOGGER.error("%s (next attempt in %d s)", message, wait_s)
        return SunshareLoginError(str(message))

    async def login(self) -> None:
        """Raises SunshareLoginError. While a failure is being waited out no request is sent."""
        if time.time() < self._login_blocked_until and self.login_error:
            raise SunshareLoginError(str(self.login_error))
        url = BASE_URL + "auth/login"
        body = {"userAccount": self._user_account, "password": self._password}
        try:
            async with self._session.post(url, json=body, headers=COMMON_HEADERS, timeout=TIMEOUT) as resp:
                data = await resp.json(content_type=None)
        except _NETWORK_ERRORS as err:
            raise self._login_failed(Msg("login.unreachable", "error", reason=str(err) or "timeout"), LOGIN_NETWORK_BACKOFF_S) from None
        if not isinstance(data, dict) or data.get("code") != 200:
            self._login_failures += 1
            msg = str(data.get("msg")) if isinstance(data, dict) else str(data)[:200]
            wait = _server_wait_s(msg)
            wait = wait + 60 if wait else min(LOGIN_MAX_BACKOFF_S, LOGIN_MIN_BACKOFF_S * 2 ** (self._login_failures - 1))
            raise self._login_failed(Msg("login.failed", "error", msg=msg), wait)
        token = (data.get("data") or {}).get("access_token")
        if not token:
            self._login_failures += 1
            raise self._login_failed(Msg("login.no_token", "error"), LOGIN_MIN_BACKOFF_S)
        self._token = token
        self._login_failures, self._login_blocked_until, self.login_error = 0, 0.0, None
        _LOGGER.info("Sunshare cloud login OK")

    async def _relogin(self) -> None:
        """The token was rejected: log in again, but never raise (the reason is in `login_error`)."""
        self._token = None
        try:
            await self.login()
        except SunshareLoginError:
            pass

    async def _post(self, path: str, body: dict[str, Any], extra_headers: dict[str, str] | None = None):
        if self._token is None:
            await self.login()
        headers = dict(COMMON_HEADERS)
        headers["Authorization"] = self._token
        if extra_headers:
            headers.update(extra_headers)
        url = BASE_URL + path
        return await self._session.post(url, json=body, headers=headers, timeout=TIMEOUT)

    async def list_devices(self) -> list[dict[str, Any]]:
        """Login-only call: returns the account's devices (id, sn, deviceName,
        statusDec, ...) so device_id/device_sn can be discovered up front."""
        async with await self._post("app/sysDeviceInfo/findDeviceListByUserId", {}) as resp:
            data = await resp.json(content_type=None)
        if _is_auth_error(data):
            await self.login()
            async with await self._post("app/sysDeviceInfo/findDeviceListByUserId", {}) as resp:
                data = await resp.json(content_type=None)
        if not isinstance(data, dict) or data.get("code") != 200:
            raise RuntimeError(f"findDeviceListByUserId failed: {data}")
        return data.get("data") or []

    async def open_realtime(self) -> None:
        """Keepalive: tells the backend to (re)open a real-time session, which is
        what makes the device start/keep pushing telemetry samples."""
        try:
            async with await self._post(
                "app/sysDeviceInfo/queryOnlineStatusByDeviceIdAndOpenRealTime",
                {"deviceId": self.device_id},
            ) as resp:
                data = await resp.json(content_type=None)
            if _is_auth_error(data):
                _LOGGER.info("Token rejected on openRealTime, re-authenticating")
                await self._relogin()
        except SunshareLoginError:
            pass  # reason is in `login_error` and was logged once
        except _NETWORK_ERRORS as err:
            _LOGGER.warning("openRealTime request failed: %s", err or "timeout")

    async def read_live_flow(self) -> dict[str, Any] | None:
        """POST the AES-encrypted systemDiagramUpdate call; returns the decrypted
        `data` dict, or None if the device isn't currently pushing / on error."""
        payload = {"clientId": CLIENT_ID_PREFIX + self.sn, "deviceId": self.device_id}
        body = {"encryptData": _aes_encrypt(payload)}
        try:
            async with await self._post(
                "app/sysDeviceInfo/systemDiagramUpdate", body, extra_headers={"encchannel": "1"}
            ) as resp:
                text = await resp.text()
        except SunshareLoginError:
            return None  # reason is in `login_error` and was logged once
        except _NETWORK_ERRORS as err:
            _LOGGER.warning("systemDiagramUpdate request failed: %s", err or "timeout")
            return None

        envelope = _decode_envelope(text)
        if _is_auth_error(envelope):
            _LOGGER.info("Token rejected on systemDiagramUpdate, re-authenticating")
            await self._relogin()
            return None
        if not isinstance(envelope, dict) or envelope.get("code") != 200:
            return None
        return envelope.get("data") or None

    async def read_energy_summary(self) -> dict[str, Any] | None:
        """POST app/inveRealDataMinute/selectInveSummary — lifetime + today's
        cumulative PV yield (kWh), confirmed in API_DOCUMENTATION.md §7. Not
        gated on an open real-time session (it's a plain stats lookup), so this
        can be polled slowly and independently of the keepalive/display mode."""
        try:
            async with await self._post(
                "app/inveRealDataMinute/selectInveSummary", {"deviceId": self.device_id}
            ) as resp:
                data = await resp.json(content_type=None)
        except SunshareLoginError:
            return None  # reason is in `login_error` and was logged once
        except _NETWORK_ERRORS as err:
            _LOGGER.warning("selectInveSummary request failed: %s", err or "timeout")
            return None
        if _is_auth_error(data):
            _LOGGER.info("Token rejected on selectInveSummary, re-authenticating")
            await self._relogin()
            return None
        if not isinstance(data, dict) or data.get("code") != 200:
            return None
        return data.get("data") or None

    async def read_ems_settings(self) -> dict[str, Any] | None:
        """POST app/sysDeviceInfo/queryMesSettingUpdate — current control settings
        (`mesSettingUpdatePojo.permPower` = constant output watts, `emsStrategyType`,
        `emsModeAdvan.countryMaxPower` = feed-in cap). See API_DOCUMENTATION.md §5."""
        try:
            async with await self._post(
                "app/sysDeviceInfo/queryMesSettingUpdate", {"deviceId": self.device_id}
            ) as resp:
                data = await resp.json(content_type=None)
        except SunshareLoginError:
            return None  # reason is in `login_error` and was logged once
        except _NETWORK_ERRORS as err:
            _LOGGER.warning("queryMesSettingUpdate request failed: %s", err or "timeout")
            return None
        if _is_auth_error(data):
            _LOGGER.info("Token rejected on queryMesSettingUpdate, re-authenticating")
            await self._relogin()
            return None
        if not isinstance(data, dict) or data.get("code") != 200:
            return None
        return data.get("data") or None

    async def set_output_power(self, watts: int, ems_strategy_type: int = 1) -> bool:
        """POST app/sysDeviceInfo/updateEmsParaById — the confirmed wattage-control
        call (API_DOCUMENTATION.md §6). Body must be wrapped in "mesSettingUpdatePojo";
        the flat shape 500s. `updateById` would only change the DB, not the device."""
        body = {
            "mesSettingUpdatePojo": {
                "emsStrategyType": ems_strategy_type,
                "permPower": int(watts),
                "powerSetPojos": [],
                "deviceId": self.device_id,
                "isOnlySave": 0,
            }
        }
        for attempt in (1, 2):
            try:
                async with await self._post("app/sysDeviceInfo/updateEmsParaById", body) as resp:
                    data = await resp.json(content_type=None)
            except SunshareLoginError:
                return False  # reason is in `login_error` and was logged once
            except _NETWORK_ERRORS as err:
                _LOGGER.warning("updateEmsParaById request failed: %s", err or "timeout")
                return False
            if _is_auth_error(data) and attempt == 1:
                _LOGGER.info("Token rejected on updateEmsParaById, re-authenticating")
                await self._relogin()
                continue
            ok = isinstance(data, dict) and data.get("code") == 200 and data.get("data") is True
            if not ok:
                _LOGGER.warning("updateEmsParaById not confirmed: %s", data)
            return ok
        return False

    async def set_device_limits(
        self,
        soc_min: int | None = None,
        soc_max: int | None = None,
        country_max_power: int | None = None,
    ) -> bool:
        """POST app/sysDeviceInfo/updateEmsModeAdvanById — the battery-settings page of
        the app (discharge stop `socMin`, charge stop `socMax`, feed-in cap
        `countryMaxPower`). Found by disassembling the app (docs/DEVICE_NOTES.md): the body
        is wrapped in "emsAdvanStagePojo" (not "emsModeAdvan" as read back) and must carry
        the complete object, so the current values are read first and only the given
        fields are replaced. Main account only: the caller checks `self.guest`."""
        changes = {"socMin": soc_min, "socMax": soc_max, "countryMaxPower": country_max_power}
        changes = {k: int(v) for k, v in changes.items() if v is not None}
        if not changes:
            return True
        for attempt in (1, 2):
            settings = await self.read_ems_settings()
            current = (settings or {}).get("emsModeAdvan")
            if not current:
                _LOGGER.warning("updateEmsModeAdvanById skipped: current emsModeAdvan unknown")
                return False
            body = {"emsAdvanStagePojo": {**current, **changes, "deviceId": self.device_id}}
            try:
                async with await self._post("app/sysDeviceInfo/updateEmsModeAdvanById", body) as resp:
                    data = await resp.json(content_type=None)
            except SunshareLoginError:
                return False  # reason is in `login_error` and was logged once
            except _NETWORK_ERRORS as err:
                _LOGGER.warning("updateEmsModeAdvanById request failed: %s", err or "timeout")
                return False
            if _is_auth_error(data) and attempt == 1:
                _LOGGER.info("Token rejected on updateEmsModeAdvanById, re-authenticating")
                await self._relogin()
                continue
            ok = isinstance(data, dict) and data.get("code") == 200 and data.get("data") is True
            if not ok:
                _LOGGER.warning("updateEmsModeAdvanById not confirmed: %s", data)
            return ok
        return False


def _aes_encrypt(obj: Any) -> str:
    raw = json.dumps(obj, separators=(",", ":")).encode()
    padder = PKCS7(algorithms.AES.block_size).padder()
    padded = padder.update(raw) + padder.finalize()
    encryptor = Cipher(algorithms.AES(AES_KEY), modes.ECB()).encryptor()
    ct = encryptor.update(padded) + encryptor.finalize()
    return base64.b64encode(ct).decode()


def _aes_decrypt(b64: str) -> str:
    ct = base64.b64decode(b64)
    decryptor = Cipher(algorithms.AES(AES_KEY), modes.ECB()).decryptor()
    padded = decryptor.update(ct) + decryptor.finalize()
    unpadder = PKCS7(algorithms.AES.block_size).unpadder()
    return (unpadder.update(padded) + unpadder.finalize()).decode()


def _decode_envelope(text: str) -> Any:
    text = (text or "").strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except ValueError:
        pass
    try:
        return json.loads(_aes_decrypt(text))
    except Exception as err:  # noqa: BLE001
        _LOGGER.warning("Could not decrypt systemDiagramUpdate response: %s", err)
        return {}


def _is_auth_error(data: Any) -> bool:
    if not isinstance(data, dict):
        return False
    if data.get("code") in (401, 403):
        return True
    msg = data.get("msg") or ""
    return isinstance(msg, str) and any(n in msg.lower() for n in ("token", "unauthor", "login", "expired"))
