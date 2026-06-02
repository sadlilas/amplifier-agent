"""Removal verification tests for the dropped --host-capabilities surface.

These tests assert that the field is GONE. They will be removed (or kept
as guardrails — choose at PR time) once the cleanup lands.
"""

from click.testing import CliRunner

from amplifier_agent_cli.modes.single_turn import run


def test_host_capabilities_flag_not_in_help() -> None:
    """`--host-capabilities` must be absent from `amplifier-agent run --help`."""
    runner = CliRunner()
    result = runner.invoke(run, ["--help"])
    assert result.exit_code == 0, result.output
    assert "--host-capabilities" not in result.output, (
        "--host-capabilities flag should be removed from `amplifier-agent run`"
    )
