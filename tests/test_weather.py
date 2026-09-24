import asyncio

from app.weather import WeatherClient, _day_average, _outlook


class FakeResponse:
    def __init__(self, data):
        self._data = data

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def json(self, content_type=None):
        return self._data


class FakeSession:
    def __init__(self, reply):
        self.reply = reply
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if isinstance(self.reply, Exception):
            raise self.reply
        return FakeResponse(self.reply)


def _slot(dt, clouds, pop=0.0):
    return {"dt": dt, "clouds": {"all": clouds}, "pop": pop}


def test_unavailable_without_api_key_or_coordinates():
    c = WeatherClient(FakeSession({}), None, 52.5, 13.4)
    assert c.available is False
    c2 = WeatherClient(FakeSession({}), "key", None, 13.4)
    assert c2.available is False


def test_poll_is_a_no_op_when_unavailable():
    c = WeatherClient(None, None, None, None)  # session itself is never touched
    asyncio.run(c.poll())
    assert c.today is None and c.error is None


def test_outlook_buckets():
    assert _outlook(10) == "sunny"
    assert _outlook(20) == "sunny"
    assert _outlook(21) == "partly"
    assert _outlook(60) == "partly"
    assert _outlook(61) == "cloudy"


def test_day_average_buckets_slots_by_local_date():
    import time

    now = time.mktime((2026, 6, 1, 8, 0, 0, 0, 0, -1))
    today_noon = time.mktime((2026, 6, 1, 12, 0, 0, 0, 0, -1))
    tomorrow_noon = time.mktime((2026, 6, 2, 12, 0, 0, 0, 0, -1))
    slots = [_slot(today_noon, 10, 0.1), _slot(today_noon + 3 * 3600, 30, 0.3), _slot(tomorrow_noon, 80, 0.9)]
    today = _day_average(slots, 0, now)
    tomorrow = _day_average(slots, 1, now)
    assert today == {"clouds_pct": 20, "pop_pct": 20, "outlook": "sunny"}
    assert tomorrow == {"clouds_pct": 80, "pop_pct": 90, "outlook": "cloudy"}


def test_day_average_is_none_when_the_forecast_does_not_reach_that_far():
    import time

    now = time.mktime((2026, 6, 1, 8, 0, 0, 0, 0, -1))
    slots = [_slot(now, 10)]
    assert _day_average(slots, 3, now) is None


def test_poll_fills_today_and_tomorrow_from_a_successful_response():
    import time

    now = time.time()
    slots = [
        {"dt": now, "clouds": {"all": 15}, "pop": 0.0},
        {"dt": now + 86400, "clouds": {"all": 90}, "pop": 0.8},
    ]
    session = FakeSession({"cod": "200", "list": slots})
    c = WeatherClient(session, "key", 52.5, 13.4)
    asyncio.run(c.poll())
    assert c.error is None and c.updated_at is not None
    assert c.today["outlook"] == "sunny" and c.tomorrow["outlook"] == "cloudy"
    (url, kwargs) = session.calls[0]
    assert url == "https://api.openweathermap.org/data/2.5/forecast"
    assert kwargs["params"] == {"lat": 52.5, "lon": 13.4, "appid": "key", "units": "metric"}


def test_poll_records_a_network_error_without_raising():
    c = WeatherClient(FakeSession(asyncio.TimeoutError()), "key", 52.5, 13.4)
    asyncio.run(c.poll())
    assert c.error == "timeout" and c.today is None


def test_poll_records_an_api_error_response():
    c = WeatherClient(FakeSession({"cod": "401", "message": "Invalid API key"}), "key", 52.5, 13.4)
    asyncio.run(c.poll())
    assert c.error == "Invalid API key" and c.today is None


def test_status_reports_the_current_snapshot():
    c = WeatherClient(FakeSession({}), None, None, None)
    assert c.status() == {"available": False, "today": None, "tomorrow": None, "updated_at": None, "error": None}
