"""The bridge sends message keys; the React app translates them. These tests keep both sides in step."""
import re
from pathlib import Path

import pytest

from app.messages import EN, Msg

ROOT = Path(__file__).resolve().parent.parent
I18N = ROOT / "frontend" / "src" / "i18n"
LINE = re.compile(r'^\s*"([^"]+)":\s*"((?:[^"\\]|\\.)*)",?\s*$', re.M)


def _catalog(lang: str) -> dict[str, str]:
    return dict(LINE.findall((I18N / f"{lang}.ts").read_text(encoding="utf-8")))


def _placeholders(text: str) -> set[str]:
    return set(re.findall(r"\{(\w+)\}", text))


@pytest.mark.parametrize("lang", ["de", "en"])
def test_every_backend_message_is_translated_with_the_same_placeholders(lang):
    catalog = _catalog(lang)
    for key, text in EN.items():
        assert f"msg.{key}" in catalog, f"{lang}.ts is missing msg.{key}"
        assert _placeholders(catalog[f"msg.{key}"]) == _placeholders(text), f"{lang}.ts: msg.{key} has other placeholders"


@pytest.mark.parametrize("lang", ["de", "en"])
def test_language_files_have_no_message_the_backend_does_not_send(lang):
    known = {f"msg.{k}" for k in EN}
    assert {k for k in _catalog(lang) if k.startswith("msg.")} == known


def test_env_groups_are_translated():
    from app.env_view import describe_env
    for lang in ("de", "en"):
        catalog = _catalog(lang)
        for group in describe_env():
            assert f"env.group.{group['id']}" in catalog


def test_source_only_uses_known_keys():
    """A typo in a Msg("...") key would raise at runtime, in a branch that may rarely run."""
    used = set()
    for path in (ROOT / "app").glob("*.py"):
        if path.name != "messages.py":
            used |= set(re.findall(r'Msg\(\s*"([\w.]+)"', path.read_text(encoding="utf-8")))
    assert used and used <= set(EN), sorted(used - set(EN))


def test_unknown_keys_and_levels_are_rejected_early():
    with pytest.raises(KeyError):
        Msg("nope.nothing")
    with pytest.raises(ValueError):
        Msg("act.params_updated", "loud")
