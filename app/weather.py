"""OpenWeatherMap forecast: a coarse, read-only PV outlook for today/tomorrow shown on the
dashboard (cloud cover % and rain probability, averaged over the local day from the free
5-day/3-hour forecast). Purely informational - it never touches the battery plan or writes
anything to the device; the user decides for themselves whether to raise NIGHT_MIN_SOC or
CHARGE_RESERVE_W ahead of a bad day. Off entirely unless OWM_API_KEY, OWM_LAT and OWM_LON are
all set, same convention as the grid meter ("not configured -> stays idle").
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import aiohttp

_LOGGER = logging.getLogger("sunshare.weather")

FORECAST_URL = "https://api.openweathermap.org/data/2.5/forecast"
TIMEOUT = aiohttp.ClientTimeout(total=15)
_NETWORK_ERRORS = (aiohttp.ClientError, asyncio.TimeoutError)

# Coarse cloud-cover buckets for the UI's icon/label; the raw percentage is sent along too.
SUNNY_MAX_PCT = 20
PARTLY_MAX_PCT = 60


def _outlook(clouds_pct: float) -> str:
    if clouds_pct <= SUNNY_MAX_PCT:
        return "sunny"
    if clouds_pct <= PARTLY_MAX_PCT:
        return "partly"
    return "cloudy"


def _day_average(slots: list[dict[str, Any]], day_offset: int, now: float) -> dict[str, Any] | None:
    """Averages the 3-hourly forecast slots whose timestamp falls on local today+day_offset
    (0 = today, 1 = tomorrow). None if the forecast doesn't reach that far (e.g. late in the day,
    "tomorrow" needs slots the free 5-day forecast may not cover)."""
    target = time.strftime("%Y-%m-%d", time.localtime(now + day_offset * 86400))
    clouds = pop = 0.0
    count = 0
    for slot in slots:
        dt = slot.get("dt")
        if dt is None or time.strftime("%Y-%m-%d", time.localtime(dt)) != target:
            continue
        clouds += (slot.get("clouds") or {}).get("all", 0)
        pop += (slot.get("pop") or 0) * 100
        count += 1
    if count == 0:
        return None
    clouds_pct = round(clouds / count)
    return {"clouds_pct": clouds_pct, "pop_pct": round(pop / count), "outlook": _outlook(clouds_pct)}


class WeatherClient:
    def __init__(self, session: aiohttp.ClientSession, api_key: str | None, lat: float | None, lon: float | None) -> None:
        self._session = session
        self._api_key = api_key
        self._lat = lat
        self._lon = lon
        self.available = bool(api_key and lat is not None and lon is not None)
        self.today: dict[str, Any] | None = None
        self.tomorrow: dict[str, Any] | None = None
        self.updated_at: float | None = None
        self.error: str | None = None

    def status(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "today": self.today,
            "tomorrow": self.tomorrow,
            "updated_at": self.updated_at,
            "error": self.error,
        }

    async def poll(self) -> None:
        if not self.available:
            return
        try:
            async with self._session.get(
                FORECAST_URL,
                params={"lat": self._lat, "lon": self._lon, "appid": self._api_key, "units": "metric"},
                timeout=TIMEOUT,
            ) as resp:
                data = await resp.json(content_type=None)
        except _NETWORK_ERRORS as err:
            self.error = str(err) or "timeout"
            _LOGGER.warning("OpenWeatherMap forecast request failed: %s", self.error)
            return
        if not isinstance(data, dict) or str(data.get("cod")) != "200":
            self.error = str(data.get("message")) if isinstance(data, dict) and data.get("message") else "invalid response"
            _LOGGER.warning("OpenWeatherMap forecast rejected: %s", self.error)
            return
        slots = data.get("list") or []
        now = time.time()
        self.today = _day_average(slots, 0, now)
        self.tomorrow = _day_average(slots, 1, now)
        self.updated_at = now
        self.error = None
