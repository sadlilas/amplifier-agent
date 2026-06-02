"""Removal verification tests for the dropped --host-capabilities surface.

These tests assert that the field is GONE. They will be removed (or kept
as guardrails — choose at PR time) once the cleanup lands.
"""

from click.testing import CliRunner

from amplifier_agent_cli.modes.single_turn import _build_envelope, _build_error_envelope, run


def test_host_capabilities_flag_not_in_help() -> None:
    """`--host-capabilities` must be absent from `amplifier-agent run --help`."""
    runner = CliRunner()
    result = runner.invoke(run, ["--help"])
    assert result.exit_code == 0, result.output
    assert "--host-capabilities" not in result.output, (
        "--host-capabilities flag should be removed from `amplifier-agent run`"
    )


def test_success_envelope_metadata_excludes_host_capabilities() -> None:
    """_build_envelope must NOT include hostCapabilities in metadata."""
    result = {
        "sessionId": "sess-1",
        "turnId": "turn-1",
        "reply": "ok",
        "tokensIn": 1,
        "tokensOut": 2,
        "bundleDigest": "sha256:abc",
    }
    envelope = _build_envelope(
        result,
        correlation_id="corr-1",
        duration_ms=42,
        session_id="sess-1",
    )
    assert "hostCapabilities" not in envelope["metadata"], (
        "hostCapabilities must not appear in success envelope metadata"
    )


def test_error_envelope_metadata_excludes_host_capabilities() -> None:
    """_build_error_envelope must NOT accept host_capabilities nor emit it."""
    envelope = _build_error_envelope(
        code="internal",
        message="boom",
        correlation_id="corr-1",
        session_id="sess-1",
        turn_id="turn-1",
        duration_ms=42,
    )
    assert "hostCapabilities" not in envelope["metadata"], "hostCapabilities must not appear in error envelope metadata"
