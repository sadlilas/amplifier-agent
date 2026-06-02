# Drop `hostCapabilities` — Implementation Plan (Phase 1)

> **Execution:** Use the `subagent-driven-development` workflow to implement this plan.

**Goal:** Cleanly remove every trace of the `hostCapabilities` surface from the engine, wrappers, schemas, conformance fixture, and tests. Pure deletion. No engine-side flag tolerance, no deprecation window.

**Architecture:** Apply TDD-for-removal: for each surface, write a test that asserts the field is GONE, watch it fail (the field is still there), delete the field, watch the test pass, commit. Some bottom layers (whole-file deletions, test-of-removed-feature) follow a verify-and-delete pattern instead — explicitly called out below.

**Tech Stack:**
- Engine: Python 3.11+ / click / pytest
- TS wrapper: TypeScript / vitest
- Python wrapper: Python / pytest
- Conformance: dual-runner (vitest + pytest) over YAML fixtures
- Commit style: Conventional Commits (`chore(engine):`, `chore(wrapper-ts):`, `chore(conformance):`, `docs(designs):`)

**Pairs with:** `docs/designs/2026-06-01-drop-host-capabilities.md` (locked design). Phase 2 (host config layer) is a separate plan at `docs/plans/2026-06-01-host-config-layer-implementation.md` and is independent.

**Baseline pre-flight (run before starting Task 1):**

```
git status                                       # expect clean working tree
uv run pytest -x -q                              # expect green (Python suite)
cd wrappers/typescript && npm test               # expect green
cd ../python && uv run pytest -x -q              # expect green
cd ../..
```

If any of these are red before you start, stop and report. This plan assumes a green baseline.

---

## Section A — Engine: drop `--host-capabilities` argv flag and parsing

### Task A1: Add the failing "flag is gone from --help" test

**Files:**
- Create: `tests/cli/test_drop_host_capabilities.py`

**Step 1: Write the failing test**

```python
# tests/cli/test_drop_host_capabilities.py
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
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/cli/test_drop_host_capabilities.py::test_host_capabilities_flag_not_in_help -v`

Expected: **FAIL** — assertion fires because `--host-capabilities` still appears in `--help` output.

**Step 3: No code change yet — commit the failing test**

`git add tests/cli/test_drop_host_capabilities.py && git commit -m "test(engine): add removal guardrail for --host-capabilities flag"`

(We are committing the red test first so the next commit's green is recorded. This is the TDD record.)

---

### Task A2: Delete the `--host-capabilities` click option, function parameter, and parser line in `single_turn.py`

**Files:**
- Modify: `src/amplifier_agent_cli/modes/single_turn.py:434-439` (delete click option block)
- Modify: `src/amplifier_agent_cli/modes/single_turn.py:475` (delete function parameter)
- Modify: `src/amplifier_agent_cli/modes/single_turn.py:543` (delete `_parse_json_or_atpath` call)

**Step 1: Delete the click option declaration**

Find this block (around line 434-439):

```python
@click.option(
    "--host-capabilities",
    "host_capabilities_raw",
    default=None,
    help="Host capabilities as inline JSON object.",
)
```

Delete it entirely.

**Step 2: Delete the function parameter**

In `def run(...)` (around line 475), delete the line:

```python
    host_capabilities_raw: str | None,
```

**Step 3: Delete the parser line**

Find (around line 543, inside `(5c) Parse host capabilities, env extras, and env allowlist`):

```python
    host_capabilities = _parse_json_or_atpath(host_capabilities_raw, flag_name="--host-capabilities")
```

Delete the line. Also update the surrounding comment block — change:

```python
    # (5c) Parse host capabilities, env extras, and env allowlist (A1'/D12').
```

to:

```python
    # (5c) Parse env extras and env allowlist (A1').
```

**Step 4: Do NOT delete `host_capabilities=...` keyword args at call sites yet**

The variable `host_capabilities` is now undefined, so every call site that passes `host_capabilities=host_capabilities` will be a `NameError`. We will fix all those call sites in Tasks A3, A4, A5 below. To keep this commit small but still leave the code runnable, **insert a transitional line** right where the parser was:

```python
    host_capabilities = None  # transitional — removed in subsequent commits
```

**Step 5: Verify the help test passes**

Run: `uv run pytest tests/cli/test_drop_host_capabilities.py::test_host_capabilities_flag_not_in_help -v`

Expected: **PASS** — flag no longer in --help output.

**Step 6: Verify the rest of the suite still passes (existing tests will fail later — that's expected and handled in Tasks A6/A7/A8/M1/M2/M3 — but the suite should not crash with import errors)**

Run: `uv run pytest tests/cli/test_drop_host_capabilities.py -v`

Expected: PASS for the new file. Other tests may fail because they still pass `--host-capabilities` on the CLI — that's expected; we handle them later.

**Step 7: Commit**

```
git add src/amplifier_agent_cli/modes/single_turn.py
git commit -m "chore(engine): drop --host-capabilities click option and parser"
```

---

### Task A3: Remove `hostCapabilities` from success envelope (`_build_envelope`)

**Files:**
- Modify: `src/amplifier_agent_cli/modes/single_turn.py:280` (function signature)
- Modify: `src/amplifier_agent_cli/modes/single_turn.py:298-299` (echo block)

**Step 1: Write the failing test** (append to `tests/cli/test_drop_host_capabilities.py`)

```python
def test_success_envelope_metadata_excludes_host_capabilities() -> None:
    """_build_envelope must NOT include hostCapabilities in metadata."""
    from amplifier_agent_cli.modes.single_turn import _build_envelope

    envelope = _build_envelope(
        {"reply": "ok", "turnId": "turn-1", "sessionId": "sid-1"},
        correlation_id="cid",
        duration_ms=1,
        session_id="sid-1",
    )
    assert "hostCapabilities" not in envelope["metadata"], (
        "envelope.metadata.hostCapabilities should be removed"
    )
```

Note: the test calls `_build_envelope` without a `host_capabilities` kwarg. **Today this raises a `TypeError` for missing required keyword.** That's the right failure shape: it asserts the parameter is gone too.

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/cli/test_drop_host_capabilities.py::test_success_envelope_metadata_excludes_host_capabilities -v`

Expected: **FAIL** — `TypeError: _build_envelope() missing 1 required keyword-only argument: 'host_capabilities'`.

**Step 3: Edit `_build_envelope`**

Around line 276-307, change the signature and body:

```python
def _build_envelope(
    result: dict[str, Any],
    *,
    correlation_id: str,
    duration_ms: int,
    session_id: str = "",
) -> dict[str, Any]:
    """Build the §4.1 success envelope from an engine turn result.

    ``session_id`` (when non-empty) overrides ``result['sessionId']`` so the
    envelope echoes the session ID supplied by the caller / CLI option.
    """
    metadata: dict[str, Any] = {
        "tokensIn": int(result.get("tokensIn", 0) or 0),
        "tokensOut": int(result.get("tokensOut", 0) or 0),
        "durationMs": duration_ms,
        "bundleDigest": result.get("bundleDigest", ""),
        "engineVersion": __version__,
        "protocolVersion": PROTOCOL_VERSION,
        "correlationId": correlation_id,
    }
    return {
        "protocolVersion": PROTOCOL_VERSION,
        "sessionId": session_id or result.get("sessionId", ""),
        "turnId": result.get("turnId", "turn-1"),
        "reply": result.get("reply", ""),
        "error": None,
        "metadata": metadata,
    }
```

The diff is: drop the `host_capabilities` kwarg from the signature and the two-line `if host_capabilities is not None: metadata["hostCapabilities"] = ...` block.

**Step 4: Update the success-path call site that invokes `_build_envelope`**

Find (around line 651-657, inside the `if output_mode == "json":` block):

```python
        envelope = _build_envelope(
            result,
            correlation_id=correlation_id,
            host_capabilities=host_capabilities,
            duration_ms=duration_ms,
            session_id=session_id or "",
        )
```

Delete the `host_capabilities=host_capabilities,` line.

**Step 5: Run test to verify it passes**

Run: `uv run pytest tests/cli/test_drop_host_capabilities.py::test_success_envelope_metadata_excludes_host_capabilities -v`

Expected: **PASS**.

**Step 6: Commit**

```
git add src/amplifier_agent_cli/modes/single_turn.py tests/cli/test_drop_host_capabilities.py
git commit -m "chore(engine): drop hostCapabilities from success envelope (_build_envelope)"
```

---

### Task A4: Remove `hostCapabilities` from error envelope (`_build_error_envelope`)

**Files:**
- Modify: `src/amplifier_agent_cli/modes/single_turn.py:234-273`
- Modify: `src/amplifier_agent_cli/modes/single_turn.py:597-604` and `:625-633` (the two error-path call sites)

**Step 1: Write the failing test** (append to `tests/cli/test_drop_host_capabilities.py`)

```python
def test_error_envelope_metadata_excludes_host_capabilities() -> None:
    """_build_error_envelope must NOT include hostCapabilities in metadata."""
    from amplifier_agent_cli.modes.single_turn import _build_error_envelope

    envelope = _build_error_envelope(
        code="internal",
        message="boom",
        correlation_id="cid",
        session_id="sid-1",
        turn_id="turn-1",
        duration_ms=1,
    )
    assert "hostCapabilities" not in envelope["metadata"], (
        "error envelope.metadata.hostCapabilities should be removed"
    )
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/cli/test_drop_host_capabilities.py::test_error_envelope_metadata_excludes_host_capabilities -v`

Expected: **FAIL** — `TypeError: missing 1 required keyword-only argument: 'host_capabilities'`.

**Step 3: Edit `_build_error_envelope`**

Around line 234-273, delete the `host_capabilities: dict[str, Any] | None,` keyword-only param and the two-line `if host_capabilities is not None: metadata["hostCapabilities"] = ...` block. The resulting signature should be:

```python
def _build_error_envelope(
    *,
    code: str,
    message: str,
    correlation_id: str,
    session_id: str,
    turn_id: str,
    duration_ms: int,
    stderr_tail: str | None = None,
) -> dict[str, Any]:
```

And the metadata dict has no conditional `hostCapabilities` injection.

**Step 4: Update both error-path call sites**

Find around line 596-604 (in the `except AaaError` block):

```python
        envelope = _build_error_envelope(
            code=exc.code,
            message=exc.message,
            correlation_id=correlation_id,
            session_id=session_id or "",
            turn_id="turn-1",
            host_capabilities=host_capabilities,
            duration_ms=duration_ms,
        )
```

Delete the `host_capabilities=host_capabilities,` line.

Find around line 625-633 (in the `except Exception` block):

```python
        envelope = _build_error_envelope(
            code="internal",
            message=f"{type(exc).__name__}: {exc}",
            correlation_id=correlation_id,
            session_id=session_id or "",
            turn_id="turn-1",
            host_capabilities=host_capabilities,
            duration_ms=duration_ms,
        )
```

Delete the `host_capabilities=host_capabilities,` line.

**Step 5: Run test to verify it passes**

Run: `uv run pytest tests/cli/test_drop_host_capabilities.py::test_error_envelope_metadata_excludes_host_capabilities -v`

Expected: **PASS**.

**Step 6: Commit**

```
git add src/amplifier_agent_cli/modes/single_turn.py tests/cli/test_drop_host_capabilities.py
git commit -m "chore(engine): drop hostCapabilities from error envelope (_build_error_envelope)"
```

---

### Task A5: Remove `hostCapabilities` from per-turn audit (`_write_audit`)

**Files:**
- Modify: `src/amplifier_agent_cli/modes/single_turn.py:170-203` (function)
- Modify: `src/amplifier_agent_cli/modes/single_turn.py:608-621`, `:636-649`, `:669-682` (three audit call sites)

**Step 1: Write the failing test** (append to `tests/cli/test_drop_host_capabilities.py`)

```python
import json
import tempfile
from pathlib import Path
from unittest.mock import patch


def test_audit_dict_excludes_host_capabilities(tmp_path) -> None:
    """Per-turn audit JSON must NOT contain a hostCapabilities key."""
    from amplifier_agent_cli.modes.single_turn import _write_audit

    sessions_root = tmp_path / "amplifier-agent" / "sessions"
    with patch(
        "amplifier_agent_lib.persistence.session_state_dir",
        return_value=sessions_root / "sid-X",
    ):
        _write_audit(
            session_id="sid-X",
            turn_id="turn-1",
            correlation_id="cid",
            exit_code=0,
            started_at="2026-06-01T00:00:00Z",
            ended_at="2026-06-01T00:00:01Z",
            argv=["amplifier-agent", "run", "hi"],
            mcp_config_path=None,
            env_allowlist=None,
            env_extra=None,
            protocol_version="0.2.0",
        )
    audit_file = sessions_root / "sid-X" / "audits" / "turn-turn-1.json"
    audit = json.loads(audit_file.read_text(encoding="utf-8"))
    assert "hostCapabilities" not in audit, "audit JSON should not contain hostCapabilities"
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/cli/test_drop_host_capabilities.py::test_audit_dict_excludes_host_capabilities -v`

Expected: **FAIL** — `TypeError: missing required keyword 'host_capabilities'`.

**Step 3: Edit `_write_audit`**

Around line 170-203, in the function signature delete the line:

```python
    host_capabilities: dict[str, Any] | None,
```

In the audit dict body (around line 195), delete:

```python
        "hostCapabilities": host_capabilities,
```

**Step 4: Update all three call sites**

There are three `_write_audit(...)` invocations in `single_turn.py`: around lines 608-621 (after AaaError envelope), 636-649 (after generic exception envelope), and 669-682 (success path). In each, delete the line:

```python
        host_capabilities=host_capabilities,
```

**Step 5: Delete the transitional `host_capabilities = None` line from Task A2**

Earlier we inserted `host_capabilities = None  # transitional — removed in subsequent commits`. Find it (around the former `(5c)` block in `single_turn.py`) and delete it. Nothing should reference `host_capabilities` anymore.

**Verify nothing references it:**

```
grep -n "host_capabilities" src/amplifier_agent_cli/modes/single_turn.py
```

Expected: zero hits.

**Step 6: Run test to verify it passes, and verify the engine module imports cleanly**

```
uv run pytest tests/cli/test_drop_host_capabilities.py -v
uv run python -c "from amplifier_agent_cli.modes.single_turn import run; print('ok')"
```

Expected: PASS, then prints `ok`.

**Step 7: Commit**

```
git add src/amplifier_agent_cli/modes/single_turn.py tests/cli/test_drop_host_capabilities.py
git commit -m "chore(engine): drop hostCapabilities from per-turn audit + clear transitional shim"
```

---

## Section B — Engine: drop runtime state write and protocol TypedDict

### Task B1: Drop `session.metadata["host_capabilities"]` write in `_runtime.py`

**Files:**
- Modify: `src/amplifier_agent_lib/_runtime.py:259-260`

**Step 1: Write the failing test** (append to `tests/cli/test_drop_host_capabilities.py`)

```python
def test_runtime_session_metadata_excludes_host_capabilities() -> None:
    """After initialize, session.metadata must NOT carry a host_capabilities key.

    Regression guard against Mode A §2.6 D12 residue.
    """
    import importlib
    import inspect

    runtime = importlib.import_module("amplifier_agent_lib._runtime")
    source = inspect.getsource(runtime)
    assert 'metadata["host_capabilities"]' not in source, (
        "_runtime.py should not assign session.metadata['host_capabilities']"
    )
    assert "host_capabilities" not in source, (
        "_runtime.py should not reference host_capabilities at all"
    )
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/cli/test_drop_host_capabilities.py::test_runtime_session_metadata_excludes_host_capabilities -v`

Expected: **FAIL** — source still contains the assignment.

**Step 3: Delete the assignment**

In `src/amplifier_agent_lib/_runtime.py` around line 259-260, delete:

```python
    # ── A5: host capabilities storage ──
    session.metadata["host_capabilities"] = (params.get("host") or {}).get("capabilities") or {}
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/cli/test_drop_host_capabilities.py::test_runtime_session_metadata_excludes_host_capabilities -v`

Expected: **PASS**.

**Step 5: Commit**

```
git add src/amplifier_agent_lib/_runtime.py tests/cli/test_drop_host_capabilities.py
git commit -m "chore(engine): drop host_capabilities write from runtime session metadata"
```

---

### Task B2: Drop `HostCapabilities` TypedDict and `InitializeHostParams.capabilities`

**Files:**
- Modify: `src/amplifier_agent_lib/protocol/methods.py:66-77`

**Step 1: Write the failing test** (append to `tests/cli/test_drop_host_capabilities.py`)

```python
def test_protocol_methods_has_no_host_capabilities_typeddict() -> None:
    """HostCapabilities and InitializeHostParams must be gone from protocol.methods."""
    import amplifier_agent_lib.protocol.methods as m

    assert not hasattr(m, "HostCapabilities"), "HostCapabilities TypedDict should be removed"
    assert not hasattr(m, "InitializeHostParams"), "InitializeHostParams TypedDict should be removed"
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/cli/test_drop_host_capabilities.py::test_protocol_methods_has_no_host_capabilities_typeddict -v`

Expected: **FAIL** — both classes still defined.

**Step 3: Delete the TypedDicts**

In `src/amplifier_agent_lib/protocol/methods.py` around lines 66-77, delete the entire block:

```python
class HostCapabilities(TypedDict, total=False):
    """Capabilities advertised by the host to the agent (design §4.10.1)."""

    supports_steering: bool
    supports_structured_errors: bool


class InitializeHostParams(TypedDict, total=False):
    """``initialize.params.host`` envelope for host-side capability advertisement."""

    capabilities: HostCapabilities
```

**Step 4: Verify no other module imports these**

```
grep -rn "HostCapabilities\|InitializeHostParams" src/ tests/
```

Expected: only the file you just edited may show no hits at all; any hits in `src/` or `tests/` outside test_drop_host_capabilities.py and the design docs are a problem to follow up. (Spoiler: there should be none — the `_runtime.py` site read the field from raw dict access, not the TypedDict.)

**Step 5: Run test to verify it passes**

Run: `uv run pytest tests/cli/test_drop_host_capabilities.py::test_protocol_methods_has_no_host_capabilities_typeddict -v`

Expected: **PASS**.

**Step 6: Commit**

```
git add src/amplifier_agent_lib/protocol/methods.py tests/cli/test_drop_host_capabilities.py
git commit -m "chore(engine): drop HostCapabilities + InitializeHostParams TypedDicts"
```

---

## Section C — Schemas

### Task C1: Delete the two schema files and update `test_protocol_gen.py`

**Files:**
- Delete: `src/amplifier_agent_lib/protocol/schemas/HostCapabilities.schema.json`
- Delete: `src/amplifier_agent_lib/protocol/schemas/InitializeHostParams.schema.json`
- Modify: `tests/test_protocol_gen.py:82-83`

**Pattern:** This task uses "verify-and-delete" — the existing `test_protocol_gen.py:82` asserts the schemas exist as part of an expected set. Updating it IS the test that asserts removal.

**Step 1: Run the existing test to verify the schemas exist today**

Run: `uv run pytest tests/test_protocol_gen.py -v -k "schema"`

Expected: **PASS** (current state — schemas exist and are listed).

**Step 2: Delete the schema files**

```
rm src/amplifier_agent_lib/protocol/schemas/HostCapabilities.schema.json
rm src/amplifier_agent_lib/protocol/schemas/InitializeHostParams.schema.json
```

**Step 3: Run the existing test to verify it now fails**

Run: `uv run pytest tests/test_protocol_gen.py -v -k "schema"`

Expected: **FAIL** — `missing schema files: {'HostCapabilities.schema.json', 'InitializeHostParams.schema.json'}`.

**Step 4: Update `tests/test_protocol_gen.py` — remove the two entries from the `expected` set**

Around line 82-83, find:

```python
        "McpServerConfig.schema.json",
        "HostCapabilities.schema.json",
        "InitializeHostParams.schema.json",
        "error_codes.schema.json",
```

Change to:

```python
        "McpServerConfig.schema.json",
        "error_codes.schema.json",
```

**Step 5: Run the test to verify it passes**

Run: `uv run pytest tests/test_protocol_gen.py -v -k "schema"`

Expected: **PASS**.

**Step 6: Commit**

```
git add -A src/amplifier_agent_lib/protocol/schemas/ tests/test_protocol_gen.py
git commit -m "chore(schemas): delete HostCapabilities + InitializeHostParams schemas"
```

---

## Section D — Engine: drop obsolete tests that assert the old surface

### Task D1: Delete obsolete envelope test in `test_mode_a_v2_envelope.py`

**Files:**
- Modify: `tests/cli/test_mode_a_v2_envelope.py:141-167`

**Step 1: Confirm the obsolete test fails today**

Run: `uv run pytest tests/cli/test_mode_a_v2_envelope.py::test_host_capabilities_threaded_to_envelope -v`

Expected: **FAIL** (or error) — because the `--host-capabilities` CLI flag no longer exists; click will exit 2 and the assertion on `envelope["metadata"]["hostCapabilities"]` will not be reachable.

**Step 2: Delete the test function**

Around lines 141-167, delete the entire `def test_host_capabilities_threaded_to_envelope() -> None:` function (including its body and the blank line after it).

**Step 3: Run the file to verify the rest still passes**

Run: `uv run pytest tests/cli/test_mode_a_v2_envelope.py -v`

Expected: PASS for all remaining tests.

**Step 4: Commit**

```
git add tests/cli/test_mode_a_v2_envelope.py
git commit -m "test(engine): delete obsolete test_host_capabilities_threaded_to_envelope"
```

---

### Task D2: Update audit-trail test to drop `hostCapabilities` assertion + `--host-capabilities` CLI args

**Files:**
- Modify: `tests/cli/test_mode_a_audit_trail.py:33-36, :48`

**Step 1: Confirm the test fails today**

Run: `uv run pytest tests/cli/test_mode_a_audit_trail.py -v`

Expected: **FAIL** — the test passes `--host-capabilities` on the CLI which click now rejects (exit 2 → exit_code != 0), and/or `assert "hostCapabilities" in audit` fails.

**Step 2: Remove the CLI args and the assertion**

Around line 33-36, find the test's argv list:

```python
                "--session-id",
                "sid-X",
                "--mcp-servers",
                '{"s":{"transport":"stdio","command":"node","args":[],"env":{"K":"SECRET"}}}',
                "--host-capabilities",
                '{"supports_steering":false}',
                "hello",
```

Delete the two lines:

```python
                "--host-capabilities",
                '{"supports_steering":false}',
```

Around line 48, find:

```python
    assert "hostCapabilities" in audit
```

Delete that line.

**Step 3: Run the test to verify it passes**

Run: `uv run pytest tests/cli/test_mode_a_audit_trail.py -v`

Expected: **PASS**.

**Step 4: Commit**

```
git add tests/cli/test_mode_a_audit_trail.py
git commit -m "test(engine): drop hostCapabilities from audit-trail test"
```

---

### Task D3: Delete obsolete runtime metadata test + helper plumbing in `test_runtime_mcp_threading.py`

**Files:**
- Modify: `tests/test_runtime_mcp_threading.py:33, :43, :125-145`

**Step 1: Confirm the obsolete test fails today**

Run: `uv run pytest tests/test_runtime_mcp_threading.py::test_host_capabilities_stored_in_session_metadata -v`

Expected: **FAIL** — `session.metadata.get("host_capabilities")` returns `None` instead of the test's expected dict (we deleted the write in Task B1).

**Step 2: Delete the test function**

Around lines 125-145, delete the entire `async def test_host_capabilities_stored_in_session_metadata() -> None:` function.

**Step 3: Clean up the helper signature**

Around line 33 the `_make_params` helper has a `host_capabilities: dict[str, Any] | None = None,` keyword parameter that nothing in the file now uses. Delete it. Also around line 43:

```python
        "host": {"capabilities": host_capabilities or {}},
```

Delete the `"host": ...` key from the dict the helper returns. (Verify no other test in the file references the `host` key — `grep -n "host" tests/test_runtime_mcp_threading.py`.)

**Step 4: Run the file to verify the rest still passes**

Run: `uv run pytest tests/test_runtime_mcp_threading.py -v`

Expected: PASS for all remaining tests.

**Step 5: Commit**

```
git add tests/test_runtime_mcp_threading.py
git commit -m "test(engine): delete obsolete host_capabilities runtime test + helper plumbing"
```

---

## Section E — Conformance fixture removal

### Task E1: Delete the `initialize-with-host-capabilities` fixture and update Python fixture-set assertions

**Files:**
- Delete: `src/amplifier_agent_lib/protocol/conformance/fixtures/initialize-with-host-capabilities.yaml`
- Modify: `tests/test_phase_2_1_exit_gate.py:52`
- Modify: `tests/test_protocol_conformance_fixtures.py:105`

**Step 1: Confirm both Python fixture-set tests pass today**

Run: `uv run pytest tests/test_phase_2_1_exit_gate.py tests/test_protocol_conformance_fixtures.py -v -k "fixture"`

Expected: **PASS**.

**Step 2: Delete the fixture file**

```
rm src/amplifier_agent_lib/protocol/conformance/fixtures/initialize-with-host-capabilities.yaml
```

**Step 3: Run the tests to verify they now fail**

Run: `uv run pytest tests/test_phase_2_1_exit_gate.py tests/test_protocol_conformance_fixtures.py -v -k "fixture"`

Expected: **FAIL** — fixture name set no longer matches the expected set; the deleted name is now in `expected - actual`.

**Step 4: Update both expected sets**

In `tests/test_phase_2_1_exit_gate.py` around line 52, remove from the list:

```python
        "initialize-with-host-capabilities",
```

In `tests/test_protocol_conformance_fixtures.py` around line 105, remove from the set:

```python
        "initialize-with-host-capabilities",
```

**Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_phase_2_1_exit_gate.py tests/test_protocol_conformance_fixtures.py -v -k "fixture"`

Expected: **PASS**.

**Step 6: Commit**

```
git add -A src/amplifier_agent_lib/protocol/conformance/fixtures/initialize-with-host-capabilities.yaml tests/test_phase_2_1_exit_gate.py tests/test_protocol_conformance_fixtures.py
git commit -m "chore(conformance): delete initialize-with-host-capabilities fixture + update consumer sets"
```

---

### Task E2: Delete the conformance runner tests that exercise the deleted fixture

**Files:**
- Modify: `wrappers/conformance/test/runner-ts.test.ts:39-44`
- Modify: `wrappers/conformance/tests/test_runner_py.py:47-53`

**Pattern:** verify-and-delete — the existing runner tests reference a fixture that no longer exists, so they fail today. Delete them.

**Step 1: Confirm the runner tests fail today**

```
cd wrappers/conformance && npm test 2>&1 | grep -i "host" || true
cd wrappers/conformance && uv run pytest -v -k "host_capabilities"
```

Expected: TS and Py runner tests fail because the fixture file is gone.

**Step 2: Delete the TS test case**

In `wrappers/conformance/test/runner-ts.test.ts` around lines 39-44, delete the entire `it("initialize_with_host_capabilities passes", async () => { ... });` block.

**Step 3: Delete the Python test case**

In `wrappers/conformance/tests/test_runner_py.py` around lines 47-53, delete the entire `async def test_initialize_with_host_capabilities() -> None: ...` function.

**Step 4: Run the suites to verify they pass**

```
cd wrappers/conformance && npm test
cd wrappers/conformance && uv run pytest -v
```

Expected: PASS in both.

**Step 5: Commit**

```
cd ../..  # back to repo root
git add wrappers/conformance/test/runner-ts.test.ts wrappers/conformance/tests/test_runner_py.py
git commit -m "chore(conformance): drop runner test cases for deleted fixture"
```

---

## Section F — TypeScript wrapper (breaking)

### Task F1: Add the failing "AssembleArgvInput has no hostCapabilities" test

**Files:**
- Modify: `wrappers/typescript/test/argv-builder.test.ts:48-65`

**Pattern:** the existing test asserts `--host-capabilities` IS in argv. Modify it to assert it is NOT.

**Step 1: Replace the existing host-capabilities assertion with the inverse**

Find the existing test around line 48-65:

```typescript
  it("(iii) --host-capabilities threaded as JSON string and parseable", () => {
    const caps = { supports_steering: false, supports_structured_errors: true };
    const input: AssembleArgvInput = {
      sessionId: "sid",
      prompt: "hello",
      protocolVersion: "0.1.0",
      hostCapabilities: caps,
    };
    const argv = assembleArgv(input);
    const idx = argv.indexOf("--host-capabilities");
    expect(idx).toBeGreaterThan(-1);
    expect(JSON.parse(argv[idx + 1] as string)).toEqual(caps);
  });
```

Replace with (this becomes the removal guardrail):

```typescript
  it("(iii) --host-capabilities is not emitted (removed surface)", () => {
    const input: AssembleArgvInput = {
      sessionId: "sid",
      prompt: "hello",
      protocolVersion: "0.1.0",
    };
    const argv = assembleArgv(input);
    expect(argv).not.toContain("--host-capabilities");
  });
```

**Step 2: Run the test to verify it fails**

```
cd wrappers/typescript && npm test -- argv-builder
```

Expected: **FAIL** — TypeScript will likely still compile (the `hostCapabilities` field is still on `AssembleArgvInput`), but the new test will not be useful until we delete the surface. Actually — it may **PASS** because we didn't pass `hostCapabilities` in input, so argv won't contain it. That's fine; the test now guards against regression. Either way: it should not assert presence anymore.

If passes: that's OK — proceed. The real failing test comes next.

**Step 3: Commit the test edit alone (intentional intermediate)**

```
cd ../..
git add wrappers/typescript/test/argv-builder.test.ts
git commit -m "test(wrapper-ts): invert host-capabilities test to assert absence"
```

---

### Task F2: Delete `hostCapabilities` from `argv-builder.ts`

**Files:**
- Modify: `wrappers/typescript/src/argv-builder.ts:32-33, :63-66`

**Step 1: Write the failing compile-time test**

Append to `wrappers/typescript/test/argv-builder.test.ts`:

```typescript
  it("(removal) AssembleArgvInput does not expose hostCapabilities", () => {
    // Compile-time check: if hostCapabilities is still on the input type,
    // this assignment is allowed; we want it to be a type error post-removal.
    // Runtime guard: assembleArgv with no host-related input never emits the flag.
    const input: AssembleArgvInput = {
      sessionId: "sid",
      prompt: "hello",
      protocolVersion: "0.1.0",
    };
    const argv = assembleArgv(input);
    expect(argv.filter((a) => a.includes("host"))).toEqual([]);
  });
```

**Step 2: Verify it passes with surface still present (runtime is fine because no host input)**

Will pass; the real value is the next step.

**Step 3: Delete the `hostCapabilities` field on `AssembleArgvInput`**

In `wrappers/typescript/src/argv-builder.ts` around lines 32-33, delete:

```typescript
  /** Host capabilities object — emitted as `--host-capabilities <JSON>`. */
  hostCapabilities?: unknown;
```

Around lines 63-66, delete:

```typescript
  if (input.hostCapabilities !== undefined) {
    argv.push("--host-capabilities", JSON.stringify(input.hostCapabilities));
  }
```

**Step 4: Compile + test**

```
cd wrappers/typescript && npx tsc --noEmit && npm test
```

Expected: PASS — type check is clean, no test references the deleted field.

**Step 5: Commit**

```
cd ../..
git add wrappers/typescript/src/argv-builder.ts wrappers/typescript/test/argv-builder.test.ts
git commit -m "chore(wrapper-ts): drop hostCapabilities from AssembleArgvInput + argv emission"
```

---

### Task F3: Delete `host?` field from `SpawnAgentParams` and the import/spread in `index.ts`

**Files:**
- Modify: `wrappers/typescript/src/index.ts:26, :29, :69-70, :162-164`

**Step 1: Edit `index.ts`**

Around line 26:

```typescript
import type { McpServerConfig, HostCapabilities } from "./types.js";
```

Change to:

```typescript
import type { McpServerConfig } from "./types.js";
```

Around line 29:

```typescript
export type { McpServerConfig, HostCapabilities } from "./types.js";
```

Change to:

```typescript
export type { McpServerConfig } from "./types.js";
```

Around lines 69-70, delete:

```typescript
  /** Optional host envelope forwarded via `--host-capabilities` (A1). */
  host?: { capabilities?: HostCapabilities };
```

Around lines 162-164, in the `new SessionHandle({ ... })` call, delete:

```typescript
    ...(params.host?.capabilities !== undefined
      ? { hostCapabilities: params.host.capabilities }
      : {}),
```

**Step 2: Verify compile + test**

```
cd wrappers/typescript && npx tsc --noEmit && npm test
```

Expected: PASS — clean compile, all tests green.

If `SessionHandle`'s constructor signature still declares a `hostCapabilities` parameter, that needs cleaning too. Search:

```
grep -n "hostCapabilities" wrappers/typescript/src/
```

If any hit appears in `session.ts` or elsewhere, follow the trail and remove it (parameter on `SessionHandle` constructor, any threading into `assembleArgv`). Run tests after each edit. Each cleanup is its own small edit but the same commit.

**Step 3: Commit**

```
cd ../..
git add wrappers/typescript/src/index.ts wrappers/typescript/src/session.ts
git commit -m "chore(wrapper-ts): drop host field from SpawnAgentParams (BREAKING)"
```

---

### Task F4: Delete `HostCapabilities` and `InitializeHostParams` from `types.ts`

**Files:**
- Modify: `wrappers/typescript/src/types.ts:100-160` (the `HostCapabilities` interface, the `InitializeHostParams` interface, and the `host?: InitializeHostParams` reference at line 135, plus any dangling duplicate comments)

**Step 1: Identify and delete every `HostCapabilities`-related declaration**

The file has three regions of interest per the earlier grep (lines 102, 104, 110-114, 116, 135, 156, 159). Open the file in your editor and delete:

1. The `export interface HostCapabilities { ... }` block (around line 104).
2. The `InitializeHostParams` interface that holds `capabilities?: HostCapabilities` (around lines 110-114).
3. The `host?: InitializeHostParams;` field on whatever wrapper-internal type holds it (around line 135). If the surrounding type becomes empty post-removal, evaluate whether the type itself should be deleted; if other unrelated fields remain, leave them.
4. Any leftover `* Capabilities advertised by the host` JSDoc comments orphaned by the deletions (around lines 102, 116, 156, 159).

**Step 2: Compile + test**

```
cd wrappers/typescript && npx tsc --noEmit && npm test
```

Expected: PASS.

**Step 3: Verify zero hits**

```
grep -n "HostCapabilities\|InitializeHostParams" wrappers/typescript/src/ wrappers/typescript/test/
```

Expected: zero hits.

**Step 4: Commit**

```
cd ../..
git add wrappers/typescript/src/types.ts
git commit -m "chore(wrapper-ts): delete HostCapabilities + InitializeHostParams types"
```

---

## Section G — Python wrapper (breaking, parity)

### Task G1: Drop `host` parameter from `spawn_agent` and threading

**Files:**
- Modify: `wrappers/python/src/amplifier_agent_client/__init__.py:64, :95, :152-154, :166`

**Step 1: Locate the surface**

```
grep -n "host\|host_capabilities" wrappers/python/src/amplifier_agent_client/__init__.py
```

Confirms the four sites cited.

**Step 2: Edit `__init__.py`**

Around line 64 (in the `def spawn_agent(...)` signature):

```python
    host: dict[str, Any] | None = None,
```

Delete the parameter line.

Around line 95 (docstring):

```python
        host:                Host capabilities envelope.
```

Delete the docstring line.

Around lines 152-154:

```python
    host_capabilities: dict[str, Any] | None = None
    if host is not None and isinstance(host.get("capabilities"), dict):
        host_capabilities = host["capabilities"]
```

Delete all three lines.

Around line 166, in the call site that constructs whatever object is returned:

```python
        host_capabilities=host_capabilities,
```

Delete that line.

**Step 3: Run the wrapper suite**

```
cd wrappers/python && uv run pytest -v
```

Expected: many failures will surface if the Python `argv_builder.py` still has a `host_capabilities` knob — that's handled in Task G2.

If failures relate only to the `argv_builder` test, proceed; we'll fix it next. Otherwise stop and diagnose.

**Step 4: Commit**

```
cd ../..
git add wrappers/python/src/amplifier_agent_client/__init__.py
git commit -m "chore(wrapper-py): drop host param from spawn_agent (BREAKING parity with ts)"
```

---

### Task G2: Drop `host_capabilities` from Python `argv_builder` and its test

**Files:**
- Modify: `wrappers/python/src/amplifier_agent_client/argv_builder.py` (search for `host_capabilities`)
- Modify: `wrappers/python/tests/test_argv_builder.py:53-65`

**Step 1: Inspect the argv_builder Python source**

```
grep -n "host_capabilities" wrappers/python/src/amplifier_agent_client/argv_builder.py
```

Expected: at least two hits — the parameter declaration and the conditional `argv.extend(["--host-capabilities", ...])`.

**Step 2: Replace the existing test with the inverse**

In `wrappers/python/tests/test_argv_builder.py`, find around line 53:

```python
def test_host_capabilities_threaded_as_json_string_and_parseable() -> None:
    """(iii) --host-capabilities threaded as JSON string and parseable."""
    ...
    argv = assemble_argv(
        ...
        host_capabilities=caps,
    )
    idx = argv.index("--host-capabilities")
    ...
```

Replace with:

```python
def test_host_capabilities_flag_not_emitted() -> None:
    """(removal) --host-capabilities is no longer assembled."""
    argv = assemble_argv(
        session_id="sid",
        prompt="hello",
        protocol_version="0.1.0",
    )
    assert "--host-capabilities" not in argv
```

**Step 3: Run the test to verify it fails or passes**

```
cd wrappers/python && uv run pytest tests/test_argv_builder.py::test_host_capabilities_flag_not_emitted -v
```

May PASS (we removed the input, so the conditional doesn't fire), or may FAIL if `assemble_argv` still demands the parameter. Either way, proceed to delete the surface.

**Step 4: Delete `host_capabilities` from `argv_builder.py`**

In `wrappers/python/src/amplifier_agent_client/argv_builder.py`:

1. Delete the `host_capabilities: dict[str, Any] | None = None,` keyword parameter from `assemble_argv(...)`.
2. Delete the conditional block:

```python
    if host_capabilities is not None:
        argv.extend(["--host-capabilities", json.dumps(host_capabilities)])
```

(Verify by grep; the exact lines may shift.)

**Step 5: Compile + test**

```
cd wrappers/python && uv run pytest -v
```

Expected: PASS.

**Step 6: Verify zero hits**

```
cd ../.. && grep -rn "host_capabilities\|hostCapabilities" wrappers/python/
```

Expected: zero hits.

**Step 7: Commit**

```
git add wrappers/python/src/amplifier_agent_client/argv_builder.py wrappers/python/tests/test_argv_builder.py
git commit -m "chore(wrapper-py): drop host_capabilities from assemble_argv + test"
```

---

## Section H — Documentation and final verification

### Task H1: Mark Mode A amendment §2.6 D12 as SUPERSEDED

**Files:**
- Modify: `docs/designs/2026-05-24-aaa-v2-mode-a-pivot-amendment.md:286`

**Step 1: Insert the SUPERSEDED banner**

Find the `### 2.6 D12 — host.capabilities as additive agent/initialize field` heading around line 286. Immediately below the heading, insert:

```markdown
> **SUPERSEDED by `docs/designs/2026-06-01-drop-host-capabilities.md` (2026-06-01).**
> The `--host-capabilities` argv flag and the `HostCapabilities` surface have
> been removed across engine, wrappers, schemas, fixtures, and tests. The
> rationale below is preserved for historical context only.
```

**Step 2: Verify rendering**

```
head -300 docs/designs/2026-05-24-aaa-v2-mode-a-pivot-amendment.md | grep -A 6 "2.6 D12"
```

Expected: the heading is followed by the SUPERSEDED block.

**Step 3: Commit**

```
git add docs/designs/2026-05-24-aaa-v2-mode-a-pivot-amendment.md
git commit -m "docs(designs): mark Mode A §2.6 D12 SUPERSEDED by drop-host-capabilities"
```

---

### Task H2: Final grep verification — zero hits

**Step 1: Run the success-metric greps**

```
grep -rn "host_capabilities" src/ tests/ wrappers/
grep -rn "hostCapabilities" wrappers/
grep -rn "HostCapabilities" src/ wrappers/
grep -rn "InitializeHostParams" src/ wrappers/
```

Expected for all four: **zero hits**.

If any hit appears, identify the file and decide:
- Test fixture or removal guardrail in `tests/cli/test_drop_host_capabilities.py` → expected and fine; the test names contain the substring on purpose. Add an exclusion or accept the hit.
- Anywhere else in `src/` or `wrappers/` → that's a missed deletion; loop back to the relevant section.

For full-suite confidence:

```
uv run pytest -x -q
cd wrappers/typescript && npm test
cd ../python && uv run pytest -x -q
cd ../conformance && npm test && uv run pytest -x -q
cd ../..
```

Expected: green across the board.

**Step 2: Verify the loud-failure success criterion from the design**

The design specifies: *"Invoking `amplifier-agent run` with `--host-capabilities '<json>'` produces a click `UsageError` and exits 2."*

```
uv run amplifier-agent run --session-id test --host-capabilities '{}' "hi" ; echo "exit=$?"
```

Expected: stderr contains `No such option: --host-capabilities`, exit code `2`. This confirms the loud-failure path.

**Step 3: Commit (only if any test fixture exclusions needed in step 1)**

If you needed to add an exclusion for the guardrail test file, commit it:

```
git add tests/cli/test_drop_host_capabilities.py
git commit -m "test(engine): scope removal guardrail names to skip the verification greps"
```

Otherwise skip — no commit needed for a successful grep.

---

### Task H3: File a follow-up task for the `nanoclaw` repo

**Pattern:** out-of-repo work. This task is a reminder, not code.

**Step 1: Create the follow-up issue in nanoclaw**

Open the `nanoclaw` repo (separate checkout) and file an issue titled:

> **Drop `host: { capabilities }` from adapter `spawnAgent` call (paired with amplifier-agent PR #__)**

Body should reference:
- This plan: `docs/plans/2026-06-01-drop-host-capabilities-implementation.md`
- Design: `docs/designs/2026-06-01-drop-host-capabilities.md`
- The site in NC's adapter that passes `host: { capabilities: { supports_steering: false, supports_structured_errors: true } }` to `spawnAgent` (per Mode A §4.1.4).

State: amplifier-agent v0.x.y removes the `host` field from `SpawnAgentParams`. NC's adapter must drop the `host:` block to compile against the new wrapper.

**Step 2: Link the issue from this PR's description**

When opening the amplifier-agent PR, include the nanoclaw issue URL in the PR body under a "Follow-up" section.

No commit. No code.

---

## Plan Summary

| Section | Tasks | Commits | Surface |
|---|---|---|---|
| A — Engine: argv flag + plumbing | A1, A2, A3, A4, A5 | 5 | `single_turn.py` |
| B — Engine: runtime + TypedDicts | B1, B2 | 2 | `_runtime.py`, `methods.py` |
| C — Schemas | C1 | 1 | 2 schema files + `test_protocol_gen.py` |
| D — Obsolete engine tests | D1, D2, D3 | 3 | 3 test files |
| E — Conformance fixture | E1, E2 | 2 | 1 fixture + 4 consumer tests |
| F — TS wrapper (BREAKING) | F1, F2, F3, F4 | 4 | `types.ts`, `index.ts`, `argv-builder.ts`, test |
| G — Python wrapper (BREAKING) | G1, G2 | 2 | `__init__.py`, `argv_builder.py`, test |
| H — Docs + verification | H1, H2, H3 | 1-2 + 1 follow-up issue | amendment SUPERSEDED note |

**Total:** ~21 tasks, ~20 commits, ~14 files touched, 3 files deleted (2 schemas + 1 fixture). Plus 1 cross-repo follow-up issue.

**Order constraint:** Sections A → B → C are the engine and must complete before any wrapper work — call sites in `single_turn.py` cannot reference an undefined `host_capabilities` for more than the duration of one commit window. Within A, the tasks are written so each commit leaves the tree compiling and the suite passing (modulo the obsolete tests, which are explicitly cleaned in Section D). Sections D, E, F, G, H can be reordered if needed but the order given minimizes cross-commit churn.

**Rollback plan:** every commit is atomic and revertable. `git revert <sha>` on any single commit returns the surface it deleted. If a multi-commit revert is needed (e.g., the engine flag is needed back urgently for a stuck consumer), revert in reverse order: H → G → F → E → D → C → B → A.

**Success criteria (from §6 of the design):**

- `grep -r "host_capabilities" src/ tests/ wrappers/` → zero hits (modulo design doc + this plan + the guardrail test file).
- `grep -r "hostCapabilities" wrappers/` → zero hits.
- Full test suite green across engine, both wrappers, and both conformance runners.
- `amplifier-agent run --host-capabilities '<json>' "hi"` → click `UsageError`, exit 2.
- NC follow-up issue filed.

When all five pass, Phase 1 is complete.
