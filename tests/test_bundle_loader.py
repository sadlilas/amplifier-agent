"""Integration tests for bundle/loader.py.

These tests exercise the REAL amplifier_foundation.load_bundle() + Bundle.prepare()
path. They are integration tests — expect seconds (cold), but never minutes.

No mocking of amplifier-foundation inside this test file.
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.mark.asyncio
async def test_load_and_prepare_returns_prepared_bundle() -> None:
    """load_and_prepare_bundle() returns a non-None PreparedBundle with a mount_plan dict."""
    from amplifier_agent_lib.bundle.loader import load_and_prepare_bundle

    prepared = await load_and_prepare_bundle(install_deps=False)

    assert prepared is not None
    assert hasattr(prepared, "mount_plan")
    assert isinstance(prepared.mount_plan, dict)


@pytest.mark.asyncio
async def test_prepared_bundle_declares_context_simple() -> None:
    """Vendored bundle.md declares context-simple as the session context module.

    Updated from context-persistent on 2026-05-19 (Thread 1 fix). context-persistent's
    own README explicitly says 'No auto-save: Does not persist context back to files' —
    it loads memory files at session start, it does not own transcript persistence.
    Transcript persistence is a planned CLI-layer hook concern (see
    docs/designs/2026-05-19-baked-in-bundle-revisit.md).
    """
    from amplifier_agent_lib.bundle.loader import load_and_prepare_bundle

    prepared = await load_and_prepare_bundle(install_deps=False)

    assert prepared.mount_plan["session"]["context"]["module"] == "context-simple"


@pytest.mark.asyncio
async def test_load_and_prepare_accepts_override_path(tmp_path: Path) -> None:
    """override_path parameter loads an alternate bundle instead of the vendored one."""
    from amplifier_agent_lib.bundle.loader import load_and_prepare_bundle

    # Write a minimal alt bundle.md with a distinct name
    override = tmp_path / "bundle.md"
    override.write_text("---\nbundle:\n  name: alt-bundle\n  version: 1.0.0\n---\n# Alt bundle\n")

    prepared = await load_and_prepare_bundle(override_path=override, install_deps=False)

    # Verify the correct bundle was loaded (checking the Bundle object, not mount_plan,
    # since to_mount_plan() does not include bundle metadata at the top level)
    assert prepared.bundle.name == "alt-bundle"


def test_agents_dir_exposes_vendored_agents() -> None:
    """AGENTS_DIR points at the bundle/agents/ directory containing the four vendored agents."""
    from amplifier_agent_lib.bundle import AGENTS_DIR

    assert AGENTS_DIR.is_dir(), f"AGENTS_DIR does not exist: {AGENTS_DIR}"
    expected_names = {"explorer.md", "planner.md", "coder.md", "tester.md"}
    actual_names = {p.name for p in AGENTS_DIR.iterdir() if p.suffix == ".md"}
    missing = expected_names - actual_names
    assert not missing, f"AGENTS_DIR missing vendored agents: {missing}"


@pytest.mark.asyncio
async def test_vendored_bundle_has_no_includes_block() -> None:
    """Vendored bundle.md must not contain `includes:` — the resolver does not handle named-bundle URIs.

    Regression guard for `No handler for URI: build-up-foundation`. Per the Strategy 1
    decision in docs/designs/2026-05-19-baked-in-bundle-decision.md, the manifest is now
    self-describing with explicit modules + agents and no foundation include.
    """
    from amplifier_agent_lib.bundle import BUNDLE_MD

    content = BUNDLE_MD.read_text()
    assert "\nincludes:" not in content, "bundle.md must not contain a top-level `includes:` block"


@pytest.mark.asyncio
async def test_vendored_bundle_declares_all_four_agents() -> None:
    """Vendored bundle.md declares explorer/planner/coder/tester via the agents: block."""
    from amplifier_agent_lib.bundle.loader import load_and_prepare_bundle

    prepared = await load_and_prepare_bundle(install_deps=False)

    # agents is dict[str, dict[str, Any]] — keys are agent names.
    agent_names = set(prepared.bundle.agents)
    assert agent_names >= {"explorer", "planner", "coder", "tester"}, (
        f"Expected all four vendored agents; got {sorted(agent_names)}"
    )


@pytest.mark.asyncio
async def test_vendored_agents_resolve_to_wheel_local_files() -> None:
    """Each agent in the agents: block resolves to a file under the bundle/agents/ directory."""
    from amplifier_agent_lib.bundle import AGENTS_DIR
    from amplifier_agent_lib.bundle.loader import load_and_prepare_bundle

    prepared = await load_and_prepare_bundle(install_deps=False)

    for agent_name, agent_def in prepared.bundle.agents.items():
        # Foundation should have resolved each agent ref to an absolute Path under AGENTS_DIR.
        # agents is dict[str, dict[str, Any]]; the definition dict carries `source_path`.
        resolved: Path = Path(agent_def["source_path"])
        assert resolved.is_file(), f"Agent {agent_name} did not resolve to a file: {resolved}"
        assert AGENTS_DIR in resolved.parents or resolved.parent == AGENTS_DIR, (
            f"Agent {agent_name} resolved outside the vendored AGENTS_DIR: {resolved}"
        )
