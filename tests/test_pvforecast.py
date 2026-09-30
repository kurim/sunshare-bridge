import asyncio
import json
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import aiohttp
import pytest

from app import pvforecast
from app.pvforecast import PvForecastClient, parse_response

BERLIN = ZoneInfo("Europe/Berlin")


def _ts(day: int, hour: int, minute: int = 0, month: int = 6) -> float:
    return datetime(2026, month, day, hour, minute, tzinfo=BERLIN).timestamp()


def _body(rows, tz="Europe/Berlin"):
    return {"timezone": tz, "values": rows}


class FakeResponse:
    def __init__(self, status, data):
        self.status, self._data = status, data

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def json(self, content_type=None):
        if isinstance(self._data, Exception):
            raise self._data
        return self._data


class FakeSession:
    def __init__(self, reply, status=200):
        self.reply, self.status, self.calls = reply, status, []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if isinstance(self.reply, Exception) and not isinstance(self.reply, ValueError):
            raise self.reply
        return FakeResponse(self.status, self.reply)


def _client(tmp_path, session, **kw):
    return PvForecastClient(session, "key", "site-1", cache_file=tmp_path / "pvforecast.json", **kw)


def test_unavailable_without_key_or_site(tmp_path):
    assert _client(tmp_path, None).available is True
    assert PvForecastClient(None, None, "s", cache_file=tmp_path / "c").available is False
    assert PvForecastClient(None, "k", "", cache_file=tmp_path / "c").available is False


def test_poll_is_a_no_op_when_unavailable():
    c = PvForecastClient(None, None, None)  # the session is never touched
    asyncio.run(c.poll())
    assert c.series == [] and c.error is None
    assert c.status()["available"] is False and c.status()["series"] == []


def test_parse_resolves_naive_timestamps_with_the_answers_timezone():
    tz, series = parse_response(_body([
        {"timestamp": "2026-06-01T12:00:00", "pv_power": 1500},
        {"timestamp": "2026-06-01T12:15:00", "pv_power": None},
    ]))
    assert tz == "Europe/Berlin"
    assert series == [(_ts(1, 12), 1500.0), (_ts(1, 12, 15), 0.0)]


def test_parse_honours_an_explicit_offset_and_other_field_names():
    _, series = parse_response(_body([{"dtm": "2026-06-01T10:00:00Z", "pv_watts": 800}]))
    assert series == [(datetime(2026, 6, 1, 10, tzinfo=ZoneInfo("UTC")).timestamp(), 800.0)]


def test_parse_sorts_drops_duplicates_and_broken_rows():
    _, series = parse_response(_body([
        {"timestamp": "2026-06-01T13:00:00", "pv_power": 5},
        {"timestamp": "not a date", "pv_power": 1},
        "junk",
        {"timestamp": "2026-06-01T12:00:00", "pv_power": 7},
        {"timestamp": "2026-06-01T13:00:00", "pv_power": 9},
        {"timestamp": "2026-06-01T14:00:00", "pv_power": "n/a"},
    ]))
    assert series == [(_ts(1, 12), 7.0), (_ts(1, 13), 9.0)]


@pytest.mark.parametrize("body", [None, [], {}, {"values": "x"}, {"values": []}, {"values": [{"pv_power": 1}]}])
def test_parse_rejects_answers_without_usable_values(body):
    assert parse_response(body) is None


def _fill(c, now):
    """Two full days of 15-minute steps: 1000 W between 08:00 and 16:00 today, 2000 W tomorrow."""
    rows = []
    for day, watts in ((1, 1000), (2, 2000)):
        for minutes in range(0, 24 * 60, 15):
            h, m = divmod(minutes, 60)
            rows.append({"timestamp": f"2026-06-0{day}T{h:02d}:{m:02d}:00", "pv_power": watts if 8 <= h < 16 else 0})
    c._adopt(*parse_response(_body(rows)), now)


def test_status_sums_days_remaining_and_peak(tmp_path):
    c = _client(tmp_path, None)
    now = _ts(1, 12, 5)
    _fill(c, now)
    s = c.status(now)
    assert s["today"]["kwh"] == 8.0 and s["tomorrow"]["kwh"] == 16.0
    # the 12:00 step is still running at 12:05 and counts: 12:00-16:00 = 4 kWh
    assert s["today"]["remaining_kwh"] == 4.0
    assert s["today"]["peak_w"] == 1000 and s["tomorrow"]["peak_w"] == 2000
    assert s["step_s"] == 900 and len(s["series"]) == 2 * 96
    assert s["series"][0] == [int(_ts(1, 0)), 0]


def test_status_rolls_over_to_the_next_day(tmp_path):
    c = _client(tmp_path, None)
    _fill(c, _ts(1, 12))
    s = c.status(_ts(2, 9))
    assert s["today"]["kwh"] == 16.0 and s["tomorrow"] is None


def test_status_empty_before_the_first_answer(tmp_path):
    s = _client(tmp_path, None).status()
    assert s["available"] and s["today"] is None and s["series"] == [] and s["error"] is None


def test_poll_requests_site_forecast_with_bearer_key(tmp_path):
    body = _body([{"timestamp": "2026-06-01T12:00:00", "pv_power": 900}])
    session = FakeSession(body)
    c = _client(tmp_path, session)
    asyncio.run(c.poll())
    (url, kw), = session.calls
    assert url == "https://api.pvnode.com/v2/forecast/site-1"
    assert kw["headers"]["Authorization"] == "Bearer key" and kw["params"] == {"forecast_days": "2"}
    assert c.error is None and c.updated_at is not None and c.series == [(_ts(1, 12), 900.0)]


def test_site_id_is_quoted_into_the_path(tmp_path):
    session = FakeSession(_body([{"timestamp": "2026-06-01T12:00:00", "pv_power": 1}]))
    c = PvForecastClient(session, "key", "a/b c", cache_file=tmp_path / "c.json")
    asyncio.run(c.poll())
    assert session.calls[0][0] == "https://api.pvnode.com/v2/forecast/a%2Fb%20c"


def test_no_second_request_before_the_interval_is_over(tmp_path):
    session = FakeSession(_body([{"timestamp": "2026-06-01T12:00:00", "pv_power": 1}]))
    c = _client(tmp_path, session, poll_interval=3600)
    asyncio.run(c.poll())
    asyncio.run(c.poll())
    assert len(session.calls) == 1
    c._next_at = 0
    asyncio.run(c.poll())
    assert len(session.calls) == 2


def test_interval_is_at_least_ten_minutes(tmp_path):
    assert _client(tmp_path, None, poll_interval=5).interval == pvforecast.MIN_POLL_S


def test_a_restart_uses_the_cache_instead_of_asking_again(tmp_path):
    first = _client(tmp_path, FakeSession(_body([{"timestamp": "2026-06-01T12:00:00", "pv_power": 500}])))
    asyncio.run(first.poll())
    session = FakeSession(_body([]))
    again = _client(tmp_path, session)
    asyncio.run(again.poll())
    assert session.calls == []
    assert again.series == [(_ts(1, 12), 500.0)] and again.updated_at == first.updated_at


def test_a_stale_cache_is_shown_but_refreshed(tmp_path):
    (tmp_path / "pvforecast.json").write_text(json.dumps(
        {"updated_at": time.time() - 10 * 86400, "timezone": "Europe/Berlin", "series": [[_ts(1, 12), 500.0]]}))
    session = FakeSession(_body([{"timestamp": "2026-06-01T13:00:00", "pv_power": 1}]))
    c = _client(tmp_path, session)
    assert c.series  # visible right away
    asyncio.run(c.poll())
    assert len(session.calls) == 1


def test_a_corrupt_cache_is_ignored(tmp_path):
    (tmp_path / "pvforecast.json").write_text("{not json")
    c = _client(tmp_path, None)
    assert c.series == [] and c.updated_at is None


def test_earlier_hours_of_today_survive_a_later_answer(tmp_path):
    c = _client(tmp_path, None)
    _adopt = lambda rows, now: c._adopt(*parse_response(_body(rows)), now)  # noqa: E731
    _adopt([{"timestamp": "2026-06-01T10:00:00", "pv_power": 100}, {"timestamp": "2026-06-01T11:00:00", "pv_power": 200}], _ts(1, 10))
    _adopt([{"timestamp": "2026-06-01T11:00:00", "pv_power": 250}, {"timestamp": "2026-06-01T12:00:00", "pv_power": 300}], _ts(1, 11, 5))
    assert c.series == [(_ts(1, 10), 100.0), (_ts(1, 11), 250.0), (_ts(1, 12), 300.0)]
    # ... but yesterday's points are dropped
    _adopt([{"timestamp": "2026-06-02T09:00:00", "pv_power": 1}], _ts(2, 8))
    assert c.series == [(_ts(2, 9), 1.0)]


@pytest.mark.parametrize("status,key,retry", [
    (401, "pvf.auth", "interval"), (403, "pvf.auth", "interval"), (404, "pvf.auth", "interval"),
    (429, "pvf.rate_limit", "interval"), (500, "pvf.http", "retry"),
])
def test_http_errors_are_reported_and_keep_the_last_forecast(tmp_path, status, key, retry):
    c = _client(tmp_path, FakeSession({}, status=status), poll_interval=21600)
    c.series = [(_ts(1, 12), 500.0)]
    before = time.time()
    asyncio.run(c.poll())
    assert c.error.key == key and c.series == [(_ts(1, 12), 500.0)]
    wait = c._next_at - before
    assert (wait >= 21000) if retry == "interval" else (wait <= pvforecast.RETRY_S + 5)
    assert c.status()["error"]["key"] == key


@pytest.mark.parametrize("reply,key", [
    (asyncio.TimeoutError(), "pvf.network"), (aiohttp.ClientConnectionError("down"), "pvf.network"),
    (ValueError("not json"), "pvf.invalid"),
])
def test_network_and_format_errors_are_reported_without_raising(tmp_path, reply, key):
    c = _client(tmp_path, FakeSession(reply))
    asyncio.run(c.poll())
    assert c.error.key == key and c.updated_at is None


def test_an_answer_without_values_is_an_error(tmp_path):
    c = _client(tmp_path, FakeSession({"timezone": "Europe/Berlin", "values": []}))
    asyncio.run(c.poll())
    assert c.error.key == "pvf.invalid"


def test_a_good_answer_clears_the_error(tmp_path):
    c = _client(tmp_path, FakeSession({}, status=500))
    asyncio.run(c.poll())
    assert c.error is not None
    c._session, c._next_at = FakeSession(_body([{"timestamp": "2026-06-01T12:00:00", "pv_power": 1}])), 0
    asyncio.run(c.poll())
    assert c.error is None


def test_the_api_key_never_appears_in_the_status_or_the_error(tmp_path):
    c = PvForecastClient(FakeSession({}, status=401), "s3cr3t-key", "site-1", cache_file=tmp_path / "c.json")
    asyncio.run(c.poll())
    assert "s3cr3t-key" not in json.dumps(c.status()) and "s3cr3t-key" not in str(c.error)
