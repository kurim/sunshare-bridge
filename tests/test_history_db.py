import sqlite3
import time
from pathlib import Path

from app.history_db import FIELDS, HistoryDB


def _db(tmp_path, days=30):
    return HistoryDB(tmp_path / "h.db", days)


def test_readings_within_a_minute_are_averaged(tmp_path):
    db = _db(tmp_path)
    t = int(time.time()) // 60 * 60 - 600
    db.add(t + 5, {"pvPow": 100, "soc": 20})
    db.add(t + 35, {"pvPow": 200, "soc": 22})
    db.add(t + 65, {"pvPow": 1})  # next minute -> flushes the previous one
    row = db.query(60)["rows"][0]
    assert row["_t"] == t and row["pvPow"] == 150 and row["soc"] == 21


def test_long_ranges_are_bucketed(tmp_path):
    db = _db(tmp_path)
    now = time.time()
    t0 = int(now) // 60 * 60 - 8 * 86400
    for m in range(8 * 1440):
        db.add(t0 + m * 60 + 1, {"pvPow": 1})
    db.add(now, {"pvPow": 1})
    q = db.query(8 * 1440)
    assert q["step"] > 60 and len(q["rows"]) <= 1500 + 1


def test_retention_prunes_old_rows(tmp_path):
    db = _db(tmp_path, days=2)
    now = time.time()
    t0 = int(now) // 60 * 60 - 3 * 86400
    for m in range(3 * 1440):
        db.add(t0 + m * 60 + 1, {"pvPow": 1})
    db.add(now + 120, {"pvPow": 1})
    oldest = db._conn.execute("SELECT MIN(t) FROM samples").fetchone()[0]
    assert now - oldest < 2 * 86400 + 7200  # pruned to ~retention (pruning runs hourly)


def test_old_database_without_new_columns_is_migrated(tmp_path):
    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.execute('CREATE TABLE samples (t INTEGER PRIMARY KEY, "pvPow" REAL, "soc" REAL)')
    old.execute("INSERT INTO samples VALUES (?, 90, 21)", (int(time.time()) // 60 * 60 - 300,))
    old.commit()
    old.close()
    db = HistoryDB(path, 30)
    cols = {r[1] for r in db._conn.execute("PRAGMA table_info(samples)")}
    assert set(FIELDS) <= cols
    assert db.query(60)["rows"][0]["pvPow"] == 90


def test_unwritable_location_disables_history_without_raising(tmp_path):
    blocked = tmp_path / "file"
    blocked.write_text("x")
    db = HistoryDB(Path(blocked) / "sub" / "h.db", 30)  # parent is a file -> cannot be created
    assert not db.enabled
    db.add(time.time(), {"pvPow": 1})
    assert db.query(60)["rows"] == []
