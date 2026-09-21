from app.env_view import MASK, describe_env


def _items(groups):
    return {i["key"]: i for g in groups for i in g["items"]}


def test_passwords_are_masked_and_never_leaked(monkeypatch):
    monkeypatch.setenv("SUNSHARE_PASSWORD", "hunter2")
    monkeypatch.setenv("MQTT_PASSWORD", "s3cret")
    groups = describe_env()
    assert "hunter2" not in str(groups) and "s3cret" not in str(groups)
    items = _items(groups)
    assert items["SUNSHARE_PASSWORD"]["value"] == MASK and items["SUNSHARE_PASSWORD"]["secret"]
    assert items["MQTT_PASSWORD"]["value"] == MASK


def test_unset_password_is_empty_and_account_partially_masked(monkeypatch):
    monkeypatch.setenv("SUNSHARE_USER_ACCOUNT", "someone@example.com")
    items = _items(describe_env())
    assert items["SUNSHARE_PASSWORD"]["value"] == ""
    assert items["SUNSHARE_USER_ACCOUNT"]["value"] == "so•••@example.com"


def test_defaults_are_reported_as_such(monkeypatch):
    items = _items(describe_env())
    assert items["MQTT_PORT"] == {"key": "MQTT_PORT", "value": "1883", "secret": False, "source": "default"}
    monkeypatch.setenv("MQTT_PORT", "8883")
    assert _items(describe_env())["MQTT_PORT"]["source"] == "env"


def test_groups_have_ids_for_translation():
    groups = describe_env()
    assert [g["id"] for g in groups] == ["account", "ui_login", "mqtt", "source", "intervals", "meter", "controller"]
    assert all(g["title"] for g in groups)  # English fallback title
