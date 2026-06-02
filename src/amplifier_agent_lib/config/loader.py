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
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

__all__ = ["load_config"]

_VALID_TOP_LEVEL_KEYS = frozenset({"mcp", "approval", "provider", "allowProtocolSkew"})


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
        TypeError: Temporary guard when the parsed JSON root is not a
            mapping; replaced by :class:`ConfigError` in B7.
    """
    path_str = config_arg or os.environ.get("AMPLIFIER_AGENT_CONFIG") or None
    if path_str is None:
        return None
    path = Path(path_str)
    raw = path.read_text(encoding="utf-8")
    parsed = json.loads(raw)
    if parsed is None:
        # D5: null literal at the root → empty dict, matching omitted-block semantics.
        return {}
    if not isinstance(parsed, dict):
        # Temporary type guard — replaced by ConfigError in B7.
        raise TypeError(f"config root must be a mapping, got {type(parsed).__name__}")
    return parsed
