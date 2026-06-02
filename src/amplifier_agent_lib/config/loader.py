"""Host configuration loader for amplifier-agent.

Resolution order (first present wins):

1. ``--config <path>`` argv flag (passed in as ``config_arg``).
2. ``$AMPLIFIER_AGENT_CONFIG`` environment variable.

Per D1, when **neither** tier is present, :func:`load_config` returns
``None`` — the caller (engine/CLI) treats this as "no host config" and
falls back to hardcoded defaults.  Per D5, a JSON ``null`` literal at the
document root is normalized to an empty dict (matching the omitted-block
semantics), while non-mapping roots currently raise :class:`TypeError`
(replaced by :class:`ConfigError` in B7).

:class:`ConfigError` is defined here (rather than the package
``__init__``) so this module can raise it without creating a circular
import.  The package ``__init__`` re-exports it.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from amplifier_agent_lib.protocol.errors import AaaError

__all__ = ["ConfigError", "load_config"]

_VALID_TOP_LEVEL_KEYS = frozenset({"mcp", "approval", "provider", "allowProtocolSkew"})


class ConfigError(AaaError):
    """Recoverable configuration error raised by loader/merger.

    Subclasses :class:`AaaError` so the CLI's existing error-envelope
    machinery catches it and emits a §4.1 envelope.  Defaults
    ``classification`` to ``"protocol"`` so the wrapper exits with the
    protocol exit code (2) unless the caller explicitly overrides it.
    """

    def __init__(
        self,
        *,
        code: str,
        message: str,
        classification: str | None = "protocol",
    ) -> None:
        super().__init__(
            code=code,
            message=message,
            classification=classification,
        )


def load_config(config_arg: str | None) -> dict[str, Any] | None:
    """Load host configuration following the documented resolution order.

    Args:
        config_arg: Value of the ``--config <path>`` CLI flag, or ``None``
            if the flag was not supplied.

    Returns:
        The parsed configuration dict if a resolution tier was present,
        or ``None`` when neither the ``--config`` flag nor the
        ``$AMPLIFIER_AGENT_CONFIG`` env var is set (D1).

    Raises:
        ConfigError: When the resolved file is missing or unreadable
            (D2, ``code='config_unreadable'``,
            ``classification='protocol'``).  Note that setting
            ``$AMPLIFIER_AGENT_CONFIG`` is treated as an affirmative
            declaration; a missing path from env raises just like a
            missing path from the flag (not silently ignored).
        ConfigError: When the resolved file contains malformed JSON
            (D7, ``code='config_malformed_json'``,
            ``classification='protocol'``).
        TypeError: Temporary guard when the parsed JSON root is not a
            mapping; replaced by :class:`ConfigError` in B7.
    """
    path_str = config_arg or os.environ.get("AMPLIFIER_AGENT_CONFIG") or None
    if path_str is None:
        return None
    path = Path(path_str)
    try:
        raw = path.read_text(encoding="utf-8")
    except (FileNotFoundError, PermissionError, IsADirectoryError, OSError) as exc:
        raise ConfigError(
            code="config_unreadable",
            message=f"Cannot read config at {path}: {exc.__class__.__name__}: {exc}",
            classification="protocol",
        ) from exc
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ConfigError(
            code="config_malformed_json",
            message=f"Failed to parse JSON at {path}: {exc}",
            classification="protocol",
        ) from exc
    if parsed is None:
        # D5: null literal at the root → empty dict, matching omitted-block semantics.
        return {}
    if not isinstance(parsed, dict):
        # Temporary type guard — replaced by ConfigError in B7.
        raise TypeError(f"config root must be a mapping, got {type(parsed).__name__}")
    return parsed
