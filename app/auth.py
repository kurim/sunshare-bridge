"""Single-user login for the web UI.

`UI_USER` / `UI_PASSWORD` in the environment switch it on; without them the UI stays
open exactly as before (trusted LAN only) and a warning is logged. The session is a signed
cookie (`user.expiry` + HMAC), so nothing is stored server-side: a restart keeps sessions
valid (the signing secret lives in `data/session_secret`) and changing the password
invalidates all of them.

Meant to sit behind an HTTPS tunnel/proxy (Cloudflare Tunnel etc.): the cookie is `Secure`
when the proxy says the request came in over https, `HttpOnly` and `SameSite=Strict`, and
unsafe requests with a foreign `Origin` are refused (CSRF). Only the UI port may be exposed —
never the LAN proxy port.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import logging
import os
import secrets
import time
from pathlib import Path
from urllib.parse import urlsplit

from aiohttp import web

from .ingress import ingress_prefix
from .version import VERSION

_LOGGER = logging.getLogger("sunshare.auth")

COOKIE = "sb_session"
SESSION_TTL_S = 30 * 86400
SECRET_FILE = Path("/data/session_secret")

MAX_FAILURES = 5          # failed logins per client before it is blocked ...
FAILURE_WINDOW_S = 900    # ... within this window
MAX_BLOCK_S = 900
FAIL_DELAY_S = 0.6        # every failed attempt costs this much, a brute-force brake

# Reachable without a session: the login API and the static app shell (it holds no data).
PUBLIC_PREFIXES = ("/api/auth/", "/app/")


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _load_secret() -> bytes:
    env = os.environ.get("UI_SESSION_SECRET")
    if env:
        return env.encode()
    try:
        return SECRET_FILE.read_bytes()
    except OSError:
        pass
    secret = secrets.token_bytes(32)
    try:
        SECRET_FILE.parent.mkdir(parents=True, exist_ok=True)
        SECRET_FILE.write_bytes(secret)
        SECRET_FILE.chmod(0o600)
    except OSError:
        _LOGGER.warning("Could not persist the session secret to %s: logins end with a restart", SECRET_FILE)
    return secret


class Auth:
    def __init__(self, user: str, password: str, secret: bytes, ttl: int = SESSION_TTL_S) -> None:
        self.user = user
        self._password = password
        self.ttl = ttl
        # Bound to the password so that changing it logs everybody out.
        self._key = hmac.new(secret, hashlib.sha256(password.encode()).digest(), hashlib.sha256).digest()
        self._failures: dict[str, list[float]] = {}
        self._blocked_until: dict[str, float] = {}

    @classmethod
    def from_env(cls) -> "Auth | None":
        user, password = os.environ.get("UI_USER", ""), os.environ.get("UI_PASSWORD", "")
        if not user or not password:
            _LOGGER.warning("UI_USER/UI_PASSWORD not set: the web UI has NO login - trusted LAN only")
            return None
        if len(password) < 8:
            _LOGGER.warning("UI_PASSWORD is shorter than 8 characters")
        return cls(user, password, _load_secret())

    # ---- credentials / tokens ---------------------------------------------
    def check(self, user: str, password: str) -> bool:
        # Both comparisons always run, so timing does not reveal which one was wrong.
        ok_user = hmac.compare_digest(user.encode(), self.user.encode())
        ok_pw = hmac.compare_digest(password.encode(), self._password.encode())
        return ok_user and ok_pw

    def make_token(self, now: float | None = None) -> str:
        expiry = int((now if now is not None else time.time()) + self.ttl)
        payload = _b64(f"{self.user}\n{expiry}".encode())
        return f"{payload}.{_b64(hmac.new(self._key, payload.encode(), hashlib.sha256).digest())}"

    def verify_token(self, token: str | None, now: float | None = None) -> bool:
        if not token or token.count(".") != 1:
            return False
        payload, sig = token.split(".")
        expected = _b64(hmac.new(self._key, payload.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, expected):
            return False
        try:
            user, expiry = _unb64(payload).decode().split("\n")
            return user == self.user and int(expiry) > (now if now is not None else time.time())
        except (ValueError, UnicodeDecodeError):
            return False

    # ---- brute-force protection -------------------------------------------
    def retry_after(self, client: str, now: float | None = None) -> int:
        """Seconds until `client` may try again (0 = allowed)."""
        now = now if now is not None else time.time()
        return max(0, int(self._blocked_until.get(client, 0) - now + 0.999))

    def record_failure(self, client: str, now: float | None = None) -> None:
        now = now if now is not None else time.time()
        recent = [t for t in self._failures.get(client, []) if now - t < FAILURE_WINDOW_S] + [now]
        self._failures[client] = recent
        if len(recent) >= MAX_FAILURES:
            self._blocked_until[client] = now + min(MAX_BLOCK_S, 30 * 2 ** (len(recent) - MAX_FAILURES))
        if len(self._failures) > 1000:  # bounded memory under a scan
            self._failures.clear()
            self._blocked_until.clear()

    def record_success(self, client: str) -> None:
        self._failures.pop(client, None)
        self._blocked_until.pop(client, None)


def client_key(request: web.Request) -> str:
    """Cloudflare passes the visitor address in `CF-Connecting-IP`; otherwise the socket peer."""
    return request.headers.get("CF-Connecting-IP") or request.remote or "?"


def is_https(request: web.Request) -> bool:
    return request.secure or request.headers.get("X-Forwarded-Proto", "").split(",")[0].strip() == "https"


def _same_origin(request: web.Request) -> bool:
    origin = request.headers.get("Origin")
    if not origin or origin == "null":
        return origin is None  # no Origin header (same-origin GET / curl) is fine, "null" is not
    hosts = {request.host, request.headers.get("X-Forwarded-Host", "").split(",")[0].strip()}
    return urlsplit(origin).netloc in hosts


def make_middleware(auth: "Auth | None"):
    @web.middleware
    async def auth_middleware(request: web.Request, handler):
        if auth is None:
            return await handler(request)
        if request.method not in ("GET", "HEAD", "OPTIONS") and not _same_origin(request):
            return web.json_response({"error": "forbidden origin"}, status=403)
        path = request.path
        if path.startswith(PUBLIC_PREFIXES) or path == "/app" or auth.verify_token(request.cookies.get(COOKIE)):
            return await handler(request)
        if path.startswith("/api/"):
            return web.json_response({"error": "unauthorized"}, status=401)
        raise web.HTTPFound(ingress_prefix(request) + "/app/")  # legacy HTML pages: send to the login screen
    return auth_middleware


def add_routes(app: web.Application, auth: "Auth | None") -> None:
    async def me(request: web.Request) -> web.Response:
        if auth is None:
            return web.json_response({"auth_required": False, "authenticated": True, "user": None, "version": VERSION})
        ok = auth.verify_token(request.cookies.get(COOKIE))
        return web.json_response(
            {"auth_required": True, "authenticated": ok, "user": auth.user if ok else None, "version": VERSION}
        )

    async def login(request: web.Request) -> web.Response:
        if auth is None:
            return web.json_response({"error": "login is not enabled"}, status=404)
        client = client_key(request)
        wait = auth.retry_after(client)
        if wait:
            return web.json_response({"error": "too many attempts"}, status=429, headers={"Retry-After": str(wait)})
        try:
            data = await request.json()
            user, password = data.get("user"), data.get("password")
            if not isinstance(user, str) or not isinstance(password, str):
                raise ValueError
        except (ValueError, AttributeError):
            return web.json_response({"error": "user and password required"}, status=400)
        if not auth.check(user, password):
            auth.record_failure(client)
            _LOGGER.warning("Failed UI login from %s", client)
            await asyncio.sleep(FAIL_DELAY_S)
            return web.json_response({"error": "wrong user or password"}, status=401)
        auth.record_success(client)
        resp = web.json_response({"auth_required": True, "authenticated": True, "user": auth.user})
        resp.set_cookie(
            COOKIE, auth.make_token(), max_age=auth.ttl, path="/",
            httponly=True, samesite="Strict", secure=is_https(request),
        )
        return resp

    async def logout(request: web.Request) -> web.Response:
        resp = web.json_response({"ok": True})
        resp.del_cookie(COOKIE, path="/")
        return resp

    app.router.add_get("/api/auth/me", me)
    app.router.add_post("/api/auth/login", login)
    app.router.add_post("/api/auth/logout", logout)
