import json
import os

from app import ha_options


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
