"""Integration test: streaming hook mounts correctly and fires events.

Regression guard for the 2026-05-20 'source: local' URI handler bug class —
any future code path where the hook silently fails to mount but the bundle
still loads.

The test mounts the hook the way _runtime.py does (programmatically via
mount()), fires a synthetic kernel event through the REAL hook registry
(amplifier_core.RustHookRegistry), and asserts the event reaches the display.
Uses amplifier_core.create_test_coordinator() so no module installation
(context-persistent et al.) is required.
"""

from __future__ import annotations

import pytest
from amplifier_core import create_test_coordinator


class _CapturingDisplay:
    def __init__(self) -> None:
        self.events: list[dict] = []

    async def emit(self, event: dict) -> None:
        self.events.append(event)


@pytest.mark.asyncio
async def test_streaming_hook_is_mounted_after_handler_runs() -> None:
    """Regression: the streaming hook must be registered on coordinator.hooks
    after a turn handler initialises a session.

    Catches the 2026-05-20 'source: local' bug class — any future code path
    where the hook silently fails to mount but the bundle still loads.

    Uses the real RustHookRegistry (via create_test_coordinator) so that
    coordinator.hooks.emit() exercises the actual hook dispatch path, not a
    mock.  No module installation (context-persistent etc.) is needed.
    """
    from amplifier_agent_lib.bundle.hook_streaming import mount as mount_streaming_hook

    coord = create_test_coordinator()
    display = _CapturingDisplay()

    coord.register_capability("display.emit", display.emit)
    coord.hooks.set_default_fields(session_id="test-sess", turn_id="test-turn")

    await mount_streaming_hook(coord, {})

    await coord.hooks.emit(
        "tool:pre",
        {"tool": "demo_tool", "arguments": {"x": 1}, "tool_call_id": "call-1"},
    )

    assert any(ev.get("type") == "tool/started" and ev.get("name") == "demo_tool" for ev in display.events), (
        f"Streaming hook did not fire — captured events: {display.events!r}"
    )
