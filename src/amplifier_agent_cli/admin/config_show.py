"""Admin command: config show — print resolved config as JSON with source annotations.

Precedence (highest to lowest):
  CLI flags > env vars > XDG config file > compiled defaults.

Phase 2 scope: surface provider + XDG config/cache/state paths.
Reading config.toml is a follow-up; non-env fields are annotated source='default'.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import click
import yaml

from amplifier_agent_lib.bundle import BUNDLE_MD


def _annotate_env_or_default(env_var: str, default: Path) -> dict[str, Any]:
    """Return a value/source dict for an XDG path env var.

    If *env_var* is set and non-empty, returns its value annotated as
    ``env:<env_var>``.  Otherwise returns the *default* path string annotated
    as ``default``.
    """
    value = os.environ.get(env_var)
    if value:
        return {"value": value, "source": f"env:{env_var}"}
    return {"value": str(default), "source": "default"}


def _resolve_provider() -> dict[str, Any]:
    """Determine the active provider from the vendored bundle.md default (D6).

    Reads ``default_provider:`` from ``bundle.md``'s YAML frontmatter. Returns
    ``source='bundle.default_provider'`` when present, ``source='unset'`` when
    the field is missing/non-string, and ``source='error'`` if the manifest
    cannot be parsed.
    """
    try:
        manifest = yaml.safe_load(BUNDLE_MD.read_text(encoding="utf-8").split("---\n")[1])
    except Exception:
        return {"value": None, "source": "error"}
    default = manifest.get("default_provider") if isinstance(manifest, dict) else None
    if isinstance(default, str):
        return {"value": default, "source": "bundle.default_provider"}
    return {"value": None, "source": "unset"}


@click.group()
def config_group() -> None:
    """Inspect resolved config."""


@config_group.command(name="show")
def config_show() -> None:
    """Print resolved configuration as JSON with source annotations."""
    home = Path(os.environ.get("HOME", str(Path.home())))

    payload: dict[str, Any] = {
        "provider": _resolve_provider(),
        "xdg_config_home": _annotate_env_or_default("XDG_CONFIG_HOME", home / ".config"),
        "xdg_cache_home": _annotate_env_or_default("XDG_CACHE_HOME", home / ".cache"),
        "xdg_state_home": _annotate_env_or_default("XDG_STATE_HOME", home / ".local" / "state"),
    }

    click.echo(json.dumps(payload, indent=2))
