"""Home Assistant Supervisor Ingress: Supervisor reverse-proxies the UI under a per-install
path like /api/hassio_ingress/<token>/ and strips that prefix before forwarding to us - our own
routes stay exactly where they are (/app/*, /api/*). The only place this prefix matters is a
`Location` header on a redirect: the browser resolves it against the original, still-prefixed
URL, so a plain "/app/" would silently drop the token. Supervisor sends the prefix back to us on
every proxied request via X-Ingress-Path; standalone requests never carry it, so this is a no-op
outside of Ingress.
"""
from __future__ import annotations

from aiohttp import web


def ingress_prefix(request: web.Request) -> str:
    return request.headers.get("X-Ingress-Path", "").rstrip("/")
