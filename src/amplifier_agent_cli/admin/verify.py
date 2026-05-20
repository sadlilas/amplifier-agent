"""Admin command: verify — verify installation and hook coverage.

Provides self-test commands for validating the installation.

--check-hooks: Verifies that the streaming hook exposes the required
minimum set of canonical wire events, gating the streaming-hook
implementation (Task 11) and Phase 2.0c exit.
"""

from __future__ import annotations

import asyncio
import importlib
import sys

import click

from amplifier_agent_lib import __version__
from amplifier_agent_lib.bundle.cache import load_and_prepare_cached

# ---------------------------------------------------------------------------
# Minimum wire-event set required for streaming-hook coverage
# ---------------------------------------------------------------------------

_MINIMUM_SET: tuple[str, ...] = (
    "result/delta",
    "result/final",
    "tool/started",
    "tool/completed",
    "usage",
)


# ---------------------------------------------------------------------------
# Internal check functions
# ---------------------------------------------------------------------------


async def _check_hooks() -> None:
    """Verify streaming hook exposes the minimum required wire events.

    Loads the prepared bundle, locates the streaming hook entry in the mount
    plan, imports ``amplifier_agent_lib.bundle.hook_streaming``, and checks
    that ``CANONICAL_WIRE_EVENTS`` covers all events in ``_MINIMUM_SET``.

    Exits 0 on success; exits 1 with a ``[FAIL]`` message on any failure.
    """
    prepared = await load_and_prepare_cached(aaa_version=__version__)

    # Locate the streaming hook entry in the mount plan.
    hooks = prepared.mount_plan.get("hooks") or {}

    found_module_name: str | None = None
    if isinstance(hooks, dict):
        for name in hooks:
            if "hook_streaming" in name or "streaming" in name:
                found_module_name = name
                break
    elif isinstance(hooks, list):
        for entry in hooks:
            module_name: str = ""
            if isinstance(entry, dict):
                module_name = str(entry.get("module", ""))
            elif isinstance(entry, str):
                module_name = entry
            if "hook_streaming" in module_name or "streaming" in module_name:
                found_module_name = module_name
                break

    if found_module_name is None:
        click.echo("[FAIL] streaming hook not mounted in bundle")
        sys.exit(1)

    # Import the streaming hook module and check CANONICAL_WIRE_EVENTS.
    try:
        streaming_mod = importlib.import_module("amplifier_agent_lib.bundle.hook_streaming")
    except ImportError as exc:
        click.echo(f"[FAIL] amplifier_agent_lib.bundle.hook_streaming not importable: {exc}")
        sys.exit(1)

    wire_events = getattr(streaming_mod, "CANONICAL_WIRE_EVENTS", None)
    if wire_events is None:
        click.echo("[FAIL] hook_streaming.CANONICAL_WIRE_EVENTS attribute not found")
        sys.exit(1)

    missing = [e for e in _MINIMUM_SET if e not in wire_events]
    if missing:
        click.echo("[FAIL] missing canonical wire events: " + ", ".join(missing))
        sys.exit(1)

    click.echo("[ OK ] hook coverage passes — all minimum-set events present")


# ---------------------------------------------------------------------------
# 'verify' command
# ---------------------------------------------------------------------------


@click.command()
@click.option(
    "--check-hooks",
    "check_hooks",
    is_flag=True,
    default=False,
    help="Verify that the streaming hook exposes the required canonical wire events.",
)
def verify(check_hooks: bool) -> None:
    """Verify the installation and hook coverage."""
    if check_hooks:
        asyncio.run(_check_hooks())
        return

    click.echo("[ OK ] verify: nothing to check (use --check-hooks for hook coverage)")
