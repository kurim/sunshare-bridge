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

import base64
import json
import logging
from typing import Any

import aiohttp
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.padding import PKCS7

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


class SunshareCloudClient:
    def __init__(
        self,
        session: aiohttp.ClientSession,
        user_account: str,
        password: str,
        device_id: int | None = None,
        device_sn: str | None = None,
    ) -> None:
        self._session = session
        self._user_account = user_account
        self._password = password
        self.device_id = device_id
        self.sn = device_sn
        self._token: str | None = None

    async def login(self) -> None:
        url = BASE_URL + "auth/login"
        body = {"userAccount": self._user_account, "password": self._password}
        async with self._session.post(url, json=body, headers=COMMON_HEADERS, timeout=TIMEOUT) as resp:
            data = await resp.json(content_type=None)
        if not isinstance(data, dict) or data.get("code") != 200:
            raise RuntimeError(f"Sunshare login failed: {data}")
        token = (data.get("data") or {}).get("access_token")
        if not token:
            raise RuntimeError(f"Sunshare login: no access_token in response: {data}")
        self._token = token
        _LOGGER.info("Sunshare cloud login OK")

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
                await self.login()
        except aiohttp.ClientError as err:
            _LOGGER.warning("openRealTime request failed: %s", err)

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
        except aiohttp.ClientError as err:
            _LOGGER.warning("systemDiagramUpdate request failed: %s", err)
            return None

        envelope = _decode_envelope(text)
        if _is_auth_error(envelope):
            _LOGGER.info("Token rejected on systemDiagramUpdate, re-authenticating")
            await self.login()
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
        except aiohttp.ClientError as err:
            _LOGGER.warning("selectInveSummary request failed: %s", err)
            return None
        if _is_auth_error(data):
            _LOGGER.info("Token rejected on selectInveSummary, re-authenticating")
            await self.login()
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
        except aiohttp.ClientError as err:
            _LOGGER.warning("queryMesSettingUpdate request failed: %s", err)
            return None
        if _is_auth_error(data):
            _LOGGER.info("Token rejected on queryMesSettingUpdate, re-authenticating")
            await self.login()
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
            except aiohttp.ClientError as err:
                _LOGGER.warning("updateEmsParaById request failed: %s", err)
                return False
            if _is_auth_error(data) and attempt == 1:
                _LOGGER.info("Token rejected on updateEmsParaById, re-authenticating")
                await self.login()
                continue
            ok = isinstance(data, dict) and data.get("code") == 200 and data.get("data") is True
            if not ok:
                _LOGGER.warning("updateEmsParaById not confirmed: %s", data)
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
