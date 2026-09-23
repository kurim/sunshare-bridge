"""Serves the built React app (frontend/, Vite output) under /app/ with a fallback to
index.html for client-side routes. Hashed files in /app/assets/ are cached forever;
index.html, the service worker and the manifest are always revalidated."""
from __future__ import annotations

import mimetypes
import os
from pathlib import Path

from aiohttp import web

from .ingress import ingress_prefix

BASE = "/app"
_HERE = Path(__file__).resolve().parent


def default_web_dir() -> Path:
    env = os.environ.get("WEB_DIR")
    if env:
        return Path(env)
    built = _HERE / "web"  # inside the Docker image
    return built if built.is_dir() else _HERE.parent / "frontend" / "dist"  # local `npm run build`


def make_handler(root: Path):
    root = root.resolve()

    async def serve(request: web.Request) -> web.StreamResponse:
        index = root / "index.html"
        if not index.is_file():
            return web.Response(
                status=404, text="Frontend nicht gebaut (siehe README: cd frontend && npm ci && npm run build)"
            )
        rel = request.match_info.get("tail", "")
        target = (root / rel).resolve() if rel else index
        if root not in target.parents and target != root:
            raise web.HTTPNotFound()  # path traversal
        if not target.is_file():
            if Path(rel).suffix:  # a missing asset must 404, not turn into the HTML shell
                raise web.HTTPNotFound()
            target = index
        headers = {"Cache-Control": "no-cache"}
        if target.parent.name == "assets":
            headers["Cache-Control"] = "public, max-age=31536000, immutable"
        ctype = mimetypes.guess_type(target.name)[0]
        if target.suffix == ".webmanifest":
            ctype = "application/manifest+json"
        resp = web.FileResponse(target, headers=headers)
        if ctype:
            resp.content_type = ctype
        return resp

    return serve


def add_routes(app: web.Application, web_dir: Path | None = None) -> None:
    serve = make_handler(web_dir or default_web_dir())

    async def redirect(request: web.Request) -> web.StreamResponse:
        raise web.HTTPFound(ingress_prefix(request) + BASE + "/")

    app.router.add_get(BASE, redirect)
    app.router.add_get(BASE + "/", serve)
    app.router.add_get(BASE + "/{tail:.+}", serve)
