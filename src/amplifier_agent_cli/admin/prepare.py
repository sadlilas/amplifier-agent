"""Admin command: prepare — prime the bundle cache at install time.

Runs load_and_prepare_cached() so the first runtime invocation of
``amplifier-agent run`` never pays the manifest-resolution + clone + pip-install cost.
Exit 0 on success; exit 1 on any failure (error + traceback are printed).
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
    """Prime the bundle cache (install-time warm-up)."""
    try:
        asyncio.run(load_and_prepare_cached(aaa_version=__version__))
    except Exception as exc:
        click.echo(f"[ERROR] prepare failed: {exc}", err=True)
        traceback.print_exc()
        sys.exit(1)

    click.echo("[ OK ] bundle cache primed")
