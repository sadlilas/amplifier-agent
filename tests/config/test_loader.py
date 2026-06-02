"""Tests for amplifier_agent_lib.config package skeleton (B1) and loader (B2+).

Verifies that ConfigError is a proper AaaError subclass that propagates
code/classification/message correctly so the CLI's existing
_build_error_envelope path emits a §4.1 envelope with
classification='protocol' (exit code 2 per _EXIT_CODE_BY_CLASSIFICATION).
"""

from __future__ import annotations

import pytest

from amplifier_agent_lib.config import ConfigError, load_config
from amplifier_agent_lib.protocol.errors import AaaError


def test_config_error_is_aaa_error_subclass() -> None:
    assert issubclass(ConfigError, AaaError)


def test_config_error_carries_code_classification_message() -> None:
    exc = ConfigError(
        code="config_unreadable",
        message="not found",
        classification="protocol",
    )
    assert exc.code == "config_unreadable"
    assert exc.classification == "protocol"
    assert exc.message == "not found"


def test_load_config_returns_none_when_no_tier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D1: returns None when neither --config arg nor env var is present."""
    monkeypatch.delenv("AMPLIFIER_AGENT_CONFIG", raising=False)
    assert load_config(config_arg=None) is None


def test_load_config_reads_flag_path_with_json_load(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D1/D3: --config flag tier reads file via json.load and returns parsed dict."""
    monkeypatch.delenv("AMPLIFIER_AGENT_CONFIG", raising=False)
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text('{"mcp": {"verbose_servers": true}}', encoding="utf-8")
    result = load_config(config_arg=str(cfg_path))
    assert result == {"mcp": {"verbose_servers": True}}
