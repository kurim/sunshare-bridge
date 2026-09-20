"""Transparent reverse proxy for the device's own plaintext telemetry push.

Your UniFi router NATs the inverter's outbound port-80 traffic (destined for
web.sunsharetek.com) to this container instead. Every request is parsed (if
it's the telemetry push we care about) and then forwarded upstream to the
real host UNCHANGED, so Sunshare's backend — and thus the official app —
keeps working exactly as if nothing sat in between.

Confirmed wire format (API_DOCUMENTATION.md §3c-CAPTURE):
    POST http://web.sunsharetek.com/collect-service/collect/emsRealDataMinute/realTimeElectricFlow
    User-Agent: ESP32 HTTP Client/1.0
    (no Authorization header — device-side ingestion)
"""
from __future__ import annotations

import asyncio
import json
import logging

import aiohttp
from aiohttp import web

from .models import normalize_lan
from .raw_log import RAW

_LOGGER = logging.getLogger("sunshare.lan")

UPSTREAM_HOST = "web.sunsharetek.com"
TELEMETRY_PATH = "/collect-service/collect/emsRealDataMinute/realTimeElectricFlow"

_HOP_BY_HOP = {"host", "content-length", "transfer-encoding", "content-encoding", "connection"}


def make_app(state, mqtt_pub, session: aiohttp.ClientSession, device_id: int) -> web.Application:
    app = web.Application()

    async def handler(request: web.Request) -> web.Response:
        body = await request.read()
        raw_entry = (
            RAW.add(request.method, request.path_qs, request.remote, dict(request.headers), body)
            if request.path == TELEMETRY_PATH
            else None
        )

        if request.path == TELEMETRY_PATH and request.method == "POST":
            try:
                reading = normalize_lan(json.loads(body), device_id)
                _LOGGER.debug("LAN telemetry: %s", reading)
                if state.mode == "lan":
                    await state.publish(reading, mqtt_pub)
            except Exception:
                _LOGGER.exception("Failed to parse LAN telemetry push")

        upstream_url = f"http://{UPSTREAM_HOST}{request.path_qs}"
        fwd_headers = {k: v for k, v in request.headers.items() if k.lower() not in _HOP_BY_HOP}
        fwd_headers["Host"] = UPSTREAM_HOST
        try:
            async with session.request(
                request.method,
                upstream_url,
                data=body,
                headers=fwd_headers,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as upstream_resp:
                resp_body = await upstream_resp.read()
                if raw_entry is not None:
                    RAW.set_response(raw_entry, upstream_resp.status, resp_body.decode("utf-8", errors="replace"))
                resp_headers = {
                    k: v for k, v in upstream_resp.headers.items() if k.lower() not in _HOP_BY_HOP
                }
                return web.Response(status=upstream_resp.status, body=resp_body, headers=resp_headers)
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            _LOGGER.exception("Upstream forward to %s failed", upstream_url)
            if raw_entry is not None:
                RAW.set_response(raw_entry, 502, f"upstream forward failed: {err!r}")
            return web.Response(status=502, text="upstream forward failed")

    app.router.add_route("*", "/{tail:.*}", handler)
    return app
