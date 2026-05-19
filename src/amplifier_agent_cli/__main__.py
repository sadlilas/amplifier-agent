"""amplifier-agent CLI dispatcher.

This module is the entry point for the ``amplifier-agent`` command.  It owns:
- Stdout/stderr discipline: the CLI layer may print to stderr freely; stdout is
  reserved for structured output (JSON-RPC responses, etc.) in Mode A.
- Subcommand routing: all business logic lives in amplifier_agent_lib; this
  module only wires click commands to the engine.
- Lib is mode-agnostic: no I/O is performed here beyond CLI dispatch.

Registered subcommands (stubbed until their respective tasks):
  run          — Mode A single-turn stdio JSON-RPC (Task 8)
  doctor       — Self-diagnostics (Task 7)
  config show  — Show current configuration (Task 6)
  cache clear  — Clear local cache (Task 5)
"""

from __future__ import annotations

import sys

import click

from amplifier_agent_cli import __version__
from amplifier_agent_cli.admin.cache_clear import cache_group as _cache_group
from amplifier_agent_cli.admin.config_show import config_group as _config_group
from amplifier_agent_cli.admin.doctor import doctor as _doctor_command
from amplifier_agent_cli.modes.single_turn import run as _run_command


@click.group(invoke_without_command=True)
@click.version_option(version=__version__, prog_name="amplifier-agent")
@click.pass_context
def cli(ctx: click.Context) -> None:
    """amplifier-agent — Amplifier-as-Agent CLI."""
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


cli.add_command(_run_command)
cli.add_command(_doctor_command)
cli.add_command(_config_group, name="config")
cli.add_command(_cache_group, name="cache")


def main() -> None:
    """Entry point referenced by pyproject.toml [project.scripts]."""
    try:
        cli(standalone_mode=True)
    except KeyboardInterrupt:
        print("\n[info] Interrupted", file=sys.stderr)
        sys.exit(130)


if __name__ == "__main__":
    main()  # pragma: no cover
