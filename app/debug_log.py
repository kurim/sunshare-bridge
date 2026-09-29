"""In-memory ring buffer of what the grid controller saw and how it reacted, for the "Debug" page
of the web UI: every meter sample, every control step (with the values it worked from and the
decision), every write to the device, export-guard moves, output adopted from the device, phase
changes and settings changes. It makes a curve in the chart traceable ("why was the setpoint 285 W
here?") without turning on LOG_LEVEL=DEBUG.

Volatile on purpose (not persisted). Entries carry a `Msg` (translated by the UI, like every other
status text) plus a few numbers (`ctx`) the decision was based on.
"""
from __future__ import annotations

import time
from collections import deque
from typing import Any

from .messages import Msg

DEBUG_LOG_SIZE = 3000  # ~1.5 days of one meter sample + one step per minute
KINDS = ("meter", "step", "write", "guard", "failsafe", "sync", "phase", "config")


class DebugLog:
    def __init__(self, size: int = DEBUG_LOG_SIZE) -> None:
        self.size = size
        self._entries: deque[dict[str, Any]] = deque(maxlen=size)
        self._seq = 0

    @property
    def last_id(self) -> int:
        return self._seq

    def add(self, kind: str, msg: Msg, **ctx: float | int | None) -> None:
        """`ctx`: the numbers behind the decision (None values are left out)."""
        if kind not in KINDS:
            raise ValueError(f"unknown debug kind {kind!r}")
        self._seq += 1
        self._entries.append({
            "id": self._seq,
            "t": time.time(),
            "kind": kind,
            "msg": msg.to_dict(),
            "ctx": {k: v for k, v in ctx.items() if v is not None},
        })

    def snapshot(self, since: int = 0) -> dict[str, Any]:
        """Entries with an id above `since` (all of them for 0), oldest first. `last_id` lets the client
        notice that the log was cleared or the bridge restarted (it then starts over)."""
        return {
            "entries": [e for e in self._entries if e["id"] > since],
            "last_id": self._seq,
            "size": self.size,
        }

    def clear(self) -> None:
        self._entries.clear()  # the counter keeps running: a client's `since` never matches new entries by accident


DEBUG = DebugLog()
