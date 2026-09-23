import json
import os
import subprocess
import sys
from pathlib import Path

from app import ha_options

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_missing_options_file_is_a_no_op(tmp_path, monkeypatch):
    monkeypatch.setattr(ha_options, "OPTIONS_FILE", tmp_path / "missing.json")
    monkeypatch.delenv("MQTT_HOST", raising=False)
    ha_options.apply_ha_options()
    assert "MQTT_HOST" not in os.environ


def test_options_are_applied_as_env_vars(tmp_path, monkeypatch):
    options_file = tmp_path / "options.json"
    options_file.write_text(json.dumps({"MQTT_HOST": "192.168.1.10", "MQTT_PORT": 1883, "UI_USER": ""}))
    monkeypatch.setattr(ha_options, "OPTIONS_FILE", options_file)
    monkeypatch.delenv("MQTT_HOST", raising=False)
    monkeypatch.delenv("UI_USER", raising=False)

    ha_options.apply_ha_options()

    assert os.environ["MQTT_HOST"] == "192.168.1.10"
    assert os.environ["MQTT_PORT"] == "1883"
    assert "UI_USER" not in os.environ  # empty option value = keep the app's own default


def test_empty_values_never_clobber_an_existing_env_var(tmp_path, monkeypatch):
    options_file = tmp_path / "options.json"
    options_file.write_text(json.dumps({"MQTT_HOST": ""}))
    monkeypatch.setattr(ha_options, "OPTIONS_FILE", options_file)
    monkeypatch.setenv("MQTT_HOST", "already-set")

    ha_options.apply_ha_options()

    assert os.environ["MQTT_HOST"] == "already-set"


def test_unreadable_options_file_is_a_no_op(tmp_path, monkeypatch):
    options_file = tmp_path / "options.json"
    options_file.write_text("not json")
    monkeypatch.setattr(ha_options, "OPTIONS_FILE", options_file)
    monkeypatch.delenv("MQTT_HOST", raising=False)

    ha_options.apply_ha_options()

    assert "MQTT_HOST" not in os.environ


def test_options_reach_module_level_singletons_that_read_env_at_import_time(tmp_path):
    """Regression: app.state builds STATE = SharedState() (reading DATA_SOURCE) and
    app.raw_log builds RAW = RawLog(...) (reading RAW_LOG_SIZE) at *import* time - so
    apply_ha_options() must run before app.main's own imports, not just before
    asyncio.run(main()). A subprocess is the only way to observe "fresh import" behaviour
    without disturbing the STATE/RAW singletons every other test in this session shares."""
    options_file = tmp_path / "options.json"
    options_file.write_text(json.dumps({"DATA_SOURCE": "cloud", "RAW_LOG_SIZE": 42}))
    script = (
        "import app.ha_options as ha_options\n"
        f"ha_options.OPTIONS_FILE = {str(options_file)!r}\n"
        "from pathlib import Path\n"
        "ha_options.OPTIONS_FILE = Path(ha_options.OPTIONS_FILE)\n"
        "import app.main\n"
        "from app.state import STATE\n"
        "from app.raw_log import RAW\n"
        "print(STATE.mode)\n"
        "print(RAW.size)\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, cwd=str(REPO_ROOT),
        env={**os.environ, "MQTT_HOST": "broker", "PYTHONPATH": str(REPO_ROOT)},
    )
    assert result.returncode == 0, result.stderr
    mode_line, size_line = result.stdout.strip().splitlines()
    assert mode_line == "cloud"
    assert size_line == "42"
