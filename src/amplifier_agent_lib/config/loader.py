"""Host configuration loader for amplifier-agent.

Resolution order (first present wins):

1. ``--config <path>`` argv flag (passed in as ``config_arg``).
2. ``$AMPLIFIER_AGENT_CONFIG`` environment variable.

Per D1, when **neither** tier is present, :func:`load_config` returns
``None`` — the caller (engine/CLI) treats this as "no host config" and
falls back to hardcoded defaults.  Concrete flag- and env-tier
resolution land in B3/B4; this module currently stubs the
not-yet-implemented paths with :class:`NotImplementedError`.
"""

from __future__ import annotations

import os
from typing import Any

__all__ = ["load_config"]


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
        NotImplementedError: When a resolution tier *is* present.  Flag-
            and env-tier handling land in B3/B4.
    """
    if config_arg is None and not os.environ.get("AMPLIFIER_AGENT_CONFIG"):
        return None
    raise NotImplementedError("flag/env-tier resolution lands in B3/B4")
