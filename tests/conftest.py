import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture(autouse=True)
def isolated_data(tmp_path, monkeypatch):
    """Keep every test away from /data and from the developer's real .env values."""
    import app.grid_control as gc
    import app.state as st

    monkeypatch.setattr(gc, "CONTROL_FILE", tmp_path / "control.json")
    monkeypatch.setattr(st, "ENERGY_FILE", tmp_path / "battery_energy.json")
    monkeypatch.setattr(st, "HISTORY_FILE", tmp_path / "history.db")
    for key in list(os.environ):
        if key.startswith(("SUNSHARE_", "UI_", "WEB_", "MQTT_", "METER_", "CONTROL_", "NIGHT_", "CHARGE_", "HISTORY_", "RAW_")):
            monkeypatch.delenv(key, raising=False)
    return tmp_path
