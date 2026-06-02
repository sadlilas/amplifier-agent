"""Tests for D6 — bundle default_provider fallback in `run` command.

When no `--provider` override is passed and no `host.provider.module` is set in
the loaded host config, the CLI must fall back to the bundle's
`default_provider:` top-level field (rather than env-var-based
`detect_provider()` autodetection).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from amplifier_agent_cli.__main__ import cli

# All env vars that the legacy detect_provider() walks. Strip them all so the
# test cannot accidentally pass via env-var autodetection.
_PROVIDER_ENV_VARS = (
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "AZURE_OPENAI_API_KEY",
    "AZURE_OPENAI_KEY",
    "OLLAMA_HOST",
)


@pytest.fixture()
def runner() -> CliRunner:
    return CliRunner()


def test_run_uses_bundle_default_provider_when_no_override(
    runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No --provider, no host.provider.module, no env vars → use bundle default_provider.

    The vendored bundle.md ships with `default_provider: anthropic` (D6).
    """
    # Strip every provider env var so detect_provider would raise if called.
    for var in _PROVIDER_ENV_VARS:
        monkeypatch.delenv(var, raising=False)

    captured: dict[str, Any] = {}

    async def _fake_execute_turn(spec):
        captured["provider"] = spec.provider
        return {"reply": "stub", "turnId": "turn-1"}

    with patch("amplifier_agent_cli.modes.single_turn._execute_turn", _fake_execute_turn):
        result = runner.invoke(cli, ["run", "hello"])

    assert result.exit_code == 0, f"Expected exit 0, got {result.exit_code}. Output:\n{result.output}"
    assert captured["provider"] == "anthropic"
