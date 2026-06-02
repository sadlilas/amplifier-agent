"""Tests for SC-3 — strict-refuse PROTOCOL_VERSION mismatch in Engine.boot().

Per D6, version skew is the worst class of bug.  Engine.boot() must:
  - Raise AaaError(code='protocol_version_mismatch') when client protocolVersion
    differs from PROTOCOL_VERSION and the override is NOT set.
  - Allow boot when allowProtocolSkew=True is passed in params.

Per D10, the AMPLIFIER_AGENT_ALLOW_PROTOCOL_SKEW env var is no longer honored —
the skew override is now sourced exclusively from host config (allowProtocolSkew
key) and forwarded to the engine via params.

Tests:
  1. test_boot_refuses_protocol_version_mismatch
  2. test_boot_allows_skew_when_override_set
  3. test_boot_no_longer_honors_amplifier_agent_allow_protocol_skew_env
"""

from __future__ import annotations

import io
from unittest.mock import MagicMock

import pytest

from amplifier_agent_lib.engine import Engine, TurnContext
from amplifier_agent_lib.protocol.errors import AaaError
from amplifier_agent_lib.protocol_points import (
    CliApprovalSystem,
    CliDisplaySystem,
    DisplayVerbosity,
    ProtocolPoints,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _noop_handler(ctx: TurnContext) -> str:
    return ""


def _make_engine() -> Engine:
    """Create an Engine with minimal CliDisplaySystem / CliApprovalSystem."""
    buf = io.StringIO()
    display = CliDisplaySystem(stream=buf, verbosity=DisplayVerbosity.VERBOSE)
    approval = CliApprovalSystem(override=None, is_tty=False)
    protocol_points: ProtocolPoints = {"approval": approval, "display": display}
    return Engine(turn_handler=_noop_handler, protocol_points=protocol_points)


# ---------------------------------------------------------------------------
# Test 1: mismatch raises AaaError with protocol_version_mismatch code
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_boot_refuses_protocol_version_mismatch() -> None:
    """Engine.boot with a mismatched protocolVersion raises AaaError.

    The error code must be 'protocol_version_mismatch'.
    The message must mention 'client', 'engine', and '--allow-protocol-skew'.
    """
    engine = _make_engine()
    with pytest.raises(AaaError) as exc_info:
        await engine.boot(
            {
                "protocolVersion": "1999-01-jurassic",
                "clientInfo": {"name": "test-client", "version": "0.0.0"},
                "capabilities": {},
                "sessionId": "test-session",
            },
            bundle_override=MagicMock(),
        )

    err = exc_info.value
    assert err.code == "protocol_version_mismatch"
    assert "client" in err.message
    assert "engine" in err.message
    # D10: remediation references the host-config key, not the (removed) env var
    # or the (removed) --allow-protocol-skew CLI flag.
    assert "allowProtocolSkew" in err.message


# ---------------------------------------------------------------------------
# Test 2: allowProtocolSkew=True bypasses the check
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_boot_allows_skew_when_override_set() -> None:
    """Engine.boot with allowProtocolSkew=True succeeds despite version mismatch."""
    engine = _make_engine()
    result = await engine.boot(
        {
            "protocolVersion": "1999-01-jurassic",
            "clientInfo": {"name": "test-client", "version": "0.0.0"},
            "capabilities": {},
            "sessionId": "test-session",
            "allowProtocolSkew": True,
        },
        bundle_override=MagicMock(),
    )
    assert result is not None


# ---------------------------------------------------------------------------
# Test 3 (D10): AMPLIFIER_AGENT_ALLOW_PROTOCOL_SKEW env var is no longer honored
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_boot_no_longer_honors_amplifier_agent_allow_protocol_skew_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Setting AMPLIFIER_AGENT_ALLOW_PROTOCOL_SKEW=1 must NOT bypass the check.

    Per D10, the env var was retired. The skew override now lives exclusively in
    host config (allowProtocolSkew). Setting the legacy env var must not affect
    Engine.boot — a version mismatch must still raise protocol_version_mismatch.
    """
    monkeypatch.setenv("AMPLIFIER_AGENT_ALLOW_PROTOCOL_SKEW", "1")
    engine = _make_engine()
    with pytest.raises(AaaError) as exc_info:
        await engine.boot(
            {
                "protocolVersion": "1999-01-jurassic",
                "clientInfo": {"name": "test-client", "version": "0.0.0"},
                "capabilities": {},
                "sessionId": "test-session",
            },
            bundle_override=MagicMock(),
        )
    assert exc_info.value.code == "protocol_version_mismatch"
