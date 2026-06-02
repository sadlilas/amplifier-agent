"""Tests for amplifier_agent_lib.config.merger (C1+).

C1 scope: stub merge_config() that returns bundle module configs unchanged
when host_config is None. Per-block per-key shallow merge for non-None host
configs lands in C2/C3/C4.

D5: layered merge of host config over bundle module configs. Bundle's static
config is the base; the four pass-through blocks override per-key. No
translation, no key renaming, no curation -- amplifier-agent only
parameterizes what bundle.md already declares (D4 pass-through stance).
"""

from __future__ import annotations

import copy

from amplifier_agent_lib.config import merge_config


def test_merge_config_returns_bundle_unchanged_when_host_is_none() -> None:
    """D5: host_config=None returns bundle modules unchanged with no input mutation."""
    bundle_modules: dict[str, dict[str, object]] = {
        "tool-mcp": {
            "config_path": "/etc/amplifier/mcp.json",
            "verbose_servers": False,
        },
        "hooks-approval": {
            "auto_approve": False,
            "patterns": ["ls *", "cat *"],
        },
    }
    snapshot = copy.deepcopy(bundle_modules)

    result = merge_config(bundle_modules=bundle_modules, host_config=None)

    # Result equals the input snapshot (semantically unchanged).
    assert result == snapshot
    # Input was not mutated.
    assert bundle_modules == snapshot


def test_merge_config_layers_mcp_block_over_tool_mcp_module() -> None:
    """D4, D5: host.mcp keys override bundle's tool-mcp config per-key (shallow).

    Bundle declares ``tool-mcp`` with three keys; host's ``mcp`` block overrides
    one (``verbose_servers``), adds one new key (``configPath``), and omits the
    remaining two (``server_log_dir``, ``max_content_size``) — for which the
    bundle defaults must stand.
    """
    bundle_modules: dict[str, dict[str, object]] = {
        "tool-mcp": {
            "verbose_servers": False,
            "server_log_dir": "/bundle/default",
            "max_content_size": 50000,
        },
    }
    host_config: dict[str, object] = {
        "mcp": {
            "verbose_servers": True,
            "configPath": "/etc/host/mcp.json",
        },
    }
    snapshot = copy.deepcopy(bundle_modules)

    result = merge_config(bundle_modules=bundle_modules, host_config=host_config)

    assert result["tool-mcp"] == {
        "verbose_servers": True,
        "server_log_dir": "/bundle/default",
        "max_content_size": 50000,
        "configPath": "/etc/host/mcp.json",
    }
    # Input was not mutated.
    assert bundle_modules == snapshot
