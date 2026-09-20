"""In-memory ring buffer of everything the inverter pushes to the telemetry endpoint
(/collect-service/collect/emsRealDataMinute/realTimeElectricFlow), byte-for-byte as it
arrived and before any parsing, plus what the real backend answered. Feeds the "Raw"
page of the web UI so unknown fields / parse problems can be inspected.

Volatile on purpose (not persisted). Authorization/cookie headers are redacted.
"""
from __future__ import annotations

import asyncio
import os
import time
from collections import deque
from typing import Any

MAX_BODY_CHARS = 16000
MAX_RESP_CHARS = 4000
_REDACT = {"authorization", "proxy-authorization", "cookie", "set-cookie"}


class RawLog:
    def __init__(self, size: int) -> None:
        self.size = size
        self._entries: deque[dict[str, Any]] = deque(maxlen=size)
        self._subscribers: set[asyncio.Queue] = set()
        self._seq = 0

    # ---- subscribers (SSE) ------------------------------------------------
    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=1000)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self._subscribers.discard(queue)

    def _emit(self, event: dict[str, Any]) -> None:
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                self._subscribers.discard(queue)  # dead/slow client: it reconnects and gets a snapshot

    # ---- writers ----------------------------------------------------------
    def add(self, method: str, path: str, remote: str | None, headers: dict[str, str], body: bytes) -> dict[str, Any]:
        self._seq += 1
        text = body.decode("utf-8", errors="replace")
        entry = {
            "id": self._seq,
            "t": time.time(),
            "method": method,
            "path": path,
            "remote": remote,
            "headers": {k: ("***" if k.lower() in _REDACT else v) for k, v in headers.items()},
            "size": len(body),
            "body": text[:MAX_BODY_CHARS],
            "truncated": len(text) > MAX_BODY_CHARS,
            "resp_status": None,
            "resp_body": None,
        }
        self._entries.append(entry)
        self._emit({"type": "add", "entry": entry})
        return entry

    def set_response(self, entry: dict[str, Any], status: int, body: str) -> None:
        entry["resp_status"] = status
        entry["resp_body"] = body[:MAX_RESP_CHARS]
        self._emit({"type": "resp", "id": entry["id"], "resp_status": status, "resp_body": entry["resp_body"]})

    def clear(self) -> None:
        self._entries.clear()
        self._emit({"type": "clear"})

    @property
    def last_id(self) -> int:
        return self._seq

    def snapshot(self) -> list[dict[str, Any]]:
        return list(self._entries)


def _size() -> int:
    try:
        return max(10, int(os.environ.get("RAW_LOG_SIZE", "500")))
    except ValueError:
        return 500


RAW = RawLog(_size())
