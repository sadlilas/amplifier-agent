"""Admin command: ``providers list`` — read-only credential-resolution report.

Surfaces, for every provider in :data:`amplifier_agent_cli.provider_sources.KNOWN_PROVIDERS`,
whether credentials are resolvable and from what source (env / file / default /
none) -- without ever emitting the credential material itself. This is the
CLI-visible counterpart to the internal :func:`resolve_credential_detailed`
resolver introduced by the Phase 1 credential-resolution convergence: ``run``,
``models list``, and ``serve`` startup all resolve credentials through that
same function, and ``providers list`` reports what they would see.

Public contract (schema_version 1)::

    {
      "schema_version": 1,
      "providers": [
        {"name": "anthropic", "module": "provider-anthropic",
         "resolvable": true, "source": "env", "env_var": "ANTHROPIC_API_KEY"},
        ...
      ]
    }

``resolvable`` mirrors :func:`enumerate_resolvable_providers` semantics: for
ollama, a source of ``"default"`` (unset, falls back to localhost) counts as
NOT resolvable -- serve auto-enable only picks up ollama when a host is
explicitly configured via env or ``credentials.json``.
"""

from __future__ import annotations

import json

import click

from amplifier_agent_cli.provider_sources import (
    KNOWN_PROVIDERS,
    PROVIDER_CATALOG,
    resolve_credential_detailed,
)
from amplifier_agent_cli.tty_detect import is_stdout_tty

SCHEMA_VERSION = 1


def _provider_rows() -> list[dict[str, object]]:
    """Build the per-provider report rows (no credential material included)."""
    rows: list[dict[str, object]] = []
    for name in KNOWN_PROVIDERS:
        resolution = resolve_credential_detailed(name)
        rows.append(
            {
                "name": name,
                "module": PROVIDER_CATALOG[name]["module"],
                "resolvable": resolution.resolved,
                "source": resolution.source,
                "env_var": resolution.env_var,
            }
        )
    return rows


def _render_json(rows: list[dict[str, object]]) -> None:
    payload = {"schema_version": SCHEMA_VERSION, "providers": rows}
    click.echo(json.dumps(payload, indent=2))


def _render_table(rows: list[dict[str, object]]) -> None:
    header = f"{'PROVIDER':<16}{'MODULE':<24}{'RESOLVABLE':<12}{'SOURCE':<10}"
    click.echo(header)
    for row in rows:
        click.echo(f"{row['name']:<16}{row['module']:<24}{row['resolvable']!s:<12}{row['source']:<10}")


@click.group(name="providers")
def providers_group() -> None:
    """Provider credential-resolution reporting."""


@providers_group.command(name="list")
@click.option(
    "--output",
    "output_mode",
    type=click.Choice(["table", "json"]),
    default=None,
    help="Output format. Defaults to table on a TTY, json otherwise.",
)
@click.option("--json", "json_flag", is_flag=True, default=False, help="Shorthand for --output json.")
def providers_list(output_mode: str | None, json_flag: bool) -> None:
    """List known providers with their credential-resolution status.

    Never prints key material -- only whether a provider is resolvable and
    which source (env / file / default / none) would supply it.
    """
    rows = _provider_rows()

    if json_flag:
        resolved_output = "json"
    elif output_mode is not None:
        resolved_output = output_mode
    else:
        resolved_output = "table" if is_stdout_tty() else "json"

    if resolved_output == "json":
        _render_json(rows)
    else:
        _render_table(rows)
