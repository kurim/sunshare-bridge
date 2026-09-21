import asyncio

import pytest

from app import sunshare_cloud as sc
from app.grid_control import GridController
from app.sunshare_cloud import SunshareCloudClient, SunshareLoginError, _server_wait_s

LOCKED = {"msg": "Account locked Please try again in 5 minutes", "code": 500}
WRONG = {"msg": "Wrong password", "code": 500}
OK = {"code": 200, "data": {"access_token": "tok"}}


class FakeResponse:
    def __init__(self, data):
        self._data = data

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def json(self, content_type=None):
        return self._data

    async def text(self):
        return ""


class FakeRequest(FakeResponse):
    """What session.post() returns: usable as `async with` and with `await`."""

    def __await__(self):
        async def resp():
            return self
        return resp().__await__()


class FakeSession:
    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append(url)
        reply = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        if isinstance(reply, Exception):
            raise reply
        return FakeRequest(reply)


@pytest.fixture
def clock(monkeypatch):
    now = [1_000_000.0]
    monkeypatch.setattr(sc.time, "time", lambda: now[0])
    return now


def _client(session):
    return SunshareCloudClient(session, "u", "p", 1, "SN")


@pytest.mark.parametrize("msg, seconds", [
    ("Account locked Please try again in 5 minutes", 300),
    ("try again in 30 seconds", 30), ("Try again in 1 hour", 3600), ("try again in 2 min", 120),
    ("Wrong password", None), ("", None),
])
def test_server_wait_is_parsed(msg, seconds):
    assert _server_wait_s(msg) == seconds


def test_locked_account_pauses_logins_instead_of_hammering(clock):
    session = FakeSession(LOCKED)
    client = _client(session)
    with pytest.raises(SunshareLoginError, match="Account locked"):
        asyncio.run(client.login())
    assert len(session.calls) == 1
    status = client.login_status()
    assert status["ok"] is False and status["retry_in_s"] == 360  # 5 min + 60 s
    assert status["error"]["key"] == "login.failed" and "Account locked" in status["error"]["params"]["msg"]

    for _ in range(20):  # every loop iteration / re-login attempt is refused locally
        with pytest.raises(SunshareLoginError):
            asyncio.run(client.login())
    assert len(session.calls) == 1

    clock[0] += 361  # waited it out: one new attempt is allowed
    session.replies = [OK]
    asyncio.run(client.login())
    assert len(session.calls) == 2 and client.login_status() == {"ok": True, "error": None, "retry_in_s": None}


def test_wrong_password_backs_off_exponentially_up_to_the_cap(clock):
    session = FakeSession(WRONG)
    client = _client(session)
    waits = []
    for _ in range(6):
        with pytest.raises(SunshareLoginError):
            asyncio.run(client.login())
        waits.append(client.login_status()["retry_in_s"])
        clock[0] += waits[-1] + 1
    assert waits == [300, 600, 1200, 1800, 1800, 1800]


def test_unreachable_server_only_pauses_briefly(clock):
    client = _client(FakeSession(asyncio.TimeoutError()))
    with pytest.raises(SunshareLoginError, match="not reachable"):
        asyncio.run(client.login())
    assert client.login_status()["retry_in_s"] == sc.LOGIN_NETWORK_BACKOFF_S


def test_callers_do_not_raise_and_send_nothing_while_the_login_is_paused(clock):
    session = FakeSession(LOCKED)
    client = _client(session)

    async def all_calls():
        await client.open_realtime()
        assert await client.read_live_flow() is None
        assert await client.read_energy_summary() is None
        assert await client.read_ems_settings() is None
        assert await client.set_output_power(100) is False
        assert await client.set_device_limits(soc_min=15) is False

    asyncio.run(all_calls())
    assert len(session.calls) == 1  # only the very first login went out


def test_a_rejected_token_triggers_one_relogin_that_may_fail_quietly(clock):
    session = FakeSession(OK, {"code": 401, "msg": "token expired"}, LOCKED)
    client = _client(session)
    asyncio.run(client.login())
    assert asyncio.run(client.read_ems_settings()) is None  # 401 -> relogin -> locked, no exception
    assert client.login_status()["ok"] is False
    assert asyncio.run(client.read_ems_settings()) is None
    assert sum(u.endswith("auth/login") for u in session.calls) == 2  # not a request more


def test_control_status_carries_the_login_state(clock):
    client = _client(FakeSession(LOCKED))
    with pytest.raises(SunshareLoginError):
        asyncio.run(client.login())
    login = GridController(client, "broker", 1883, None, None).status()["cloud_login"]
    assert login["ok"] is False and login["error"]["key"] == "login.failed"
    assert "Account locked" in login["error"]["params"]["msg"]
    assert GridController(None, "broker", 1883, None, None).status()["cloud_login"] is None
