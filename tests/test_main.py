import pytest

from app.main import _env_bool, _optional_float


@pytest.mark.parametrize("raw, expected", [
    (None, True), ("", True), ("TRUE", True), ("true", True), ("1", True),
    ("FALSE", False), ("false", False), (" False ", False), ("0", False), ("off", False), ("no", False),
])
def test_env_bool_with_a_true_default(raw, expected):
    assert _env_bool(raw, True) is expected


@pytest.mark.parametrize("raw, expected", [
    (None, False), ("", False), ("FALSE", False),
    ("TRUE", True), ("true", True), ("1", True),
])
def test_env_bool_with_a_false_default(raw, expected):
    assert _env_bool(raw, False) is expected


def test_optional_float_parses_or_falls_back_to_none():
    assert _optional_float(None) is None
    assert _optional_float("") is None
    assert _optional_float("52.5") == 52.5
    assert _optional_float("not a number") is None
