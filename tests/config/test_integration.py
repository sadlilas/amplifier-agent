"""End-to-end: amplifier-agent run --config <path> <prompt> reflects merged config."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from amplifier_agent_cli.__main__ import cli


def test_run_with_config_threads_overrides_through_to_spec(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """G1: --config flag's mcp+provider blocks reach _TurnSpec.host_config and spec.provider.

    End-to-end smoke test that verifies the config file is loaded by the CLI,
    threaded through to the _TurnSpec, and that the provider resolution honors
    host.provider.module ahead of the bundle default.
    """
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")

    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(
        '{"mcp": {"verbose_servers": true}, "provider": {"module": "anthropic"}}',
        encoding="utf-8",
    )

    captured: dict[str, Any] = {}

    async def _fake_execute_turn(spec):
        captured["host_config"] = spec.host_config
        captured["provider"] = spec.provider
        return {"reply": "stub", "turnId": "turn-1"}

    runner = CliRunner()
    with patch("amplifier_agent_cli.modes.single_turn._execute_turn", _fake_execute_turn):
        result = runner.invoke(cli, ["run", "--config", str(cfg_path), "hello"])

    assert result.exit_code == 0, f"Expected exit 0, got {result.exit_code}. Output:\n{result.output}"
    assert captured["host_config"] == {
        "mcp": {"verbose_servers": True},
        "provider": {"module": "anthropic"},
    }
    assert captured["provider"] == "anthropic"
