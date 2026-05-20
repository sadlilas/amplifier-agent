# Phase 2.0c — Engine Gap Fixes Implementation Plan

> **Execution:** Use the subagent-driven-development workflow to implement this plan.

**Goal:** Close engine gaps (a)(b)(c)(d)(e) + SC-3/SC-4/SC-6, delete dead Mode B code, split admin verbs, and ship the streaming hook so production emits real display events.

**Architecture:** This plan implements Phase 2.0c of the locked AaA v2 design. It modifies five surfaces: (1) the protocol-point Protocols + their CLI defaults; (2) the wire protocol TypedDicts (deletions only); (3) the CLI `run` command and `__main__` dispatcher; (4) the admin verbs (split `doctor` into `doctor` + `prepare` + `verify`); (5) the vendored bundle (new streaming hook + manifest registration + `_runtime.py` bridge that connects foundation kernel events to `ctx.display.emit()`).

**Tech Stack:** Python 3.13, `pytest` + `pytest-asyncio` (strict mode), Click for CLI, `TypedDict` + `Protocol` (runtime_checkable) for shapes, ruff + pyright via the `python_check` tool, conventional commit messages. Foundation kernel hook API: `coordinator.hooks.register(event_name, async_handler)`.

**Design source:** `docs/designs/2026-05-20-aaa-v2-wrapper-and-wire.md` (commit `ff12eb8`). Read §4 (components), §5 (flows), §8 (decisions D1–D10), §10 (migration plan), and **Appendix C (engine fix sequencing — the 8-row table that drives this plan)**.

**SC-1 finding (already done; do not redo):** Foundation kernel emits `tool:pre` and `tool:post` as separate hook events. They map 1:1 to wire events `tool/started` and `tool/completed`. The minimum-set of 5 events is implementable as designed.

---

## Task ordering at a glance

| # | Task | Appendix C step | Critical path? |
|---|---|---|---|
| 1 | Patch design checkpoint (Appendix A + B) | (doc) | No |
| 2 | Gap (a): `DisplaySystem.emit` → async + single-arg | step 1 | **Yes** — blocks 10/11 |
| 3 | Gap (b): lock `ApprovalSystem.request` shape with conformance test | step 2 | No (already conforms) |
| 4 | Gap (e): remove `turn/cancel` TypedDicts | step 3 | No |
| 5 | Delete Mode B (`defaults_stdio.py`, `stdio_loop.py`, `--stdio`, tests) | step 3 (extends) | No |
| 6 | Gap (c): thread `--session-id` / `--resume` / `--provider` / `--cwd` into `Engine.boot()` | step 4 | No |
| 7 | Admin verb split: `prepare` + `verify` (new); `doctor` trimmed | step 8 | No |
| 8 | SC-3: strict-refuse `PROTOCOL_VERSION` mismatch in `Engine.boot()` | step 7 | No |
| 9 | SC-6: verify `sessionId` in final-reply scalar envelope | step 6 | No |
| 10 | Gap (d) Part 1: rewrite `_runtime.py` bridge (display + approval coordinator wiring) | step 5 | **Yes** |
| 11 | Gap (d) Part 2: new `bundle/hook_streaming.py` | step 5 | **Yes** — depends on 2, 10 |
| 12 | Gap (d) Part 3: register streaming hook in `bundle.md` | step 5 | **Yes** — depends on 11 |
| 13 | SC-4: resume continuity end-to-end test | (gate) | No |
| 14 | Phase 2.0c exit gate: real foundation turn + `verify --check-hooks` | (gate) | **Yes** — depends on 11, 12 |

**Critical-path:** 2 → 10 → 11 → 12 → 14. Everything else is parallel-safe but is written here in the canonical order for clean reviewable commits.

---

## Conventions for every task

- Read all referenced files **before** editing. The `edit_file` tool requires it; you will save yourself debugging time by skimming the surrounding code first.
- TDD discipline: write a failing test, run it, see it fail, implement minimum code, run it, see it pass, commit.
- Run `python_check` (the lint+type+format tool — equivalent to CI) on every changed Python file before committing. Fix all errors. Warnings OK.
- Use `pytest` directly (NOT `uv run pytest`) for fast iteration when running a single test. Use `uv run pytest` for full suites and for tests under `tests/cli/test_end_to_end.py` (those need the installed console-script).
- Commits use conventional commit style. Observe `git log --oneline` for examples (`feat(bundle): ...`, `feat: ...`, `docs(design): ...`). Default scope for engine work is `engine`, for cli work is `cli`, for bundle work is `bundle`.
- After every commit, run `pytest tests/ -q` once to confirm the whole suite still passes. Fix any breakage before moving to the next task.

---

## Task 1: Patch design checkpoint with Appendix A + B amendments

**Why:** The locked design supersedes §4 of `docs/status/amplifier-as-agent-design-checkpoint.md`. The four factual corrections from the PC + NC empirical surveys (Appendix B of the design doc) should land in the checkpoint too. Doing this first means every subsequent task can quote the canonical, post-amendment language.

**Files:**
- Modify: `docs/status/amplifier-as-agent-design-checkpoint.md`

**Step 1: Read the current checkpoint section**

Run: `grep -n "^## §4\|^### §4\|^## 4\|^### 4\|lifecycle:\|turn/cancel" docs/status/amplifier-as-agent-design-checkpoint.md`

Read the file (probably ~500 lines). Locate the §4 wrapper public API section and the listing of wire methods.

**Step 2: Apply Appendix A amendment**

Replace the existing `lifecycle: 'one-shot' | 'burst'` passage with the verbatim block from Appendix A of `docs/designs/2026-05-20-aaa-v2-wrapper-and-wire.md` (lines 593–605 of that doc). The replacement covers: lifecycle locked to `'one-shot'`, `turn/cancel` removed from wire methods, `handle.getEngineInfo()` exposed, first-run UX via `prepare`. Use `edit_file` with the existing checkpoint text as `old_string`.

**Step 3: Apply Appendix B factual corrections**

Add a new sub-section at the end of the doc (or wherever inline `NanoClaw` descriptions live):

```markdown
## Factual corrections from 2026-05-20 empirical surveys

The following four checkpoint claims were corrected after surveys of
`/Users/mpaidiparthy/repos/AaA/paperclip` and `/Users/mpaidiparthy/repos/AaA/nanoclaw`:

1. **`idleHeartbeat: true` does not exist in NanoClaw.** The NC host has no
   provider abstraction at all; the `AgentProvider` interface lives inside
   each container's agent-runner at `container/agent-runner/src/providers/types.ts`.
2. **NanoClaw's V1 `amplifier_local` provider does not exist** — zero refs
   anywhere in the NC repo.
3. **NanoClaw's `cachedClient` does not exist** — zero occurrences in NC repo.
4. **Codex in NanoClaw is spawn-per-query, not a burst daemon**
   (`add-codex/SKILL.md:139` documents "no long-lived daemon to keep healthy").

Net implication: NC at the host level is one-shot, same as PC. The one-shot
pivot (D10) is grounded in both hosts' actual implementations.
```

**Step 4: Commit**

```bash
git add docs/status/amplifier-as-agent-design-checkpoint.md
git commit -m "docs(status): amend checkpoint §4 per design doc Appendix A + B

- lifecycle: locked to 'one-shot' in v1; 'burst' reserved-but-rejected
- turn/cancel: removed from wire methods (SIGTERM replaces routing)
- handle.getEngineInfo(): new method exposing resolved binary metadata
- First-run UX: install-time prepare verb
- Factual corrections from PC + NC surveys (4 items)

Refs: docs/designs/2026-05-20-aaa-v2-wrapper-and-wire.md (Appendix A + B)"
```

No tests required — this is a documentation patch.

---

## Task 2: Gap (a) — `DisplaySystem.emit` async + single-arg `DisplayEvent`

**Why:** The `DisplaySystem` Protocol is currently `def emit(self, event: DisplayEvent) -> None` (sync). The design (§4.7 row (a)) locks it to **`async def emit(self, event: DisplayEvent) -> None`**. Foundation kernel hooks are async (per SC-1 finding); making `emit` async lets the streaming hook (Task 11) call it directly from inside `async def on_tool_pre(...)` without thread-bridging gymnastics.

**Files:**
- Modify: `src/amplifier_agent_lib/protocol_points/base.py`
- Modify: `src/amplifier_agent_lib/protocol_points/defaults_cli.py`
- Modify: `src/amplifier_agent_lib/protocol_points/defaults_stdio.py` (transitional — file deleted in Task 5)
- Modify: `tests/test_protocol_points_base.py`
- Modify: `tests/test_protocol_points_defaults_cli.py`

**Step 1: Write the failing test (Protocol conformance is async)**

Read `tests/test_protocol_points_base.py`. Replace the body of `test_display_system_protocol_conformance` to assert async-emit conformance:

```python
@pytest.mark.asyncio
async def test_display_system_protocol_conformance() -> None:
    """A class with an async emit() method satisfies the DisplaySystem Protocol."""
    from amplifier_agent_lib.protocol_points.base import DisplayEvent, DisplaySystem

    class _RecordingDisplay:
        def __init__(self) -> None:
            self.events: list[DisplayEvent] = []

        async def emit(self, event: DisplayEvent) -> None:
            self.events.append(event)

    recorder = _RecordingDisplay()
    assert isinstance(recorder, DisplaySystem), "_RecordingDisplay should conform to DisplaySystem"
    event: DisplayEvent = {"type": "result/delta", "sessionId": "sess-1"}
    await recorder.emit(event)
    assert recorder.events == [event]
```

**Step 2: Run test to verify it fails**

```bash
pytest tests/test_protocol_points_base.py::test_display_system_protocol_conformance -v
```

Expected: FAIL — the current Protocol declares `emit` as sync; the async signature won't satisfy `isinstance(...)` for the runtime_checkable Protocol. (Note: runtime_checkable only checks attribute presence, so the isinstance check may still pass — but the test should fail on `await recorder.emit(event)` raising a TypeError because Coroutines aren't returned by the current sync signature... actually, since `_RecordingDisplay` defines async itself, the test will pass against the current sync Protocol too. To make this a real failure, we need a different shape — see Step 3.)

**Step 2 (revised): make the test gate on the actual Protocol signature**

Replace the assertion with a stricter check that interrogates the Protocol signature:

```python
def test_display_system_emit_signature_is_async() -> None:
    """DisplaySystem.emit MUST be declared as `async def`."""
    import inspect

    from amplifier_agent_lib.protocol_points.base import DisplaySystem

    assert inspect.iscoroutinefunction(DisplaySystem.emit), (
        "DisplaySystem.emit must be `async def emit(event: DisplayEvent) -> None`"
    )
```

Re-run:

```bash
pytest tests/test_protocol_points_base.py::test_display_system_emit_signature_is_async -v
```

Expected: FAIL — `DisplaySystem.emit` is currently a sync `def`.

**Step 3: Implement — make `emit` async on the Protocol**

In `src/amplifier_agent_lib/protocol_points/base.py`, change the `DisplaySystem` Protocol to:

```python
@runtime_checkable
class DisplaySystem(Protocol):
    """One-way display event sink injected at ``Engine.boot()``.

    Per design §4.7 (gap a), ``emit`` is async with a single ``DisplayEvent``
    argument. Implementations may queue internally; callers must ``await``.
    """

    async def emit(self, event: DisplayEvent) -> None:
        """Emit a display event."""
        ...
```

**Step 4: Update `CliDisplaySystem.emit` to be async**

In `src/amplifier_agent_lib/protocol_points/defaults_cli.py`, change `def emit` to `async def emit`. The body is unchanged (it's pure stream IO, fast enough to run inline on the event loop).

**Step 5: Update `StdioDisplaySystem.emit` to be async (transitional — file deleted in Task 5)**

In `src/amplifier_agent_lib/protocol_points/defaults_stdio.py`, change every `def emit` to `async def emit`. This keeps the file conforming until Task 5 deletes it.

**Step 6: Update the recording-style sync test in `test_protocol_points_base.py`**

The previous `test_display_system_protocol_conformance` used a sync-emit recorder. Replace with the async version shown in Step 1.

**Step 7: Update CLI defaults tests**

In `tests/test_protocol_points_defaults_cli.py`, find every `display.emit(...)` call and wrap with `await`; mark the surrounding test `@pytest.mark.asyncio` if not already. Same for any tests in `tests/test_defaults_stdio.py` that call `.emit(...)` — note Task 5 deletes that file entirely, so transient breakage is OK as long as the test suite passes at the end of Task 2.

**Step 8: Update callers of `.emit(...)` in production code**

Grep for emit call sites:

```bash
grep -rn "\.emit(" src/ tests/ --include="*.py" | grep -v "^.*:.*#"
```

For each call site (engine.py is a likely candidate; `_runtime.py` does NOT currently call emit but will in Task 10), update to `await display.emit(...)` if the caller is async. If a sync caller exists that cannot easily become async, surface it in the implementation note — but inspection should show all call sites are already async.

**Step 9: Run python_check**

```python
python_check(paths=["src/amplifier_agent_lib/protocol_points/", "tests/test_protocol_points_base.py", "tests/test_protocol_points_defaults_cli.py", "tests/test_defaults_stdio.py"])
```

Fix every reported error. Re-run until clean.

**Step 10: Run the test suite to verify pass**

```bash
pytest tests/ -q
```

Expected: ALL PASS. If `tests/test_defaults_stdio.py` fails because StdioDisplaySystem callers (e.g. in `stdio_loop.py`) still call sync `.emit(...)`, either fix those call sites now or mark them `xfail` (Task 5 deletes them).

**Step 11: Commit**

```bash
git add src/amplifier_agent_lib/protocol_points/ tests/test_protocol_points_base.py tests/test_protocol_points_defaults_cli.py tests/test_defaults_stdio.py
git commit -m "feat(engine): gap (a) — DisplaySystem.emit async + single-arg DisplayEvent

Per design §4.7 (a). Makes emit awaitable so streaming hook (Task 11)
can call ctx.display.emit() directly from async kernel hook callbacks
without thread bridging.

Updates: base.Protocol, CliDisplaySystem, StdioDisplaySystem (transitional;
StdioDisplaySystem is deleted in Phase 2.0c step 5).

Refs: docs/designs/2026-05-20-aaa-v2-wrapper-and-wire.md Appendix C step 1"
```

---

## Task 3: Gap (b) — lock `ApprovalSystem.request` shape with conformance test

**Why:** Inspection of `src/amplifier_agent_lib/protocol_points/base.py` shows `ApprovalSystem.request` is already `async def request(self, req: ApprovalRequest) -> ApprovalResponse` (single-arg, async, typed). `CliApprovalSystem.request` already conforms. The design (§4.7 row (b)) calls for "reconciliation"; in practice, the protocol-point base already matches the locked shape. This task lays down a conformance test that future PRs cannot regress.

**Files:**
- Modify: `tests/test_protocol_points_base.py`

**Step 1: Write the failing test (lock the shape)**

Add to `tests/test_protocol_points_base.py`:

```python
def test_approval_system_request_signature_is_async_single_arg() -> None:
    """ApprovalSystem.request MUST be `async def request(req: ApprovalRequest)`."""
    import inspect

    from amplifier_agent_lib.protocol_points.base import ApprovalSystem

    assert inspect.iscoroutinefunction(ApprovalSystem.request), (
        "ApprovalSystem.request must be async"
    )
    sig = inspect.signature(ApprovalSystem.request)
    params = [p for p in sig.parameters.values() if p.name != "self"]
    assert len(params) == 1, f"Expected one non-self parameter, got {len(params)}"
    assert params[0].name == "req", f"Expected param name 'req', got {params[0].name!r}"
```

**Step 2: Run test to verify it passes (no implementation needed)**

```bash
pytest tests/test_protocol_points_base.py::test_approval_system_request_signature_is_async_single_arg -v
```

Expected: PASS. The shape already conforms. If it fails, you've misread the existing code — go back to `base.py` and check.

**Step 3: Run python_check on the test file**

```python
python_check(paths=["tests/test_protocol_points_base.py"])
```

**Step 4: Commit**

```bash
git add tests/test_protocol_points_base.py
git commit -m "test(protocol_points): gap (b) — lock ApprovalSystem.request shape

Adds an introspection-based test asserting ApprovalSystem.request is
async + single-arg. Shape already matches the locked design; this test
prevents future regressions.

Refs: docs/designs/2026-05-20-aaa-v2-wrapper-and-wire.md Appendix C step 2"
```

---

## Task 4: Gap (e) — remove `turn/cancel` TypedDicts from wire

**Why:** D3 of the locked design removes `turn/cancel` from the wire entirely. Cancel is performed by the wrapper sending SIGTERM to the engine subprocess. This task deletes the `TurnCancelParams` and `TurnCancelResult` TypedDicts from `protocol/methods.py`. Routing code that consumed `turn/cancel` is deleted by Task 5 (it lives in `stdio_loop.py`).

**Files:**
- Modify: `src/amplifier_agent_lib/protocol/methods.py`
- Modify: `src/amplifier_agent_lib/protocol/__init__.py` (if it re-exports `TurnCancelParams`/`TurnCancelResult`)
- Modify: `tests/test_protocol_methods.py`

**Step 1: Write the failing test (TypedDicts are gone)**

Add to `tests/test_protocol_methods.py`:

```python
def test_turn_cancel_typeddicts_removed() -> None:
    """TurnCancelParams and TurnCancelResult MUST NOT exist in protocol/methods.

    Per design D3, cancel is SIGTERM of the subprocess; no wire method.
    """
    from amplifier_agent_lib.protocol import methods as _methods

    forbidden = ("TurnCancelParams", "TurnCancelResult")
    module_names = dir(_methods)
    for name in forbidden:
        assert name not in module_names, (
            f"{name!r} must be removed from protocol/methods.py (design D3)"
        )
```

**Step 2: Run test to verify it fails**

```bash
pytest tests/test_protocol_methods.py::test_turn_cancel_typeddicts_removed -v
```

Expected: FAIL with `assert 'TurnCancelParams' not in [...]`.

**Step 3: Delete the TypedDicts**

In `src/amplifier_agent_lib/protocol/methods.py`, delete the entire `# turn/cancel` section (lines around 82–98):

```python
# ---------------------------------------------------------------------------
# turn/cancel
# ---------------------------------------------------------------------------


class TurnCancelParams(TypedDict):
    ...


class TurnCancelResult(TypedDict):
    ...
```

**Step 4: Remove re-exports**

Grep:

```bash
grep -rn "TurnCancel" src/amplifier_agent_lib/
```

Remove any line that imports or re-exports `TurnCancelParams` / `TurnCancelResult`. Common location: `src/amplifier_agent_lib/protocol/__init__.py`.

**Step 5: Run test to verify it passes**

```bash
pytest tests/test_protocol_methods.py::test_turn_cancel_typeddicts_removed -v
```

Expected: PASS.

**Step 6: Run the full test suite + python_check**

```bash
pytest tests/ -q
```

```python
python_check(paths=["src/amplifier_agent_lib/protocol/"])
```

Tests that referenced `TurnCancelParams` will fail — but inspection earlier suggested only `stdio_loop.py` dispatches `turn/cancel`. That code is deleted in Task 5. For now, if any test fails because of this, add an `xfail` marker with a TODO referring to Task 5.

**Step 7: Commit**

```bash
git add src/amplifier_agent_lib/protocol/ tests/test_protocol_methods.py
git commit -m "feat(protocol): gap (e) — remove turn/cancel TypedDicts (D3)

Per design D3: cancel is SIGTERM of the engine subprocess. No wire-level
turn/cancel method. TurnCancelParams + TurnCancelResult deleted; routing
code that consumed turn/cancel is removed in the Mode B deletion task.

Refs: docs/designs/2026-05-20-aaa-v2-wrapper-and-wire.md Appendix C step 3, D3"
```

---

## Task 5: Delete Mode B (`defaults_stdio.py`, `stdio_loop.py`, `--stdio`, all tests)

**Why:** Per design Assumption A0 and §10 of the design doc, Mode B (stdio JSON-RPC loop) is unused. Both Paperclip and NanoClaw spawn fresh subprocesses per query. Mode B is ~600 LOC of routing + lifecycle infrastructure that no consumer exercises. Deleting it eliminates an entire class of bugs (CR-4 silent `turn/cancel` consumption, F11 mid-burst death) by construction.

**Step 5 is split into THREE sub-commits** for review clarity: (a) delete sources, (b) delete tests, (c) strip `--stdio` from CLI.

**Files removed:**
- `src/amplifier_agent_lib/protocol_points/defaults_stdio.py`
- `src/amplifier_agent_cli/modes/stdio_loop.py`
- `tests/test_defaults_stdio.py`
- `tests/cli/test_stdio_loop_dispatch.py`
- `tests/cli/test_stdio_loop_handshake.py`
- `tests/cli/test_stdio_loop_subprocess.py`

**Files modified:**
- `src/amplifier_agent_cli/__main__.py` (no change — does not currently reference stdio_loop)
- `src/amplifier_agent_cli/modes/single_turn.py` (strip the `--stdio` flag + the entire `if stdio:` block)
- `tests/cli/test_end_to_end.py` (replace `test_run_stdio_exits_0_on_stdin_close` with a `test_stdio_flag_removed`)

**Step 1: Write the failing test (modes/stdio_loop is gone, --stdio flag rejected)**

In `tests/cli/test_end_to_end.py`, replace `test_run_stdio_exits_0_on_stdin_close` with:

```python
def test_stdio_flag_removed() -> None:
    """The --stdio flag must be removed (Mode B deleted per design D10/A0).

    Invoking `amplifier-agent run --stdio` should exit with a usage error
    (exit code 2, click's "no such option").
    """
    result = _run("run", "--stdio", env={"ANTHROPIC_API_KEY": "sk-test"}, input_text="")
    assert result.returncode == 2, (
        f"--stdio must be rejected; got exit {result.returncode}, "
        f"stdout={result.stdout!r}, stderr={result.stderr!r}"
    )
    assert "no such option" in result.stderr.lower() or "unrecognized" in result.stderr.lower()
```

Also add a deletion-detector test in `tests/test_smoke.py` (or wherever import-level smoke lives):

```python
def test_modes_stdio_loop_module_removed() -> None:
    """The stdio_loop module must not be importable (Mode B deleted)."""
    import importlib

    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("amplifier_agent_cli.modes.stdio_loop")


def test_defaults_stdio_module_removed() -> None:
    """The defaults_stdio module must not be importable (Mode B deleted)."""
    import importlib

    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("amplifier_agent_lib.protocol_points.defaults_stdio")
```

If `tests/test_smoke.py` doesn't import `pytest`, add `import pytest` at the top.

**Step 2: Run tests to verify they fail**

```bash
pytest tests/test_smoke.py::test_modes_stdio_loop_module_removed tests/test_smoke.py::test_defaults_stdio_module_removed tests/cli/test_end_to_end.py::test_stdio_flag_removed -v
```

Expected: FAIL (modules still importable; `--stdio` still accepted).

**Step 3: Delete the source files**

```bash
git rm src/amplifier_agent_lib/protocol_points/defaults_stdio.py
git rm src/amplifier_agent_cli/modes/stdio_loop.py
```

**Step 4: Delete the test files**

```bash
git rm tests/test_defaults_stdio.py
git rm tests/cli/test_stdio_loop_dispatch.py
git rm tests/cli/test_stdio_loop_handshake.py
git rm tests/cli/test_stdio_loop_subprocess.py
```

**Step 5: Strip `--stdio` from `single_turn.py`**

In `src/amplifier_agent_cli/modes/single_turn.py`:

1. Remove the `@click.option("--stdio", ...)` decorator line.
2. Remove `stdio: bool` from the `run(...)` function signature.
3. Remove the entire `# (1) --stdio: Mode B — run the JSON-RPC stdio loop.` block (the `if stdio: ... sys.exit(_asyncio.run(_main_stdio()))` block). That's roughly lines 191–279 of the current file.
4. Remove now-unused imports: `from amplifier_agent_cli.modes import stdio_loop as _stdio_loop` (it's inside the deleted block; verify there are no stale top-level imports of stdio_loop or defaults_stdio).
5. Remove `--idle-timeout` flag if it's only used by the stdio block; otherwise leave it.

Re-read the file after edits — confirm the `run()` function is clean. The function signature becomes (alphabetical-ish, kept in declared order):

```python
def run(
    prompt: str | None,
    session_id: str | None,
    resume: bool,
    fresh: bool,
    provider_override: str | None,
    bundle: str | None,
    config_path: str | None,
    cwd: str | None,
    verbose: bool,
    debug: bool,
    yes_flag: bool,
    no_flag: bool,
    quiet: bool,
) -> None:
```

**Step 6: Grep for any lingering references**

```bash
grep -rn "stdio_loop\|defaults_stdio\|StdioDisplaySystem\|StdioApprovalSystem\|--stdio" src/ tests/ | grep -v "\.md:"
```

Remove every remaining reference. Comments referring to "Mode B" in surviving code should be deleted or updated.

**Step 7: Run python_check**

```python
python_check(paths=["src/", "tests/"])
```

Fix every error.

**Step 8: Run the full test suite**

```bash
pytest tests/ -q
```

Expected: ALL PASS. If a test fails because it imported `StdioDisplaySystem` or similar, delete the test if its purpose was Mode B; otherwise migrate the test to use a `_RecordingDisplay` mock.

**Step 9: Commit (single commit; the three sub-tasks are bundled because they're all "delete Mode B")**

```bash
git status   # verify deletions + edits are staged
git add -A
git commit -m "feat: delete Mode B (defaults_stdio + stdio_loop + --stdio)

Per design D10 + A0: no host on Brian's roadmap needs in-process burst
or mid-turn submit() against the same subprocess. Mode B (~600 LOC) was
designed for a use case empirical surveys of PC + NC show no host uses.

Removed:
  src/amplifier_agent_lib/protocol_points/defaults_stdio.py
  src/amplifier_agent_cli/modes/stdio_loop.py
  tests/test_defaults_stdio.py
  tests/cli/test_stdio_loop_dispatch.py
  tests/cli/test_stdio_loop_handshake.py
  tests/cli/test_stdio_loop_subprocess.py

Modified:
  src/amplifier_agent_cli/modes/single_turn.py — strip --stdio flag
  tests/cli/test_end_to_end.py — assert --stdio is rejected
  tests/test_smoke.py — assert removed modules unimportable

Closes design failure modes F11, CR-4 by structural construction.

Refs: docs/designs/2026-05-20-aaa-v2-wrapper-and-wire.md D10, Appendix C step 3"
```

---

## Task 6: Gap (c) — thread CLI flags through `Engine.boot()`

**Why:** Per design §4.7 (c), `single_turn.py` constructs `init_params` for `Engine.boot()` but currently drops `cwd`, `providerOverride`, and (effectively) `resume` (it's passed but Engine.boot doesn't propagate it usefully). This task widens the path so all four init params arrive at the bundle layer.

**Files:**
- Modify: `src/amplifier_agent_cli/modes/single_turn.py`
- Modify: `src/amplifier_agent_lib/engine.py`
- Modify: `tests/test_engine.py`
- Create: `tests/cli/test_single_turn_init_params.py`

**Step 1: Write the failing test (Engine.boot honors all init params in the returned sessionState)**

Add to `tests/test_engine.py`:

```python
@pytest.mark.asyncio
async def test_boot_propagates_session_id_and_resume_and_cwd() -> None:
    """Engine.boot must echo sessionId/resume into sessionState and accept cwd/providerOverride."""
    from amplifier_agent_lib.engine import Engine

    async def _noop_handler(ctx):  # type: ignore[no-untyped-def]
        return "ok"

    class _Display:
        async def emit(self, event):  # type: ignore[no-untyped-def]
            pass

    class _Approval:
        async def request(self, req):  # type: ignore[no-untyped-def]
            return {"action": "accept"}

    # We need a bundle override to avoid touching the real XDG cache.
    class _FakeBundle:
        pass

    engine = Engine(turn_handler=_noop_handler, protocol_points={"approval": _Approval(), "display": _Display()})
    result = await engine.boot(
        {
            "protocolVersion": "2026-05-aaa-v0",
            "capabilities": {},
            "sessionId": "sess-xyz",
            "resume": True,
            "cwd": "/tmp",
            "providerOverride": "anthropic",
        },
        bundle_override=_FakeBundle(),
    )
    assert result["sessionState"]["sessionId"] == "sess-xyz"
    assert result["sessionState"]["resumed"] is True
```

**Step 2: Run test to verify it fails or passes**

```bash
pytest tests/test_engine.py::test_boot_propagates_session_id_and_resume_and_cwd -v
```

Expected: PASS (engine.py already echoes those). If FAIL, fix the echo path in `engine.py`.

**Step 3: Write the failing test (single_turn passes cwd to make_turn_handler)**

Create `tests/cli/test_single_turn_init_params.py`:

```python
"""Verify single_turn.run threads --cwd / --provider / --session-id / --resume into the engine."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from click.testing import CliRunner


@pytest.mark.asyncio
async def test_run_passes_cwd_to_make_turn_handler() -> None:
    """run --cwd /tmp must reach make_turn_handler as cwd='/tmp'."""
    from amplifier_agent_cli.modes.single_turn import run

    captured: dict[str, object] = {}

    def _fake_make_turn_handler(prepared, *, cwd, is_resumed):  # type: ignore[no-untyped-def]
        captured["cwd"] = cwd
        captured["is_resumed"] = is_resumed

        async def _h(ctx):  # type: ignore[no-untyped-def]
            return "ok"

        return _h

    with (
        patch("amplifier_agent_cli.modes.single_turn.make_turn_handler", side_effect=_fake_make_turn_handler),
        patch("amplifier_agent_cli.modes.single_turn.load_and_prepare_cached", AsyncMock(return_value=object())),
        patch("amplifier_agent_cli.modes.single_turn.inject_provider"),
        patch("amplifier_agent_cli.modes.single_turn.detect_provider", return_value="anthropic"),
        patch("amplifier_agent_cli.modes.single_turn.Engine") as mock_engine_cls,
    ):
        mock_engine = mock_engine_cls.return_value
        mock_engine.boot = AsyncMock(return_value={"sessionState": {"sessionId": "s", "resumed": False}})
        mock_engine.submit_turn = AsyncMock(return_value={"reply": "ok", "turnId": "turn-1"})
        mock_engine.shutdown = AsyncMock(return_value={})

        runner = CliRunner()
        result = runner.invoke(
            run,
            ["hello", "--cwd", "/tmp", "--session-id", "sess-xyz", "--resume"],
            env={"ANTHROPIC_API_KEY": "sk-test"},
        )
        assert result.exit_code == 0, result.output

    assert captured["cwd"] == "/tmp", f"Expected cwd='/tmp', got {captured['cwd']!r}"
    assert captured["is_resumed"] is True, f"Expected is_resumed=True, got {captured['is_resumed']!r}"
```

**Step 4: Run test to verify it fails or passes**

```bash
pytest tests/cli/test_single_turn_init_params.py -v
```

Expected: depends on current behavior. If `single_turn._execute_turn` already calls `make_turn_handler(prepared, cwd=spec.cwd, is_resumed=spec.resume and not spec.fresh)`, this passes — inspection of `single_turn.py` lines 111–115 shows it does. Then add a stronger test:

```python
def test_run_passes_provider_override_to_detect_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    """run --provider must reach detect_provider as override='anthropic'."""
    from amplifier_agent_cli.modes import single_turn

    seen: dict[str, object] = {}

    def _fake_detect(override):  # type: ignore[no-untyped-def]
        seen["override"] = override
        return "anthropic"

    monkeypatch.setattr(single_turn, "detect_provider", _fake_detect)
    monkeypatch.setattr(single_turn, "load_and_prepare_cached", AsyncMock(return_value=object()))
    monkeypatch.setattr(single_turn, "inject_provider", lambda *a, **kw: None)
    monkeypatch.setattr(single_turn, "make_turn_handler", lambda *a, **kw: AsyncMock(return_value="ok"))

    class _FakeEngine:
        def __init__(self, **kw):  # type: ignore[no-untyped-def]
            pass

        boot = AsyncMock(return_value={"sessionState": {"sessionId": "", "resumed": False}})
        submit_turn = AsyncMock(return_value={"reply": "ok", "turnId": "turn-1"})
        shutdown = AsyncMock(return_value={})

    monkeypatch.setattr(single_turn, "Engine", _FakeEngine)

    runner = CliRunner()
    result = runner.invoke(single_turn.run, ["hello", "--provider", "anthropic"], env={"ANTHROPIC_API_KEY": "sk-test"})
    assert result.exit_code == 0, result.output
    assert seen["override"] == "anthropic"
```

**Step 5: If tests already pass, confirm; otherwise wire the missing param**

If `--cwd`, `--session-id`, `--resume`, `--provider` are already threaded in (inspection of `single_turn.py` suggests they are), this task is mostly **add the locking tests**. The remaining work is to add `cwd` and `providerOverride` to the `init_params` dict that the engine receives:

In `single_turn.py` `_execute_turn`, change the `init_params` dict (currently lines 121–127) to:

```python
init_params: dict[str, Any] = {
    "protocolVersion": PROTOCOL_VERSION,
    "clientInfo": {"name": "amplifier-agent-cli", "version": __version__},
    "capabilities": dict(server_default_capabilities()),
    "sessionId": spec.session_id or "",
    "resume": spec.resume,
}
if spec.cwd:
    init_params["cwd"] = spec.cwd
if spec.provider:
    init_params["providerOverride"] = spec.provider
```

The `InitializeParams` TypedDict in `protocol/methods.py` already declares `cwd: NotRequired[str]` and `providerOverride: NotRequired[str]`, so this is compatible.

**Step 6: Run tests + python_check**

```bash
pytest tests/cli/test_single_turn_init_params.py tests/test_engine.py -v
```

```python
python_check(paths=["src/amplifier_agent_cli/modes/single_turn.py", "src/amplifier_agent_lib/engine.py", "tests/cli/test_single_turn_init_params.py", "tests/test_engine.py"])
```

**Step 7: Commit**

```bash
git add src/amplifier_agent_cli/modes/single_turn.py src/amplifier_agent_lib/engine.py tests/cli/test_single_turn_init_params.py tests/test_engine.py
git commit -m "feat(cli): gap (c) — thread cwd/providerOverride into init_params

CLI flags --session-id, --resume, --cwd, --provider already reached
make_turn_handler. This commit ensures cwd and providerOverride also
flow into Engine.boot's init_params (the InitializeParams shape already
declares them as NotRequired). Adds locking tests.

Refs: docs/designs/2026-05-20-aaa-v2-wrapper-and-wire.md Appendix C step 4"
```

---

## Task 7: Admin verb split — `prepare` + `verify` (new); trim `doctor` to diagnostics

**Why:** Per D8, install-time `prepare` primes the cache so the first runtime invocation never pays the manifest-resolution + clone + pip-install cost (F13a). `doctor` reports primed state but does not itself prime. `verify --check-hooks` is the hook-coverage self-test that gates the streaming-hook implementation (Task 11) and Phase 2.0c exit.

**Files:**
- Create: `src/amplifier_agent_cli/admin/prepare.py`
- Create: `src/amplifier_agent_cli/admin/verify.py`
- Modify: `src/amplifier_agent_cli/admin/doctor.py` (trim to diagnostics)
- Modify: `src/amplifier_agent_cli/__main__.py` (wire `prepare` + `verify`)
- Create: `tests/cli/test_admin_prepare.py`
- Create: `tests/cli/test_admin_verify.py`
- Modify: `tests/cli/test_doctor.py`

**Step 1: Write the failing test for `prepare`**

Create `tests/cli/test_admin_prepare.py`:

```python
"""Tests for the `amplifier-agent prepare` admin verb."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from click.testing import CliRunner


def test_prepare_runs_load_and_prepare_cached() -> None:
    """`amplifier-agent prepare` calls load_and_prepare_cached() and exits 0."""
    from amplifier_agent_cli.admin.prepare import prepare

    with patch("amplifier_agent_cli.admin.prepare.load_and_prepare_cached", AsyncMock(return_value=object())) as mock_prep:
        runner = CliRunner()
        result = runner.invoke(prepare, [])
        assert result.exit_code == 0, result.output
        mock_prep.assert_awaited_once()


def test_prepare_exits_nonzero_on_failure() -> None:
    """`prepare` exits nonzero if the cache prepare raises."""
    from amplifier_agent_cli.admin.prepare import prepare

    with patch(
        "amplifier_agent_cli.admin.prepare.load_and_prepare_cached",
        AsyncMock(side_effect=RuntimeError("boom")),
    ):
        runner = CliRunner()
        result = runner.invoke(prepare, [])
        assert result.exit_code != 0
        assert "boom" in result.output or "boom" in (result.stderr_bytes or b"").decode()
```

**Step 2: Write the failing test for `verify`**

Create `tests/cli/test_admin_verify.py`:

```python
"""Tests for the `amplifier-agent verify` admin verb."""

from __future__ import annotations

from click.testing import CliRunner


def test_verify_help_lists_check_hooks_flag() -> None:
    """`verify --help` mentions --check-hooks."""
    from amplifier_agent_cli.admin.verify import verify

    runner = CliRunner()
    result = runner.invoke(verify, ["--help"])
    assert result.exit_code == 0
    assert "--check-hooks" in result.output


def test_verify_check_hooks_minimum_set_passes_when_all_five_present() -> None:
    """verify --check-hooks exits 0 when the streaming hook emits the 5 min-set events.

    Uses a recorded-fixture-style approach: the verify implementation walks
    the loaded bundle's hooks, looks for the streaming hook module, and
    asserts it has registered handlers for the 5 minimum-set events.

    Minimum-set (per design §4.4):
      result/delta, result/final, tool/started, tool/completed, usage
    """
    from amplifier_agent_cli.admin.verify import verify

    runner = CliRunner()
    result = runner.invoke(verify, ["--check-hooks"])
    # The streaming hook lands in Task 11; this test should PASS only after
    # Task 11 + Task 12 land. For Task 7, accept either exit 0 (hook present)
    # or a specific "hook_not_found" message.
    assert result.exit_code in (0, 1), result.output
```

**Step 3: Write the failing test for trimmed `doctor`**

Modify `tests/cli/test_doctor.py` (or add) to assert `doctor` does NOT prime:

```python
def test_doctor_does_not_prime_cache() -> None:
    """`doctor` must NOT call load_and_prepare_cached (priming is `prepare`'s job)."""
    from unittest.mock import patch

    from amplifier_agent_cli.admin.doctor import doctor

    with patch("amplifier_agent_cli.admin.doctor.load_and_prepare_cached") as mock_prep:
        runner = CliRunner()
        runner.invoke(doctor, [], env={"ANTHROPIC_API_KEY": "sk-test"})
        mock_prep.assert_not_called()
```

If `doctor.py` doesn't currently import `load_and_prepare_cached`, this test still serves as a regression lock — patch will fail with AttributeError if the import doesn't exist. Adjust:

```python
def test_doctor_does_not_call_load_and_prepare_cached() -> None:
    """doctor must NOT import load_and_prepare_cached (priming = prepare's job)."""
    import amplifier_agent_cli.admin.doctor as _doctor

    # Inspect: load_and_prepare_cached must not be referenced.
    src = _doctor.__file__
    assert src is not None
    text = open(src).read()
    assert "load_and_prepare_cached" not in text, (
        "doctor.py must not invoke priming (use `amplifier-agent prepare` instead)"
    )
```

**Step 4: Run tests to verify they fail**

```bash
pytest tests/cli/test_admin_prepare.py tests/cli/test_admin_verify.py tests/cli/test_doctor.py -v
```

Expected: FAIL — `prepare` and `verify` modules don't exist.

**Step 5: Implement `src/amplifier_agent_cli/admin/prepare.py`**

```python
"""Admin command: prepare — prime the bundle cache (install-time / manual).

Per design D8: this verb runs the full bundle resolution + module clone +
pip install + cache warm. Idempotent. Designed for invocation from a
turnkey installer's post-install hook (npm postinstall, brew formula,
uv tool install hook). Once prepare succeeds, runtime invocations
(`amplifier-agent run`) always pay zero first-run cost.

`doctor` reports primed state; it does NOT itself prime.
"""

from __future__ import annotations

import asyncio
import sys
import traceback

import click

from amplifier_agent_lib import __version__
from amplifier_agent_lib.bundle.cache import load_and_prepare_cached


@click.command()
def prepare() -> None:
    """Prime the bundle cache for the current amplifier-agent version.

    Resolves the vendored manifest, clones every module source URL, runs
    `pip install`, and writes the pickled PreparedBundle to the XDG cache.
    Idempotent: re-running is safe and short-circuits if the cache is warm.
    """
    try:
        asyncio.run(load_and_prepare_cached(aaa_version=__version__))
    except Exception as exc:  # noqa: BLE001 — surface every prepare failure
        click.echo(f"[error] prepare failed: {exc}", err=True)
        click.echo(traceback.format_exc(), err=True)
        sys.exit(1)
    click.echo("[ OK ] bundle cache primed")
```

**Step 6: Implement `src/amplifier_agent_cli/admin/verify.py`**

```python
"""Admin command: verify — self-test the engine's invariants.

Currently implements:
  --check-hooks   Walk the prepared bundle's mounted hooks. Confirm the
                  streaming hook is mounted and that it registers handlers
                  for the minimum-set 5 canonical wire events.

Minimum-set (per design §4.4, validated by SC-1 kernel investigation):
  result/delta, result/final, tool/started, tool/completed, usage

Exit 0 iff every minimum-set event has a registered handler in the
streaming hook module. Exit 1 with the missing event(s) listed otherwise.
"""

from __future__ import annotations

import asyncio
import sys

import click

from amplifier_agent_lib import __version__
from amplifier_agent_lib.bundle.cache import load_and_prepare_cached

_MINIMUM_SET: tuple[str, ...] = (
    "result/delta",
    "result/final",
    "tool/started",
    "tool/completed",
    "usage",
)


@click.command()
@click.option(
    "--check-hooks",
    is_flag=True,
    default=False,
    help="Self-test that the streaming hook covers the minimum-set 5 events.",
)
def verify(check_hooks: bool) -> None:
    """Run engine self-tests.

    Without flags, verify exits 0 (placeholder for future invariants).
    """
    if check_hooks:
        sys.exit(asyncio.run(_check_hooks()))


async def _check_hooks() -> int:
    """Return 0 if the streaming hook covers the minimum-set events.

    The streaming hook lives in the vendored bundle. After the bundle is
    prepared and mounted, walking ``prepared.mount_plan["hooks"]`` gives
    every hook entry. We look up the streaming hook by module name and
    introspect the wire-event coverage declared by its
    ``CANONICAL_WIRE_EVENTS`` attribute.
    """
    prepared = await load_and_prepare_cached(aaa_version=__version__)
    hooks_block = prepared.mount_plan.get("hooks") or []  # type: ignore[union-attr]

    streaming_entry: dict | None = None
    for entry in hooks_block:
        if not isinstance(entry, dict):
            continue
        module_name = entry.get("module", "")
        if "hook_streaming" in module_name or "streaming" in module_name.lower():
            streaming_entry = entry
            break

    if streaming_entry is None:
        click.echo("[FAIL] streaming hook not mounted in bundle.md", err=True)
        click.echo("       (Task 12 of Phase 2.0c registers it.)", err=True)
        return 1

    # Introspect the wire-event coverage declared by the module.
    try:
        import importlib

        module = importlib.import_module("amplifier_agent_lib.bundle.hook_streaming")
    except ImportError as exc:
        click.echo(f"[FAIL] hook_streaming module not importable: {exc}", err=True)
        return 1

    covered: set[str] = set(getattr(module, "CANONICAL_WIRE_EVENTS", ()))
    missing = [evt for evt in _MINIMUM_SET if evt not in covered]
    if missing:
        click.echo(f"[FAIL] minimum-set events missing: {missing}", err=True)
        return 1

    click.echo(f"[ OK ] streaming hook covers minimum-set: {list(_MINIMUM_SET)}")
    return 0
```

> The streaming hook declares `CANONICAL_WIRE_EVENTS: tuple[str, ...] = (...)` as a module-level constant; Task 11 creates that file with the correct tuple.

**Step 7: Trim `doctor.py`**

Read `src/amplifier_agent_cli/admin/doctor.py`. Remove any logic that calls `load_and_prepare_cached` if it exists. The current `doctor.py` (inspected earlier) already reports cache state via `check_cache_state` without priming — so likely no source change is needed. **Verify** by re-reading the file.

If `check_cache_state` already exists and works, the only change is in `__main__.py` to wire the new verbs.

**Step 8: Wire new verbs in `src/amplifier_agent_cli/__main__.py`**

Add the imports + registrations:

```python
from amplifier_agent_cli.admin.prepare import prepare as _prepare_command
from amplifier_agent_cli.admin.verify import verify as _verify_command

# ... after existing cli.add_command(...) lines:
cli.add_command(_prepare_command)
cli.add_command(_verify_command)
```

**Step 9: Run tests to verify pass**

```bash
pytest tests/cli/test_admin_prepare.py tests/cli/test_admin_verify.py tests/cli/test_doctor.py -v
```

Expected: PASS for all `prepare` tests + the doctor regression test. The `verify --check-hooks` test will pass only after Task 11 + 12 land — accept exit 1 here (the test allows that).

**Step 10: Run python_check**

```python
python_check(paths=["src/amplifier_agent_cli/admin/", "src/amplifier_agent_cli/__main__.py", "tests/cli/test_admin_prepare.py", "tests/cli/test_admin_verify.py", "tests/cli/test_doctor.py"])
```

**Step 11: Commit**

```bash
git add src/amplifier_agent_cli/admin/ src/amplifier_agent_cli/__main__.py tests/cli/test_admin_prepare.py tests/cli/test_admin_verify.py tests/cli/test_doctor.py
git commit -m "feat(cli): admin verb split — add prepare + verify; doctor stays diagnostic

Per design D8 + Appendix C step 8:
  prepare   — primes the bundle cache (install-time / manual). Idempotent.
              Designed for turnkey installer post-install hook.
  verify    — self-tests engine invariants. --check-hooks introspects the
              streaming hook for minimum-set 5-event coverage.
  doctor    — reports primed state but does NOT itself prime.

Refs: docs/designs/2026-05-20-aaa-v2-wrapper-and-wire.md D8, §4.8, Appendix C step 8"
```

---

## Task 8: SC-3 — strict-refuse `PROTOCOL_VERSION` mismatch

**Why:** Per D6, version skew is the worst class of bug — silent wire incompatibility that surfaces as nonsense behavior days later. Engine compares client-supplied `protocolVersion` against `PROTOCOL_VERSION` constant at `Engine.boot()`. Mismatch → typed `AaaError(code='protocol_version_mismatch', ...)` with high-fidelity self-remediating message. Override available via CLI flag `--allow-protocol-skew` and env var `AMPLIFIER_AGENT_ALLOW_PROTOCOL_SKEW=1`.

**Files:**
- Modify: `src/amplifier_agent_lib/engine.py`
- Modify: `src/amplifier_agent_lib/protocol/errors.py` (add the new error code if not present)
- Modify: `src/amplifier_agent_cli/modes/single_turn.py` (add `--allow-protocol-skew` flag)
- Create: `tests/test_engine_version_skew.py`

**Step 1: Write the failing test**

Create `tests/test_engine_version_skew.py`:

```python
"""Tests for SC-3: strict-refuse protocol version skew at Engine.boot()."""

from __future__ import annotations

import pytest

from amplifier_agent_lib.engine import Engine
from amplifier_agent_lib.protocol.errors import AaaError


class _Display:
    async def emit(self, event):  # type: ignore[no-untyped-def]
        pass


class _Approval:
    async def request(self, req):  # type: ignore[no-untyped-def]
        return {"action": "accept"}


async def _h(ctx):  # type: ignore[no-untyped-def]
    return "ok"


@pytest.mark.asyncio
async def test_boot_refuses_protocol_version_mismatch() -> None:
    """Engine.boot raises AaaError(code='protocol_version_mismatch') on skew."""
    engine = Engine(turn_handler=_h, protocol_points={"approval": _Approval(), "display": _Display()})
    with pytest.raises(AaaError) as excinfo:
        await engine.boot(
            {
                "protocolVersion": "1999-01-jurassic",
                "capabilities": {},
                "sessionId": "",
                "resume": False,
            },
            bundle_override=object(),
        )
    assert excinfo.value.code == "protocol_version_mismatch"
    msg = excinfo.value.message.lower()
    assert "client" in msg
    assert "engine" in msg
    assert "--allow-protocol-skew" in excinfo.value.message


@pytest.mark.asyncio
async def test_boot_allows_skew_when_override_set() -> None:
    """allowProtocolSkew=True bypasses the strict-refuse."""
    engine = Engine(turn_handler=_h, protocol_points={"approval": _Approval(), "display": _Display()})
    result = await engine.boot(
        {
            "protocolVersion": "1999-01-jurassic",
            "capabilities": {},
            "sessionId": "",
            "resume": False,
            "allowProtocolSkew": True,
        },
        bundle_override=object(),
    )
    assert result is not None
```

**Step 2: Run test to verify it fails**

```bash
pytest tests/test_engine_version_skew.py -v
```

Expected: FAIL — `AaaError` not raised, current `Engine.boot` does not check `protocolVersion`.

**Step 3: Add `protocol_version_mismatch` to `protocol/errors.py`**

Read `src/amplifier_agent_lib/protocol/errors.py`. If `AaaError` already exists with a `code` field, this is just a documented code string — no source change. If `AaaError` has a fixed Literal-typed `code`, add `'protocol_version_mismatch'` to the union.

**Step 4: Implement strict-refuse in `Engine.boot()`**

In `src/amplifier_agent_lib/engine.py`, at the start of `boot()` (after the not-shutdown guard, before bundle loading), add:

```python
# SC-3: strict-refuse protocol version skew (D6).
client_version = params.get("protocolVersion", "")
allow_skew = bool(params.get("allowProtocolSkew", False)) or bool(
    __import__("os").environ.get("AMPLIFIER_AGENT_ALLOW_PROTOCOL_SKEW")
)
if client_version and client_version != PROTOCOL_VERSION and not allow_skew:
    from amplifier_agent_lib.protocol.errors import AaaError

    raise AaaError(
        code="protocol_version_mismatch",
        message=(
            f"Protocol version mismatch: client requested {client_version!r}, "
            f"engine speaks {PROTOCOL_VERSION!r}. Remediation: reinstall both "
            f"wrapper and engine to compatible versions, or pass "
            f"--allow-protocol-skew (engine CLI flag) / "
            f"AMPLIFIER_AGENT_ALLOW_PROTOCOL_SKEW=1 (env var) to override."
        ),
    )
```

Add `from amplifier_agent_lib.protocol import PROTOCOL_VERSION` near the top of `engine.py` if not present.

**Step 5: Add `--allow-protocol-skew` to single_turn.py**

In the `run()` Click command, add:

```python
@click.option(
    "--allow-protocol-skew",
    "allow_protocol_skew",
    is_flag=True,
    default=False,
    help="Bypass protocol-version-mismatch strict refusal (D6 override).",
)
```

Pass through to `init_params`:

```python
if allow_protocol_skew or os.environ.get("AMPLIFIER_AGENT_ALLOW_PROTOCOL_SKEW"):
    init_params["allowProtocolSkew"] = True
```

Add `import os` if not already imported. Add `allow_protocol_skew: bool` to the function signature.

**Step 6: Run tests + python_check**

```bash
pytest tests/test_engine_version_skew.py tests/ -q
```

```python
python_check(paths=["src/amplifier_agent_lib/engine.py", "src/amplifier_agent_lib/protocol/errors.py", "src/amplifier_agent_cli/modes/single_turn.py", "tests/test_engine_version_skew.py"])
```

**Step 7: Commit**

```bash
git add src/amplifier_agent_lib/engine.py src/amplifier_agent_lib/protocol/errors.py src/amplifier_agent_cli/modes/single_turn.py tests/test_engine_version_skew.py
git commit -m "feat(engine): SC-3 — strict-refuse protocol version skew (D6)

Engine.boot now compares client-supplied protocolVersion against
PROTOCOL_VERSION. Mismatch → AaaError(code='protocol_version_mismatch')
with self-remediating message that includes both versions and the
override mechanism. Override via:
  - CLI:   --allow-protocol-skew
  - env:   AMPLIFIER_AGENT_ALLOW_PROTOCOL_SKEW=1
  - param: allowProtocolSkew=True in init_params

Refs: docs/designs/2026-05-20-aaa-v2-wrapper-and-wire.md D6, Appendix C step 7"
```

---

## Task 9: SC-6 — verify `sessionId` is in the final-reply envelope

**Why:** Per design SC-6, every wire-emitted notification + the final-reply scalar envelope must carry `sessionId`. SC-1 found that the foundation kernel auto-injects `session_id` via `coordinator.hooks.set_default_fields(session_id=...)`, which lands in Task 10. This task locks the **scalar envelope** at the Engine layer — `TurnSubmitResult` must include `sessionId`.

**Files:**
- Modify: `src/amplifier_agent_lib/protocol/methods.py` (`TurnSubmitResult` adds `sessionId`)
- Modify: `src/amplifier_agent_lib/engine.py` (`submit_turn` populates `sessionId`)
- Modify: `tests/test_engine.py`

**Step 1: Write the failing test**

Add to `tests/test_engine.py`:

```python
@pytest.mark.asyncio
async def test_submit_turn_result_includes_session_id() -> None:
    """TurnSubmitResult must carry sessionId (SC-6)."""

    async def _h(ctx):  # type: ignore[no-untyped-def]
        return "the answer"

    class _Display:
        async def emit(self, event):  # type: ignore[no-untyped-def]
            pass

    class _Approval:
        async def request(self, req):  # type: ignore[no-untyped-def]
            return {"action": "accept"}

    engine = Engine(turn_handler=_h, protocol_points={"approval": _Approval(), "display": _Display()})
    await engine.boot(
        {"protocolVersion": PROTOCOL_VERSION, "capabilities": {}, "sessionId": "sess-9", "resume": False},
        bundle_override=object(),
    )
    result = await engine.submit_turn({"sessionId": "sess-9", "turnId": "turn-1", "prompt": "?"})
    assert result["sessionId"] == "sess-9"
    assert result["reply"] == "the answer"
    assert result["turnId"] == "turn-1"
```

Import `PROTOCOL_VERSION` and `Engine` at the top of the test file as needed.

**Step 2: Run test to verify it fails**

```bash
pytest tests/test_engine.py::test_submit_turn_result_includes_session_id -v
```

Expected: FAIL with `KeyError: 'sessionId'`.

**Step 3: Add `sessionId` to `TurnSubmitResult`**

In `src/amplifier_agent_lib/protocol/methods.py`:

```python
class TurnSubmitResult(TypedDict):
    """Result returned by the ``turn/submit`` JSON-RPC method."""

    reply: str | None
    turnId: str
    sessionId: str  # SC-6: every envelope carries sessionId
    finalEvent: NotRequired[dict[str, Any]]
```

**Step 4: Update `Engine.submit_turn` to populate `sessionId`**

In `src/amplifier_agent_lib/engine.py`:

```python
return TurnSubmitResult(
    reply=reply,
    turnId=params["turnId"],
    sessionId=params["sessionId"],
)
```

**Step 5: Run tests + python_check**

```bash
pytest tests/test_engine.py -v
```

```python
python_check(paths=["src/amplifier_agent_lib/protocol/methods.py", "src/amplifier_agent_lib/engine.py", "tests/test_engine.py"])
```

**Step 6: Commit**

```bash
git add src/amplifier_agent_lib/protocol/methods.py src/amplifier_agent_lib/engine.py tests/test_engine.py
git commit -m "feat(engine): SC-6 — sessionId in turn/submit result envelope

TurnSubmitResult now carries sessionId. Per design SC-6, every wire-side
envelope must include sessionId so consumers can correlate across turns
without out-of-band threading. Foundation-kernel notifications get
sessionId via coordinator.hooks.set_default_fields() in Task 10.

Refs: docs/designs/2026-05-20-aaa-v2-wrapper-and-wire.md SC-6, Appendix C step 6"
```

---

## Task 10: Gap (d) Part 1 — rewrite `_runtime.py` bridge

**Why:** This is the heart of gap (d). Currently `make_turn_handler` creates a session and calls `session.execute(ctx.prompt)` but **does not pass `ctx.display` or `ctx.approval` into the session**. So when the orchestrator inside the bundle fires hook events, there is nowhere for them to go. This task wires `ctx.display.emit` and `ctx.approval.request` into the foundation coordinator as capabilities, and sets the session's default event fields (per SC-1 finding) so every kernel event carries `session_id` automatically.

**Files:**
- Modify: `src/amplifier_agent_lib/_runtime.py`
- Modify: `tests/test_runtime.py`

**Step 1: Read the current `_runtime.py` (already done in plan-writing; re-read at task start)**

```bash
cat src/amplifier_agent_lib/_runtime.py
```

The handler currently does:
1. Hydrate agent configs.
2. Inside handler: `session = await prepared.create_session(...)`.
3. Register `session.spawn` capability.
4. `await session.execute(ctx.prompt)`.

**Step 2: Write the failing test (display + approval bridged into session)**

Update `tests/test_runtime.py`:

```python
"""Tests for _runtime.make_turn_handler — bridges ctx.display / ctx.approval into the session."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


@pytest.mark.asyncio
async def test_make_turn_handler_registers_display_emit_as_capability() -> None:
    """The handler must register ctx.display.emit on the session coordinator.

    Per design §4.7 (d): the foundation kernel hooks fire on the coordinator;
    the streaming hook (Task 11) translates those events and calls
    ctx.display.emit() to send them to the wire. _runtime.py is the layer that
    makes ctx.display.emit reachable from inside the running session.
    """
    from amplifier_agent_lib._runtime import make_turn_handler
    from amplifier_agent_lib.engine import TurnContext

    captured_caps: dict[str, object] = {}

    class _FakeCoordinator:
        def __init__(self):
            self.hooks = MagicMock()

        def register_capability(self, name, fn):
            captured_caps[name] = fn

    class _FakeSession:
        def __init__(self):
            self.coordinator = _FakeCoordinator()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def execute(self, prompt):
            return "ok"

    class _FakePrepared:
        mount_plan = {"agents": {}}

        async def create_session(self, **kw):
            return _FakeSession()

    class _Display:
        async def emit(self, event):
            pass

    class _Approval:
        async def request(self, req):
            return {"action": "accept"}

    handler = make_turn_handler(_FakePrepared(), cwd=None, is_resumed=False)
    ctx = TurnContext(
        session_id="sess-9",
        turn_id="turn-1",
        prompt="?",
        approval=_Approval(),
        display=_Display(),
    )
    reply = await handler(ctx)

    assert reply == "ok"
    assert "display.emit" in captured_caps, f"expected display.emit registered; got {list(captured_caps)}"
    assert "approval.request" in captured_caps, f"expected approval.request registered; got {list(captured_caps)}"


@pytest.mark.asyncio
async def test_make_turn_handler_sets_default_fields_session_id() -> None:
    """The handler must set coordinator.hooks.set_default_fields(session_id=...)."""
    from amplifier_agent_lib._runtime import make_turn_handler
    from amplifier_agent_lib.engine import TurnContext

    set_default_args: dict[str, object] = {}

    class _FakeHooks:
        def set_default_fields(self, **kw):
            set_default_args.update(kw)

        def register(self, *a, **kw):
            pass

    class _FakeCoordinator:
        def __init__(self):
            self.hooks = _FakeHooks()

        def register_capability(self, name, fn):
            pass

    class _FakeSession:
        def __init__(self):
            self.coordinator = _FakeCoordinator()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def execute(self, prompt):
            return "ok"

    class _FakePrepared:
        mount_plan = {"agents": {}}

        async def create_session(self, **kw):
            return _FakeSession()

    class _Display:
        async def emit(self, event):
            pass

    class _Approval:
        async def request(self, req):
            return {"action": "accept"}

    handler = make_turn_handler(_FakePrepared(), cwd=None, is_resumed=False)
    ctx = TurnContext(
        session_id="sess-9",
        turn_id="turn-1",
        prompt="?",
        approval=_Approval(),
        display=_Display(),
    )
    await handler(ctx)
    assert set_default_args.get("session_id") == "sess-9"
```

**Step 3: Run tests to verify they fail**

```bash
pytest tests/test_runtime.py -v
```

Expected: FAIL — `display.emit` / `approval.request` not registered; `set_default_fields` not called.

**Step 4: Implement the bridge in `_runtime.py`**

Replace the handler body (after `session = await prepared.create_session(...)`) with:

```python
        # SC-6 / SC-1: every emitted kernel event auto-includes session_id +
        # turn_id, so the streaming hook in the vendored bundle does not have
        # to thread these through manually.
        session.coordinator.hooks.set_default_fields(
            session_id=ctx.session_id,
            turn_id=ctx.turn_id,
        )

        # Gap (d): expose ctx.display.emit and ctx.approval.request on the
        # coordinator as capabilities. The streaming hook (bundle/hook_streaming.py)
        # invokes the display capability from inside async kernel-hook callbacks;
        # the approval bridge invokes ctx.approval.request when the kernel asks
        # for human-in-the-loop confirmation before a tool runs.
        session.coordinator.register_capability("display.emit", ctx.display.emit)
        session.coordinator.register_capability("approval.request", ctx.approval.request)

        # Existing session.spawn registration stays as-is.
        async def _spawn_fn(**kw: Any) -> dict[str, Any]:
            kw.setdefault("agent_configs", agent_configs)
            kw["parent_session"] = session
            return await spawn_sub_session(**kw)

        session.coordinator.register_capability("session.spawn", _spawn_fn)

        async with session:
            return await session.execute(ctx.prompt)
```

**Step 5: Run tests + python_check**

```bash
pytest tests/test_runtime.py -v
```

```python
python_check(paths=["src/amplifier_agent_lib/_runtime.py", "tests/test_runtime.py"])
```

Expected: PASS.

**Step 6: Commit**

```bash
git add src/amplifier_agent_lib/_runtime.py tests/test_runtime.py
git commit -m "feat(engine): gap (d) part 1 — bridge display + approval in _runtime

Per design §4.7 row (d) and SC-1 kernel investigation:
  - register ctx.display.emit as the 'display.emit' coordinator capability
  - register ctx.approval.request as the 'approval.request' capability
  - call coordinator.hooks.set_default_fields(session_id=, turn_id=) so
    every kernel-emitted event auto-includes the identity fields

Without this bridge, production today emits zero display events to the
wire regardless of streaming-hook implementation (CR-1). This is the
plumbing that makes Task 11's streaming hook actually reachable.

Refs: docs/designs/2026-05-20-aaa-v2-wrapper-and-wire.md Appendix C step 5"
```

---

## Task 11: Gap (d) Part 2 — new `bundle/hook_streaming.py` streaming hook

**Why:** This is the biggest task in the plan. The streaming hook subscribes to foundation kernel hook events, translates them into typed `DisplayEvent` shapes, and emits each via `ctx.display.emit()` (reached through the `display.emit` capability registered by Task 10). Without this module, the `_runtime.py` bridge is wired to nothing.

Per SC-1 investigation findings:
- Foundation kernel emits `tool:pre` and `tool:post` (not `tool/started` / `tool/completed`) — our hook translates names.
- `content_block:delta` may not fire in `loop-streaming` — we emit a single `result/delta` fallback from `content_block:end` when delta didn't fire during the block.
- Production data field names may be `tool_name` instead of `tool` — defensive `data.get("tool") or data.get("tool_name")`.
- Hook handler signature: `async def handler(event: str, data: dict) -> HookResult` returning `HookResult(action="continue")`.

**This task contains FIVE TDD sub-cycles** (one per minimum-set event group). Commit at the end of each sub-cycle so a regression in one cycle never gates the next.

**Files:**
- Create: `src/amplifier_agent_lib/bundle/hook_streaming.py`
- Create: `tests/test_bundle_hook_streaming.py`

### Task 11 sub-cycle structure

Each sub-cycle: write test → run/fail → implement minimum code → run/pass → commit.

### Step 1: Scaffold the hook module (no events yet)

**Create `src/amplifier_agent_lib/bundle/hook_streaming.py`:**

```python
"""Streaming hook — translates foundation kernel events to wire DisplayEvents.

Per design §4.5 + §4.7 row (d). Subscribes to foundation kernel hook events
(``tool:pre``, ``tool:post``, ``content_block:start``, ``content_block:delta``,
``content_block:end``, ``llm:response``, ``tool:error``) and translates each
to one of the 9 canonical wire ``DisplayEvent`` types (see protocol/notifications.py).

Reaches the wire via the ``display.emit`` coordinator capability registered by
``_runtime.make_turn_handler``. Each translated event is dispatched with
``await coordinator.call_capability("display.emit", event)``.

SC-1 findings folded in:
  - Foundation emits ``tool:pre`` (NOT ``tool/started``); we map names.
  - ``content_block:delta`` may not fire; we emit a fallback ``result/delta``
    from ``content_block:end`` if no delta arrived during the block.
  - Field name may be ``tool_name`` (production Rust kernel) instead of ``tool``
    (Python loop-streaming); we use ``data.get("tool") or data.get("tool_name")``.
  - ``set_default_fields(session_id=, turn_id=)`` was already called by
    ``_runtime.make_turn_handler``, so ``data`` already includes both fields;
    we do not re-thread them.

This module is mounted as a bundle hook (registered in ``bundle.md``). The
``mount()`` entry point is the foundation module-loader contract.
"""

from __future__ import annotations

from typing import Any

# The 5 minimum-set wire events this hook is responsible for emitting.
# Verified by `amplifier-agent verify --check-hooks` (Task 7).
CANONICAL_WIRE_EVENTS: tuple[str, ...] = (
    "result/delta",
    "result/final",
    "tool/started",
    "tool/completed",
    "usage",
)


class StreamingEmitter:
    """Stateful kernel-event → wire-event translator.

    Per-block state tracks whether a ``content_block:delta`` arrived during
    a given content block. If not, ``content_block:end`` emits a single
    fallback ``result/delta`` from the block's final text.
    """

    def __init__(self, coordinator: Any) -> None:
        self._coordinator = coordinator
        # Maps block_id -> True if any delta fired during this block.
        self._delta_seen: dict[str, bool] = {}
        # Maps block_id -> the final text accumulated (for fallback emission).
        self._block_text: dict[str, str] = {}

    async def _emit(self, event: dict[str, Any]) -> None:
        """Send a wire DisplayEvent through the registered display.emit capability."""
        await self._coordinator.call_capability("display.emit", event)


async def mount(coordinator: Any, config: dict[str, Any] | None = None) -> None:
    """Foundation module-loader entry point.

    Instantiates a ``StreamingEmitter`` bound to the coordinator and registers
    its handlers for the 7 kernel events that produce the 5 minimum-set wire
    events. Returns nothing; the emitter is held in closure scope by the
    registered handlers.
    """
    _ = config  # config not used yet; reserved for future verbosity flags
    emitter = StreamingEmitter(coordinator)
    coordinator.hooks.register("tool:pre", emitter.on_tool_pre)
    coordinator.hooks.register("tool:post", emitter.on_tool_post)
    coordinator.hooks.register("tool:error", emitter.on_tool_error)
    coordinator.hooks.register("content_block:start", emitter.on_content_block_start)
    coordinator.hooks.register("content_block:delta", emitter.on_content_block_delta)
    coordinator.hooks.register("content_block:end", emitter.on_content_block_end)
    coordinator.hooks.register("llm:response", emitter.on_llm_response)
```

### Sub-cycle 11A — `tool/started` from `tool:pre`

**Step 11A.1: Write the failing test**

Create `tests/test_bundle_hook_streaming.py`:

```python
"""Tests for the streaming hook — kernel events → wire DisplayEvents."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest


class _FakeHooks:
    def __init__(self):
        self.registered: dict[str, Any] = {}

    def register(self, event_name, handler):
        self.registered[event_name] = handler


class _FakeCoordinator:
    def __init__(self):
        self.hooks = _FakeHooks()
        self.call_capability = AsyncMock()


@pytest.mark.asyncio
async def test_tool_pre_emits_tool_started() -> None:
    """`tool:pre` translates to wire event `tool/started`."""
    from amplifier_agent_lib.bundle.hook_streaming import mount

    coordinator = _FakeCoordinator()
    await mount(coordinator, {})
    on_tool_pre = coordinator.hooks.registered["tool:pre"]
    await on_tool_pre(
        "tool:pre",
        {
            "session_id": "sess-1",
            "turn_id": "turn-1",
            "tool": "bash",
            "arguments": {"cmd": "ls"},
            "tool_call_id": "tc-1",
        },
    )
    coordinator.call_capability.assert_awaited()
    args, kw = coordinator.call_capability.await_args
    assert args[0] == "display.emit"
    emitted = args[1]
    assert emitted["type"] == "tool/started"
    assert emitted["sessionId"] == "sess-1"
    assert emitted["turnId"] == "turn-1"
    assert emitted["name"] == "bash"
    assert emitted["toolCallId"] == "tc-1"
    assert emitted["args"] == {"cmd": "ls"}


@pytest.mark.asyncio
async def test_tool_pre_defensive_tool_name_field() -> None:
    """Hook accepts `tool_name` as alternate field name (production Rust kernel)."""
    from amplifier_agent_lib.bundle.hook_streaming import mount

    coordinator = _FakeCoordinator()
    await mount(coordinator, {})
    on_tool_pre = coordinator.hooks.registered["tool:pre"]
    await on_tool_pre(
        "tool:pre",
        {
            "session_id": "sess-1",
            "turn_id": "turn-1",
            "tool_name": "filesystem",  # NOTE: tool_name, not tool
            "tool_input": {"path": "/x"},
            "tool_call_id": "tc-2",
        },
    )
    args, _ = coordinator.call_capability.await_args
    emitted = args[1]
    assert emitted["name"] == "filesystem"
    assert emitted["args"] == {"path": "/x"}
```

**Step 11A.2: Run test to verify it fails**

```bash
pytest tests/test_bundle_hook_streaming.py::test_tool_pre_emits_tool_started -v
```

Expected: FAIL — handler raises AttributeError (`StreamingEmitter` has no `on_tool_pre`).

**Step 11A.3: Implement `on_tool_pre`**

Add to `StreamingEmitter` in `src/amplifier_agent_lib/bundle/hook_streaming.py`:

```python
    async def on_tool_pre(self, event: str, data: dict[str, Any]) -> Any:
        """Translate kernel `tool:pre` to wire `tool/started`."""
        tool_name = data.get("tool") or data.get("tool_name") or ""
        tool_args = data.get("arguments") or data.get("tool_input") or {}
        await self._emit(
            {
                "type": "tool/started",
                "sessionId": data.get("session_id", ""),
                "turnId": data.get("turn_id", ""),
                "toolCallId": data.get("tool_call_id", ""),
                "name": tool_name,
                "args": tool_args,
            }
        )
        return {"action": "continue"}
```

**Step 11A.4: Run test to verify it passes**

```bash
pytest tests/test_bundle_hook_streaming.py -v -k tool_pre
```

Expected: PASS.

**Step 11A.5: python_check + commit**

```python
python_check(paths=["src/amplifier_agent_lib/bundle/hook_streaming.py", "tests/test_bundle_hook_streaming.py"])
```

```bash
git add src/amplifier_agent_lib/bundle/hook_streaming.py tests/test_bundle_hook_streaming.py
git commit -m "feat(bundle): streaming hook — tool/started from tool:pre

Sub-cycle 11A. Translates foundation kernel tool:pre → wire tool/started.
Defensive on field name: data.get('tool') or data.get('tool_name')
(Python loop-streaming uses 'tool'; production Rust kernel may use 'tool_name').

Refs: docs/designs/2026-05-20-aaa-v2-wrapper-and-wire.md §4.5, SC-1 finding"
```

### Sub-cycle 11B — `tool/completed` from `tool:post`

**Step 11B.1: Write the failing test**

Add to `tests/test_bundle_hook_streaming.py`:

```python
@pytest.mark.asyncio
async def test_tool_post_emits_tool_completed() -> None:
    """`tool:post` translates to wire event `tool/completed`."""
    from amplifier_agent_lib.bundle.hook_streaming import mount

    coordinator = _FakeCoordinator()
    await mount(coordinator, {})
    on_tool_post = coordinator.hooks.registered["tool:post"]
    await on_tool_post(
        "tool:post",
        {
            "session_id": "sess-1",
            "turn_id": "turn-1",
            "tool": "bash",
            "tool_call_id": "tc-1",
            "result": {"stdout": "file.txt"},
            "duration_ms": 42,
        },
    )
    args, _ = coordinator.call_capability.await_args
    emitted = args[1]
    assert emitted["type"] == "tool/completed"
    assert emitted["sessionId"] == "sess-1"
    assert emitted["turnId"] == "turn-1"
    assert emitted["name"] == "bash"
    assert emitted["toolCallId"] == "tc-1"
    assert emitted["result"] == {"stdout": "file.txt"}
    assert emitted["durationMs"] == 42
```

**Step 11B.2: Run + see fail**

```bash
pytest tests/test_bundle_hook_streaming.py::test_tool_post_emits_tool_completed -v
```

**Step 11B.3: Implement `on_tool_post`**

```python
    async def on_tool_post(self, event: str, data: dict[str, Any]) -> Any:
        """Translate kernel `tool:post` to wire `tool/completed`."""
        tool_name = data.get("tool") or data.get("tool_name") or ""
        await self._emit(
            {
                "type": "tool/completed",
                "sessionId": data.get("session_id", ""),
                "turnId": data.get("turn_id", ""),
                "toolCallId": data.get("tool_call_id", ""),
                "name": tool_name,
                "result": data.get("result"),
                "durationMs": int(data.get("duration_ms", 0)),
            }
        )
        return {"action": "continue"}
```

**Step 11B.4: Pass + python_check + commit**

```bash
pytest tests/test_bundle_hook_streaming.py -v -k tool_post
```

```bash
git add src/amplifier_agent_lib/bundle/hook_streaming.py tests/test_bundle_hook_streaming.py
git commit -m "feat(bundle): streaming hook — tool/completed from tool:post

Sub-cycle 11B."
```

### Sub-cycle 11C — `result/delta` from `content_block:delta` (and fallback path)

**Step 11C.1: Write the failing test**

```python
@pytest.mark.asyncio
async def test_content_block_delta_emits_result_delta() -> None:
    """`content_block:delta` translates to wire `result/delta`."""
    from amplifier_agent_lib.bundle.hook_streaming import mount

    coordinator = _FakeCoordinator()
    await mount(coordinator, {})
    on_start = coordinator.hooks.registered["content_block:start"]
    on_delta = coordinator.hooks.registered["content_block:delta"]
    await on_start("content_block:start", {"session_id": "s", "turn_id": "t", "block_id": "b1"})
    await on_delta("content_block:delta", {"session_id": "s", "turn_id": "t", "block_id": "b1", "text": "Hello"})

    # call_capability.await_args_list contains every call;
    # find the result/delta entry.
    deltas = [
        call.args[1] for call in coordinator.call_capability.await_args_list
        if call.args[0] == "display.emit" and call.args[1].get("type") == "result/delta"
    ]
    assert len(deltas) == 1
    assert deltas[0]["text"] == "Hello"
    assert deltas[0]["sessionId"] == "s"
    assert deltas[0]["turnId"] == "t"


@pytest.mark.asyncio
async def test_content_block_end_fallback_when_no_delta_fired() -> None:
    """`content_block:end` emits a single fallback `result/delta` if no delta arrived."""
    from amplifier_agent_lib.bundle.hook_streaming import mount

    coordinator = _FakeCoordinator()
    await mount(coordinator, {})
    on_start = coordinator.hooks.registered["content_block:start"]
    on_end = coordinator.hooks.registered["content_block:end"]
    await on_start("content_block:start", {"session_id": "s", "turn_id": "t", "block_id": "b1"})
    # No delta call.
    await on_end("content_block:end", {"session_id": "s", "turn_id": "t", "block_id": "b1", "text": "Full text"})

    deltas = [
        call.args[1] for call in coordinator.call_capability.await_args_list
        if call.args[0] == "display.emit" and call.args[1].get("type") == "result/delta"
    ]
    assert len(deltas) == 1, f"expected exactly one fallback result/delta, got {len(deltas)}"
    assert deltas[0]["text"] == "Full text"


@pytest.mark.asyncio
async def test_content_block_end_skips_fallback_when_delta_fired() -> None:
    """If a delta fired during the block, content_block:end emits no fallback."""
    from amplifier_agent_lib.bundle.hook_streaming import mount

    coordinator = _FakeCoordinator()
    await mount(coordinator, {})
    on_start = coordinator.hooks.registered["content_block:start"]
    on_delta = coordinator.hooks.registered["content_block:delta"]
    on_end = coordinator.hooks.registered["content_block:end"]
    await on_start("content_block:start", {"session_id": "s", "turn_id": "t", "block_id": "b1"})
    await on_delta("content_block:delta", {"session_id": "s", "turn_id": "t", "block_id": "b1", "text": "chunk-1"})
    await on_end("content_block:end", {"session_id": "s", "turn_id": "t", "block_id": "b1", "text": "chunk-1 full"})

    deltas = [
        call.args[1] for call in coordinator.call_capability.await_args_list
        if call.args[0] == "display.emit" and call.args[1].get("type") == "result/delta"
    ]
    assert len(deltas) == 1  # only the real delta; no fallback
    assert deltas[0]["text"] == "chunk-1"
```

**Step 11C.2: Run + see fail**

```bash
pytest tests/test_bundle_hook_streaming.py -v -k content_block
```

**Step 11C.3: Implement the three handlers**

```python
    async def on_content_block_start(self, event: str, data: dict[str, Any]) -> Any:
        """Initialize per-block delta-seen + text state."""
        block_id = data.get("block_id", "")
        self._delta_seen[block_id] = False
        self._block_text[block_id] = ""
        return {"action": "continue"}

    async def on_content_block_delta(self, event: str, data: dict[str, Any]) -> Any:
        """Translate kernel `content_block:delta` to wire `result/delta`.

        Marks the block as having seen a delta, so on_content_block_end
        skips its fallback emission.
        """
        block_id = data.get("block_id", "")
        self._delta_seen[block_id] = True
        text = data.get("text", "")
        await self._emit(
            {
                "type": "result/delta",
                "sessionId": data.get("session_id", ""),
                "turnId": data.get("turn_id", ""),
                "text": text,
            }
        )
        return {"action": "continue"}

    async def on_content_block_end(self, event: str, data: dict[str, Any]) -> Any:
        """Fallback emission: if no delta fired, emit one result/delta from the block text."""
        block_id = data.get("block_id", "")
        if not self._delta_seen.get(block_id, False):
            text = data.get("text", "")
            if text:
                await self._emit(
                    {
                        "type": "result/delta",
                        "sessionId": data.get("session_id", ""),
                        "turnId": data.get("turn_id", ""),
                        "text": text,
                    }
                )
        # Cleanup per-block state.
        self._delta_seen.pop(block_id, None)
        self._block_text.pop(block_id, None)
        return {"action": "continue"}
```

**Step 11C.4: Pass + commit**

```bash
pytest tests/test_bundle_hook_streaming.py -v -k content_block
```

```bash
git add src/amplifier_agent_lib/bundle/hook_streaming.py tests/test_bundle_hook_streaming.py
git commit -m "feat(bundle): streaming hook — result/delta + content_block fallback

Sub-cycle 11C. Per SC-1 finding, loop-streaming may not emit
content_block:delta. The hook tracks per-block delta-seen state and
emits a single fallback result/delta from content_block:end when the
real delta hook didn't fire during the block.

Refs: SC-1 finding #3"
```

### Sub-cycle 11D — `usage` and `result/final` from `llm:response`

**Step 11D.1: Write the failing test**

```python
@pytest.mark.asyncio
async def test_llm_response_emits_usage_and_result_final() -> None:
    """`llm:response` emits both usage and result/final events."""
    from amplifier_agent_lib.bundle.hook_streaming import mount

    coordinator = _FakeCoordinator()
    await mount(coordinator, {})
    on_resp = coordinator.hooks.registered["llm:response"]
    await on_resp(
        "llm:response",
        {
            "session_id": "s",
            "turn_id": "t",
            "text": "the full reply",
            "input_tokens": 100,
            "output_tokens": 50,
        },
    )
    emitted_types = [
        call.args[1].get("type")
        for call in coordinator.call_capability.await_args_list
        if call.args[0] == "display.emit"
    ]
    assert "usage" in emitted_types
    assert "result/final" in emitted_types

    final = next(
        call.args[1]
        for call in coordinator.call_capability.await_args_list
        if call.args[1].get("type") == "result/final"
    )
    assert final["text"] == "the full reply"

    usage = next(
        call.args[1]
        for call in coordinator.call_capability.await_args_list
        if call.args[1].get("type") == "usage"
    )
    assert usage["inputTokens"] == 100
    assert usage["outputTokens"] == 50
```

**Step 11D.2: Run + fail**

```bash
pytest tests/test_bundle_hook_streaming.py -v -k llm_response
```

**Step 11D.3: Implement `on_llm_response`**

```python
    async def on_llm_response(self, event: str, data: dict[str, Any]) -> Any:
        """Translate kernel `llm:response` to wire `usage` + `result/final`.

        result/final carries the final assistant text. Per design §4.4 + SC-1
        finding, result/final is NOT a kernel event — it's synthesized by the
        engine layer. This hook emits it as a wire envelope from llm:response
        so wrappers always see a turn-closing event.
        """
        sid = data.get("session_id", "")
        tid = data.get("turn_id", "")
        in_tok = int(data.get("input_tokens", 0))
        out_tok = int(data.get("output_tokens", 0))
        text = data.get("text", "")

        if in_tok or out_tok:
            await self._emit(
                {
                    "type": "usage",
                    "sessionId": sid,
                    "turnId": tid,
                    "inputTokens": in_tok,
                    "outputTokens": out_tok,
                }
            )
        if text:
            await self._emit(
                {
                    "type": "result/final",
                    "sessionId": sid,
                    "turnId": tid,
                    "text": text,
                }
            )
        return {"action": "continue"}
```

**Step 11D.4: Pass + commit**

```bash
pytest tests/test_bundle_hook_streaming.py -v -k llm_response
```

```bash
git add src/amplifier_agent_lib/bundle/hook_streaming.py tests/test_bundle_hook_streaming.py
git commit -m "feat(bundle): streaming hook — usage + result/final from llm:response

Sub-cycle 11D. Per design §4.4: result/final is the turn-closing wire
event; it's not a kernel event, so this hook synthesizes it from the
llm:response data. Usage carries token counts."
```

### Sub-cycle 11E — `error` from `tool:error`

**Step 11E.1: Write the failing test**

```python
@pytest.mark.asyncio
async def test_tool_error_emits_error_event() -> None:
    """`tool:error` translates to wire `error` (recoverable=True)."""
    from amplifier_agent_lib.bundle.hook_streaming import mount

    coordinator = _FakeCoordinator()
    await mount(coordinator, {})
    on_err = coordinator.hooks.registered["tool:error"]
    await on_err(
        "tool:error",
        {
            "session_id": "s",
            "turn_id": "t",
            "tool": "bash",
            "error_code": "tool_failed",
            "error_message": "exit code 1",
        },
    )
    args, _ = coordinator.call_capability.await_args
    emitted = args[1]
    assert emitted["type"] == "error"
    assert emitted["code"] == "tool_failed"
    assert emitted["message"] == "exit code 1"
    assert emitted["recoverable"] is True
```

**Step 11E.2: Run + fail; implement; pass; commit**

Add to `StreamingEmitter`:

```python
    async def on_tool_error(self, event: str, data: dict[str, Any]) -> Any:
        """Translate kernel `tool:error` to wire `error`."""
        await self._emit(
            {
                "type": "error",
                "sessionId": data.get("session_id", ""),
                "turnId": data.get("turn_id", ""),
                "code": data.get("error_code", "tool_failed"),
                "message": data.get("error_message", ""),
                "recoverable": True,
            }
        )
        return {"action": "continue"}
```

Run, pass, commit:

```bash
pytest tests/test_bundle_hook_streaming.py -v
python_check ...
git commit -m "feat(bundle): streaming hook — error event from tool:error

Sub-cycle 11E. Recoverable=True per design §4.4 row 8.

Refs: docs/designs/2026-05-20-aaa-v2-wrapper-and-wire.md §4.5 (complete)"
```

After all five sub-cycles, run the full suite once:

```bash
pytest tests/ -q
```

Expected: ALL PASS.

---

## Task 12: Gap (d) Part 3 — register streaming hook in `bundle.md`

**Why:** A module is dead code until the manifest mounts it. This task adds the `hook_streaming` entry to the `hooks:` section of `bundle/bundle.md`. Per design §4.5, the upstream `hooks-streaming-ui` writes to stdout (incompatible with our framing); ours writes through the `display.emit` capability registered by Task 10.

The bundle manifest references **external** module URLs for all upstream hooks. Our hook lives **inside the vendored bundle** (`src/amplifier_agent_lib/bundle/hook_streaming.py`), so it needs a `local:` source convention or the bundle loader needs to support inline modules. Inspect `bundle.md` + `src/amplifier_agent_lib/bundle/loader.py` to confirm the convention used by the existing vendored sub-agents (the `agents:` block).

**Files:**
- Modify: `src/amplifier_agent_lib/bundle/bundle.md`
- Possibly modify: `src/amplifier_agent_lib/bundle/loader.py` (if it doesn't already support local hook modules)
- Modify: `tests/test_bundle_loader.py`

**Step 1: Read the existing bundle loader to learn the convention**

```bash
cat src/amplifier_agent_lib/bundle/loader.py | head -120
```

Find how `agents:` (which are vendored at `src/amplifier_agent_lib/bundle/agents/*.md`) are wired. The hook needs to follow the same pattern OR use a `module: amplifier_agent_lib.bundle.hook_streaming` reference that the loader resolves as a Python import.

**Step 2: Write the failing test (bundle prepared mount_plan includes the streaming hook)**

Add to `tests/test_bundle_loader.py` (or create `tests/test_bundle_hook_registration.py`):

```python
@pytest.mark.asyncio
async def test_prepared_bundle_mounts_hook_streaming() -> None:
    """The prepared bundle's mount_plan['hooks'] must include the streaming hook."""
    from amplifier_agent_lib import __version__
    from amplifier_agent_lib.bundle.cache import load_and_prepare_cached

    prepared = await load_and_prepare_cached(aaa_version=__version__)
    hooks_block = prepared.mount_plan.get("hooks") or []
    module_names = [entry.get("module", "") for entry in hooks_block if isinstance(entry, dict)]
    assert any("hook_streaming" in name or "streaming" in name.lower() for name in module_names), (
        f"streaming hook must be mounted; got hooks={module_names}"
    )
```

**Step 3: Run test to verify it fails**

```bash
pytest tests/test_bundle_loader.py::test_prepared_bundle_mounts_hook_streaming -v
```

Expected: FAIL.

**Step 4: Edit `bundle/bundle.md` to register the hook**

In the `hooks:` block (around line 93–124), add a new entry. The exact form depends on how the loader resolves local modules; use the convention discovered in Step 1. Likely:

```yaml
  - module: amplifier_agent_lib.bundle.hook_streaming
    source: local
```

Or if the loader requires a git source for every entry, modify the loader to short-circuit on `source: local` by importing the Python module directly. **Read `loader.py` carefully and choose the minimal-impact path.**

If the bundle hash is content-addressed (line 16 of `bundle.md` says "Editing this file changes the cache key"), the existing warm cache will self-invalidate — that's intentional.

**Step 5: If the loader needs to support `source: local`, add it**

In `src/amplifier_agent_lib/bundle/loader.py`, find the hook-loading loop. Add a branch:

```python
if entry.get("source") == "local":
    # In-process module — import by dotted path; skip clone + pip install.
    import importlib
    module = importlib.import_module(entry["module"])
    # Call mount() if present; the resulting handlers register themselves.
    if hasattr(module, "mount"):
        await module.mount(coordinator, entry.get("config") or {})
    continue
```

**Step 6: Run the test (full prepare cycle) — may be slow on first run**

```bash
pytest tests/test_bundle_loader.py::test_prepared_bundle_mounts_hook_streaming -v
```

Expected: PASS after the bundle re-resolves. May take 30+ seconds on first run (clones modules).

**Step 7: Verify `amplifier-agent verify --check-hooks` now exits 0**

```bash
uv run amplifier-agent verify --check-hooks
```

Expected: `[ OK ] streaming hook covers minimum-set: ['result/delta', 'result/final', 'tool/started', 'tool/completed', 'usage']` and exit 0.

**Step 8: python_check + commit**

```python
python_check(paths=["src/amplifier_agent_lib/bundle/"])
```

```bash
git add src/amplifier_agent_lib/bundle/bundle.md src/amplifier_agent_lib/bundle/loader.py tests/test_bundle_loader.py
git commit -m "feat(bundle): gap (d) part 3 — register streaming hook in bundle.md

Mounts amplifier_agent_lib.bundle.hook_streaming as a bundle hook so
every kernel event flowing through coordinator.hooks reaches the wire
via the display.emit capability bridged in _runtime.py.

Bundle hash changes; warm cache self-invalidates on first run.

\`amplifier-agent verify --check-hooks\` now exits 0.

Refs: docs/designs/2026-05-20-aaa-v2-wrapper-and-wire.md §4.5, Appendix C step 5"
```

---

## Task 13: SC-4 — resume continuity end-to-end test

**Why:** Per design A7, `context-simple` is assumed to replay transcripts when `is_resumed=True`. No production test currently validates this end-to-end. If it doesn't replay, the design's resume claim is broken; the right fix is to swap to `context-persistent` in `bundle.md`.

**Files:**
- Create: `tests/test_resume_continuity.py`

**Step 1: Write the failing test**

```python
"""End-to-end test: two turns with --session-id X --resume see continuity (SC-4)."""

from __future__ import annotations

import json
import os
import subprocess


def _run(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    return subprocess.run(
        ["uv", "run", "amplifier-agent", *args],
        capture_output=True,
        text=True,
        env=merged_env,
        timeout=120,
    )


def test_resume_continuity_two_turns_share_context() -> None:
    """Turn 2 with --resume sees turn 1's context.

    Strategy: turn 1 plants a fact ("my favorite color is purple"); turn 2
    with --resume asks "what is my favorite color?" and the reply should
    include 'purple'.

    Skipped if ANTHROPIC_API_KEY is not set (real provider required for
    end-to-end LLM calls).
    """
    if not os.environ.get("ANTHROPIC_API_KEY"):
        import pytest

        pytest.skip("ANTHROPIC_API_KEY not set; resume continuity needs a real provider")

    session_id = "test-resume-cont-001"
    # Turn 1: plant a fact.
    r1 = _run("run", "My favorite color is purple. Please remember it.", "--session-id", session_id, "--fresh")
    assert r1.returncode == 0, f"turn 1 failed: stdout={r1.stdout!r} stderr={r1.stderr!r}"

    # Turn 2: resume and probe.
    r2 = _run("run", "What is my favorite color?", "--session-id", session_id, "--resume")
    assert r2.returncode == 0, f"turn 2 failed: stdout={r2.stdout!r} stderr={r2.stderr!r}"
    parsed = json.loads(r2.stdout)
    reply = (parsed.get("reply") or "").lower()
    assert "purple" in reply, (
        f"resume context did not propagate; turn 2 reply={reply!r}. "
        f"If this fails, swap context module in bundle.md from context-simple "
        f"to context-persistent per design A7."
    )
```

**Step 2: Run test**

```bash
pytest tests/test_resume_continuity.py -v
```

Expected: PASS if `context-simple` handles resume correctly; FAIL if not.

**Step 3: If FAIL — swap bundle context module**

Edit `src/amplifier_agent_lib/bundle/bundle.md`:

```yaml
  context:
    module: context-persistent
    source: git+https://github.com/microsoft/amplifier-module-context-persistent@main
    config:
      max_tokens: 300000
```

Re-run the test. If it still fails, escalate: this means the `is_resumed=True` flag isn't reaching the persistence layer at all, and the design's resume guarantee is materially broken. Stop and surface to the user.

**Step 4: Commit**

```bash
git add tests/test_resume_continuity.py src/amplifier_agent_lib/bundle/bundle.md
git commit -m "test: SC-4 — resume continuity across two turns

Validates A7 from the design: --session-id X --resume on a second
invocation sees the first turn's context. The test plants a fact in
turn 1 and probes for it in turn 2.

If the test forced a bundle.md change (context-simple → context-persistent),
the swap is recorded in this commit per the design's A7 contingency.

Refs: docs/designs/2026-05-20-aaa-v2-wrapper-and-wire.md A7"
```

---

## Task 14: Phase 2.0c exit gate

**Why:** This is the final gate. A real-foundation single-turn invocation must produce ≥1 `result/delta` and exactly one `result/final` notification observable from `amplifier-agent run "hello"`. `amplifier-agent verify --check-hooks` must exit 0. Phase 2.0c is not complete until both are green.

**Files:**
- Modify: `tests/cli/test_end_to_end.py`

**Step 1: Write the failing test**

Add to `tests/cli/test_end_to_end.py`:

```python
def test_phase_2_0c_exit_gate_verify_check_hooks_exits_0() -> None:
    """`amplifier-agent verify --check-hooks` exits 0 with min-set coverage."""
    result = _run("verify", "--check-hooks", env={"ANTHROPIC_API_KEY": "sk-test"})
    assert result.returncode == 0, (
        f"verify --check-hooks must exit 0; got {result.returncode}. "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    assert "minimum-set" in result.stdout.lower() or "ok" in result.stdout.lower()


def test_phase_2_0c_exit_gate_real_turn_emits_result_events() -> None:
    """A real-provider `run` produces ≥1 result/delta and 1 result/final to stderr.

    Per design §4.4 + §5.1: the streaming hook emits all wire DisplayEvents
    via ctx.display.emit. CliDisplaySystem writes them as [type] prefixed
    lines to stderr.

    Skipped if ANTHROPIC_API_KEY is not set.
    """
    if not os.environ.get("ANTHROPIC_API_KEY"):
        import pytest

        pytest.skip("ANTHROPIC_API_KEY not set; exit-gate needs real provider")

    result = _run("run", "Say hi in three words.", "--verbose")
    assert result.returncode == 0, f"run failed: stderr={result.stderr!r}"

    stderr_lines = result.stderr.splitlines()
    delta_count = sum(1 for line in stderr_lines if "[result/delta]" in line)
    final_count = sum(1 for line in stderr_lines if "[result/final]" in line)

    assert delta_count >= 1, (
        f"expected >=1 result/delta event on stderr; got {delta_count}. "
        f"stderr tail: {stderr_lines[-30:]!r}"
    )
    assert final_count == 1, (
        f"expected exactly 1 result/final event on stderr; got {final_count}. "
        f"stderr tail: {stderr_lines[-30:]!r}"
    )
```

**Step 2: Run tests**

```bash
pytest tests/cli/test_end_to_end.py::test_phase_2_0c_exit_gate_verify_check_hooks_exits_0 tests/cli/test_end_to_end.py::test_phase_2_0c_exit_gate_real_turn_emits_result_events -v
```

Expected: PASS for `verify --check-hooks` test (already validated in Task 12). The real-turn test exercises the entire bridge built in Tasks 10–12.

**Step 3: If real-turn test fails, debug in this order:**

1. **Did `verify --check-hooks` pass?** If yes, the hook is mounted. Continue.
2. **Are stderr lines empty?** Run `uv run amplifier-agent run "hi" --verbose 2>&1 | tail -50` and inspect. If the LLM responded but no `[result/...]` lines appear, the hook is mounted but events aren't reaching `CliDisplaySystem`. Check `_runtime.py` — confirm `register_capability("display.emit", ctx.display.emit)` runs before `session.execute()`.
3. **Are events being emitted but with wrong types?** Add `--debug` instead of `--verbose` and re-run; the debug output dumps every emitted event as JSON. Confirm the `type` field matches the canonical wire taxonomy.
4. **If `tool/started` doesn't appear but `result/*` does**, the LLM didn't use any tools — the test prompt should be benign enough not to invoke tools. That's a test-design issue, not a code issue; adjust the test to only assert on `result/delta` + `result/final`.

**Step 4: Run the FULL test suite + python_check + linting**

```bash
pytest tests/ -q
```

```python
python_check(paths=["src/", "tests/"])
```

Both must be green. Fix any drift.

**Step 5: Final commit — Phase 2.0c complete**

```bash
git add tests/cli/test_end_to_end.py
git commit -m "feat(engine): Phase 2.0c gap fixes complete — bridges display + approval per design doc 2026-05-20

Exit gate:
  ✓ amplifier-agent verify --check-hooks exits 0 (minimum-set 5 events)
  ✓ amplifier-agent run \"...\" emits ≥1 result/delta + 1 result/final
    from a real foundation turn (observable via --verbose stderr)

This commit closes Phase 2.0c of the AaA v2 design. Wire protocol v0
(\"2026-05-aaa-v0\") is snapshotted; Phase 2.1 (protocol/_gen.py + shared
YAML fixtures + conformance harness) can now begin.

Eight V1 / NC failure modes designed out by construction:
  F5  — this.active race (one subprocess per SessionHandle)
  F7  — implicit L14 contract (explicit + tested)
  F11 — mid-burst death (burst removed in D10)
  F13a — first-run cliff (install-time prepare)
  F15 — cancel races (turn/cancel removed in D3)
  NC-L14 — same as F5
  NC-L16 — same as F7
  CR-4 — turn/cancel silently consumed (deleted with Mode B)

Refs: docs/designs/2026-05-20-aaa-v2-wrapper-and-wire.md (Phase 2.0c)"
```

---

## Phase 2.0c done — what's next

After Task 14 lands and `pytest tests/ -q` is green:

1. **Snapshot the wire as v0.** Update `PROTOCOL_VERSION` in `src/amplifier_agent_lib/protocol/methods.py` to the locked string `"2026-05-aaa-v0"` (already that value — confirm). Tag the commit: `git tag wire-v0 && git push origin wire-v0`.

2. **Notify downstream consumers** (per design §10.9). Send NC + PC implementation owners the wire version string, the design doc link, and a snippet of `[result/delta]` output proving the streaming hook works end-to-end.

3. **Move to Phase 2.1 (separate plan).** Author `protocol/_gen.py` + generated `spec.md` + JSON schemas + shared YAML wire-sequence fixtures + parity lint. That plan is sized for ~3 days of work and lives at `docs/plans/<date>-phase-2-1-wire-spec-hardening.md` when written.

4. **Phase 2.2 + 2.3 (also separate plan):** TS + Py wrappers, co-designed against the snapshotted wire v0.

## Cross-task notes / common pitfalls

- **`asyncio_mode = 'strict'` in `pyproject.toml`:** every async test MUST be decorated with `@pytest.mark.asyncio`. Forgetting it produces a warning that becomes an error in strict mode.
- **Don't run `uv run amplifier-agent ...` inside a Python test that's already inside `uv run pytest ...`.** The subprocess inherits the parent uv environment and works correctly, but timeouts compound — set `timeout=120` for real-provider tests.
- **The bundle cache key is content-addressed by `bundle.md`'s sha256.** Every Task that edits `bundle.md` (Task 12) self-invalidates the warm cache. The first `pytest` run after such an edit takes 30+ seconds while modules clone. That's not a test failure.
- **When a `python_check` issue is `module not found` for a deleted file, the autocache may be stale.** Run `find . -name __pycache__ -exec rm -rf {} +` once and re-check.
- **If a Task's commit breaks an unrelated test, fix it in the same commit OR add an `xfail` marker referencing the next Task that closes the breakage.** Do not skip — `xfail` carries a TODO; `skip` hides.
