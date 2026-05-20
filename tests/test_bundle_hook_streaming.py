"""Tests for src/amplifier_agent_lib/bundle/hook_streaming.py.

Five TDD sub-cycles:
  11A: tool:pre -> tool/started
  11B: tool:post -> tool/completed
  11C: content_block handlers (delta + fallback)
  11D: llm:response -> usage + result/final
  11E: tool:error -> error
"""

from __future__ import annotations

import pytest

from amplifier_agent_lib.bundle.hook_streaming import (
    CANONICAL_WIRE_EVENTS,
    StreamingEmitter,
    mount,
)


# ---------------------------------------------------------------------------
# Test infrastructure — mock coordinator
# ---------------------------------------------------------------------------


class _MockHooks:
    """Records calls to register()."""

    def __init__(self) -> None:
        self.registered: list[tuple[str, object, str | None]] = []

    def register(self, event: str, handler: object, *, name: str | None = None, priority: int = 0) -> None:
        self.registered.append((event, handler, name))


class _MockCoordinator:
    """Mock coordinator that captures emitted display events."""

    def __init__(self) -> None:
        self.emitted: list[dict] = []
        self.hooks = _MockHooks()

    def get_capability(self, name: str) -> object:
        if name == "display.emit":
            async def _emit(event: dict) -> None:
                self.emitted.append(event)
            return _emit
        raise KeyError(f"Unknown capability: {name!r}")


# ---------------------------------------------------------------------------
# Sanity: CANONICAL_WIRE_EVENTS constant
# ---------------------------------------------------------------------------


def test_canonical_wire_events_contains_required_types() -> None:
    """CANONICAL_WIRE_EVENTS must contain the 5 required wire event types."""
    required = {"result/delta", "result/final", "tool/started", "tool/completed", "usage"}
    assert required == set(CANONICAL_WIRE_EVENTS)


# ---------------------------------------------------------------------------
# mount() registers 7 handlers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mount_registers_seven_handlers() -> None:
    """mount() must register exactly 7 handlers on coordinator.hooks."""
    coord = _MockCoordinator()
    await mount(coord)

    registered_events = [evt for evt, _, _ in coord.hooks.registered]
    expected_events = {
        "tool:pre",
        "tool:post",
        "tool:error",
        "content_block:start",
        "content_block:delta",
        "content_block:end",
        "llm:response",
    }
    assert len(coord.hooks.registered) == 7
    assert set(registered_events) == expected_events


# ---------------------------------------------------------------------------
# Sub-cycle 11A: tool:pre -> tool/started
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tool_pre_emits_tool_started() -> None:
    """on_tool_pre emits type='tool/started' with sessionId, turnId, name, toolCallId, args."""
    coord = _MockCoordinator()
    emitter = StreamingEmitter(coord)

    data = {
        "session_id": "sess-1",
        "turn_id": "turn-1",
        "tool_call_id": "call-abc",
        "tool": "bash",
        "arguments": {"cmd": "ls"},
    }
    result = await emitter.on_tool_pre("tool:pre", data)

    assert result.action == "continue"
    assert len(coord.emitted) == 1
    ev = coord.emitted[0]
    assert ev["type"] == "tool/started"
    assert ev["sessionId"] == "sess-1"
    assert ev["turnId"] == "turn-1"
    assert ev["toolCallId"] == "call-abc"
    assert ev["name"] == "bash"
    assert ev["args"] == {"cmd": "ls"}


@pytest.mark.asyncio
async def test_tool_pre_defensive_tool_name_field() -> None:
    """on_tool_pre reads 'tool_name' when 'tool' is absent; reads 'tool_input' as args."""
    coord = _MockCoordinator()
    emitter = StreamingEmitter(coord)

    data = {
        "session_id": "sess-2",
        "turn_id": "turn-2",
        "tool_call_id": "call-xyz",
        "tool_name": "filesystem",
        "tool_input": {"path": "/x"},
    }
    result = await emitter.on_tool_pre("tool:pre", data)

    assert result.action == "continue"
    assert len(coord.emitted) == 1
    ev = coord.emitted[0]
    assert ev["type"] == "tool/started"
    assert ev["name"] == "filesystem"
    assert ev["args"] == {"path": "/x"}


# ---------------------------------------------------------------------------
# Sub-cycle 11B: tool:post -> tool/completed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tool_post_emits_tool_completed() -> None:
    """on_tool_post emits type='tool/completed' with name, toolCallId, result, durationMs."""
    coord = _MockCoordinator()
    emitter = StreamingEmitter(coord)

    data = {
        "session_id": "sess-3",
        "turn_id": "turn-3",
        "tool_call_id": "call-def",
        "tool": "bash",
        "result": {"stdout": "file.txt"},
        "duration_ms": 42,
    }
    result = await emitter.on_tool_post("tool:post", data)

    assert result.action == "continue"
    assert len(coord.emitted) == 1
    ev = coord.emitted[0]
    assert ev["type"] == "tool/completed"
    assert ev["sessionId"] == "sess-3"
    assert ev["turnId"] == "turn-3"
    assert ev["toolCallId"] == "call-def"
    assert ev["name"] == "bash"
    assert ev["result"] == {"stdout": "file.txt"}
    assert ev["durationMs"] == 42


# ---------------------------------------------------------------------------
# Sub-cycle 11C: content_block handlers (result/delta + fallback)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_content_block_delta_emits_result_delta() -> None:
    """on_start then on_delta with text='Hello' emits one result/delta with text='Hello'."""
    coord = _MockCoordinator()
    emitter = StreamingEmitter(coord)

    block_data = {
        "session_id": "sess-4",
        "turn_id": "turn-4",
        "block_id": "block-1",
    }
    await emitter.on_content_block_start("content_block:start", block_data)
    assert len(coord.emitted) == 0  # start emits nothing

    delta_data = {
        "session_id": "sess-4",
        "turn_id": "turn-4",
        "block_id": "block-1",
        "text": "Hello",
    }
    result = await emitter.on_content_block_delta("content_block:delta", delta_data)

    assert result.action == "continue"
    assert len(coord.emitted) == 1
    ev = coord.emitted[0]
    assert ev["type"] == "result/delta"
    assert ev["sessionId"] == "sess-4"
    assert ev["turnId"] == "turn-4"
    assert ev["text"] == "Hello"


@pytest.mark.asyncio
async def test_content_block_end_fallback_when_no_delta_fired() -> None:
    """on_start then on_end with text='Full text' (no delta) emits exactly one fallback result/delta."""
    coord = _MockCoordinator()
    emitter = StreamingEmitter(coord)

    start_data = {
        "session_id": "sess-5",
        "turn_id": "turn-5",
        "block_id": "block-2",
    }
    await emitter.on_content_block_start("content_block:start", start_data)

    end_data = {
        "session_id": "sess-5",
        "turn_id": "turn-5",
        "block_id": "block-2",
        "text": "Full text",
    }
    result = await emitter.on_content_block_end("content_block:end", end_data)

    assert result.action == "continue"
    assert len(coord.emitted) == 1
    ev = coord.emitted[0]
    assert ev["type"] == "result/delta"
    assert ev["text"] == "Full text"


@pytest.mark.asyncio
async def test_content_block_end_skips_fallback_when_delta_fired() -> None:
    """start, delta('chunk-1'), end emits only the real delta (no fallback on end)."""
    coord = _MockCoordinator()
    emitter = StreamingEmitter(coord)

    block_id = "block-3"
    base = {"session_id": "sess-6", "turn_id": "turn-6", "block_id": block_id}

    await emitter.on_content_block_start("content_block:start", base)
    await emitter.on_content_block_delta("content_block:delta", {**base, "text": "chunk-1"})

    emitted_before = list(coord.emitted)
    await emitter.on_content_block_end("content_block:end", {**base, "text": "chunk-1"})

    # No extra emission from on_end
    assert len(coord.emitted) == len(emitted_before)


@pytest.mark.asyncio
async def test_content_block_end_cleans_up_state() -> None:
    """on_end cleans up _delta_seen and _block_text for the block."""
    coord = _MockCoordinator()
    emitter = StreamingEmitter(coord)

    block_id = "block-cleanup"
    base = {"session_id": "s", "turn_id": "t", "block_id": block_id}

    await emitter.on_content_block_start("content_block:start", base)
    assert block_id in emitter._delta_seen

    await emitter.on_content_block_end("content_block:end", {**base, "text": ""})

    assert block_id not in emitter._delta_seen
    assert block_id not in emitter._block_text
