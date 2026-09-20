#!/usr/bin/env python3
"""Standalone CLI to log into the Sunshare account and list its devices —
use this to find the SUNSHARE_DEVICE_ID/SUNSHARE_DEVICE_SN values for .env
before the bridge container has them (see README.md "Setup").

Reads SUNSHARE_USER_ACCOUNT/SUNSHARE_PASSWORD from .env in the repo root (or
the environment); prompts for whichever is missing. Sunshare allows one active
session per account: use a dedicated invited-user account (see README) so the
mobile app is not logged out - with the main account they kick each other out.

Usage:
    python3 scripts/sunshare_login.py login
    python3 scripts/sunshare_login.py devices
"""
from __future__ import annotations

import asyncio
import getpass
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import aiohttp

from app.sunshare_cloud import SunshareCloudClient

ENV_FILE = REPO_ROOT / ".env"


def _load_env_file() -> None:
    if not ENV_FILE.exists():
        return
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


def _credentials() -> tuple[str, str]:
    _load_env_file()
    user = os.environ.get("SUNSHARE_USER_ACCOUNT") or input("Sunshare email: ").strip()
    password = os.environ.get("SUNSHARE_PASSWORD") or getpass.getpass("Sunshare password: ")
    return user, password


async def _run(command: str) -> None:
    user, password = _credentials()
    async with aiohttp.ClientSession() as session:
        client = SunshareCloudClient(session, user, password)
        await client.login()
        print("Login OK.")
        if command == "devices":
            devices = await client.list_devices()
            if not devices:
                print("No devices found on this account.")
                return
            for d in devices:
                print(
                    f"id={d.get('id')}  sn={d.get('sn')}  "
                    f"name={d.get('deviceName')!r}  status={d.get('statusDec')}"
                )


def main() -> None:
    if len(sys.argv) != 2 or sys.argv[1] not in ("login", "devices"):
        print("Usage: sunshare_login.py [login|devices]", file=sys.stderr)
        raise SystemExit(1)
    asyncio.run(_run(sys.argv[1]))


if __name__ == "__main__":
    main()
