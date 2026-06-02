"""Wire-type tests for v0.1.0 — MCP extensions (A1).

Originally these tests covered the additive TypedDicts introduced by §4.10.1 of
the design: McpServerConfig, HostCapabilities, InitializeHostParams, and the
``mcpServers`` / ``host`` fields on ``InitializeParams``.

The ``HostCapabilities`` TypedDict was removed by the drop-host-capabilities
work (B2), and the ``mcpServers`` / ``host`` fields on ``InitializeParams``
were superseded by the protocol-0.2.0 rename (now ``mcpConfigPath``). The
tests asserting those shapes have been deleted; ``McpServerConfig`` remains
on the protocol surface and is still covered here.
"""

from __future__ import annotations

import typing


def test_mcp_server_config_typed_dict_exists() -> None:
    """McpServerConfig is a TypedDict with a required ``transport`` field."""
    from amplifier_agent_lib.protocol.methods import McpServerConfig

    # TypedDicts expose __required_keys__ and __optional_keys__
    assert hasattr(McpServerConfig, "__required_keys__")
    assert hasattr(McpServerConfig, "__optional_keys__")
    assert "transport" in McpServerConfig.__required_keys__

    hints = typing.get_type_hints(McpServerConfig, include_extras=True)
    assert "transport" in hints
