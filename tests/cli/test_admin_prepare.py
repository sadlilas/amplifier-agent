"""Tests for the prepare admin verb (Task 7).

Verifies that `amplifier-agent prepare`:
  - Runs load_and_prepare_cached and exits 0 on success.
  - Exits non-zero and surfaces the error message on failure.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from click.testing import CliRunner

from amplifier_agent_cli.__main__ import cli


@pytest.fixture()
def runner() -> CliRunner:
    return CliRunner()


def test_prepare_runs_load_and_prepare_cached(runner: CliRunner) -> None:
    """prepare command calls load_and_prepare_cached exactly once and exits 0."""
    mock_prepared = object()  # any truthy object

    async def _fake_load(*, aaa_version: str) -> object:
        return mock_prepared

    fake_load = AsyncMock(side_effect=_fake_load)

    with patch("amplifier_agent_cli.admin.prepare.load_and_prepare_cached", fake_load):
        result = runner.invoke(cli, ["prepare"])

    assert result.exit_code == 0, f"Expected exit 0, got {result.exit_code}. Output:\n{result.output}"
    fake_load.assert_awaited_once()


def test_prepare_exits_nonzero_on_failure(runner: CliRunner) -> None:
    """prepare command exits non-zero and surfaces error message when load_and_prepare_cached raises."""
    fake_load = AsyncMock(side_effect=RuntimeError("boom"))

    with patch("amplifier_agent_cli.admin.prepare.load_and_prepare_cached", fake_load):
        result = runner.invoke(cli, ["prepare"])

    assert result.exit_code != 0, f"Expected non-zero exit on failure, got {result.exit_code}."
    assert "boom" in result.output, f"Expected 'boom' in output.\nOutput: {result.output}"
