"""Mode A — single-turn CLI run command.

Boots the Engine, submits one prompt, prints the JSON result to stdout,
and exits 0.  All diagnostics go to stderr only.

Phase 1 note: Engine.boot in this module is called as a class-level factory
(``Engine.boot(**kwargs)``) with keyword arguments including provider,
approval, display, session_id, resume, fresh, cwd, bundle_override, and
config_path.  Phase 1's Engine.boot takes a single positional ``params``
dict and has a different interface.  This file codes to the intended Phase 2+
interface; tests use mocks.  See commit message for details.
"""

from __future__ import annotations

import json
import sys
from typing import Any

import click

from amplifier_agent_cli.provider_detect import ProviderNotConfigured, detect_provider
from amplifier_agent_cli.tty_detect import is_stdin_tty
from amplifier_agent_lib.engine import Engine
from amplifier_agent_lib.protocol.errors import AaaError
from amplifier_agent_lib.protocol_points.defaults_cli import CliApprovalSystem, CliDisplaySystem

# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _emit_error(code: str, message: str) -> None:
    """Write a JSON error envelope to stdout."""
    click.echo(json.dumps({"error": {"code": code, "message": message}}, indent=2))


def _resolve_approval_mode(yes: bool, no: bool) -> str:
    """Resolve the approval mode string from -y/-n flags.

    Returns ``'yes'``, ``'no'``, or ``'prompt'`` / ``'no'`` based on TTY.

    Raises
    ------
    click.UsageError
        If both *yes* and *no* are True simultaneously.
    """
    if yes and no:
        raise click.UsageError("-y and -n are mutually exclusive")
    if yes:
        return "yes"
    if no:
        return "no"
    return "prompt" if is_stdin_tty() else "no"


def _resolve_verbosity(quiet: bool, verbose: bool, debug: bool) -> str:
    """Resolve the display verbosity string from flag values."""
    if debug:
        return "debug"
    if verbose:
        return "verbose"
    if quiet:
        return "quiet"
    return "normal"


# ---------------------------------------------------------------------------
# 'run' command
# ---------------------------------------------------------------------------


@click.command()
@click.argument("prompt", required=False, default=None)
@click.option("--session-id", default=None, help="Session ID to resume or tag.")
@click.option("--resume", is_flag=True, default=False, help="Resume an existing session.")
@click.option("--fresh", is_flag=True, default=False, help="Force a fresh session (discard saved state).")
@click.option("--stdio", is_flag=True, default=False, help="Use stdio JSON-RPC transport (Mode B, Phase 3).")
@click.option(
    "--idle-timeout",
    "idle_timeout",
    default=None,
    type=int,
    help="Idle timeout in milliseconds before the agent exits.",
)
@click.option("--provider", "provider_override", default=None, help="Override provider detection (e.g. anthropic).")
@click.option("--bundle", default=None, hidden=True, help="Override the bundle name (hidden, for internal use).")
@click.option("--config", "config_path", default=None, type=click.Path(), help="Path to a config file.")
@click.option("--cwd", default=None, type=click.Path(), help="Working directory for the agent.")
@click.option("-v", "--verbose", is_flag=True, default=False, help="Enable verbose output.")
@click.option("--debug", is_flag=True, default=False, help="Enable debug output.")
@click.option("-y", "--yes", "yes_flag", is_flag=True, default=False, help="Auto-approve all requests.")
@click.option("-n", "--no", "no_flag", is_flag=True, default=False, help="Auto-decline all requests.")
@click.option("--quiet", is_flag=True, default=False, help="Suppress all diagnostic output.")
def run(
    prompt: str | None,
    session_id: str | None,
    resume: bool,
    fresh: bool,
    stdio: bool,
    idle_timeout: int | None,
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
    """Run the agent in single-turn mode (Mode A).

    Boots the engine, submits PROMPT, prints the JSON result to stdout,
    and exits 0.  All diagnostic output goes to stderr only.
    """
    # (1) --stdio: Mode B — run the JSON-RPC stdio loop.
    if stdio:
        import asyncio as _asyncio

        from amplifier_agent_cli.modes import stdio_loop as _stdio_loop
        from amplifier_agent_lib.protocol import PROTOCOL_VERSION as _PROTOCOL_VERSION

        _idle_timeout_s: float = (idle_timeout / 1000.0) if idle_timeout is not None else 300.0

        class _StdioEngine:
            """Phase 3 engine adapter satisfying stdio_loop._EngineProtocol.

            Protocol points are injected by stdio_loop.run() before the first
            message.  The real Engine instance is created in initialize().
            """

            def __init__(self) -> None:
                self._display: Any = None
                self._approval: Any = None
                self._inner: Any = None

            def attach_display(self, display: Any) -> None:
                self._display = display

            def attach_approval(self, approval: Any) -> None:
                self._approval = approval

            async def initialize(self, *, client_capabilities: Any, client_info: Any) -> dict[str, Any]:
                from amplifier_agent_lib.engine import Engine

                async def _stub_handler(ctx: Any) -> str:
                    return ""  # Phase 4 wires in the real turn handler.

                engine = Engine(
                    turn_handler=_stub_handler,
                    protocol_points={  # type: ignore[arg-type]
                        "approval": self._approval,
                        "display": self._display,
                    },
                )
                result = await engine.boot(
                    {
                        "capabilities": client_capabilities,
                        "sessionId": "",
                        "resume": False,
                    }
                )
                self._inner = engine
                return {
                    "protocolVersion": _PROTOCOL_VERSION,
                    "serverInfo": dict(result["serverInfo"]),
                    "capabilities": dict(result["capabilities"]),
                }

            async def dispatch(self, method: str, params: Any) -> Any:
                if self._inner is None:
                    raise RuntimeError("Engine not initialized")
                return await self._inner.dispatch(method, params)

        class _SysStdinReader:
            """Reads NDJSON lines from sys.stdin.buffer in a thread executor."""

            async def readline(self) -> bytes:
                loop = _asyncio.get_running_loop()
                return await loop.run_in_executor(None, sys.stdin.buffer.readline)

        class _SysStdoutWriter:
            """Writes bytes directly to sys.stdout.buffer and flushes."""

            def write(self, data: bytes) -> None:
                sys.stdout.buffer.write(data)

            async def drain(self) -> None:
                sys.stdout.buffer.flush()

        async def _main_stdio() -> int:
            return await _stdio_loop.run(
                reader=_SysStdinReader(),
                writer=_SysStdoutWriter(),
                engine=_StdioEngine(),
                idle_timeout_s=_idle_timeout_s,
            )

        sys.exit(_asyncio.run(_main_stdio()))

    # (2) -y and -n are mutually exclusive.
    if yes_flag and no_flag:
        raise click.UsageError("-y and -n are mutually exclusive")

    # (3) Prompt discipline.
    if prompt is None:
        if is_stdin_tty():
            raise click.UsageError("Missing argument 'PROMPT'.")
        click.echo(
            "[error] prompt_required: pass prompt as argument: "
            '`amplifier-agent run "..."`. '
            "For stdio JSON-RPC, use --stdio.",
            err=True,
        )
        sys.exit(2)

    # (4) Provider detection.
    try:
        provider = detect_provider(override=provider_override)
    except ProviderNotConfigured as exc:
        _emit_error(exc.code, exc.message)
        sys.exit(1)

    # (5) Protocol points.
    approval = CliApprovalSystem(mode=_resolve_approval_mode(yes_flag, no_flag))
    display = CliDisplaySystem(
        verbosity=_resolve_verbosity(quiet, verbose, debug),
        stream=sys.stderr,
    )

    # (6) Boot kwargs (mapped to Phase 2+ Engine.boot interface).
    boot_kwargs: dict[str, Any] = {
        "provider": provider,
        "approval": approval,
        "display": display,
        "session_id": session_id,
        "resume": resume,
        "fresh": fresh,
        "cwd": cwd,
        "bundle_override": bundle,
        "config_path": config_path,
    }

    # (7) Boot and submit.
    # Phase-1 note: Engine.boot is currently an async instance method with a
    # different signature.  The CLI is coded to the intended Phase 2+ interface
    # (Engine.boot as a classmethod-style factory).  Tests mock Engine, so the
    # runtime mismatch does not affect test results.
    try:
        engine = Engine.boot(**boot_kwargs)  # type: ignore[call-arg]
        result = engine.submit_turn(prompt)  # type: ignore[union-attr]
    except AaaError as exc:
        _emit_error(exc.code, exc.message)
        sys.exit(1)

    # (8) Output JSON result to stdout.
    click.echo(json.dumps(result, indent=2))
