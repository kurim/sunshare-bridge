"""Long-term power history: one averaged sample per minute in SQLite (/data/history.db),
so the power-flow chart can look back days and survives container restarts.

The live view keeps using the in-memory deque of raw readings (see state.py); this only
feeds the longer ranges. A failing/unwritable database disables the feature (logged once)
but never affects telemetry.
"""
from __future__ import annotations

import json
import logging
import math
import sqlite3
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Any

_LOGGER = logging.getLogger("sunshare.history")

# Column names are the reading keys the charts use, so rows can be fed to them unchanged.
FIELDS = ("pvPow", "pvPreal", "invPow", "batPow", "batPreal", "loadPow", "offGridPow", "exportPow", "gridPow", "meterPow", "soc", "setpointW")
PRUNE_EVERY_S = 3600
MAX_POINTS = 1500  # longer ranges are averaged into coarser buckets to keep the SVG light


def _local_midnight(t: float) -> float:
    lt = time.localtime(t)
    return time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1))


class HistoryDB:
    def __init__(self, path: Path, retention_days: int) -> None:
        self.retention_days = retention_days
        self._conn: sqlite3.Connection | None = None
        self._minute: int | None = None
        self._acc: dict[str, list[float]] = {f: [0.0, 0] for f in FIELDS}  # field -> [sum, count]
        self._last_prune = 0.0
        self.full_soc = 95.0  # "battery full" threshold of the History page, kept in sync with the controller's CHARGE_FULL_SOC
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
            # One row per local calendar day for the History page; never pruned (a few hundred bytes a day),
            # so the day list outlives the minute samples.
            conn.execute("CREATE TABLE IF NOT EXISTS days (day TEXT PRIMARY KEY, pv_kwh REAL, full_at INTEGER, fc_kwh REAL, fc_series TEXT)")
            self._conn = conn
            self._summarize(0, overwrite=False)  # days recorded before the table existed
            conn.commit()
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
                self._summarize(_local_midnight(self._minute))
            if now - self._last_prune > PRUNE_EVERY_S:
                self._last_prune = now
                self._conn.execute("DELETE FROM samples WHERE t < ?", (int(now) - self.retention_days * 86400,))
            self._conn.commit()
        except sqlite3.Error as err:
            _LOGGER.warning("Could not write history sample: %s", err)

    def _summarize(self, since: float, overwrite: bool = True) -> None:
        """Per-day PV yield (booked pvPow, minute averages) and the first minute the battery was full,
        from the samples since `since`. Without `overwrite` existing days are kept (their oldest samples may be pruned)."""
        assert self._conn is not None
        action = "UPDATE SET pv_kwh = excluded.pv_kwh, full_at = excluded.full_at" if overwrite else "NOTHING"
        self._conn.execute(
            "INSERT INTO days (day, pv_kwh, full_at) SELECT date(t, 'unixepoch', 'localtime') AS d,"
            ' SUM(MAX("pvPow", 0)) / 60000.0, MIN(CASE WHEN soc >= ? THEN t END)'
            f" FROM samples WHERE t >= ? GROUP BY d ON CONFLICT(day) DO {action}",
            (self.full_soc, int(since)),
        )

    def set_forecast(self, days: dict[str, tuple[float, list[list[int]]]]) -> None:
        """Stores the latest PV forecast per day ({"YYYY-MM-DD": (kWh, [[epoch s, W], ...])})."""
        if self._conn is None:
            return
        try:
            self._conn.executemany(
                "INSERT INTO days (day, fc_kwh, fc_series) VALUES (?, ?, ?)"
                " ON CONFLICT(day) DO UPDATE SET fc_kwh = excluded.fc_kwh, fc_series = excluded.fc_series",
                [(d, kwh, json.dumps(series)) for d, (kwh, series) in days.items()],
            )
            self._conn.commit()
        except sqlite3.Error as err:
            _LOGGER.warning("Could not store the PV forecast: %s", err)

    def days(self) -> list[dict[str, Any]]:
        """Recorded days, newest first: {day, pv_kwh, full_at, fc_kwh} (fc_kwh None without a forecast)."""
        if self._conn is None:
            return []
        try:
            cur = self._conn.execute("SELECT day, pv_kwh, full_at, fc_kwh FROM days WHERE pv_kwh IS NOT NULL ORDER BY day DESC")
            return [{"day": d, "pv_kwh": round(pv, 2), "full_at": full, "fc_kwh": fc} for d, pv, full, fc in cur]
        except sqlite3.Error as err:
            _LOGGER.warning("History day list failed: %s", err)
            return []

    def day(self, day: date) -> dict[str, Any]:
        """One day for the History page: its summary, the forecast curve and the samples of that day."""
        out: dict[str, Any] = {"day": day.isoformat(), "pv_kwh": None, "full_at": None, "fc_kwh": None, "fc_series": []}
        if self._conn is not None:
            try:
                row = self._conn.execute("SELECT pv_kwh, full_at, fc_kwh, fc_series FROM days WHERE day = ?", (day.isoformat(),)).fetchone()
                if row:
                    out.update(pv_kwh=row[0] and round(row[0], 2), full_at=row[1], fc_kwh=row[2], fc_series=json.loads(row[3] or "[]"))
            except (sqlite3.Error, ValueError) as err:
                _LOGGER.warning("History day query failed: %s", err)
        out["history"] = self.query_range(time.mktime(day.timetuple()), time.mktime((day + timedelta(days=1)).timetuple()))
        return out

    def query(self, minutes: int) -> dict[str, Any]:
        """Samples of the last `minutes`, averaged into buckets so there are <= MAX_POINTS.
        Returns {"step": bucket seconds, "retention_days": ..., "rows": [{"_t", <FIELDS>}]}."""
        minutes = max(1, min(minutes, self.retention_days * 1440))
        now = time.time()
        return self._query(now - minutes * 60, now)

    def query_range(self, start: float, end: float) -> dict[str, Any]:
        """Samples strictly between two epoch timestamps (e.g. a specific calendar day from
        main.py's "today"/"yesterday"), same bucketing and return shape as query(). Clamped to
        [now - retention, now] - a future end (like "today" before midnight) would otherwise ask
        for data that doesn't exist yet."""
        now = time.time()
        return self._query(max(start, now - self.retention_days * 86400), min(end, now))

    def _query(self, start: float, end: float) -> dict[str, Any]:
        span_minutes = max(1, (end - start) / 60)
        step = max(60, math.ceil(span_minutes * 60 / MAX_POINTS / 60) * 60)
        rows: list[dict[str, Any]] = []
        if self._conn is not None:
            avg = ", ".join(f'AVG("{f}")' for f in FIELDS)
            try:
                cur = self._conn.execute(
                    f"SELECT (t / ?) * ? AS bt, {avg} FROM samples WHERE t >= ? AND t < ? GROUP BY bt ORDER BY bt",
                    (step, step, int(start), int(end)),
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
