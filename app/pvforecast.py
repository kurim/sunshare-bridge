"""PV yield forecast from pvnode (API v2, https://pvnode.com): expected PV power in 15-minute steps
for today and tomorrow, shown on the dashboard as kWh per day plus a curve. Purely informational -
it never touches the battery plan or writes anything to the device. Off entirely unless
PVNODE_API_KEY and PVNODE_SITE_ID are both set (the site - roof surfaces, tilt, power - is set up
at pvnode.com/sites), same convention as the weather forecast ("not configured -> stays idle").

The free pvnode plan allows only a few hundred requests a month, so the last answer is cached in
/data: a restart (or a crash loop) does not ask again before the poll interval is over, and the
dashboard always reads the cached curve - "remaining today" is computed from it on every request.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import date, datetime, timedelta, tzinfo
from pathlib import Path
from typing import Any
from urllib.parse import quote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import aiohttp

from .messages import Msg

_LOGGER = logging.getLogger("sunshare.pvforecast")

FORECAST_URL = "https://api.pvnode.com/v2/forecast/{site_id}"
FORECAST_DAYS = 2  # today + tomorrow; the smallest plan (free) allows exactly this
CACHE_FILE = Path("/data/pvforecast.json")
TIMEOUT = aiohttp.ClientTimeout(total=20)
_NETWORK_ERRORS = (aiohttp.ClientError, asyncio.TimeoutError)

MIN_POLL_S = 600  # the plans allow at most one update per 10 minutes
DEFAULT_POLL_S = 21600  # 4 requests a day, ~120 a month: fits every plan
RETRY_S = 1800  # after a failed request (network, server error) - not after a rejected key or limit
DEFAULT_STEP_S = 900

_TIME_KEYS = ("timestamp", "time", "dtm", "datetime")
_POWER_KEYS = ("pv_power", "pv_watts", "power_w", "power")


def _zone(name: Any) -> ZoneInfo | None:
    try:
        return ZoneInfo(name) if isinstance(name, str) and name else None
    except (ZoneInfoNotFoundError, ValueError):
        return None


def parse_response(body: Any) -> tuple[str | None, list[tuple[float, float]]] | None:
    """(IANA timezone name, [(epoch seconds, watts)] sorted by time) from a v2 answer, or None if it
    holds no usable values. Timestamps are site-local wall-clock time, so a timestamp without an
    offset is resolved with the answer's own timezone (else the container's). Null power (night) is 0 W."""
    if not isinstance(body, dict) or not isinstance(body.get("values"), list):
        return None
    zone = _zone(body.get("timezone"))
    points: dict[float, float] = {}
    for row in body["values"]:
        if not isinstance(row, dict):
            continue
        raw_t = next((row[k] for k in _TIME_KEYS if row.get(k) is not None), None)
        raw_w = next((row[k] for k in _POWER_KEYS if k in row), None)
        try:
            moment = datetime.fromisoformat(str(raw_t))
            if moment.tzinfo is None and zone is not None:
                moment = moment.replace(tzinfo=zone)
            watts = 0.0 if raw_w is None else max(float(raw_w), 0.0)
            points[moment.timestamp()] = watts
        except (TypeError, ValueError, OverflowError):
            continue
    if not points:
        return None
    return (zone.key if zone else None), sorted(points.items())


def _step_s(series: list[tuple[float, float]]) -> int:
    gaps = sorted(b[0] - a[0] for a, b in zip(series, series[1:]) if b[0] > a[0])
    return int(gaps[len(gaps) // 2]) if gaps else DEFAULT_STEP_S


def _day_start(day: date, zone: tzinfo | None) -> float:
    return datetime(day.year, day.month, day.day, tzinfo=zone).timestamp()


def _day_summary(points: list[tuple[float, float]], step_s: int, now: float, with_remaining: bool) -> dict[str, Any] | None:
    if not points:
        return None
    kwh = sum(w for _, w in points) * step_s / 3600 / 1000
    peak_t, peak_w = max(points, key=lambda p: p[1])
    out: dict[str, Any] = {"kwh": round(kwh, 2), "peak_w": round(peak_w), "peak_t": int(peak_t)}
    if with_remaining:
        # a step still counts while it is running
        out["remaining_kwh"] = round(sum(w for t, w in points if t + step_s > now) * step_s / 3600 / 1000, 2)
    return out


class PvForecastClient:
    def __init__(
        self, session: aiohttp.ClientSession | None, api_key: str | None, site_id: str | None,
        poll_interval: float = DEFAULT_POLL_S, cache_file: Path | None = None,
    ) -> None:
        self._session = session
        self._api_key = api_key
        self._site_id = site_id
        self.interval = max(float(poll_interval), MIN_POLL_S)
        self._cache_file = cache_file or CACHE_FILE
        self.available = bool(api_key and site_id)
        self.series: list[tuple[float, float]] = []
        self.timezone: str | None = None
        self.updated_at: float | None = None
        self.error: Msg | None = None
        self._next_at = 0.0
        if self.available:
            self._load_cache()
            if self.updated_at is not None:
                self._next_at = self.updated_at + self.interval

    # ---- cache -------------------------------------------------------------------------------
    def _load_cache(self) -> None:
        try:
            saved = json.loads(self._cache_file.read_text())
            series = [(float(t), float(w)) for t, w in saved["series"]]
            self.series, self.timezone, self.updated_at = series, saved.get("timezone"), float(saved["updated_at"])
        except FileNotFoundError:
            pass
        except (OSError, ValueError, KeyError, TypeError):
            _LOGGER.warning("Ignoring unreadable forecast cache %s", self._cache_file)

    def _save_cache(self) -> None:
        try:
            tmp = self._cache_file.with_suffix(".tmp")
            tmp.write_text(json.dumps({"updated_at": self.updated_at, "timezone": self.timezone, "series": self.series}))
            tmp.replace(self._cache_file)
        except OSError:
            _LOGGER.warning("Could not write the forecast cache %s (is /data writable?)", self._cache_file)

    # ---- polling -----------------------------------------------------------------------------
    def _fail(self, msg: Msg, retry_s: float) -> None:
        self.error = msg
        self._next_at = time.time() + retry_s
        _LOGGER.warning("%s", msg)

    async def poll(self, force: bool = False) -> None:
        """One request if the interval is over (the loop calls this every minute); never raises."""
        if not self.available or self._session is None:
            return
        now = time.time()
        if not force and now < self._next_at:
            return
        try:
            async with self._session.get(
                FORECAST_URL.format(site_id=quote(str(self._site_id), safe="")),
                params={"forecast_days": str(FORECAST_DAYS)},
                headers={"Authorization": f"Bearer {self._api_key}", "Accept": "application/json"},
                timeout=TIMEOUT,
            ) as resp:
                status = resp.status
                body = await resp.json(content_type=None) if status == 200 else None
        except _NETWORK_ERRORS as err:
            self._fail(Msg("pvf.network", "error", reason=str(err) or "timeout"), min(self.interval, RETRY_S))
            return
        except ValueError:  # not JSON
            self._fail(Msg("pvf.invalid", "error"), min(self.interval, RETRY_S))
            return
        if status in (401, 403, 404):
            self._fail(Msg("pvf.auth", "error", status=status), self.interval)
            return
        if status == 429:
            self._fail(Msg("pvf.rate_limit", "warn"), self.interval)
            return
        if status != 200:
            self._fail(Msg("pvf.http", "error", status=status), min(self.interval, RETRY_S))
            return
        parsed = parse_response(body)
        if parsed is None:
            self._fail(Msg("pvf.invalid", "error"), min(self.interval, RETRY_S))
            return
        self._adopt(*parsed, now)

    def _adopt(self, tz_name: str | None, series: list[tuple[float, float]], now: float) -> None:
        # The answer may start at "now": keep the earlier hours of today that an earlier answer
        # delivered, so the daily total does not shrink as the day goes on.
        zone = _zone(tz_name)
        today = datetime.fromtimestamp(now, zone).date()
        first = series[0][0]
        kept = [p for p in self.series if _day_start(today, zone) <= p[0] < first]
        self.series, self.timezone = kept + series, tz_name
        self.updated_at, self.error = now, None
        self._next_at = now + self.interval
        self._save_cache()

    # ---- view --------------------------------------------------------------------------------
    def status(self, now: float | None = None) -> dict[str, Any]:
        now = time.time() if now is None else now
        out: dict[str, Any] = {
            "available": self.available, "updated_at": self.updated_at, "step_s": DEFAULT_STEP_S,
            "today": None, "tomorrow": None, "series": [], "error": self.error.to_dict() if self.error else None,
        }
        if not self.series:
            return out
        zone = _zone(self.timezone)  # None -> the container's local time (TZ)
        today = datetime.fromtimestamp(now, zone).date()
        start = _day_start(today, zone)
        mid = _day_start(today + timedelta(days=1), zone)
        end = _day_start(today + timedelta(days=2), zone)
        step = _step_s(self.series)
        today_pts = [p for p in self.series if start <= p[0] < mid]
        tomorrow_pts = [p for p in self.series if mid <= p[0] < end]
        out.update(
            step_s=step,
            today=_day_summary(today_pts, step, now, True),
            tomorrow=_day_summary(tomorrow_pts, step, now, False),
            series=[[int(t), round(w)] for t, w in today_pts + tomorrow_pts],
        )
        return out
