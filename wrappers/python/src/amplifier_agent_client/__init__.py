"""amplifier_agent_client — Python client wrapper for the Amplifier agent protocol.

Public API is built up across Tasks 4-12. This skeleton exports only the
protocol version constant required by the wrapper, used by smoke tests to
verify that the package is correctly installed.
"""

from __future__ import annotations

#: The protocol version that this Python wrapper requires.
#: Must match the version string shipped by `amplifier-agent` (amplifier_agent_lib).
PROTOCOL_VERSION_REQUIRED_BY_WRAPPER = "2026-05-aaa-v0"

__all__ = ["PROTOCOL_VERSION_REQUIRED_BY_WRAPPER"]
