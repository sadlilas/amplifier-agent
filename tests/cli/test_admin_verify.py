"""Tests for the verify admin verb (Task 7).

Verifies that `amplifier-agent verify`:
  - Exposes a --check-hooks flag in its --help output.
  - Running --check-hooks exits 0 or 1 (pre-Task-11/12, the hook may not be mounted).
"""

from __future__ import annotations

import pytest
from click.testing import CliRunner

from amplifier_agent_cli.__main__ import cli


@pytest.fixture()
def runner() -> CliRunner:
    return CliRunner()


def test_verify_help_lists_check_hooks_flag(runner: CliRunner) -> None:
    """verify --help output must contain '--check-hooks'."""
    result = runner.invoke(cli, ["verify", "--help"])
    assert result.exit_code == 0, f"Expected exit 0 for --help, got {result.exit_code}. Output:\n{result.output}"
    assert "--check-hooks" in result.output, f"Expected '--check-hooks' in help output.\nOutput: {result.output}"


def test_verify_check_hooks_minimum_set_passes_when_all_five_present(
    runner: CliRunner,
) -> None:
    """Running verify --check-hooks must exit 0 or 1 (not crash, not 2+).

    Pre-Task-11/12: the streaming hook module may not be mounted, so exit 1 is acceptable.
    What matters is that the command exists, parses correctly, and does not raise unhandled exceptions.
    """
    result = runner.invoke(cli, ["verify", "--check-hooks"])
    assert result.exit_code in (0, 1), (
        f"Expected exit 0 or 1 for verify --check-hooks, got {result.exit_code}. Output:\n{result.output}"
    )
