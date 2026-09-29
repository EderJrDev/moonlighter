"""llm_timeout_seconds: how long a `claude -p` call may run before it is killed."""

import pytest
from moonlighter.core.config import DEFAULTS, ConfigError, load_config, validate_config


def test_the_default_timeout_is_180_seconds():
    assert DEFAULTS["llm_timeout_seconds"] == 180


def test_a_positive_timeout_is_accepted():
    config = load_config()
    config["llm_timeout_seconds"] = 300
    validate_config(config)


@pytest.mark.parametrize("value", [0, -5])
def test_a_non_positive_timeout_is_rejected(value):
    """Zero would kill every call before it answered — a config mistake that reads
    like the CLI being broken."""
    config = load_config()
    config["llm_timeout_seconds"] = value
    with pytest.raises(ConfigError, match="llm_timeout_seconds"):
        validate_config(config)


def test_a_non_numeric_timeout_is_rejected():
    config = load_config()
    config["llm_timeout_seconds"] = "three minutes"
    with pytest.raises(ConfigError, match="llm_timeout_seconds"):
        validate_config(config)
