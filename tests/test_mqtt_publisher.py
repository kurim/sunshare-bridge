import json

import paho.mqtt.client as mqtt

from app.mqtt_publisher import MqttPublisher
from app.models import normalize_lan


class FakeClient:
    sent: list = []

    def __init__(self, *a, **k):
        pass

    def username_pw_set(self, *a):
        pass

    def connect_async(self, *a):
        pass

    def loop_start(self):
        pass

    def publish(self, topic, payload, retain=False):
        FakeClient.sent.append((topic, json.loads(payload)))


def test_discovery_and_state_payload(monkeypatch):
    FakeClient.sent = []
    monkeypatch.setattr(mqtt, "Client", FakeClient)
    pub = MqttPublisher("host", 1883, None, None, "sunshare", 42)
    pub.publish_state(normalize_lan({"pvPow": 0, "pvPreal": 24, "batPreal": -3, "invPreal": -1, "offGridPow": 30}, 42))

    configs = {t.split("/")[2]: p for t, p in FakeClient.sent if t.endswith("/config")}
    state = [p for t, p in FakeClient.sent if not t.endswith("/config")][0]
    for key in ("pv_power_real", "battery_power_real", "inverter_power_real", "offgrid_power", "house_feedin_power"):
        assert f"sunshare_42_{key}" in configs
    assert configs["sunshare_42_pv_power_real"]["value_template"] == "{{ value_json.pvPreal }}"
    assert state["pvPreal"] == 24 and state["batPreal"] == -3
    assert len({c["unique_id"] for c in configs.values()}) == len(configs)
