import asyncio

import pytest
from aiohttp.test_utils import TestClient, TestServer

import app.auth as auth_mod
from app.auth import COOKIE, Auth
from app.grid_control import GridController
from app.main import make_ui_app

SECRET = b"s" * 32


def _auth(password="correct horse"):
    return Auth("admin", password, SECRET)


def _run(check, auth, web_dir=None):
    async def go():
        app = make_ui_app(GridController(None, "broker", 1883, None, None), auth, web_dir)
        async with TestClient(TestServer(app)) as client:
            await check(client)
    asyncio.run(go())


@pytest.fixture(autouse=True)
def fast_failures(monkeypatch):
    monkeypatch.setattr(auth_mod, "FAIL_DELAY_S", 0)


@pytest.fixture
def web_dir(tmp_path):
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<html>shell</html>")
    (tmp_path / "assets" / "app-abc123.js").write_text("console.log(1)")
    (tmp_path / "manifest.webmanifest").write_text("{}")
    return tmp_path


def test_without_credentials_the_ui_stays_open_as_before():
    async def check(client):
        me = await (await client.get("/api/auth/me")).json()
        assert me == {"auth_required": False, "authenticated": True, "user": None, "version": "dev", "ingress": False}
        assert (await client.get("/api/state")).status == 200
        assert (await client.post("/api/auth/login", json={"user": "a", "password": "b"})).status == 404
    _run(check, None)


def test_me_reports_ingress_from_the_request_header():
    async def check(client):
        me = await (await client.get("/api/auth/me", headers={"X-Ingress-Path": "/api/hassio_ingress/abc123"})).json()
        assert me["ingress"] is True
        me = await (await client.get("/api/auth/me")).json()
        assert me["ingress"] is False
    _run(check, None)


def test_api_and_legacy_pages_need_a_session(web_dir):
    async def check(client):
        assert (await client.get("/api/state")).status == 401
        assert (await client.get("/api/stream")).status == 401
        assert (await client.post("/api/control", json={"enabled": True})).status == 401
        r = await client.get("/control", allow_redirects=False)
        assert r.status == 302 and r.headers["Location"] == "/app/"
        me = await (await client.get("/api/auth/me")).json()
        assert me["auth_required"] is True and me["authenticated"] is False
    _run(check, _auth(), web_dir)


def test_login_redirect_honours_the_ingress_path(web_dir):
    async def check(client):
        r = await client.get("/control", headers={"X-Ingress-Path": "/api/hassio_ingress/abc123"}, allow_redirects=False)
        assert r.status == 302 and r.headers["Location"] == "/api/hassio_ingress/abc123/app/"
    _run(check, _auth(), web_dir)


def test_login_sets_a_hardened_cookie_and_unlocks_the_api(web_dir):
    async def check(client):
        r = await client.post("/api/auth/login", json={"user": "admin", "password": "correct horse"})
        assert r.status == 200
        cookie = r.cookies[COOKIE]
        assert cookie["httponly"] and cookie["samesite"] == "Strict" and not cookie["secure"]
        assert (await client.get("/api/state")).status == 200  # the client keeps the cookie
        assert (await client.post("/api/auth/logout")).status == 200
        assert (await client.get("/api/state")).status == 401
    _run(check, _auth(), web_dir)


def test_cookie_is_secure_behind_an_https_proxy(web_dir):
    async def check(client):
        r = await client.post(
            "/api/auth/login", json={"user": "admin", "password": "correct horse"},
            headers={"X-Forwarded-Proto": "https"},
        )
        assert r.cookies[COOKIE]["secure"]
    _run(check, _auth(), web_dir)


@pytest.mark.parametrize("creds", [
    {"user": "admin", "password": "wrong"}, {"user": "root", "password": "correct horse"}, {"user": "admin"}, {},
])
def test_wrong_credentials_are_rejected(creds, web_dir):
    async def check(client):
        r = await client.post("/api/auth/login", json=creds)
        assert r.status in (400, 401) and COOKIE not in r.cookies
    _run(check, _auth(), web_dir)


def test_repeated_failures_lock_the_client_out_even_with_the_right_password(web_dir):
    async def check(client):
        for _ in range(auth_mod.MAX_FAILURES):
            assert (await client.post("/api/auth/login", json={"user": "admin", "password": "x"})).status == 401
        r = await client.post("/api/auth/login", json={"user": "admin", "password": "correct horse"})
        assert r.status == 429 and int(r.headers["Retry-After"]) > 0
    _run(check, _auth(), web_dir)


def test_foreign_origin_cannot_change_anything_even_with_a_session(web_dir):
    async def check(client):
        await client.post("/api/auth/login", json={"user": "admin", "password": "correct horse"})
        r = await client.post("/api/control", json={"enabled": False}, headers={"Origin": "https://evil.example"})
        assert r.status == 403
        r = await client.post("/api/control", json={"plan": True}, headers={"Origin": "null"})
        assert r.status == 403
        own = f"http://{client.server.host}:{client.server.port}"
        assert (await client.post("/api/control", json={"plan": True}, headers={"Origin": own})).status == 200
    _run(check, _auth(), web_dir)


def test_tokens_expire_and_cannot_be_forged_or_reused_after_a_password_change():
    a = _auth()
    token = a.make_token(now=1000)
    assert a.verify_token(token, now=1000 + 10)
    assert not a.verify_token(token, now=1000 + a.ttl + 1)                  # expired
    assert not a.verify_token(token[:-2] + "AA", now=1010)                  # bad signature
    assert not a.verify_token("x.y", now=1010) and not a.verify_token(None) and not a.verify_token("")
    assert not _auth("another password").verify_token(token, now=1010)      # password changed
    assert not Auth("admin", "correct horse", b"o" * 32).verify_token(token, now=1010)  # other secret


def test_bare_app_redirect_honours_the_ingress_path(web_dir):
    async def check(client):
        r = await client.get("/app", headers={"X-Ingress-Path": "/api/hassio_ingress/abc123"}, allow_redirects=False)
        assert r.status == 302 and r.headers["Location"] == "/api/hassio_ingress/abc123/app/"
    _run(check, _auth(), web_dir)


def test_spa_shell_assets_and_path_traversal(web_dir):
    async def check(client):
        r = await client.get("/app/")
        assert r.status == 200 and "shell" in await r.text() and r.headers["Cache-Control"] == "no-cache"
        assert "shell" in await (await client.get("/app/settings/deep/route")).text()  # client-side route
        r = await client.get("/app/assets/app-abc123.js")
        assert r.status == 200 and "immutable" in r.headers["Cache-Control"]
        assert (await client.get("/app/assets/missing.js")).status == 404          # not the HTML shell
        assert (await client.get("/app/manifest.webmanifest")).headers["Content-Type"].startswith("application/manifest+json")
    _run(check, _auth(), web_dir)


def test_spa_handler_refuses_path_traversal(tmp_path):
    """The HTTP client normalises `..` away, so build the request the handler would see."""
    from aiohttp import web
    from aiohttp.test_utils import make_mocked_request

    from app import spa

    root = tmp_path / "web"
    root.mkdir()
    (root / "index.html").write_text("shell")
    (tmp_path / "secret.txt").write_text("secret")
    handler = spa.make_handler(root)
    for tail in ("../secret.txt", "assets/../../secret.txt", "/etc/passwd"):
        request = make_mocked_request("GET", "/app/x", match_info={"tail": tail})
        with pytest.raises(web.HTTPNotFound):
            asyncio.run(handler(request))


def test_missing_frontend_build_is_a_clear_404(tmp_path):
    async def check(client):
        r = await client.get("/app/")
        assert r.status == 404 and "nicht gebaut" in await r.text()
    _run(check, _auth(), tmp_path)
