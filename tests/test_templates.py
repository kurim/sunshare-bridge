import re
import shutil
import subprocess

import pytest

from app.templates import CONTROL_HTML, FLOW_HTML, INDEX_HTML, RAW_HTML

PAGES = {"telemetry": INDEX_HTML, "flow": FLOW_HTML, "control": CONTROL_HTML, "raw": RAW_HTML}


@pytest.mark.parametrize("name", PAGES)
def test_pages_load_no_external_resources(name):
    """The UI must work on an isolated LAN: no CDN scripts, fonts or images."""
    assert not re.search(r'(?:src|href)=["\']https?://', PAGES[name])
    assert "@import" not in PAGES[name]


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
@pytest.mark.parametrize("name", PAGES)
def test_page_javascript_is_valid(name, tmp_path):
    js = re.search(r"<script>(.*)</script>", PAGES[name], re.S).group(1)
    f = tmp_path / f"{name}.js"
    f.write_text(js)
    result = subprocess.run(["node", "--check", str(f)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
