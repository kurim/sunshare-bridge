#!/usr/bin/env python3
"""Read-only probe: log in and print the device's control settings
(`queryMesSettingUpdate`) with serial number / IDs masked, so it can be checked
whether `emsModeAdvan.socMin` / `socMax` exist for this device type.

Never writes anything to the device. Reads SUNSHARE_* from .env (repo root) or
the environment. Logging in ends any other session of the same account.

Usage:
    python3 scripts/sunshare_probe.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import aiohttp

from app.sunshare_cloud import SunshareCloudClient

SENSITIVE_KEYS = ("sn", "deviceid", "userid", "mac", "ip", "ssid", "account", "email", "phone", "token")


def _load_env_file() -> None:
    env_file = REPO_ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


def _mask(obj: Any, secrets: set[str]) -> Any:
    if isinstance(obj, dict):
        return {
            k: "<masked>" if any(s == k.lower() or k.lower().endswith(s) for s in SENSITIVE_KEYS) and v not in (None, "")
            else _mask(v, secrets)
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [_mask(v, secrets) for v in obj]
    if isinstance(obj, str) and any(s and s in obj for s in secrets):
        for s in secrets:
            obj = obj.replace(s, "<masked>")
    return obj


async def _run() -> None:
    _load_env_file()
    user, password = os.environ["SUNSHARE_USER_ACCOUNT"], os.environ["SUNSHARE_PASSWORD"]
    device_id = int(os.environ["SUNSHARE_DEVICE_ID"])
    sn = os.environ["SUNSHARE_DEVICE_SN"]
    async with aiohttp.ClientSession() as session:
        client = SunshareCloudClient(session, user, password, device_id, sn)
        await client.login()
        settings = await client.read_ems_settings()
    if settings is None:
        print("queryMesSettingUpdate: no data (see logs / auth error)")
        return
    print(json.dumps(_mask(settings, {sn, str(device_id), user}), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(_run())
