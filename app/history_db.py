"""Long-term power history: one averaged sample per minute in SQLite (/data/history.db),
so the power-flow chart can look back days and survives container restarts.

The live view keeps using the in-memory deque of raw readings (see state.py); this only
feeds the longer ranges. A failing/unwritable database disables the feature (logged once)
but never affects telemetry.
"""
from __future__ import annotations

import logging
import math
import sqlite3
import time
from pathlib import Path
from typing import Any

_LOGGER = logging.getLogger("sunshare.history")

# Column names are the reading keys the charts use, so rows can be fed to them unchanged.
FIELDS = ("pvPow", "pvPreal", "invPow", "batPow", "batPreal", "loadPow", "offGridPow", "exportPow", "gridPow", "meterPow", "soc")
PRUNE_EVERY_S = 3600
MAX_POINTS = 1500  # longer ranges are averaged into coarser buckets to keep the SVG light


class HistoryDB:
    def __init__(self, path: Path, retention_days: int) -> None:
        self.retention_days = retention_days
        self._conn: sqlite3.Connection | None = None
        self._minute: int | None = None
        self._acc: dict[str, list[float]] = {f: [0.0, 0] for f in FIELDS}  # field -> [sum, count]
        self._last_prune = 0.0
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(path)
            conn.execute("PRAGMA journal_mode=WAL")
            cols = ", ".join(f'"{f}" REAL' for f in FIELDS)
            conn.execute(f"CREATE TABLE IF NOT EXISTS samples (t INTEGER PRIMARY KEY, {cols})")
            # Databases created by older versions lack columns added later.
            have = {row[1] for row in conn.execute("PRAGMA table_info(samples)")}
            for f in FIELDS:
                if f not in have:
                    conn.execute(f'ALTER TABLE samples ADD COLUMN "{f}" REAL')
            conn.commit()
            self._conn = conn
        except (sqlite3.Error, OSError) as err:
            _LOGGER.warning("History database unavailable (%s) - long-term history disabled", err)

    @property
    def enabled(self) -> bool:
        return self._conn is not None

    def add(self, now: float, reading: dict[str, Any]) -> None:
        """Accumulates a raw reading; the previous minute is written when a new one begins."""
        if self._conn is None:
            return
        minute = int(now) // 60 * 60
        if self._minute is None:
            self._minute = minute
        elif minute != self._minute:
            self._flush(now)
            self._minute = minute
        for f in FIELDS:
            v = reading.get(f)
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                self._acc[f][0] += v
                self._acc[f][1] += 1

    def _flush(self, now: float) -> None:
        assert self._conn is not None and self._minute is not None
        values = [(a[0] / a[1] if a[1] else None) for a in self._acc.values()]
        self._acc = {f: [0.0, 0] for f in FIELDS}
        try:
            if any(v is not None for v in values):
                cols = ", ".join(f'"{f}"' for f in FIELDS)
                marks = ", ".join("?" for _ in range(len(FIELDS) + 1))
                self._conn.execute(f"INSERT OR REPLACE INTO samples (t, {cols}) VALUES ({marks})", (self._minute, *values))
            if now - self._last_prune > PRUNE_EVERY_S:
                self._last_prune = now
                self._conn.execute("DELETE FROM samples WHERE t < ?", (int(now) - self.retention_days * 86400,))
            self._conn.commit()
        except sqlite3.Error as err:
            _LOGGER.warning("Could not write history sample: %s", err)

    def query(self, minutes: int) -> dict[str, Any]:
        """Samples of the last `minutes`, averaged into buckets so there are <= MAX_POINTS.
        Returns {"step": bucket seconds, "retention_days": ..., "rows": [{"_t", <FIELDS>}]}."""
        minutes = max(1, min(minutes, self.retention_days * 1440))
        step = max(60, math.ceil(minutes * 60 / MAX_POINTS / 60) * 60)
        rows: list[dict[str, Any]] = []
        if self._conn is not None:
            avg = ", ".join(f'AVG("{f}")' for f in FIELDS)
            try:
                cur = self._conn.execute(
                    f"SELECT (t / ?) * ? AS bt, {avg} FROM samples WHERE t >= ? GROUP BY bt ORDER BY bt",
                    (step, step, int(time.time()) - minutes * 60),
                )
                for bt, *vals in cur:
                    row: dict[str, Any] = {"_t": bt}
                    for f, v in zip(FIELDS, vals):
                        if v is not None:
                            row[f] = round(v, 1)
                    rows.append(row)
            except sqlite3.Error as err:
                _LOGGER.warning("History query failed: %s", err)
        return {"step": step, "retention_days": self.retention_days, "enabled": self.enabled, "rows": rows}
