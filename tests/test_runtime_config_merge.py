"""Tests for host_config plumbing through _runtime.make_turn_handler (D5).

Two tests:
  1. ``make_turn_handler`` accepts ``host_config`` as a keyword argument
     without raising, and returns a callable handler.
  2. ``make_turn_handler`` invokes ``merge_config`` with the host_config
     it was given, so the host overlay reaches the merger at the
     bundle-mount seam.
"""

from __future__ import annotations

from typing import Any

import pytest

from amplifier_agent_lib import _runtime


class _FakePrepared:
    """Minimal stand-in for PreparedBundle.

    ``make_turn_handler`` only touches ``prepared.mount_plan`` at handler
    construction time (the rest happens inside the returned coroutine, which
    these tests never invoke).  A dict with an ``agents`` key is enough to
    satisfy the agent-overlay hydration path.
    """

    def __init__(self, mount_plan: dict[str, Any] | None = None) -> None:
        # Default to a mount_plan with no agents and one bundle module block
        # so the merge path has something concrete to copy and update.
        self.mount_plan: dict[str, Any] = (
            mount_plan if mount_plan is not None else {"agents": {}, "tool-mcp": {"verbose_servers": False}}
        )


def test_make_turn_handler_accepts_host_config_kwarg() -> None:
    """make_turn_handler must accept ``host_config`` without raising."""
    fake_prepared = _FakePrepared()

    handler = _runtime.make_turn_handler(
        fake_prepared,  # type: ignore[arg-type]
        cwd=None,
        is_resumed=False,
        host_config=None,
    )

    assert callable(handler)


def test_make_turn_handler_calls_merge_config_when_host_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """make_turn_handler must forward host_config into merge_config."""
    captured: dict[str, Any] = {}

    def _fake_merge_config(
        *,
        bundle_modules: dict[str, dict[str, Any]],
        host_config: dict[str, Any] | None,
    ) -> tuple[dict[str, dict[str, Any]], bool]:
        captured["bundle_modules"] = bundle_modules
        captured["host_config"] = host_config
        # Return the bundle_modules unchanged so downstream code can update
        # the mount_plan with values shaped like the real merger output.
        return bundle_modules, False

    monkeypatch.setattr(_runtime, "merge_config", _fake_merge_config)

    fake_prepared = _FakePrepared()
    host_config = {"mcp": {"verbose_servers": True}}

    _runtime.make_turn_handler(
        fake_prepared,  # type: ignore[arg-type]
        cwd=None,
        is_resumed=False,
        host_config=host_config,
    )

    assert captured["host_config"] == host_config
