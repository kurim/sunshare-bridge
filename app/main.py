"""Entry point: runs the LAN reverse-proxy listener, the small web UI, and the
background cloud keepalive/poll loops side by side in one asyncio process.

Required env vars: SUNSHARE_USER_ACCOUNT, SUNSHARE_PASSWORD, SUNSHARE_DEVICE_ID,
SUNSHARE_DEVICE_SN, MQTT_HOST. See .env.example for the full list.
"""
from __future__ import annotations

# Must run before any of the app's own imports below: several of them read env vars (e.g.
# DATA_SOURCE, see state.py) at *import* time, into module-level singletons - too late to
# still catch a change made here.
from .ha_options import apply_ha_options

apply_ha_options()

import asyncio
import json
import logging
import os
import time

import aiohttp
from aiohttp import web

from . import auth as auth_mod
from . import spa
from .auth import Auth
from .env_view import describe_env
from .grid_control import GridController
from .ingress import ingress_prefix
from .messages import MsgError
from .lan_proxy import make_app as make_lan_app
from .models import normalize_cloud, normalize_energy_summary
from .mqtt_publisher import MqttPublisher
from .raw_log import RAW
from .state import STATE
from .sunshare_cloud import SunshareCloudClient, SunshareLoginError, guest_from_env
from .weather import WeatherClient

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
_LOGGER = logging.getLogger("sunshare.main")


# Keys the charts need from each raw reading; the full readings (~30 fields) are only
# needed for the newest one, which arrives over the SSE stream anyway.
CHART_KEYS = ("_t", "pvPow", "pvPreal", "invPow", "batPow", "batPreal", "loadPow", "offGridPow", "exportPow", "gridPow", "meterPow", "soc")


# The pre-React UI lived at these addresses; they lead to the same pages of the React app now
# (bookmarks, and "/" as the entry point of a tunnel).
LEGACY_REDIRECTS = {"/": "/app/", "/flow": "/app/flow", "/control": "/app/control", "/raw": "/app/raw"}


@web.middleware
async def compress(request: web.Request, handler):
    resp = await handler(request)
    # Plain responses only - the SSE streams are StreamResponse instances and must stay unbuffered.
    if type(resp) is web.Response and resp.status == 200:
        resp.enable_compression()
    return resp


def _redirect(target: str):
    async def handler(request: web.Request) -> web.Response:
        raise web.HTTPFound(ingress_prefix(request) + target)

    return handler


def make_ui_app(
    controller: GridController, auth: Auth | None = None, web_dir=None, weather: WeatherClient | None = None
) -> web.Application:
    """`auth` None = no login (LAN only). `web_dir` overrides where the built React app lives."""
    app = web.Application(middlewares=[compress, auth_mod.make_middleware(auth)])

    async def get_state(request: web.Request) -> web.Response:
        return web.json_response({"mode": STATE.mode, "latest": STATE.latest})

    async def get_history(request: web.Request) -> web.Response:
        rows = await STATE.get_history()
        if request.query.get("compact"):
            rows = [{k: r[k] for k in CHART_KEYS if k in r} for r in rows]
        return web.json_response(rows)

    async def get_history_long(request: web.Request) -> web.Response:
        """One averaged sample per minute from SQLite, bucketed for long ranges: ?minutes=N for a
        rolling window, or ?range=today|yesterday for the actual local calendar day (TZ env) -
        "24h" and "today" differ once it's past midnight."""
        day = request.query.get("range")
        if day in ("today", "yesterday"):
            lt = time.localtime()
            midnight = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1))
            start, end = (midnight, time.time()) if day == "today" else (midnight - 86400, midnight)
            return web.json_response(STATE.db.query_range(start, end))
        if day is not None:
            return web.json_response({"error": "range must be 'today' or 'yesterday'"}, status=400)
        try:
            minutes = int(request.query.get("minutes", "1440"))
        except ValueError:
            return web.json_response({"error": "minutes must be an integer"}, status=400)
        return web.json_response(STATE.db.query(minutes))

    async def stream(request: web.Request) -> web.StreamResponse:
        """Server-Sent Events: pushes a {"mode", "reading"} payload the instant
        state.publish() runs, instead of the dashboard polling."""
        resp = web.StreamResponse(
            headers={
                "Content-Type": "text/event-stream",
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            }
        )
        await resp.prepare(request)
        queue = STATE.subscribe()
        try:
            await resp.write(f"data: {json.dumps({'mode': STATE.mode, 'reading': STATE.latest})}\n\n".encode())
            while True:
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=15)
                    await resp.write(f"data: {json.dumps(payload)}\n\n".encode())
                except asyncio.TimeoutError:
                    await resp.write(b": keepalive\n\n")  # a write to a closed socket raises -> handler ends
        except (asyncio.CancelledError, ConnectionResetError):
            pass
        finally:
            STATE.unsubscribe(queue)
        return resp

    async def get_control(request: web.Request) -> web.Response:
        return web.json_response(controller.status())

    async def set_control(request: web.Request) -> web.Response:
        try:
            data = await request.json()
            enabled, dry_run, plan = data.get("enabled"), data.get("dry_run"), data.get("plan")
            cover_load, adaptive_gain = data.get("cover_load"), data.get("adaptive_gain")
            if not all(isinstance(v, bool) or v is None for v in (enabled, dry_run, plan, cover_load, adaptive_gain)):
                raise ValueError("enabled/dry_run/plan/cover_load/adaptive_gain must be booleans")
            settings = data.get("settings")
            if settings is not None and not isinstance(settings, dict):
                raise ValueError("settings must be an object")
            device = data.get("device")
            if device is not None and not isinstance(device, dict):
                raise ValueError("device must be an object")
            await controller.configure(
                enabled=enabled, dry_run=dry_run, plan=plan, cover_load=cover_load,
                adaptive_gain=adaptive_gain, settings=settings, device=device,
            )
        except (ValueError, json.JSONDecodeError) as err:
            body = {"error": str(err)}
            if isinstance(err, MsgError):
                body["msg"] = err.msg.to_dict()  # the UI shows the reason in its own language
            return web.json_response(body, status=400)
        return web.json_response(controller.status())

    async def get_raw(request: web.Request) -> web.Response:
        return web.json_response(RAW.snapshot())

    async def raw_stream(request: web.Request) -> web.StreamResponse:
        """SSE: a hello marker first, then add/resp/clear events as they happen."""
        resp = web.StreamResponse(
            headers={"Content-Type": "text/event-stream", "Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"}
        )
        await resp.prepare(request)
        queue = RAW.subscribe()
        try:
            # Only a marker: the client fetches the buffer from /api/raw (compressed) and then
            # applies the events that follow, skipping ids it already has.
            await resp.write(f"data: {json.dumps({'type': 'hello', 'last_id': RAW.last_id, 'size': RAW.size})}\n\n".encode())
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=20)
                    await resp.write(f"data: {json.dumps(event)}\n\n".encode())
                except asyncio.TimeoutError:
                    await resp.write(b": keepalive\n\n")
        except (asyncio.CancelledError, ConnectionResetError):
            pass
        finally:
            RAW.unsubscribe(queue)
        return resp

    async def clear_raw(request: web.Request) -> web.Response:
        RAW.clear()
        return web.json_response({"ok": True})

    async def get_env(request: web.Request) -> web.Response:
        return web.json_response(describe_env())

    async def get_weather(request: web.Request) -> web.Response:
        return web.json_response(weather.status() if weather else {
            "available": False, "today": None, "tomorrow": None, "updated_at": None, "error": None,
        })

    for old, new in LEGACY_REDIRECTS.items():
        app.router.add_get(old, _redirect(new))
    app.router.add_get("/api/raw", get_raw)
    app.router.add_get("/api/raw/stream", raw_stream)
    app.router.add_post("/api/raw/clear", clear_raw)
    app.router.add_get("/api/env", get_env)
    app.router.add_get("/api/weather", get_weather)
    app.router.add_get("/api/control", get_control)
    app.router.add_post("/api/control", set_control)
    app.router.add_get("/api/state", get_state)
    app.router.add_get("/api/history", get_history)
    app.router.add_get("/api/history/long", get_history_long)
    app.router.add_get("/api/stream", stream)
    auth_mod.add_routes(app, auth)
    spa.add_routes(app, web_dir)
    return app


async def keepalive_loop(client: SunshareCloudClient, interval: float) -> None:
    """Runs regardless of mode — this is what makes the device push telemetry
    at all, whether you then read it back via cloud or tap it on the LAN."""
    while True:
        try:
            await client.open_realtime()
        except Exception:  # noqa: BLE001 - a background loop must never end the process
            _LOGGER.exception("Keepalive failed")
        await asyncio.sleep(interval)


async def cloud_poll_loop(client: SunshareCloudClient, mqtt_pub: MqttPublisher, interval: float) -> None:
    while True:
        try:
            if STATE.mode == "cloud":
                data = await client.read_live_flow()
                if data:
                    reading = normalize_cloud(data, client.device_id)
                    await STATE.publish(reading, mqtt_pub)
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Cloud poll failed")
        await asyncio.sleep(interval)


async def energy_poll_loop(client: SunshareCloudClient, mqtt_pub: MqttPublisher, interval: float) -> None:
    """Cumulative PV yield (kWh) — separate from the power-flow source above,
    runs regardless of cloud/lan display mode, needed for HA's Energy dashboard."""
    while True:
        try:
            data = await client.read_energy_summary()
            if data:
                await STATE.publish(normalize_energy_summary(data), mqtt_pub)
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Energy poll failed")
        await asyncio.sleep(interval)


async def weather_poll_loop(weather: WeatherClient, interval: float) -> None:
    """No-ops (see WeatherClient.available) unless OWM_API_KEY/OWM_LAT/OWM_LON are all set - runs
    unconditionally regardless, same as the other poll loops."""
    while True:
        try:
            await weather.poll()
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Weather poll failed")
        await asyncio.sleep(interval)


def _optional_float(value: str | None) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except ValueError:
        _LOGGER.warning("Ignoring invalid float env value %r", value)
        return None


async def main() -> None:
    user_account = os.environ["SUNSHARE_USER_ACCOUNT"]
    password = os.environ["SUNSHARE_PASSWORD"]
    device_id = int(os.environ["SUNSHARE_DEVICE_ID"])
    device_sn = os.environ["SUNSHARE_DEVICE_SN"]
    guest = guest_from_env(os.environ.get("SUNSHARE_USER_GUEST"))

    mqtt_host = os.environ["MQTT_HOST"]
    mqtt_port = int(os.environ.get("MQTT_PORT", "1883"))
    mqtt_username = os.environ.get("MQTT_USERNAME") or None
    mqtt_password = os.environ.get("MQTT_PASSWORD") or None
    mqtt_base_topic = os.environ.get("MQTT_BASE_TOPIC", "sunshare")

    ui_port = int(os.environ.get("UI_PORT", "8099"))
    lan_port = int(os.environ.get("LAN_PORT", "80"))
    keepalive_interval = float(os.environ.get("KEEPALIVE_INTERVAL", "3"))
    cloud_poll_interval = float(os.environ.get("CLOUD_POLL_INTERVAL", "2"))
    energy_poll_interval = float(os.environ.get("ENERGY_POLL_INTERVAL", "60"))
    weather_poll_interval = float(os.environ.get("WEATHER_POLL_INTERVAL", "1800"))

    mqtt_pub = MqttPublisher(mqtt_host, mqtt_port, mqtt_username, mqtt_password, mqtt_base_topic, device_id)

    async with aiohttp.ClientSession() as session:
        client = SunshareCloudClient(session, user_account, password, device_id, device_sn, guest)
        try:
            await client.login()
        except SunshareLoginError as err:
            # Do not exit: a crashing container is restarted and logs in again, which is exactly
            # what locks the account. The UI shows the error; the client waits before retrying.
            _LOGGER.error("Starting without Sunshare login: %s", err)

        # access_log=None: one line per request (every ~3s device push, every UI poll) drowns out
        # the app's own, actually useful INFO logs; a specific problem is still visible via each
        # handler's own logging (e.g. lan_proxy's raw_log) or LOG_LEVEL=DEBUG.
        lan_app = make_lan_app(STATE, mqtt_pub, session, device_id)
        lan_runner = web.AppRunner(lan_app, access_log=None)
        await lan_runner.setup()
        await web.TCPSite(lan_runner, "0.0.0.0", lan_port).start()

        controller = GridController(client, mqtt_host, mqtt_port, mqtt_username, mqtt_password)
        weather = WeatherClient(
            session, os.environ.get("OWM_API_KEY") or None,
            _optional_float(os.environ.get("OWM_LAT")), _optional_float(os.environ.get("OWM_LON")),
        )
        ui_runner = web.AppRunner(make_ui_app(controller, Auth.from_env(), weather=weather), access_log=None)
        await ui_runner.setup()
        await web.TCPSite(ui_runner, "0.0.0.0", ui_port).start()

        _LOGGER.info(
            "LAN listener on :%s, UI on :%s, starting mode=%s (device_id=%s, sn=%s, account=%s)",
            lan_port, ui_port, STATE.mode, device_id, device_sn, "guest" if guest else "main",
        )

        await asyncio.gather(
            keepalive_loop(client, keepalive_interval),
            cloud_poll_loop(client, mqtt_pub, cloud_poll_interval),
            energy_poll_loop(client, mqtt_pub, energy_poll_interval),
            weather_poll_loop(weather, weather_poll_interval),
            controller.run(),
        )


if __name__ == "__main__":
    asyncio.run(main())
