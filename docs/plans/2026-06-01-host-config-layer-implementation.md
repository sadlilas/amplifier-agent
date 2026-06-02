# Host Config Layer Implementation Plan (Phase 2)

> **Execution:** Use the subagent-driven-development workflow to implement this plan.

**Goal:** Add a persistent host config layer between the sealed bundle and per-turn argv: wire `--config <path>` / `$AMPLIFIER_AGENT_CONFIG`, parse with `json.load`, validate strict-by-default, layered-merge into bundle module configs (mcp, approval, provider), and drop the three argv flags + one env var + one vestigial helper that the config layer subsumes.

**Architecture:** A new `amplifier_agent_lib.config` package owns resolution (`loader.py`) and per-block layered merge (`merger.py`). The CLI `run` command resolves+parses the config before bundle mount; `_runtime.py` merges parsed config into the mount plan before sessions spawn. Validation is strict (unknown top-level keys → hard error; unknown nested keys → module's responsibility). All config errors flow as `AaaError` subclass `ConfigError` so they ride the existing envelope schema. XDG path computation is consolidated through `persistence.py`.

**Tech Stack:** Python 3.12 (stdlib `json` only — no parser dependency), click, pytest, AaaError envelope shape (`code`/`classification`/`message`).

**Phase context:** This is Phase 2 of two. Phase 1 (`docs/plans/2026-06-01-drop-host-capabilities-implementation.md`) removes `hostCapabilities` from the engine and wrappers. The two phases are independent — this one is engine-only and modifies no wrapper code.

**Design source:** `docs/designs/2026-06-01-host-config-layer-revisit.md` (decisions D1–D10).

---

## Prerequisites

Before starting Task A1, verify the baseline:

```bash
cd /Users/mpaidiparthy/repos/amplifier-agent
git status                                # working tree clean on main
uv sync                                   # deps installed
uv run pytest -x -q 2>&1 | tail -20       # full suite GREEN
```

Expected: `passed` line at the bottom, exit code 0. If anything is red, STOP and fix before proceeding.

---

## Section A — Foundation (XDG consolidation, no behavior change)

These three tasks land first so the new config code path uses `persistence.py` from day one and never re-introduces duplicate XDG resolvers.

### Task A1: Consolidate `bundle/cache.py` XDG lookup through `persistence.cache_root()`

**Files:**
- Modify: `src/amplifier_agent_lib/bundle/cache.py`
- Test: `tests/test_bundle_cache.py` (add one test; do not modify existing)

**Step 1: Write the failing test.**

Append this test to `tests/test_bundle_cache.py` (if the file has no `monkeypatch`+`persistence` import yet, add them):

```python
def test_cache_dir_for_version_uses_persistence_cache_root(monkeypatch, tmp_path):
    """cache_dir_for_version() must compute its base via persistence.cache_root().

    Regression guard for D9 (XDG consolidation). After A1, bundle/cache.py
    must NOT define a private _xdg_cache_home(); the only XDG resolver is
    amplifier_agent_lib.persistence.cache_root().
    """
    import amplifier_agent_lib.bundle.cache as cache_mod

    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "custom-cache"))

    result = cache_mod.cache_dir_for_version("1.2.3")

    # The directory layout under cache_root() is
    # "<root>/prepared/<version>/<sha[:16]>"; assert both the root and the
    # "prepared/<version>" prefix.
    assert str(result).startswith(str(tmp_path / "custom-cache" / "amplifier-agent" / "prepared" / "1.2.3"))

    # The private helper must be gone.
    assert not hasattr(cache_mod, "_xdg_cache_home"), (
        "_xdg_cache_home() must be removed; use persistence.cache_root()"
    )
```

**Step 2: Run the test, watch it fail.**

```bash
uv run pytest tests/test_bundle_cache.py::test_cache_dir_for_version_uses_persistence_cache_root -v
```

Expected: `FAILED` with `AssertionError: _xdg_cache_home() must be removed; ...` (the function still exists at line 43). The first `assert .startswith(...)` may or may not fail depending on whether the layouts already match — the second assertion is the load-bearing one.

**Step 3: Implement.**

Edit `src/amplifier_agent_lib/bundle/cache.py`:

1. Remove the `_xdg_cache_home()` function entirely (lines 43–51).
2. Remove the now-unused `import os` line if no other reference remains (grep first).
3. Replace `_xdg_cache_home() / _CACHE_SUBDIR / aaa_version / content_hash` in `cache_dir_for_version` with `persistence.cache_root() / "prepared" / aaa_version / content_hash`.
4. Add `from amplifier_agent_lib import persistence` at the top.
5. Delete the `_CACHE_SUBDIR` constant — it duplicated `persistence.APP_NAME + "/prepared"`. The new path uses `persistence.cache_root()` (which already includes `amplifier-agent`) plus `"prepared"`.

The new `cache_dir_for_version` body becomes:

```python
target = bundle_path if bundle_path is not None else BUNDLE_MD
content_hash = hashlib.sha256(target.read_bytes()).hexdigest()[:16]
return persistence.cache_root() / "prepared" / aaa_version / content_hash
```

Update the module docstring's "Cache layout" section to read `$XDG_CACHE_HOME/amplifier-agent/prepared/...` (no functional change — it's already the same path; just remove the stale `_CACHE_SUBDIR` reference if mentioned).

**Step 4: Run the test, watch it pass.**

```bash
uv run pytest tests/test_bundle_cache.py -v
```

Expected: all tests PASS. Run the full `bundle_cache` file to make sure existing tests still pass with the consolidated implementation.

**Step 5: Commit.**

```bash
git add src/amplifier_agent_lib/bundle/cache.py tests/test_bundle_cache.py
git commit -m "refactor(bundle): route bundle/cache.py XDG lookup through persistence.cache_root() (D9)"
```

---

### Task A2: Consolidate `admin/doctor.py` XDG lookup through `persistence` helpers

**Files:**
- Modify: `src/amplifier_agent_cli/admin/doctor.py`
- Test: `tests/cli/test_doctor.py` (verify existing tests still pass; add one regression test)

**Step 1: Write the failing test.**

Append to `tests/cli/test_doctor.py`:

```python
def test_doctor_uses_persistence_for_xdg_paths(monkeypatch, tmp_path):
    """doctor.py must not redefine private XDG helpers (D9).

    After A2, the private _xdg() helper must be removed. The doctor command
    must compute its three XDG roots via amplifier_agent_lib.persistence.
    """
    import amplifier_agent_cli.admin.doctor as doctor_mod

    assert not hasattr(doctor_mod, "_xdg"), (
        "doctor._xdg() must be removed; use persistence.config_root() / cache_root() / state_root()"
    )
```

**Step 2: Run, watch it fail.**

```bash
uv run pytest tests/cli/test_doctor.py::test_doctor_uses_persistence_for_xdg_paths -v
```

Expected: `FAILED — doctor._xdg() must be removed`.

**Step 3: Implement.**

Edit `src/amplifier_agent_cli/admin/doctor.py`:

1. Delete the `_xdg()` function (lines 72–75).
2. Add `from amplifier_agent_lib import persistence` to the imports.
3. In the `doctor()` function body (around line 414–417), replace the three `_xdg(...)` calls with the persistence helpers — these already include the `amplifier-agent` suffix, so drop the `/ "amplifier-agent"` suffix in the calling code:

```python
cfg = persistence.config_root()
cache = persistence.cache_root()
state = persistence.state_root()
```

4. The `home = Path(os.environ.get("HOME", str(Path.home())))` line just above is now unused; delete it if nothing else in `doctor()` references `home`. Grep first to confirm.

**Step 4: Run, watch it pass.**

```bash
uv run pytest tests/cli/test_doctor.py -v
```

Expected: all tests PASS. The pre-existing doctor tests probe writable XDG paths via `monkeypatch.setenv` on the XDG env vars; since `persistence.cache_root()` reads the same env vars, the existing tests must keep passing unchanged.

**Step 5: Commit.**

```bash
git add src/amplifier_agent_cli/admin/doctor.py tests/cli/test_doctor.py
git commit -m "refactor(cli): route admin/doctor.py XDG lookup through persistence (D9)"
```

---

### Task A3: Normalize empty-string XDG env vars in `persistence.py`

**Files:**
- Modify: `src/amplifier_agent_lib/persistence.py`
- Test: `tests/test_persistence.py` (add three tests)

**Step 1: Write the failing tests.**

Append to `tests/test_persistence.py`:

```python
def test_cache_root_treats_empty_xdg_cache_home_as_absent(monkeypatch, tmp_path):
    """XDG_CACHE_HOME='' → fall back to ~/.cache (per D9 consolidation).

    Today persistence.py:28 reads `os.environ.get('XDG_CACHE_HOME')` which
    returns the empty string when the var is set-but-empty. The empty
    string is then treated as a valid path → cache_root() returns
    Path('') / 'amplifier-agent'. A3 normalizes to 'empty == absent'.
    """
    monkeypatch.setenv("XDG_CACHE_HOME", "")
    monkeypatch.setenv("HOME", str(tmp_path))

    result = persistence.cache_root()

    assert result == tmp_path / ".cache" / "amplifier-agent"


def test_config_root_treats_empty_xdg_config_home_as_absent(monkeypatch, tmp_path):
    """XDG_CONFIG_HOME='' → fall back to ~/.config."""
    monkeypatch.setenv("XDG_CONFIG_HOME", "")
    monkeypatch.setenv("HOME", str(tmp_path))

    result = persistence.config_root()

    assert result == tmp_path / ".config" / "amplifier-agent"


def test_state_root_treats_empty_xdg_state_home_as_absent(monkeypatch, tmp_path):
    """XDG_STATE_HOME='' → fall back to ~/.local/state."""
    monkeypatch.setenv("XDG_STATE_HOME", "")
    monkeypatch.setenv("HOME", str(tmp_path))

    result = persistence.state_root()

    assert result == tmp_path / ".local" / "state" / "amplifier-agent"
```

**Step 2: Run, watch them fail.**

```bash
uv run pytest tests/test_persistence.py::test_cache_root_treats_empty_xdg_cache_home_as_absent tests/test_persistence.py::test_config_root_treats_empty_xdg_config_home_as_absent tests/test_persistence.py::test_state_root_treats_empty_xdg_state_home_as_absent -v
```

Expected: 3 FAILED (current behavior is `xdg = os.environ.get("XDG_CACHE_HOME"); base = Path(xdg) if xdg else ...`, but `Path("")` is the current working directory in pathlib — actually `Path("") == Path(".")`, so the assertion compares against `Path(".") / "amplifier-agent"` and fails).

**Step 3: Implement.**

Edit `src/amplifier_agent_lib/persistence.py`. In each of `cache_root`, `config_root`, `state_root`, change the pattern from:

```python
xdg = os.environ.get("XDG_CACHE_HOME")
base = Path(xdg) if xdg else _home() / ".cache"
```

to:

```python
xdg = os.environ.get("XDG_CACHE_HOME") or None
base = Path(xdg) if xdg else _home() / ".cache"
```

The `or None` coerces the empty string to `None`, making the `if xdg` branch consistent with "set and non-empty". Apply to all three functions.

**Step 4: Run, watch them pass.**

```bash
uv run pytest tests/test_persistence.py -v
```

Expected: all PASS.

**Step 5: Commit.**

```bash
git add src/amplifier_agent_lib/persistence.py tests/test_persistence.py
git commit -m "fix(persistence): treat empty XDG env vars as absent (D9)"
```

---

## Section B — Config layer foundation (loader)

The `loader.py` module owns resolution + parsing + validation. Strict-by-default: any deviation raises `ConfigError`. The error class subclasses `AaaError` so it flows through the existing envelope path (`error.code`, `error.classification`, `error.message`).

### Task B1: Create `config` package + `ConfigError` exception class

**Files:**
- Create: `src/amplifier_agent_lib/config/__init__.py`
- Create: `tests/config/__init__.py`
- Create: `tests/config/test_loader.py`

**Step 1: Write the failing test.**

Create `tests/config/__init__.py` as an empty file. Create `tests/config/test_loader.py` with this content:

```python
"""Tests for amplifier_agent_lib.config.loader and ConfigError."""

from __future__ import annotations

import pytest

from amplifier_agent_lib.config import ConfigError
from amplifier_agent_lib.protocol.errors import AaaError


def test_config_error_is_aaa_error_subclass() -> None:
    """ConfigError must subclass AaaError so it rides the envelope path."""
    assert issubclass(ConfigError, AaaError)


def test_config_error_carries_code_classification_message() -> None:
    """ConfigError must propagate code/classification/message into AaaError."""
    exc = ConfigError(
        code="config_unreadable",
        message="not found",
        classification="protocol",
    )
    assert exc.code == "config_unreadable"
    assert exc.classification == "protocol"
    assert exc.message == "not found"
```

**Step 2: Run, watch it fail.**

```bash
uv run pytest tests/config/test_loader.py -v
```

Expected: `ModuleNotFoundError: No module named 'amplifier_agent_lib.config'`.

**Step 3: Implement.**

Create `src/amplifier_agent_lib/config/__init__.py`:

```python
"""Host config layer for amplifier-agent.

Two responsibilities:
  - loader.py — resolve ($AMPLIFIER_AGENT_CONFIG / --config), parse (json.load),
    validate (strict-by-default per D7).
  - merger.py — layered merge of host config over bundle module configs (D5).

Per design D4 the schema is a pass-through to module configs; amplifier-agent
invents no vocabulary of its own. See docs/designs/2026-06-01-host-config-layer-revisit.md.
"""

from __future__ import annotations

from amplifier_agent_lib.protocol.errors import AaaError


class ConfigError(AaaError):
    """Host config resolution/parse/validation failure.

    Subclasses AaaError so the CLI's existing _build_error_envelope path
    catches it and emits a §4.1 envelope with classification='protocol'
    (exit code 2 per _EXIT_CODE_BY_CLASSIFICATION).
    """

    def __init__(
        self,
        *,
        code: str,
        message: str,
        classification: str = "protocol",
    ) -> None:
        super().__init__(
            code=code,
            message=message,
            classification=classification,
        )


__all__ = ["ConfigError"]
```

**Step 4: Run, watch it pass.**

```bash
uv run pytest tests/config/test_loader.py -v
```

Expected: 2 PASS.

**Step 5: Commit.**

```bash
git add src/amplifier_agent_lib/config/__init__.py tests/config/__init__.py tests/config/test_loader.py
git commit -m "feat(config): add config package skeleton + ConfigError(AaaError) subclass"
```

---

### Task B2: Stub `load_config()` returning `None` when no tier is present

**Files:**
- Create: `src/amplifier_agent_lib/config/loader.py`
- Modify: `src/amplifier_agent_lib/config/__init__.py` (re-export `load_config`)
- Modify: `tests/config/test_loader.py`

**Step 1: Write the failing test.** Append to `tests/config/test_loader.py`:

```python
def test_load_config_returns_none_when_no_tier(monkeypatch) -> None:
    """No --config arg and no env var → returns None (bundle defaults apply, D1)."""
    monkeypatch.delenv("AMPLIFIER_AGENT_CONFIG", raising=False)

    from amplifier_agent_lib.config import load_config

    assert load_config(config_arg=None) is None
```

**Step 2: Run, watch it fail.**

```bash
uv run pytest tests/config/test_loader.py::test_load_config_returns_none_when_no_tier -v
```

Expected: `ImportError: cannot import name 'load_config'`.

**Step 3: Implement.**

Create `src/amplifier_agent_lib/config/loader.py`:

```python
"""Host config resolution + parse + validation (D1, D2, D3, D7).

Resolution order (first hit wins):
  1. --config <path> argv flag.
  2. $AMPLIFIER_AGENT_CONFIG env var.
Absent both, returns None (bundle defaults apply; D1).
"""

from __future__ import annotations

import os
from typing import Any


def load_config(config_arg: str | None) -> dict[str, Any] | None:
    """Resolve, parse, and validate a host config file.

    Parameters
    ----------
    config_arg:
        The argv value of --config <path>, or None if the flag was absent.

    Returns
    -------
    dict | None
        Parsed config dict if a tier matched; None otherwise.

    Raises
    ------
    ConfigError
        On unreadable path, malformed JSON, or schema violation.
    """
    if config_arg is None and not os.environ.get("AMPLIFIER_AGENT_CONFIG"):
        return None
    raise NotImplementedError("flag/env-tier resolution lands in B3/B4")
```

Edit `src/amplifier_agent_lib/config/__init__.py` to re-export:

```python
from amplifier_agent_lib.config.loader import load_config
from amplifier_agent_lib.protocol.errors import AaaError

class ConfigError(AaaError):  # ... (unchanged body)

__all__ = ["ConfigError", "load_config"]
```

**Step 4: Run, watch it pass.**

```bash
uv run pytest tests/config/test_loader.py -v
```

Expected: 3 PASS.

**Step 5: Commit.**

```bash
git add src/amplifier_agent_lib/config/loader.py src/amplifier_agent_lib/config/__init__.py tests/config/test_loader.py
git commit -m "feat(config): stub load_config() returning None when no resolution tier (D1)"
```

---

### Task B3: Flag-tier resolution + minimal happy-path JSON parse

**Files:**
- Modify: `src/amplifier_agent_lib/config/loader.py`
- Modify: `tests/config/test_loader.py`

**Step 1: Write the failing test.** Append:

```python
def test_load_config_reads_flag_path_with_json_load(tmp_path, monkeypatch) -> None:
    """--config <path> → json.load → dict (D3)."""
    monkeypatch.delenv("AMPLIFIER_AGENT_CONFIG", raising=False)

    cfg_path = tmp_path / "aaa.json"
    cfg_path.write_text('{"mcp": {"verbose_servers": true}}', encoding="utf-8")

    from amplifier_agent_lib.config import load_config

    result = load_config(config_arg=str(cfg_path))

    assert result == {"mcp": {"verbose_servers": True}}
```

**Step 2: Run, watch it fail.**

```bash
uv run pytest tests/config/test_loader.py::test_load_config_reads_flag_path_with_json_load -v
```

Expected: `NotImplementedError`.

**Step 3: Implement.**

Replace the body of `load_config` in `src/amplifier_agent_lib/config/loader.py` with:

```python
from pathlib import Path
import json

# ... (top-of-file imports already in place)

_VALID_TOP_LEVEL_KEYS = frozenset({"mcp", "approval", "provider", "allowProtocolSkew"})


def load_config(config_arg: str | None) -> dict[str, Any] | None:
    """..."""  # docstring unchanged
    path_str = config_arg or os.environ.get("AMPLIFIER_AGENT_CONFIG") or None
    if path_str is None:
        return None

    path = Path(path_str)
    raw = path.read_text(encoding="utf-8")
    parsed = json.loads(raw)
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        # B7 will replace this stub with a proper ConfigError; keep type-narrow now.
        raise TypeError(f"config root must be a mapping, got {type(parsed).__name__}")
    return parsed
```

Note: `import json` and `from pathlib import Path` go at the top of `loader.py`. JSON does not have an "empty document" case the way YAML does — an empty file is a `json.JSONDecodeError` (caught in B5). A file containing the literal `null` parses to `None`; we map that to an empty dict for the same reason YAML's empty doc did (D5: omitted block → bundle default).

**Step 4: Run, watch it pass.**

```bash
uv run pytest tests/config/test_loader.py -v
```

Expected: 4 PASS.

**Step 5: Commit.**

```bash
git add src/amplifier_agent_lib/config/loader.py tests/config/test_loader.py
git commit -m "feat(config): wire --config flag tier with json.load (D1, D3)"
```

---

### Task B4: Env-tier resolution + flag-wins-over-env precedence

**Files:**
- Modify: `tests/config/test_loader.py`

(Implementation already supports env-tier from the `or os.environ.get(...)` chain in B3; we add tests to lock the contract.)

**Step 1: Write the failing test(s).** Append:

```python
def test_load_config_reads_env_path_when_flag_absent(tmp_path, monkeypatch) -> None:
    """--config absent + $AMPLIFIER_AGENT_CONFIG set → reads env path (D1)."""
    cfg_path = tmp_path / "env.json"
    cfg_path.write_text('{"approval": {"auto_approve": false}}', encoding="utf-8")
    monkeypatch.setenv("AMPLIFIER_AGENT_CONFIG", str(cfg_path))

    from amplifier_agent_lib.config import load_config

    result = load_config(config_arg=None)

    assert result == {"approval": {"auto_approve": False}}


def test_load_config_flag_wins_over_env(tmp_path, monkeypatch) -> None:
    """Both tiers set → --config wins (D1: first hit wins, top of order)."""
    flag_path = tmp_path / "flag.json"
    flag_path.write_text('{"mcp": {"verbose_servers": true}}', encoding="utf-8")
    env_path = tmp_path / "env.json"
    env_path.write_text('{"mcp": {"verbose_servers": false}}', encoding="utf-8")

    monkeypatch.setenv("AMPLIFIER_AGENT_CONFIG", str(env_path))

    from amplifier_agent_lib.config import load_config

    result = load_config(config_arg=str(flag_path))

    assert result == {"mcp": {"verbose_servers": True}}
```

**Step 2: Run, watch them pass (B3's `or` chain already handles this).**

```bash
uv run pytest tests/config/test_loader.py -v
```

Expected: all 6 PASS. (If a test unexpectedly fails, the precedence chain in `load_config` is wrong — fix it before committing.)

**Step 3:** No implementation change needed; the B3 chain already encodes flag-wins-over-env.

**Step 4: Commit.**

```bash
git add tests/config/test_loader.py
git commit -m "test(config): lock flag-wins-over-env-tier precedence (D1)"
```

---

### Task B5: Hard error on malformed JSON

**Files:**
- Modify: `src/amplifier_agent_lib/config/loader.py`
- Modify: `tests/config/test_loader.py`

**Step 1: Write the failing test.** Append:

```python
def test_load_config_raises_on_malformed_json(tmp_path, monkeypatch) -> None:
    """Broken JSON → ConfigError(code='config_malformed_json', classification='protocol') (D7)."""
    monkeypatch.delenv("AMPLIFIER_AGENT_CONFIG", raising=False)

    cfg_path = tmp_path / "bad.json"
    cfg_path.write_text('{"mcp": {"verbose_servers": true,', encoding="utf-8")  # truncated / trailing comma

    from amplifier_agent_lib.config import ConfigError, load_config

    with pytest.raises(ConfigError) as exc_info:
        load_config(config_arg=str(cfg_path))

    assert exc_info.value.code == "config_malformed_json"
    assert exc_info.value.classification == "protocol"
    assert str(cfg_path) in exc_info.value.message
```

**Step 2: Run, watch it fail.**

```bash
uv run pytest tests/config/test_loader.py::test_load_config_raises_on_malformed_json -v
```

Expected: FAILED — raises raw `json.JSONDecodeError`, not `ConfigError`.

**Step 3: Implement.**

In `src/amplifier_agent_lib/config/loader.py`, wrap the parse step:

```python
from amplifier_agent_lib.config import ConfigError

# ... in load_config, replace `parsed = json.loads(raw)`:
try:
    parsed = json.loads(raw)
except json.JSONDecodeError as exc:
    raise ConfigError(
        code="config_malformed_json",
        message=f"Failed to parse JSON at {path}: {exc}",
        classification="protocol",
    ) from exc
```

Note the circular-import risk: `loader.py` importing `ConfigError` from `amplifier_agent_lib.config` (i.e. `__init__.py`). To avoid it, place the `from amplifier_agent_lib.config import ConfigError` import INSIDE the function body (lazy) OR define `ConfigError` in `loader.py` and re-export from `__init__.py`. Prefer the second: move the `ConfigError` class definition from `__init__.py` to `loader.py`, then make `__init__.py` `from amplifier_agent_lib.config.loader import ConfigError, load_config`. Verify with `uv run python -c "from amplifier_agent_lib.config import ConfigError, load_config"` — must succeed.

**Step 4: Run, watch it pass.**

```bash
uv run pytest tests/config/test_loader.py -v
```

Expected: 7 PASS.

**Step 5: Commit.**

```bash
git add src/amplifier_agent_lib/config/loader.py src/amplifier_agent_lib/config/__init__.py tests/config/test_loader.py
git commit -m "feat(config): hard error on malformed JSON (D7, code=config_malformed_json)"
```

---

### Task B6: Hard error on missing / unreadable path

**Files:**
- Modify: `src/amplifier_agent_lib/config/loader.py`
- Modify: `tests/config/test_loader.py`

**Step 1: Write the failing test.** Append:

```python
def test_load_config_raises_on_missing_path(tmp_path, monkeypatch) -> None:
    """--config /missing/path → ConfigError(config_unreadable) (D2)."""
    monkeypatch.delenv("AMPLIFIER_AGENT_CONFIG", raising=False)
    missing = tmp_path / "does-not-exist.json"

    from amplifier_agent_lib.config import ConfigError, load_config

    with pytest.raises(ConfigError) as exc_info:
        load_config(config_arg=str(missing))

    assert exc_info.value.code == "config_unreadable"
    assert exc_info.value.classification == "protocol"
    assert str(missing) in exc_info.value.message


def test_load_config_raises_on_missing_env_path(tmp_path, monkeypatch) -> None:
    """$AMPLIFIER_AGENT_CONFIG set to missing path → ConfigError(config_unreadable) (D2).

    The env var is NOT silently ignored on missing — setting it is an
    affirmative declaration that this file is the config.
    """
    missing = tmp_path / "missing-env.json"
    monkeypatch.setenv("AMPLIFIER_AGENT_CONFIG", str(missing))

    from amplifier_agent_lib.config import ConfigError, load_config

    with pytest.raises(ConfigError) as exc_info:
        load_config(config_arg=None)

    assert exc_info.value.code == "config_unreadable"
```

**Step 2: Run, watch them fail.**

```bash
uv run pytest tests/config/test_loader.py::test_load_config_raises_on_missing_path tests/config/test_loader.py::test_load_config_raises_on_missing_env_path -v
```

Expected: FAILED with `FileNotFoundError` propagating from `Path.read_text`.

**Step 3: Implement.**

In `loader.py`, wrap the read step:

```python
try:
    raw = path.read_text(encoding="utf-8")
except (FileNotFoundError, PermissionError, IsADirectoryError, OSError) as exc:
    raise ConfigError(
        code="config_unreadable",
        message=f"Cannot read config at {path}: {exc.__class__.__name__}: {exc}",
        classification="protocol",
    ) from exc
```

**Step 4: Run, watch them pass.**

```bash
uv run pytest tests/config/test_loader.py -v
```

Expected: 9 PASS.

**Step 5: Commit.**

```bash
git add src/amplifier_agent_lib/config/loader.py tests/config/test_loader.py
git commit -m "feat(config): hard error on missing/unreadable path (D2, code=config_unreadable)"
```

---

### Task B7: Hard error on unknown top-level keys (strict-by-default)

**Files:**
- Modify: `src/amplifier_agent_lib/config/loader.py`
- Modify: `tests/config/test_loader.py`

**Step 1: Write the failing test.** Append:

```python
def test_load_config_rejects_unknown_top_level_key(tmp_path, monkeypatch) -> None:
    """Unknown top-level key → ConfigError(config_unknown_key) (D7)."""
    monkeypatch.delenv("AMPLIFIER_AGENT_CONFIG", raising=False)

    cfg_path = tmp_path / "unknown.json"
    cfg_path.write_text('{"notifications": {"foo": "bar"}}', encoding="utf-8")

    from amplifier_agent_lib.config import ConfigError, load_config

    with pytest.raises(ConfigError) as exc_info:
        load_config(config_arg=str(cfg_path))

    assert exc_info.value.code == "config_unknown_key"
    assert "notifications" in exc_info.value.message
    # Message must list the four valid keys to guide the operator.
    assert "mcp" in exc_info.value.message
    assert "approval" in exc_info.value.message
    assert "provider" in exc_info.value.message
    assert "allowProtocolSkew" in exc_info.value.message


def test_load_config_accepts_all_four_known_keys(tmp_path, monkeypatch) -> None:
    """Config with all four known top-level keys parses without error."""
    monkeypatch.delenv("AMPLIFIER_AGENT_CONFIG", raising=False)

    cfg_path = tmp_path / "valid.json"
    cfg_path.write_text(
        '{'
        '  "mcp": {"verbose_servers": false},'
        '  "approval": {"auto_approve": false},'
        '  "provider": {"module": "anthropic"},'
        '  "allowProtocolSkew": false'
        '}',
        encoding="utf-8",
    )

    from amplifier_agent_lib.config import load_config

    result = load_config(config_arg=str(cfg_path))

    assert set(result.keys()) == {"mcp", "approval", "provider", "allowProtocolSkew"}
```

**Step 2: Run, watch the first one fail.**

```bash
uv run pytest tests/config/test_loader.py::test_load_config_rejects_unknown_top_level_key tests/config/test_loader.py::test_load_config_accepts_all_four_known_keys -v
```

Expected: first FAILED (no validation yet), second PASS.

**Step 3: Implement.**

In `loader.py`, after the `parsed = json.loads(...)` step and the `not isinstance(parsed, dict)` guard, add:

```python
unknown = set(parsed) - _VALID_TOP_LEVEL_KEYS
if unknown:
    raise ConfigError(
        code="config_unknown_key",
        message=(
            f"Unknown top-level config key(s): {sorted(unknown)}. "
            f"Valid keys: {sorted(_VALID_TOP_LEVEL_KEYS)}. "
            "amplifier-agent's config schema is closed at the top level (D7)."
        ),
        classification="protocol",
    )
```

Replace the temporary `raise TypeError(...)` from B3 with a proper `ConfigError`:

```python
if not isinstance(parsed, dict):
    raise ConfigError(
        code="config_malformed_json",
        message=f"Config root at {path} must be a JSON object, got {type(parsed).__name__}.",
        classification="protocol",
    )
```

**Step 4: Run, watch both pass.**

```bash
uv run pytest tests/config/test_loader.py -v
```

Expected: 11 PASS.

**Step 5: Commit.**

```bash
git add src/amplifier_agent_lib/config/loader.py tests/config/test_loader.py
git commit -m "feat(config): reject unknown top-level keys (D7, code=config_unknown_key)"
```

---

### Task B8: Validate `approval.patterns` items are strings (type guard)

**Files:**
- Modify: `src/amplifier_agent_lib/config/loader.py`
- Modify: `tests/config/test_loader.py`

JSON parses literal types unambiguously — `"no"` is a string, `false` is a boolean, `123` is a number. The YAML Norway problem (bare `no` accidentally coerced to `False`) does not apply here. This task still enforces the type constraint so a host passing a numeric or boolean literal where a string is expected gets a clear error rather than a downstream surprise inside `hooks-approval`.

**Step 1: Write the failing test.** Append:

```python
def test_load_config_rejects_non_string_approval_pattern(tmp_path, monkeypatch) -> None:
    """approval.patterns items must be strings → ConfigError (D7 type guard)."""
    monkeypatch.delenv("AMPLIFIER_AGENT_CONFIG", raising=False)

    cfg_path = tmp_path / "bad-pattern.json"
    cfg_path.write_text('{"approval": {"patterns": [123]}}', encoding="utf-8")

    from amplifier_agent_lib.config import ConfigError, load_config

    with pytest.raises(ConfigError) as exc_info:
        load_config(config_arg=str(cfg_path))

    assert exc_info.value.code == "config_invalid_type"
    # Message must instruct that pattern list members are strings.
    assert "approval.patterns" in exc_info.value.message
    assert "string" in exc_info.value.message.lower()


def test_load_config_accepts_string_patterns(tmp_path, monkeypatch) -> None:
    """approval.patterns: ["no", "rm -rf"] parses cleanly."""
    monkeypatch.delenv("AMPLIFIER_AGENT_CONFIG", raising=False)

    cfg_path = tmp_path / "ok.json"
    cfg_path.write_text('{"approval": {"patterns": ["no", "rm -rf"]}}', encoding="utf-8")

    from amplifier_agent_lib.config import load_config

    result = load_config(config_arg=str(cfg_path))

    assert result == {"approval": {"patterns": ["no", "rm -rf"]}}
```

**Step 2: Run, watch the first one fail.**

```bash
uv run pytest tests/config/test_loader.py::test_load_config_rejects_non_string_approval_pattern tests/config/test_loader.py::test_load_config_accepts_string_patterns -v
```

Expected: first FAILED (no validation), second PASS.

**Step 3: Implement.**

In `loader.py`, after the unknown-key check, add a per-block validator. Place this validation step right after the unknown-key check, before returning:

```python
_validate_approval_patterns(parsed.get("approval"), path)
```

And define the helper at module scope:

```python
def _validate_approval_patterns(approval_block: Any, path: Path) -> None:
    """Each approval.patterns item must be a string (D7 type guard)."""
    if not isinstance(approval_block, dict):
        return  # absent → bundle default applies (D5)
    patterns = approval_block.get("patterns")
    if patterns is None:
        return
    if not isinstance(patterns, list):
        raise ConfigError(
            code="config_invalid_type",
            message=(
                f"approval.patterns at {path} must be a JSON array of strings, "
                f"got {type(patterns).__name__}."
            ),
            classification="protocol",
        )
    for i, item in enumerate(patterns):
        if not isinstance(item, str):
            raise ConfigError(
                code="config_invalid_type",
                message=(
                    f"approval.patterns[{i}] at {path} must be a string, got "
                    f"{type(item).__name__} ({item!r}). "
                    "Each member of approval.patterns must be a JSON string literal."
                ),
                classification="protocol",
            )
```

**Step 4: Run, watch both pass.**

```bash
uv run pytest tests/config/test_loader.py -v
```

Expected: 13 PASS.

**Step 5: Commit.**

```bash
git add src/amplifier_agent_lib/config/loader.py tests/config/test_loader.py
git commit -m "feat(config): validate approval.patterns items are strings (D7 type guard)"
```

---

## Section C — Pass-through merger

The merger module owns the layered merge of host config over bundle module configs. Pure mechanism: `{**bundle_static, **host_overrides}` per block, no rename / no translation / no curation (D4).

### Task C1: Stub `merge_config()` returning bundle configs unchanged when host is None

**Files:**
- Create: `src/amplifier_agent_lib/config/merger.py`
- Modify: `src/amplifier_agent_lib/config/__init__.py` (re-export `merge_config`)
- Create: `tests/config/test_merger.py`

**Step 1: Write the failing test.** Create `tests/config/test_merger.py`:

```python
"""Tests for amplifier_agent_lib.config.merger.merge_config."""

from __future__ import annotations

import copy

import pytest


def test_merge_config_returns_bundle_unchanged_when_host_is_none() -> None:
    """host_config=None → bundle module configs flow through (D5)."""
    from amplifier_agent_lib.config import merge_config

    bundle_modules = {
        "tool-mcp": {"verbose_servers": False, "max_content_size": 50000},
        "hooks-approval": {"auto_approve": True},
    }
    snapshot = copy.deepcopy(bundle_modules)

    result = merge_config(bundle_modules=bundle_modules, host_config=None)

    assert result == snapshot
    # And it must not mutate the input.
    assert bundle_modules == snapshot
```

**Step 2: Run, watch it fail.**

```bash
uv run pytest tests/config/test_merger.py -v
```

Expected: `ImportError: cannot import name 'merge_config'`.

**Step 3: Implement.**

Create `src/amplifier_agent_lib/config/merger.py`:

```python
"""Layered merge of host config over bundle module configs (D5).

Per-block, per-key shallow merge: {**bundle_static, **host_overrides}.
No translation, no key renaming, no curation — amplifier-agent only
parameterizes what bundle.md already declares (D4 pass-through stance).
"""

from __future__ import annotations

import copy
from typing import Any


def merge_config(
    *,
    bundle_modules: dict[str, dict[str, Any]],
    host_config: dict[str, Any] | None,
) -> dict[str, dict[str, Any]]:
    """Return a new dict with bundle module configs layered with host overrides.

    Parameters
    ----------
    bundle_modules:
        Module-name → config dict mapping for the modules mounted by the
        bundle. The caller (typically `_runtime`) extracts these from
        `prepared.mount_plan` before calling merge.
    host_config:
        Parsed host config dict (output of `load_config`) or None.

    Returns
    -------
    dict
        New mapping with the same shape as ``bundle_modules`` but with
        host overrides layered per the rules below. Input is never
        mutated.
    """
    if host_config is None:
        return copy.deepcopy(bundle_modules)
    raise NotImplementedError("per-block merges land in C2/C3/C4")
```

Edit `__init__.py` to re-export:

```python
from amplifier_agent_lib.config.merger import merge_config

__all__ = ["ConfigError", "load_config", "merge_config"]
```

**Step 4: Run, watch it pass.**

```bash
uv run pytest tests/config/test_merger.py -v
```

Expected: 1 PASS.

**Step 5: Commit.**

```bash
git add src/amplifier_agent_lib/config/merger.py src/amplifier_agent_lib/config/__init__.py tests/config/test_merger.py
git commit -m "feat(config): merge_config() stub returning bundle unchanged when host is None (D5)"
```

---

### Task C2: Merge `mcp` block into the `tool-mcp` module config

**Files:**
- Modify: `src/amplifier_agent_lib/config/merger.py`
- Modify: `tests/config/test_merger.py`

**Step 1: Write the failing test.** Append:

```python
def test_merge_config_layers_mcp_block_over_tool_mcp_module() -> None:
    """host.mcp keys override bundle's tool-mcp config; absent keys keep bundle (D5)."""
    from amplifier_agent_lib.config import merge_config

    bundle_modules = {
        "tool-mcp": {
            "verbose_servers": False,
            "server_log_dir": "/bundle/default",
            "max_content_size": 50000,
        },
    }
    host_config = {
        "mcp": {
            "verbose_servers": True,            # overrides bundle
            "configPath": "/etc/host/mcp.json", # adds new key
            # server_log_dir + max_content_size omitted → bundle wins
        },
    }

    result = merge_config(bundle_modules=bundle_modules, host_config=host_config)

    assert result["tool-mcp"] == {
        "verbose_servers": True,
        "server_log_dir": "/bundle/default",
        "max_content_size": 50000,
        "configPath": "/etc/host/mcp.json",
    }
```

**Step 2: Run, watch it fail.**

```bash
uv run pytest tests/config/test_merger.py::test_merge_config_layers_mcp_block_over_tool_mcp_module -v
```

Expected: `NotImplementedError`.

**Step 3: Implement.**

Replace the `NotImplementedError` body of `merge_config` with:

```python
merged = copy.deepcopy(bundle_modules)

mcp_overrides = host_config.get("mcp")
if isinstance(mcp_overrides, dict):
    base = merged.get("tool-mcp", {})
    merged["tool-mcp"] = {**base, **mcp_overrides}

return merged
```

**Step 4: Run, watch it pass.**

```bash
uv run pytest tests/config/test_merger.py -v
```

Expected: 2 PASS.

**Step 5: Commit.**

```bash
git add src/amplifier_agent_lib/config/merger.py tests/config/test_merger.py
git commit -m "feat(config): merge host.mcp block into tool-mcp module config (D4, D5)"
```

---

### Task C3: Merge `approval` block into the `hooks-approval` module config

**Files:**
- Modify: `src/amplifier_agent_lib/config/merger.py`
- Modify: `tests/config/test_merger.py`

**Step 1: Write the failing test.** Append:

```python
def test_merge_config_layers_approval_block_over_hooks_approval_module() -> None:
    """host.approval keys override bundle's hooks-approval config (D5)."""
    from amplifier_agent_lib.config import merge_config

    bundle_modules = {
        "hooks-approval": {
            "patterns": ["rm -rf"],
            "auto_approve": False,
            "default_action": "deny",
            "policy_driven_only": False,
        },
    }
    host_config = {
        "approval": {
            "auto_approve": True,
            "patterns": ["sudo", "rm -rf /"],
        },
    }

    result = merge_config(bundle_modules=bundle_modules, host_config=host_config)

    assert result["hooks-approval"] == {
        "patterns": ["sudo", "rm -rf /"],
        "auto_approve": True,
        "default_action": "deny",
        "policy_driven_only": False,
    }
```

**Step 2: Run, watch it fail.**

```bash
uv run pytest tests/config/test_merger.py::test_merge_config_layers_approval_block_over_hooks_approval_module -v
```

Expected: FAILED (no `approval` handling yet).

**Step 3: Implement.**

Add to `merge_config` after the mcp block:

```python
approval_overrides = host_config.get("approval")
if isinstance(approval_overrides, dict):
    base = merged.get("hooks-approval", {})
    merged["hooks-approval"] = {**base, **approval_overrides}
```

**Step 4: Run, watch it pass.**

```bash
uv run pytest tests/config/test_merger.py -v
```

Expected: 3 PASS.

**Step 5: Commit.**

```bash
git add src/amplifier_agent_lib/config/merger.py tests/config/test_merger.py
git commit -m "feat(config): merge host.approval block into hooks-approval module (D4, D5)"
```

---

### Task C4: Merge `provider.config` into the selected provider module

**Files:**
- Modify: `src/amplifier_agent_lib/config/merger.py`
- Modify: `tests/config/test_merger.py`

**Step 1: Write the failing tests.** Append:

```python
def test_merge_config_uses_provider_module_field_to_pick_target(monkeypatch) -> None:
    """host.provider.module names which provider module receives the config (D4).

    The four valid module names map to four bundle keys:
      anthropic   → 'anthropic-provider'
      openai      → 'openai-provider'
      azure-openai → 'azure-openai-provider'
      ollama      → 'ollama-provider'
    """
    from amplifier_agent_lib.config import merge_config

    bundle_modules = {
        "anthropic-provider": {"default_model": "claude-sonnet-4-5", "max_tokens": 8192},
    }
    host_config = {
        "provider": {
            "module": "anthropic",
            "config": {"default_model": "claude-opus-4-5", "max_tokens": 16000},
        },
    }

    result = merge_config(bundle_modules=bundle_modules, host_config=host_config)

    assert result["anthropic-provider"] == {
        "default_model": "claude-opus-4-5",
        "max_tokens": 16000,
    }


def test_merge_config_provider_module_required_when_provider_block_present() -> None:
    """provider: {} with no `module` field is rejected by the merger contract.

    The merger is mechanism — it assumes the loader rejected this case.
    But guard defensively: if module is missing, fall through (no merge),
    leaving bundle's provider config intact.
    """
    from amplifier_agent_lib.config import merge_config

    bundle_modules = {"anthropic-provider": {"default_model": "claude-sonnet-4-5"}}
    host_config = {"provider": {"config": {"default_model": "claude-opus-4-5"}}}  # no module

    # Without a module name, the merger has nothing to target → bundle wins.
    result = merge_config(bundle_modules=bundle_modules, host_config=host_config)

    assert result["anthropic-provider"] == {"default_model": "claude-sonnet-4-5"}
```

**Step 2: Run, watch them fail.**

```bash
uv run pytest tests/config/test_merger.py::test_merge_config_uses_provider_module_field_to_pick_target tests/config/test_merger.py::test_merge_config_provider_module_required_when_provider_block_present -v
```

Expected: first FAILED (no provider merge), second probably passes by accident (bundle unchanged).

**Step 3: Implement.**

Add to `merger.py` at module scope:

```python
_PROVIDER_NAME_TO_MODULE_KEY = {
    "anthropic": "anthropic-provider",
    "openai": "openai-provider",
    "azure-openai": "azure-openai-provider",
    "ollama": "ollama-provider",
}
```

And inside `merge_config`, after the approval block:

```python
provider_block = host_config.get("provider")
if isinstance(provider_block, dict):
    provider_module = provider_block.get("module")
    provider_config = provider_block.get("config")
    if (
        isinstance(provider_module, str)
        and provider_module in _PROVIDER_NAME_TO_MODULE_KEY
        and isinstance(provider_config, dict)
    ):
        module_key = _PROVIDER_NAME_TO_MODULE_KEY[provider_module]
        base = merged.get(module_key, {})
        merged[module_key] = {**base, **provider_config}
```

**Step 4: Run, watch them pass.**

```bash
uv run pytest tests/config/test_merger.py -v
```

Expected: 5 PASS.

**Step 5: Commit.**

```bash
git add src/amplifier_agent_lib/config/merger.py tests/config/test_merger.py
git commit -m "feat(config): merge host.provider.config into selected provider module (D4, D5)"
```

---

### Task C5: Surface `allowProtocolSkew` from the merged config

**Files:**
- Modify: `src/amplifier_agent_lib/config/merger.py`
- Modify: `tests/config/test_merger.py`

`allowProtocolSkew` is the one top-level key that is NOT a module pass-through — it's engine-level. The merger surfaces it as a separate return field so `_runtime`/`engine.boot` can read it without re-parsing.

**Step 1: Write the failing test.** Append:

```python
def test_merge_config_returns_allow_protocol_skew_flag() -> None:
    """merge_config exposes the host's allowProtocolSkew choice (engine-level, D4)."""
    from amplifier_agent_lib.config import merge_config

    host = {"allowProtocolSkew": True}
    result, allow_skew = merge_config_with_skew(bundle_modules={}, host_config=host)

    assert allow_skew is True


def test_merge_config_skew_defaults_to_false() -> None:
    """When the key is absent, allow_skew is False."""
    from amplifier_agent_lib.config import merge_config

    result, allow_skew = merge_config_with_skew(bundle_modules={}, host_config={})

    assert allow_skew is False
```

NOTE: We need a helper `merge_config_with_skew` because `merge_config`'s return signature is the modules dict only. Implement `merge_config_with_skew` as the public API and keep `merge_config` as the modules-only shorthand. Update both test stubs by replacing `merge_config_with_skew` with `from amplifier_agent_lib.config import merge_config_with_skew` after Step 3 is done. **Actually**, prefer the simpler design: change `merge_config` to return a `(modules, allow_skew)` tuple. Update the three earlier tests in `tests/config/test_merger.py` accordingly — replace `result = merge_config(...)` with `result, _allow_skew = merge_config(...)`. This is the simpler, single-return-shape design.

Rewrite the two tests above to use the unified signature:

```python
def test_merge_config_returns_allow_protocol_skew_flag() -> None:
    from amplifier_agent_lib.config import merge_config

    _modules, allow_skew = merge_config(bundle_modules={}, host_config={"allowProtocolSkew": True})
    assert allow_skew is True


def test_merge_config_skew_defaults_to_false() -> None:
    from amplifier_agent_lib.config import merge_config

    _modules, allow_skew = merge_config(bundle_modules={}, host_config={})
    assert allow_skew is False
```

Also update the previous merger tests (C1–C4) to unpack the tuple. The C1 test becomes:

```python
result, _ = merge_config(bundle_modules=bundle_modules, host_config=None)
```

etc. Apply this to all merger tests in one edit.

**Step 2: Run, watch them fail.**

```bash
uv run pytest tests/config/test_merger.py -v
```

Expected: previous tests now FAIL (signature mismatch) plus the new two FAIL (no allow_skew return yet).

**Step 3: Implement.**

Change `merge_config`'s return type annotation and body:

```python
def merge_config(
    *,
    bundle_modules: dict[str, dict[str, Any]],
    host_config: dict[str, Any] | None,
) -> tuple[dict[str, dict[str, Any]], bool]:
    """Returns (merged_modules, allow_protocol_skew)."""
    if host_config is None:
        return copy.deepcopy(bundle_modules), False

    merged = copy.deepcopy(bundle_modules)
    # ... existing mcp / approval / provider merges unchanged ...

    allow_skew = bool(host_config.get("allowProtocolSkew", False))
    return merged, allow_skew
```

**Step 4: Run, watch them pass.**

```bash
uv run pytest tests/config/test_merger.py -v
```

Expected: 7 PASS.

**Step 5: Commit.**

```bash
git add src/amplifier_agent_lib/config/merger.py tests/config/test_merger.py
git commit -m "feat(config): return allowProtocolSkew from merge_config (D4 engine-level key)"
```

---

### Task C6: Loader-side validation of `provider.module` value

**Files:**
- Modify: `src/amplifier_agent_lib/config/loader.py`
- Modify: `tests/config/test_loader.py`

The merger silently falls through on invalid `provider.module` (defensive). The loader catches it loudly so the operator sees the error at parse time, not as a silent no-op.

**Step 1: Write the failing test.** Append to `tests/config/test_loader.py`:

```python
_VALID_PROVIDER_MODULES = {"anthropic", "openai", "azure-openai", "ollama"}


def test_load_config_rejects_unknown_provider_module(tmp_path, monkeypatch) -> None:
    """provider.module not in the four supported values → ConfigError (A3, D7)."""
    monkeypatch.delenv("AMPLIFIER_AGENT_CONFIG", raising=False)

    cfg_path = tmp_path / "bad-provider.json"
    cfg_path.write_text('{"provider": {"module": "auto"}}', encoding="utf-8")

    from amplifier_agent_lib.config import ConfigError, load_config

    with pytest.raises(ConfigError) as exc_info:
        load_config(config_arg=str(cfg_path))

    assert exc_info.value.code == "config_invalid_provider_module"
    assert "auto" in exc_info.value.message
    for valid in _VALID_PROVIDER_MODULES:
        assert valid in exc_info.value.message


def test_load_config_accepts_each_valid_provider_module(tmp_path, monkeypatch) -> None:
    """Each of the four valid module names parses cleanly."""
    monkeypatch.delenv("AMPLIFIER_AGENT_CONFIG", raising=False)
    from amplifier_agent_lib.config import load_config

    for valid in _VALID_PROVIDER_MODULES:
        cfg = tmp_path / f"{valid}.json"
        cfg.write_text(f'{{"provider": {{"module": "{valid}"}}}}', encoding="utf-8")
        assert load_config(config_arg=str(cfg)) == {"provider": {"module": valid}}
```

**Step 2: Run, watch them fail/pass.**

```bash
uv run pytest tests/config/test_loader.py::test_load_config_rejects_unknown_provider_module tests/config/test_loader.py::test_load_config_accepts_each_valid_provider_module -v
```

Expected: first FAILED, second PASS.

**Step 3: Implement.**

In `loader.py`, add at module scope:

```python
_VALID_PROVIDER_MODULES = frozenset({"anthropic", "openai", "azure-openai", "ollama"})
```

And add a validator function, calling it after the approval-pattern validator:

```python
_validate_provider_module(parsed.get("provider"), path)
```

```python
def _validate_provider_module(provider_block: Any, path: Path) -> None:
    """provider.module (if present) must be one of the four supported modules (A3)."""
    if not isinstance(provider_block, dict):
        return
    module = provider_block.get("module")
    if module is None:
        return  # bundle's default_provider applies (D6)
    if module not in _VALID_PROVIDER_MODULES:
        raise ConfigError(
            code="config_invalid_provider_module",
            message=(
                f"provider.module at {path} must be one of "
                f"{sorted(_VALID_PROVIDER_MODULES)}, got {module!r}."
            ),
            classification="protocol",
        )
```

**Step 4: Run, watch them pass.**

```bash
uv run pytest tests/config/test_loader.py -v
```

Expected: 16 PASS.

**Step 5: Commit.**

```bash
git add src/amplifier_agent_lib/config/loader.py tests/config/test_loader.py
git commit -m "feat(config): validate provider.module is one of the four supported (A3, D7)"
```

---

## Section D — Bundle and runtime integration

These tasks connect the loader/merger to the CLI and the bundle mount path.

### Task D1: Add `default_provider:` field to vendored `bundle.md`

**Files:**
- Modify: `src/amplifier_agent_lib/bundle/bundle.md`
- Create: `tests/test_bundle_default_provider.py`

**Step 1: Write the failing test.** Create `tests/test_bundle_default_provider.py`:

```python
"""Tests for the bundle's default_provider field (D6).

Per design D6 bundle.md must declare default_provider; current behavior
maps to 'anthropic'.
"""

from __future__ import annotations

import yaml

from amplifier_agent_lib.bundle import BUNDLE_MD


def test_bundle_md_declares_default_provider_anthropic() -> None:
    """bundle.md top-level YAML frontmatter has default_provider: anthropic (D6)."""
    text = BUNDLE_MD.read_text(encoding="utf-8")
    parts = text.split("---\n")
    assert len(parts) >= 3, "bundle.md must have YAML frontmatter"

    manifest = yaml.safe_load(parts[1])
    assert isinstance(manifest, dict)
    assert manifest.get("default_provider") == "anthropic", (
        "bundle.md must declare default_provider: anthropic (D6)"
    )
```

**Step 2: Run, watch it fail.**

```bash
uv run pytest tests/test_bundle_default_provider.py -v
```

Expected: FAILED (key absent).

**Step 3: Implement.**

Edit `src/amplifier_agent_lib/bundle/bundle.md`. Add a top-level YAML key inside the frontmatter. Place it right after the closing of the `bundle:` block and before `session:`:

```yaml
default_provider: anthropic
```

The frontmatter section starts at line 1 (after `---`) and the `bundle:` block is the first key. Insert `default_provider: anthropic` as a sibling top-level key (same indentation as `bundle:`, `session:`, `tools:`).

**Step 4: Run, watch it pass.**

```bash
uv run pytest tests/test_bundle_default_provider.py -v
```

Expected: PASS.

**Step 5: Commit.**

```bash
git add src/amplifier_agent_lib/bundle/bundle.md tests/test_bundle_default_provider.py
git commit -m "feat(bundle): add default_provider: anthropic to vendored bundle.md (D6)"
```

---

### Task D2: Wire `--config` flag into `single_turn.py` and propagate to `_TurnSpec`

**Files:**
- Modify: `src/amplifier_agent_cli/modes/single_turn.py`
- Modify: `tests/cli/test_single_turn.py` (add one test)

**Step 1: Write the failing test.** Append to `tests/cli/test_single_turn.py`:

```python
def test_run_loads_config_and_forwards_to_spec(tmp_path, monkeypatch):
    """`amplifier-agent run --config <path>` calls load_config(<path>).

    Spec assertion: load_config is called with the flag's value.
    """
    from unittest.mock import patch
    from click.testing import CliRunner
    from amplifier_agent_cli.__main__ import cli

    cfg = tmp_path / "host.json"
    cfg.write_text('{"mcp": {"verbose_servers": true}}', encoding="utf-8")

    captured = {}

    def _fake_load_config(config_arg):
        captured["arg"] = config_arg
        return {"mcp": {"verbose_servers": True}}

    runner = CliRunner()
    with (
        patch("amplifier_agent_cli.modes.single_turn.load_config", _fake_load_config),
        patch("amplifier_agent_cli.modes.single_turn._execute_turn") as mock_exec,
    ):
        mock_exec.return_value = {"reply": "ok", "turnId": "turn-1", "sessionId": ""}
        result = runner.invoke(
            cli,
            ["run", "--config", str(cfg), "hello"],
            env={"ANTHROPIC_API_KEY": "sk-test"},
        )

    assert result.exit_code == 0, result.output
    assert captured.get("arg") == str(cfg), f"load_config not called with --config value: {captured}"
```

**Step 2: Run, watch it fail.**

```bash
uv run pytest tests/cli/test_single_turn.py::test_run_loads_config_and_forwards_to_spec -v
```

Expected: FAILED — `ImportError` or `AttributeError` (load_config not yet imported in single_turn).

**Step 3: Implement.**

Edit `src/amplifier_agent_cli/modes/single_turn.py`:

1. Add import: `from amplifier_agent_lib.config import ConfigError, load_config`.
2. In the `_TurnSpec` dataclass, add: `host_config: dict | None = None`.
3. In `run()` after the existing `mcp_config_path` validation (around line 538), add the config-resolution block. Important: this MUST happen before `_execute_turn` is called so `_TurnSpec` carries the parsed dict:

```python
# (5e) Resolve host config (D1, D2, D3, D7). Raises ConfigError → caught
# by the AaaError envelope path below (ConfigError subclasses AaaError).
try:
    host_config = load_config(config_arg=config_path)
except ConfigError as exc:
    # Emit the §4.1 envelope and exit 2 per D2 / D7. The classification
    # 'protocol' maps to exit code 2 in _EXIT_CODE_BY_CLASSIFICATION.
    _emit_argv_envelope(exc.code, exc.message, exit_code=2)
    return
```

4. Add `host_config=host_config` to the `_TurnSpec(...)` call in step (6).

`_emit_argv_envelope` already calls `sys.exit(exit_code)` internally — verify by reading lines 100–110 of single_turn.py. If it does not, replace the call with `_emit_argv_envelope(...)` + `sys.exit(2)`.

**Step 4: Run, watch it pass.**

```bash
uv run pytest tests/cli/test_single_turn.py::test_run_loads_config_and_forwards_to_spec -v
```

Expected: PASS.

**Step 5: Commit.**

```bash
git add src/amplifier_agent_cli/modes/single_turn.py tests/cli/test_single_turn.py
git commit -m "feat(cli): wire --config flag → load_config → _TurnSpec (D1)"
```

---

### Task D3: Plumb `host_config` from `_TurnSpec` through to `_runtime` and the merger

**Files:**
- Modify: `src/amplifier_agent_cli/modes/single_turn.py`
- Modify: `src/amplifier_agent_lib/_runtime.py`
- Create: `tests/test_runtime_config_merge.py`

**Step 1: Write the failing test.** Create `tests/test_runtime_config_merge.py`:

```python
"""Tests that host_config flows through _runtime.make_turn_handler to the bundle mount.

Per D5 the layered merge applies at bundle-mount time, before sessions spawn.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from amplifier_agent_lib._runtime import make_turn_handler


def test_make_turn_handler_accepts_host_config_kwarg() -> None:
    """make_turn_handler must accept host_config and call merge_config()."""
    fake_prepared = MagicMock()
    fake_prepared.mount_plan = {"agents": {}}

    # Should not raise — host_config is an accepted keyword.
    handler = make_turn_handler(
        fake_prepared,
        cwd=None,
        is_resumed=False,
        host_config=None,
    )
    assert callable(handler)


def test_make_turn_handler_calls_merge_config_when_host_present(monkeypatch) -> None:
    """When host_config is not None, _runtime calls config.merge_config()."""
    from amplifier_agent_lib import _runtime

    fake_prepared = MagicMock()
    fake_prepared.mount_plan = {"agents": {}, "tool-mcp": {"verbose_servers": False}}

    captured = {}

    def _fake_merge(*, bundle_modules, host_config):
        captured["bundle_modules"] = bundle_modules
        captured["host_config"] = host_config
        return bundle_modules, False

    monkeypatch.setattr(_runtime, "merge_config", _fake_merge)

    handler = make_turn_handler(
        fake_prepared,
        cwd=None,
        is_resumed=False,
        host_config={"mcp": {"verbose_servers": True}},
    )

    assert captured.get("host_config") == {"mcp": {"verbose_servers": True}}
    assert callable(handler)
```

**Step 2: Run, watch it fail.**

```bash
uv run pytest tests/test_runtime_config_merge.py -v
```

Expected: FAILED — `make_turn_handler` does not accept `host_config`.

**Step 3: Implement.**

Edit `src/amplifier_agent_lib/_runtime.py`:

1. Add import: `from amplifier_agent_lib.config import merge_config`.
2. Change the `make_turn_handler` signature to add `host_config: dict[str, Any] | None = None`.
3. Near the top of the function body (before agent_configs construction), add the merge:

```python
# Layered merge of host config over bundle module configs (D5).
# merge_config is mechanism — it never mutates `prepared.mount_plan`;
# instead it produces a merged-modules dict that the caller threads into
# the per-module mount step. For the present milestone we surface the
# merged config via the prepared.mount_plan in-place for forward compat:
# tool-mcp / hooks-approval / provider modules read from the same plan.
merged_modules, _allow_skew = merge_config(
    bundle_modules=dict(prepared.mount_plan or {}),
    host_config=host_config,
)
# Mutate mount_plan in-place so foundation's mount logic sees the merged
# values. The deep-copy in merge_config protects against accidental
# bundle mutation; we only write our copy back into mount_plan.
if prepared.mount_plan is not None:
    prepared.mount_plan.update({
        k: v for k, v in merged_modules.items() if k != "agents"
    })
```

4. Edit `src/amplifier_agent_cli/modes/single_turn.py` `_execute_turn` (around line 356) to pass `host_config=spec.host_config` to `make_turn_handler`.

**Step 4: Run, watch it pass.**

```bash
uv run pytest tests/test_runtime_config_merge.py -v
```

Expected: 2 PASS.

**Step 5: Commit.**

```bash
git add src/amplifier_agent_lib/_runtime.py src/amplifier_agent_cli/modes/single_turn.py tests/test_runtime_config_merge.py
git commit -m "feat(runtime): thread host_config through _runtime → merge_config → mount_plan (D5)"
```

---

### Task D4: Remove `provider_detect.detect_provider()` call from `single_turn.py`, fall back to bundle `default_provider`

**Files:**
- Modify: `src/amplifier_agent_cli/modes/single_turn.py`
- Create: `tests/cli/test_default_provider_fallback.py`

**Step 1: Write the failing test.** Create `tests/cli/test_default_provider_fallback.py`:

```python
"""When no --provider flag and no host config provider block, the bundle's
default_provider applies (D6). detect_provider() must not be called."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from click.testing import CliRunner

from amplifier_agent_cli.__main__ import cli


def test_run_uses_bundle_default_provider_when_no_override(monkeypatch):
    """Absent --provider flag + absent config provider → bundle default (anthropic)."""
    # Strip provider env vars so the (now-dead) detect_provider path would fail.
    for var in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "AZURE_OPENAI_API_KEY",
                "AZURE_OPENAI_KEY", "OLLAMA_HOST"):
        monkeypatch.delenv(var, raising=False)

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")  # provider module needs this

    captured = {}

    async def _fake_exec(spec):
        captured["provider"] = spec.provider
        return {"reply": "ok", "turnId": "turn-1", "sessionId": ""}

    with patch("amplifier_agent_cli.modes.single_turn._execute_turn", _fake_exec):
        runner = CliRunner()
        result = runner.invoke(cli, ["run", "hello"], catch_exceptions=False)

    assert result.exit_code == 0, result.output
    assert captured.get("provider") == "anthropic", (
        f"expected bundle default 'anthropic', got {captured.get('provider')!r}"
    )
```

**Step 2: Run, watch it fail.**

```bash
uv run pytest tests/cli/test_default_provider_fallback.py -v
```

Expected: pre-existing `detect_provider()` works (env has anthropic key), so this would actually pass — but the goal is that even WITHOUT env vars the bundle default applies. Tighten by removing the env-key setter and re-running:

Edit the test: also remove the `monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")` line and rerun. Expected: FAILED with `provider_not_configured` (current behavior calls `detect_provider`).

**Step 3: Implement.**

Edit `src/amplifier_agent_cli/modes/single_turn.py`:

1. Add a helper to read bundle's `default_provider`:

```python
def _read_bundle_default_provider() -> str:
    """Read bundle.md's top-level default_provider field (D6)."""
    import yaml
    from amplifier_agent_lib.bundle import BUNDLE_MD
    text = BUNDLE_MD.read_text(encoding="utf-8")
    parts = text.split("---\n")
    manifest = yaml.safe_load(parts[1]) or {}
    default = manifest.get("default_provider")
    if not isinstance(default, str):
        raise AaaError(
            code="bundle_load_failed",
            message=(
                "bundle.md missing required `default_provider:` top-level field. "
                "This is a bundle integrity error (D6); reinstall amplifier-agent."
            ),
            classification="protocol",
        )
    return default
```

2. Replace the existing provider-resolution block (lines 515–520) with:

```python
# (4) Provider resolution: --provider flag > host.provider.module > bundle default_provider.
# detect_provider() is removed per D6; provider selection no longer sniffs env vars.
if provider_override is not None:
    provider_name = provider_override
elif isinstance(host_config, dict) and isinstance(host_config.get("provider"), dict):
    provider_name = host_config["provider"].get("module") or _read_bundle_default_provider()
else:
    provider_name = _read_bundle_default_provider()
```

Note: this block needs to run AFTER the `host_config = load_config(...)` call from D2 (which is at section 5e). Re-order so config resolution happens before provider resolution. Move the `host_config = load_config(...)` block to just before the provider-resolution block (i.e. before section 4).

3. Keep the `from amplifier_agent_cli.provider_detect import ProviderNotConfigured, detect_provider` import for now (E5 will delete it). Drop the `try / except ProviderNotConfigured` since the new path can no longer raise that exception.

**Step 4: Run, watch it pass.**

```bash
uv run pytest tests/cli/test_default_provider_fallback.py -v
uv run pytest tests/cli/test_single_turn.py -v
```

Expected: new test PASS. Existing single_turn tests may FAIL where they assumed `detect_provider` was on the path — review failures and adjust: tests that patched `detect_provider` should now either (a) be deleted (E5 territory) or (b) patch `_read_bundle_default_provider` instead. For now, mark expected-broken single_turn tests with `pytest.mark.skip(reason="moved to E5: detect_provider removal")` rather than rewriting; the cleanup batch in Section E will resolve them.

**Step 5: Commit.**

```bash
git add src/amplifier_agent_cli/modes/single_turn.py tests/cli/test_default_provider_fallback.py
git commit -m "feat(cli): provider selection from config / bundle default; drop detect_provider call (D6)"
```

---

## Section E — Argv flag and env var cleanup

These five tasks remove the surfaces that the config layer subsumes. They land together — no surface should be silently duplicated mid-implementation (per the design's §8 ordering note).

### Task E1: Drop `--env-allowlist` argv flag

**Files:**
- Modify: `src/amplifier_agent_cli/modes/single_turn.py`
- Modify: `tests/cli/test_single_turn.py` (add a "flag is gone" test)

**Step 1: Write the failing test.** Append to `tests/cli/test_single_turn.py`:

```python
def test_env_allowlist_flag_is_removed() -> None:
    """--env-allowlist is removed (D10). Invoking with the flag must fail."""
    from click.testing import CliRunner
    from amplifier_agent_cli.__main__ import cli

    runner = CliRunner()
    result = runner.invoke(cli, ["run", "--env-allowlist", "PATH", "hello"])

    assert result.exit_code != 0
    assert "no such option" in result.output.lower() or "no such option" in str(result.exception).lower()
```

**Step 2: Run, watch it fail.**

```bash
uv run pytest tests/cli/test_single_turn.py::test_env_allowlist_flag_is_removed -v
```

Expected: FAILED (flag still defined at line 441).

**Step 3: Implement.**

Edit `src/amplifier_agent_cli/modes/single_turn.py`:

1. Remove the `@click.option("--env-allowlist", ...)` decorator (around lines 440–445).
2. Remove the `env_allowlist_raw: str | None` parameter from `def run(...)`.
3. Remove the line `env_allowlist = [k.strip() for k in env_allowlist_raw.split(",") ...]` (around line 545).
4. Remove `env_allowlist=env_allowlist` from the three `_write_audit(...)` call sites (or replace with `env_allowlist=None` if the helper requires the kwarg — check the function signature first).

Also delete any audit log fields and downstream references that expected the value.

**Step 4: Run, watch it pass.**

```bash
uv run pytest tests/cli/test_single_turn.py::test_env_allowlist_flag_is_removed -v
```

Expected: PASS.

**Step 5: Commit.**

```bash
git add src/amplifier_agent_cli/modes/single_turn.py tests/cli/test_single_turn.py
git commit -m "feat(cli)!: drop --env-allowlist argv flag, subsumed by host config (D10)"
```

---

### Task E2: Drop `--env-extra` argv flag

**Files:**
- Modify: `src/amplifier_agent_cli/modes/single_turn.py`
- Modify: `tests/cli/test_single_turn.py`

**Step 1: Write the failing test.** Append:

```python
def test_env_extra_flag_is_removed() -> None:
    """--env-extra is removed (D10)."""
    from click.testing import CliRunner
    from amplifier_agent_cli.__main__ import cli

    runner = CliRunner()
    result = runner.invoke(cli, ["run", "--env-extra", "{}", "hello"])

    assert result.exit_code != 0
    assert "no such option" in result.output.lower() or "no such option" in str(result.exception).lower()
```

**Step 2: Run, watch it fail.**

```bash
uv run pytest tests/cli/test_single_turn.py::test_env_extra_flag_is_removed -v
```

Expected: FAILED.

**Step 3: Implement.**

Same shape as E1: delete the `@click.option("--env-extra", ...)` decorator (lines 446–451), the `env_extra_raw` parameter, the `env_extra = _parse_json_or_atpath(...)` line, and any `env_extra=...` kwargs at audit call sites.

**Step 4: Run, watch it pass.**

```bash
uv run pytest tests/cli/test_single_turn.py::test_env_extra_flag_is_removed -v
```

Expected: PASS.

**Step 5: Commit.**

```bash
git add src/amplifier_agent_cli/modes/single_turn.py tests/cli/test_single_turn.py
git commit -m "feat(cli)!: drop --env-extra argv flag, subsumed by host config (D10)"
```

---

### Task E3: Drop `--allow-protocol-skew` argv flag

**Files:**
- Modify: `src/amplifier_agent_cli/modes/single_turn.py`
- Modify: `tests/cli/test_single_turn.py`
- Modify: `tests/cli/test_mode_a_v2_envelope.py` (existing test uses the flag; rewrite it)

**Step 1: Write the failing test.** Append to `tests/cli/test_single_turn.py`:

```python
def test_allow_protocol_skew_flag_is_removed() -> None:
    """--allow-protocol-skew is removed (D10). Behavior moves to config key."""
    from click.testing import CliRunner
    from amplifier_agent_cli.__main__ import cli

    runner = CliRunner()
    result = runner.invoke(cli, ["run", "--allow-protocol-skew", "hello"])

    assert result.exit_code != 0
    assert "no such option" in result.output.lower() or "no such option" in str(result.exception).lower()
```

**Step 2: Run, watch it fail.**

```bash
uv run pytest tests/cli/test_single_turn.py::test_allow_protocol_skew_flag_is_removed -v
```

Expected: FAILED.

**Step 3: Implement.**

1. Delete the `@click.option("--allow-protocol-skew", ...)` decorator (lines 427–433).
2. Delete the `allow_protocol_skew: bool` parameter from `run()`.
3. In `_TurnSpec`, replace `allow_protocol_skew: bool = False` with the value sourced from the merged config: `allow_protocol_skew` becomes derived from `host_config.get("allowProtocolSkew", False)`.
4. Inside `run()`, replace the line that built `allow_protocol_skew=allow_protocol_skew or bool(os.environ.get(...))` with `allow_protocol_skew=bool((host_config or {}).get("allowProtocolSkew", False))`.
5. Delete the protocol_version self-validation block (lines 547–558) that referenced `allow_protocol_skew` from argv — replace with the same check sourced from the config dict:

```python
if protocol_version_arg and not bool((host_config or {}).get("allowProtocolSkew", False)):
    if protocol_version_arg != PROTOCOL_VERSION:
        _emit_argv_envelope(
            "protocol_version_mismatch",
            f"Wrapper expects protocol {protocol_version_arg}, engine compiled with {PROTOCOL_VERSION}.",
            remediation=(
                "To force, set `allowProtocolSkew: true` in your --config file (unsafe) "
                "or reinstall both: "
                "`uv tool install --reinstall amplifier-agent` and "
                "`npm install amplifier-agent-client-ts@latest`."
            ),
        )
```

6. Edit `tests/cli/test_mode_a_v2_envelope.py:203` — the test asserts the flag is accepted. Rewrite it to use a temp config file with `allowProtocolSkew: true` instead:

```python
def test_mode_a_envelope_allowprotocolskew_via_config(tmp_path):
    """allowProtocolSkew: true in config bypasses version check (D10 replaces argv flag)."""
    cfg = tmp_path / "skew.json"
    cfg.write_text('{"allowProtocolSkew": true}', encoding="utf-8")
    # ... rest of the test, replacing ["--allow-protocol-skew"] with ["--config", str(cfg)]
```

(Use the existing test body as a template; only the flag→config substitution changes.)

**Step 4: Run, watch them pass.**

```bash
uv run pytest tests/cli/test_single_turn.py::test_allow_protocol_skew_flag_is_removed tests/cli/test_mode_a_v2_envelope.py -v
```

Expected: PASS.

**Step 5: Commit.**

```bash
git add src/amplifier_agent_cli/modes/single_turn.py tests/cli/test_single_turn.py tests/cli/test_mode_a_v2_envelope.py
git commit -m "feat(cli)!: drop --allow-protocol-skew flag, behavior moves to config (D10)"
```

---

### Task E4: Drop `AMPLIFIER_AGENT_ALLOW_PROTOCOL_SKEW` env var

**Files:**
- Modify: `src/amplifier_agent_lib/engine.py`
- Modify: `src/amplifier_agent_cli/modes/single_turn.py`
- Modify: `tests/test_engine_version_skew.py`

**Step 1: Write the failing test.** Append to `tests/test_engine_version_skew.py`:

```python
@pytest.mark.asyncio
async def test_boot_no_longer_honors_amplifier_agent_allow_protocol_skew_env(monkeypatch):
    """AMPLIFIER_AGENT_ALLOW_PROTOCOL_SKEW env var is removed (D10).

    The only allow-skew path is allowProtocolSkew=True in init_params,
    which comes from the host config file's allowProtocolSkew key.
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
```

**Step 2: Run, watch it fail.**

```bash
uv run pytest tests/test_engine_version_skew.py::test_boot_no_longer_honors_amplifier_agent_allow_protocol_skew_env -v
```

Expected: FAILED (env var still honored at line 151 of engine.py — boot succeeds, no AaaError).

**Step 3: Implement.**

1. Edit `src/amplifier_agent_lib/engine.py`:
   - Line 150–152: remove the `or bool(os.environ.get("AMPLIFIER_AGENT_ALLOW_PROTOCOL_SKEW"))`.
   - Line 163 (remediation message): drop the `AMPLIFIER_AGENT_ALLOW_PROTOCOL_SKEW=1` mention. Replace the remediation text with: `allowProtocolSkew: true in the host config file (--config)`.
   - If `import os` is now unused in engine.py, delete it.

2. Edit `src/amplifier_agent_cli/modes/single_turn.py`:
   - Around line 548: remove the `os.environ.get("AMPLIFIER_AGENT_ALLOW_PROTOCOL_SKEW")` clause from the protocol-version self-validation. After E3 you already replaced this with `(host_config or {}).get("allowProtocolSkew", False)`; double-check no env-var reference remains.
   - Around line 570: same cleanup if any reference remains in `_TurnSpec` construction.

3. Update the existing `tests/test_engine_version_skew.py` `test_boot_refuses_protocol_version_mismatch` assertion at line 76: the message no longer contains `--allow-protocol-skew`. Change the assertion to check for `allowProtocolSkew` (the config key) instead.

**Step 4: Run, watch it pass.**

```bash
uv run pytest tests/test_engine_version_skew.py -v
```

Expected: all PASS.

**Step 5: Commit.**

```bash
git add src/amplifier_agent_lib/engine.py src/amplifier_agent_cli/modes/single_turn.py tests/test_engine_version_skew.py
git commit -m "feat(engine)!: drop AMPLIFIER_AGENT_ALLOW_PROTOCOL_SKEW env var (D10)"
```

---

### Task E5: Delete `provider_detect.py` and clean up all callers

**Files:**
- Delete: `src/amplifier_agent_cli/provider_detect.py`
- Delete: `tests/cli/test_provider_detect.py`
- Modify: `src/amplifier_agent_cli/modes/single_turn.py`
- Modify: `src/amplifier_agent_cli/admin/config_show.py`
- Modify: `src/amplifier_agent_cli/admin/doctor.py`
- Modify: `src/amplifier_agent_cli/provider_sources.py` (if it imports provider_detect)
- Modify: `tests/cli/test_provider_sources.py`
- Modify: `tests/cli/test_single_turn.py`
- Modify: `tests/cli/test_single_turn_init_params.py`
- Modify: `tests/cli/test_mode_a_audit_trail.py`
- Modify: `tests/cli/test_mode_a_stdout_discipline.py`

**Step 1: Write the failing test.** Create `tests/cli/test_provider_detect_removed.py`:

```python
"""provider_detect.py is deleted per D6 (vestigial under config layer)."""

import importlib

import pytest


def test_provider_detect_module_no_longer_importable():
    """amplifier_agent_cli.provider_detect must not exist."""
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("amplifier_agent_cli.provider_detect")
```

**Step 2: Run, watch it fail.**

```bash
uv run pytest tests/cli/test_provider_detect_removed.py -v
```

Expected: FAILED — module imports fine.

**Step 3: Implement.**

1. Delete the file: `rm src/amplifier_agent_cli/provider_detect.py`.
2. Delete `tests/cli/test_provider_detect.py`.
3. Edit `src/amplifier_agent_cli/modes/single_turn.py`: remove the line `from amplifier_agent_cli.provider_detect import ProviderNotConfigured, detect_provider`. After D4 these symbols are no longer referenced; grep to confirm.
4. Edit `src/amplifier_agent_cli/admin/config_show.py`: the file imports `_DETECTION_ORDER` and `detect_provider` from provider_detect. Replace `_resolve_provider()` with a simpler implementation that reports the bundle's `default_provider`:

```python
import yaml
from amplifier_agent_lib.bundle import BUNDLE_MD


def _resolve_provider() -> dict[str, Any]:
    """Return the bundle's default_provider with source='bundle.default_provider' (D6)."""
    try:
        manifest = yaml.safe_load(BUNDLE_MD.read_text(encoding="utf-8").split("---\n")[1])
    except Exception:
        return {"value": None, "source": "error"}
    default = manifest.get("default_provider")
    if isinstance(default, str):
        return {"value": default, "source": "bundle.default_provider"}
    return {"value": None, "source": "unset"}
```

   And delete the two `from amplifier_agent_cli.provider_detect import ...` lines.

5. Edit `src/amplifier_agent_cli/admin/doctor.py`: the `_check_provider()` function imports `detect_provider` and is no longer meaningful (provider selection no longer sniffs env vars). Replace its body with a check that the bundle declares `default_provider`:

```python
def _check_provider() -> tuple[bool, str]:
    """Return (True, OK) if bundle.md declares default_provider (D6)."""
    import yaml
    from amplifier_agent_lib.bundle import BUNDLE_MD
    try:
        manifest = yaml.safe_load(BUNDLE_MD.read_text(encoding="utf-8").split("---\n")[1])
    except Exception as exc:
        return (False, f"{_FAIL} bundle default_provider: parse failed ({exc.__class__.__name__})")
    default = manifest.get("default_provider")
    if isinstance(default, str):
        return (True, f"{_OK} bundle default_provider: {default}")
    return (False, f"{_FAIL} bundle default_provider: missing in bundle.md (D6)")
```

   And remove the import `from amplifier_agent_cli.provider_detect import ProviderNotConfigured, detect_provider`.

6. Edit `src/amplifier_agent_cli/provider_sources.py` — grep for `provider_detect` references and replace with a hard-coded list of the four supported providers (matches A3). Tests in `tests/cli/test_provider_sources.py:27` import `KNOWN_PROVIDERS` from provider_detect; replace with a local constant in provider_sources.py:

```python
KNOWN_PROVIDERS: Final[tuple[str, ...]] = ("anthropic", "openai", "azure-openai", "ollama")
```

7. Edit all listed test files: replace `patch("amplifier_agent_cli.provider_detect.detect_provider", ...)` with appropriate replacements. In most cases the test should be simplified to not need the patch at all (the new provider-selection path is config + bundle-default). For each test:
   - If it asserts `detect_provider` behavior — delete the test (logic gone with D6).
   - If it patches `detect_provider` to inject a provider — replace with `patch("amplifier_agent_cli.modes.single_turn._read_bundle_default_provider", return_value="anthropic")`.

8. Run a global grep to confirm zero references remain:

```bash
grep -rn "provider_detect\|detect_provider\|ProviderNotConfigured" src/ tests/
```

Expected: zero matches.

**Step 4: Run, watch it pass.**

```bash
uv run pytest tests/cli/test_provider_detect_removed.py -v
uv run pytest -x -q 2>&1 | tail -10
```

Expected: removal test PASS. Full suite should also pass; failures point at additional cleanup sites missed above — fix them and re-run before commit.

**Step 5: Commit.**

```bash
git add -A
git commit -m "feat(cli)!: delete provider_detect.py and all callers; provider from config/bundle (D6)"
```

---

## Section F — `config show` extension

`config show` is the 2am operator affordance. Per D8 it must report the resolved config path, the resolution source, parsed values, AND remain functional when the file fails to parse.

### Task F1: Report `--config` flag source in `config show`

**Files:**
- Modify: `src/amplifier_agent_cli/admin/config_show.py`
- Modify: `tests/cli/test_config_show.py`

**Step 1: Write the failing test.** Append:

```python
def test_config_show_reports_flag_resolution_source(runner, tmp_path, monkeypatch) -> None:
    """`config show --config <path>` reports source='--config flag' (D8)."""
    cfg = tmp_path / "host.json"
    cfg.write_text('{"mcp": {"verbose_servers": true}}', encoding="utf-8")

    monkeypatch.delenv("AMPLIFIER_AGENT_CONFIG", raising=False)

    result = runner.invoke(
        cli, ["config", "show", "--config", str(cfg)],
        env={"HOME": str(tmp_path)},
    )

    assert result.exit_code == 0, result.output
    parsed = json.loads(result.output)
    assert parsed["host_config"]["path"] == str(cfg)
    assert parsed["host_config"]["source"] == "--config flag"
```

**Step 2: Run, watch it fail.**

```bash
uv run pytest tests/cli/test_config_show.py::test_config_show_reports_flag_resolution_source -v
```

Expected: FAILED — no `--config` option on `config show`, no `host_config` key in output.

**Step 3: Implement.**

Edit `src/amplifier_agent_cli/admin/config_show.py`:

1. Add a `--config` click option to `config_show`:

```python
@config_group.command(name="show")
@click.option("--config", "config_path", default=None, type=click.Path(), help="Path to host config file.")
def config_show(config_path: str | None) -> None:
    """..."""
```

2. Add a helper to resolve and report the config tier:

```python
def _resolve_host_config(config_arg: str | None) -> dict[str, Any]:
    """Report the resolved config path + source (D8). Never raises."""
    if config_arg is not None:
        return {"path": config_arg, "source": "--config flag"}
    env_val = os.environ.get("AMPLIFIER_AGENT_CONFIG")
    if env_val:
        return {"path": env_val, "source": "$AMPLIFIER_AGENT_CONFIG env"}
    return {"path": None, "source": "none"}
```

3. Add `"host_config": _resolve_host_config(config_path)` to the `payload` dict.

**Step 4: Run, watch it pass.**

```bash
uv run pytest tests/cli/test_config_show.py::test_config_show_reports_flag_resolution_source -v
```

Expected: PASS.

**Step 5: Commit.**

```bash
git add src/amplifier_agent_cli/admin/config_show.py tests/cli/test_config_show.py
git commit -m "feat(cli): config show reports --config flag resolution source (D8)"
```

---

### Task F2: Report env-var resolution source in `config show`

**Files:**
- Modify: `tests/cli/test_config_show.py`

(Implementation already supports env-tier from F1's helper.)

**Step 1: Write the failing test.** Append:

```python
def test_config_show_reports_env_resolution_source(runner, tmp_path, monkeypatch) -> None:
    """$AMPLIFIER_AGENT_CONFIG set → source='$AMPLIFIER_AGENT_CONFIG env' (D8)."""
    cfg = tmp_path / "env-config.json"
    cfg.write_text('{"approval": {"auto_approve": false}}', encoding="utf-8")

    result = runner.invoke(
        cli, ["config", "show"],
        env={
            "HOME": str(tmp_path),
            "AMPLIFIER_AGENT_CONFIG": str(cfg),
        },
    )

    assert result.exit_code == 0, result.output
    parsed = json.loads(result.output)
    assert parsed["host_config"]["path"] == str(cfg)
    assert parsed["host_config"]["source"] == "$AMPLIFIER_AGENT_CONFIG env"


def test_config_show_reports_no_source_when_absent(runner, tmp_path) -> None:
    """No flag, no env → source='none' (D8)."""
    result = runner.invoke(
        cli, ["config", "show"],
        env={"HOME": str(tmp_path)},
    )

    assert result.exit_code == 0, result.output
    parsed = json.loads(result.output)
    assert parsed["host_config"]["path"] is None
    assert parsed["host_config"]["source"] == "none"
```

**Step 2: Run, watch them pass (F1 implementation already handles these).**

```bash
uv run pytest tests/cli/test_config_show.py -v
```

Expected: PASS.

**Step 3:** No implementation change. The tests lock the contract.

**Step 4: Commit.**

```bash
git add tests/cli/test_config_show.py
git commit -m "test(cli): lock config show env-tier and none-tier source reporting (D8)"
```

---

### Task F3: Report parsed (merged) values in `config show`

**Files:**
- Modify: `src/amplifier_agent_cli/admin/config_show.py`
- Modify: `tests/cli/test_config_show.py`

**Step 1: Write the failing test.** Append:

```python
def test_config_show_emits_parsed_values(runner, tmp_path, monkeypatch) -> None:
    """`config show --config <path>` includes the parsed config under host_config.parsed (D8)."""
    cfg = tmp_path / "host.json"
    cfg.write_text(
        '{'
        '  "mcp": {"verbose_servers": true},'
        '  "approval": {"auto_approve": false}'
        '}',
        encoding="utf-8",
    )

    monkeypatch.delenv("AMPLIFIER_AGENT_CONFIG", raising=False)

    result = runner.invoke(
        cli, ["config", "show", "--config", str(cfg)],
        env={"HOME": str(tmp_path)},
    )

    assert result.exit_code == 0, result.output
    parsed = json.loads(result.output)
    assert parsed["host_config"]["parsed"] == {
        "mcp": {"verbose_servers": True},
        "approval": {"auto_approve": False},
    }
```

**Step 2: Run, watch it fail.**

```bash
uv run pytest tests/cli/test_config_show.py::test_config_show_emits_parsed_values -v
```

Expected: FAILED — no `parsed` field yet.

**Step 3: Implement.**

In `src/amplifier_agent_cli/admin/config_show.py`, extend `_resolve_host_config` to also call `load_config`:

```python
def _resolve_host_config(config_arg: str | None) -> dict[str, Any]:
    """Report path + source + parsed values (D8). Best-effort on parse failure."""
    if config_arg is not None:
        result = {"path": config_arg, "source": "--config flag"}
    elif (env_val := os.environ.get("AMPLIFIER_AGENT_CONFIG")):
        result = {"path": env_val, "source": "$AMPLIFIER_AGENT_CONFIG env"}
    else:
        return {"path": None, "source": "none", "parsed": None}

    from amplifier_agent_lib.config import ConfigError, load_config
    try:
        result["parsed"] = load_config(config_arg=config_arg)
    except ConfigError as exc:
        result["parsed"] = None
        result["parse_error"] = {"code": exc.code, "message": exc.message}
    return result
```

**Step 4: Run, watch it pass.**

```bash
uv run pytest tests/cli/test_config_show.py::test_config_show_emits_parsed_values -v
```

Expected: PASS.

**Step 5: Commit.**

```bash
git add src/amplifier_agent_cli/admin/config_show.py tests/cli/test_config_show.py
git commit -m "feat(cli): config show emits parsed host config values (D8)"
```

---

### Task F4: `config show` reports path + source even on parse failure

**Files:**
- Modify: `tests/cli/test_config_show.py`

(Behavior already implemented in F3.)

**Step 1: Write the failing test.** Append:

```python
def test_config_show_succeeds_when_config_malformed(runner, tmp_path, monkeypatch) -> None:
    """`config show` MUST succeed (exit 0) even if --config points at malformed JSON.

    The operator can locate the file before debugging its contents (D8).
    parsed=None and parse_error.code present.
    """
    cfg = tmp_path / "broken.json"
    cfg.write_text('{"mcp": {"verbose_servers": true,', encoding="utf-8")  # truncated

    monkeypatch.delenv("AMPLIFIER_AGENT_CONFIG", raising=False)

    result = runner.invoke(
        cli, ["config", "show", "--config", str(cfg)],
        env={"HOME": str(tmp_path)},
    )

    assert result.exit_code == 0, result.output
    parsed = json.loads(result.output)
    assert parsed["host_config"]["path"] == str(cfg)
    assert parsed["host_config"]["source"] == "--config flag"
    assert parsed["host_config"]["parsed"] is None
    assert parsed["host_config"]["parse_error"]["code"] == "config_malformed_json"
```

**Step 2: Run, watch it pass.**

```bash
uv run pytest tests/cli/test_config_show.py::test_config_show_succeeds_when_config_malformed -v
```

Expected: PASS (F3 already handles the parse-error branch).

**Step 3:** No implementation change.

**Step 4: Commit.**

```bash
git add tests/cli/test_config_show.py
git commit -m "test(cli): lock config show graceful-on-parse-failure contract (D8)"
```

---

## Section G — Final integration

### Task G1: End-to-end integration test — config overrides flow through to envelope

**Files:**
- Create: `tests/config/test_integration.py`

**Step 1: Write the failing test.** Create the file:

```python
"""End-to-end: `amplifier-agent run --config <path> <prompt>` reflects merged config."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from amplifier_agent_cli.__main__ import cli


def test_run_with_config_threads_overrides_through_to_spec(tmp_path, monkeypatch):
    """Config file's mcp + provider blocks reach _TurnSpec via the loader+merger."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")

    cfg = tmp_path / "aaa.json"
    cfg.write_text(
        '{'
        '  "mcp": {"verbose_servers": true},'
        '  "provider": {"module": "anthropic"}'
        '}',
        encoding="utf-8",
    )

    captured = {}

    async def _fake_exec(spec):
        captured["host_config"] = spec.host_config
        captured["provider"] = spec.provider
        return {"reply": "ok", "turnId": "turn-1", "sessionId": ""}

    with patch("amplifier_agent_cli.modes.single_turn._execute_turn", _fake_exec):
        runner = CliRunner()
        result = runner.invoke(cli, ["run", "--config", str(cfg), "hello"])

    assert result.exit_code == 0, result.output
    assert captured["host_config"] == {
        "mcp": {"verbose_servers": True},
        "provider": {"module": "anthropic"},
    }
    assert captured["provider"] == "anthropic"
```

**Step 2: Run, watch it pass.**

```bash
uv run pytest tests/config/test_integration.py::test_run_with_config_threads_overrides_through_to_spec -v
```

Expected: PASS.

**Step 3:** No implementation change.

**Step 4: Commit.**

```bash
git add tests/config/test_integration.py
git commit -m "test(config): end-to-end --config → _TurnSpec.host_config integration"
```

---

### Task G2: Integration test — no config file → bundle defaults unchanged

**Files:**
- Modify: `tests/config/test_integration.py`

**Step 1: Write the failing test.** Append:

```python
def test_run_without_config_matches_today_behavior(tmp_path, monkeypatch):
    """No --config + no env var → host_config is None; provider from bundle default."""
    monkeypatch.delenv("AMPLIFIER_AGENT_CONFIG", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")

    captured = {}

    async def _fake_exec(spec):
        captured["host_config"] = spec.host_config
        captured["provider"] = spec.provider
        return {"reply": "ok", "turnId": "turn-1", "sessionId": ""}

    with patch("amplifier_agent_cli.modes.single_turn._execute_turn", _fake_exec):
        runner = CliRunner()
        result = runner.invoke(cli, ["run", "hello"])

    assert result.exit_code == 0, result.output
    assert captured["host_config"] is None
    assert captured["provider"] == "anthropic"  # bundle default
```

**Step 2: Run, watch it pass.**

```bash
uv run pytest tests/config/test_integration.py -v
```

Expected: PASS.

**Step 3:** No implementation change.

**Step 4: Commit.**

```bash
git add tests/config/test_integration.py
git commit -m "test(config): lock no-config-file fall-through behavior matches today"
```

---

### Task G3: Update Mode A amendment §3 supersession note

**Files:**
- Modify: `docs/designs/2026-05-24-aaa-v2-mode-a-pivot-amendment.md`

**Step 1:** No test (docs change). The work product is the diff itself.

**Step 2: Implement.**

Open `docs/designs/2026-05-24-aaa-v2-mode-a-pivot-amendment.md` and locate §3. Add at the top of §3 (before any other content):

```
> **SUPERSEDED for argv surface.** The per-turn argv flags `--env-allowlist`,
> `--env-extra`, and `--allow-protocol-skew` are removed per
> `docs/designs/2026-06-01-host-config-layer-revisit.md` (D10). The
> `AMPLIFIER_AGENT_ALLOW_PROTOCOL_SKEW` env var is also removed. These
> knobs are now host-config keys (`mcp:`, `approval:`, `allowProtocolSkew:`).
> Mode A's other §3 decisions (D1, D3, D4, D6, D9, D12 inspectability,
> wire shape, secret-spill pattern) remain unchanged.
```

**Step 3: Verify.**

```bash
grep -n "SUPERSEDED for argv surface" docs/designs/2026-05-24-aaa-v2-mode-a-pivot-amendment.md
```

Expected: one match.

**Step 4: Commit.**

```bash
git add docs/designs/2026-05-24-aaa-v2-mode-a-pivot-amendment.md
git commit -m "docs(design): note Mode A amendment §3 supersession by host config layer"
```

---

### Task G4: Final verification — grep + full test suite

**Files:** none — verification only.

**Step 1: Grep for residual references.**

```bash
cd /Users/mpaidiparthy/repos/amplifier-agent

grep -rn "env-allowlist\|env-extra\|allow-protocol-skew" src/
grep -rn "detect_provider\|provider_detect\|ProviderNotConfigured" src/
grep -rn "AMPLIFIER_AGENT_ALLOW_PROTOCOL_SKEW" src/
grep -rn "_xdg_cache_home\|_xdg(" src/
# Host config format is JSON — no yaml.load anywhere in the new config code paths.
# (bundle.md is still YAML; the legitimate yaml.safe_load callers are bundle/* and
# the _read_bundle_default_provider / _resolve_provider / _check_provider helpers
# introduced in D4 and E5. Anything in src/amplifier_agent_lib/config/ that calls
# yaml.load or yaml.safe_load is a bug.)
grep -rn "yaml\.load\|yaml\.safe_load" src/amplifier_agent_lib/config/
```

Expected: each returns zero matches. (False positives are OK in comments referencing "the dropped flag"; functional code references must be zero.)

If any source-file match remains in a non-comment location, STOP and fix before the next step.

**Step 2: Run the full test suite.**

```bash
uv run pytest -q 2>&1 | tail -30
```

Expected: all tests pass, exit code 0.

**Step 3: Run ruff + pyright** (per §9 success metric).

```bash
uv run ruff check src/ tests/
uv run pyright src/amplifier_agent_lib/config/ src/amplifier_agent_cli/modes/single_turn.py
```

Expected: clean (zero errors). Fix any reported issues before the final commit.

**Step 4: Tag + commit a milestone marker (no code change).**

```bash
git commit --allow-empty -m "chore: host config layer (D1–D10) complete — Phase 2 done

Verification:
- grep: zero residual references to dropped flags / env var / provider_detect.
- pytest: full suite green.
- ruff + pyright: clean.

Closes Phase 2 of docs/plans/2026-06-01-host-config-layer-implementation.md.
Mode A amendment §3 marked SUPERSEDED for argv surface."
```

---

## Plan summary

**Total tasks: 32** (A1–A3, B1–B8, C1–C6, D1–D4, E1–E5, F1–F4, G1–G4).

**Estimated duration: 2–4 hours** at 3 minutes per task average; some tasks (D4, E5) run longer due to cross-file cleanup.

**Risk hotspots to watch:**

1. **E5 (provider_detect deletion)** is the highest-coupling task — it touches admin/, modes/, provider_sources, and four test files. Run the full suite after each sub-step. Consider splitting if it exceeds 10 minutes.
2. **D3 (runtime merge)** mutates `prepared.mount_plan` in place. Confirm that subsequent bundle mount logic in foundation reads the mutated values rather than the original snapshot. If it doesn't, the merge must happen earlier (before `prepared` is constructed) — escalate before forcing a workaround.
3. **C5 (signature change to `merge_config`)** introduces a tuple return that ripples through C1–C4 tests and D3. Update all callers in the same commit to keep CI green between tasks.

**What this plan does NOT change** (defends against scope creep):

- Wire shape, envelope schema (except via Phase 1's hostCapabilities removal), exit codes, protocol handshake.
- Bundle composition (only adds `default_provider:`).
- Session-state persistence and XDG state/cache directories (D9 only touches the config-tier resolver — there is no config-tier file; the helpers are kept for callers reading state/cache).
- Mode B (not reintroduced).
- CR-A secret-spill pattern.

**Acceptance criteria** (per design §9):

- ✅ `amplifier-agent run "..."` with no config / no env produces identical behavior to today (bundle defaults).
- ✅ Host shipping a 4-section config gets overrides applied; `config show` reflects merged values.
- ✅ Adversarial: `{"provider": {"module": "auto"}}` → hard error `config_invalid_provider_module` (C6).
- ✅ Adversarial: `{"approval": {"patterns": [123]}}` → hard error `config_invalid_type` (B8).
- ✅ Adversarial: `{"notifications": {...}}` → hard error `config_unknown_key` (B7).
- ✅ Adversarial: `--config /missing/path.json` → hard error `config_unreadable`, exit 2 (B6).
- ✅ Adversarial: malformed JSON at `--config <path>` → hard error `config_malformed_json`, exit 2 (B5).
- ✅ Test suite, ruff, pyright clean (G4).
