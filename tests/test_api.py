import asyncio
import json

from aiohttp.test_utils import TestClient, TestServer

from app.grid_control import GridController
from app.main import make_ui_app


def _run(coro_fn):
    async def go():
        async with TestClient(TestServer(make_ui_app(GridController(None, "broker", 1883, None, None)))) as client:
            return await coro_fn(client)

    return asyncio.run(go())


def test_pages_are_served_and_revalidated_with_etag():
    async def check(client):
        for path in ("/", "/flow", "/control", "/raw"):
            r = await client.get(path)
            assert r.status == 200 and "text/html" in r.headers["Content-Type"]
            etag = r.headers["ETag"]
            assert (await client.get(path, headers={"If-None-Match": etag})).status == 304

    _run(check)


def test_env_endpoint_never_returns_passwords(monkeypatch):
    monkeypatch.setenv("SUNSHARE_PASSWORD", "hunter2")

    async def check(client):
        body = await (await client.get("/api/env")).text()
        assert "hunter2" not in body

    _run(check)


def test_control_settings_roundtrip_and_validation():
    async def check(client):
        ok = await client.post("/api/control", json={"settings": {"NIGHT_MAX_W": 120}})
        assert ok.status == 200 and (await ok.json())["settings"]["NIGHT_MAX_W"] == 120
        bad = await client.post("/api/control", json={"settings": {"CHARGE_RELEASE_SOC": 99}})
        assert bad.status == 400 and "CHARGE_RELEASE_SOC" in (await bad.json())["error"]
        assert (await client.post("/api/control", json={"enabled": "yes"})).status == 400

    _run(check)


def test_history_endpoints_validate_input():
    async def check(client):
        assert (await client.get("/api/history/long?minutes=abc")).status == 400
        long = await (await client.get("/api/history/long?minutes=60")).json()
        assert set(long) >= {"step", "rows", "retention_days"}
        assert isinstance(await (await client.get("/api/history?compact=1")).json(), list)

    _run(check)


def test_raw_log_endpoints():
    async def check(client):
        from app.raw_log import RAW

        RAW.clear()
        RAW.add("POST", "/collect-service/x", "10.0.0.5", {"Authorization": "Bearer secret", "User-Agent": "t"}, b'{"a":1}')
        entries = await (await client.get("/api/raw")).json()
        assert entries[-1]["headers"]["Authorization"] == "***" and entries[-1]["body"] == '{"a":1}'
        await client.post("/api/raw/clear")
        assert await (await client.get("/api/raw")).json() == []

    _run(check)
