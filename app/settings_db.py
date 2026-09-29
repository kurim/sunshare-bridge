"""What the user changed in the web UI, kept in SQLite (/data/settings.db).

The .env / add-on options only provide defaults; a value saved here wins over them and survives
restarts, updates and edits of the .env. Only keys that differ from the default are stored (see
GridController._save), so a default changed later still reaches every setting the user never touched.

A transaction per save keeps a crash or kill from leaving a half-written file (which the earlier
control.json could be, and which then silently fell back to the defaults). A failing/unwritable
database is logged once and disables persistence, but never affects the control loop.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Any, Iterable

_LOGGER = logging.getLogger("sunshare.settings")

SETTINGS_FILE = Path("/data/settings.db")


class SettingsDB:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or SETTINGS_FILE
        self._conn: sqlite3.Connection | None = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(self.path)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                "CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL, updated INTEGER NOT NULL)"
            )
            conn.commit()
            self._conn = conn
        except (sqlite3.Error, OSError) as err:
            _LOGGER.warning("Settings database unavailable (%s) - changes made in the UI are not persisted", err)

    @property
    def enabled(self) -> bool:
        return self._conn is not None

    def load(self) -> dict[str, Any]:
        """Every stored key -> value. A row that no longer parses is skipped, not fatal: one bad value
        must not cost the user all the others."""
        out: dict[str, Any] = {}
        if self._conn is None:
            return out
        try:
            rows = list(self._conn.execute("SELECT key, value FROM settings"))
        except sqlite3.Error as err:
            _LOGGER.warning("Could not read settings: %s", err)
            return out
        for key, raw in rows:
            try:
                out[key] = json.loads(raw)
            except ValueError:
                _LOGGER.warning("Ignoring unreadable stored setting %r", key)
        return out

    def save(self, values: dict[str, Any], remove: Iterable[str] = ()) -> None:
        """Upserts `values` and deletes `remove` in one transaction."""
        if self._conn is None:
            return
        now = int(time.time())
        try:
            with self._conn:
                self._conn.executemany(
                    "INSERT INTO settings (key, value, updated) VALUES (?, ?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated = excluded.updated",
                    [(key, json.dumps(value), now) for key, value in values.items()],
                )
                self._conn.executemany("DELETE FROM settings WHERE key = ?", [(key,) for key in remove])
        except sqlite3.Error as err:
            _LOGGER.warning("Could not persist settings to %s (non-fatal): %s", self.path, err)
