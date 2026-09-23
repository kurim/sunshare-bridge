"""Home Assistant Supervisor writes the add-on's user-configured options to /data/options.json
before each start; translate them into the env vars app.main already reads (config.yaml's option
keys are named identically to the env vars, see config.yaml). Standalone Docker Compose never
creates this file, so apply_ha_options() is a no-op there - the same `python -m app.main`
entrypoint serves both deployments.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

_LOGGER = logging.getLogger("sunshare.ha_options")
OPTIONS_FILE = Path("/data/options.json")


def apply_ha_options() -> None:
    if not OPTIONS_FILE.is_file():
        return
    try:
        options = json.loads(OPTIONS_FILE.read_text())
    except (OSError, json.JSONDecodeError):
        _LOGGER.exception("Could not read %s", OPTIONS_FILE)
        return
    for key, value in options.items():
        if value is None or value == "":
            continue  # empty = "use the app's own default", same convention as .env.example
        os.environ[key] = str(value)
