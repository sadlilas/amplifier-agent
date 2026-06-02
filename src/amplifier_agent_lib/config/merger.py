"""Layered merge of host config over bundle module configs (D5).

Per the host config design (``docs/designs/2026-06-01-host-config-layer-revisit.md``
\u00a7D5), the engine composes the effective module config at bundle-mount time
by overlaying the host's pass-through config on top of the bundle's static
config.  The bundle's declaration is the base; host overrides apply per
block, per key.

The merge is a **shallow** per-key overlay within each module block
(``{**bundle_static, **host_overrides}``).  There is no recursive
merging, no key renaming, no curation, and no schema translation:
amplifier-agent only parameterizes what ``bundle.md`` already declares
(D4 pass-through stance).  If the host wants to override a key that the
bundle exposes, it sets that key; otherwise the bundle default stands.

When the host did not provide a config tier at all (``host_config is None``,
returned by :func:`amplifier_agent_lib.config.load_config` when neither
``--config`` nor ``$AMPLIFIER_AGENT_CONFIG`` is present), the merge is a
no-op and the bundle module configs pass through unchanged.

This module is the **C1 stub**: it implements only the
``host_config is None`` path.  The per-block merges for ``mcp``,
``approval``, ``provider``, and ``allowProtocolSkew`` land in C2/C3/C4 and
will replace the ``NotImplementedError`` below.
"""

from __future__ import annotations

import copy
from typing import Any


def merge_config(
    *,
    bundle_modules: dict[str, dict[str, Any]],
    host_config: dict[str, Any] | None,
) -> dict[str, dict[str, Any]]:
    """Overlay host config over bundle module configs (D5, shallow per-key).

    Arguments are keyword-only so call sites at the bundle-mount seam stay
    self-documenting; the two dicts are easy to swap by accident.

    :param bundle_modules: The bundle's declared module configs, keyed by
        module id (e.g. ``"tool-mcp"``, ``"hooks-approval"``).  Each value
        is the static config block that ``bundle.md`` declares for that
        module.  This dict is treated as immutable input \u2014 callers can
        rely on it being unchanged on return.
    :param host_config: The parsed host config dict from
        :func:`amplifier_agent_lib.config.load_config`, or ``None`` when
        neither config tier (``--config`` flag, ``$AMPLIFIER_AGENT_CONFIG``
        env var) was provided.  When ``None``, the bundle module configs
        are returned unchanged (D5 no-op path).
    :returns: A new dict of module configs with host overrides applied
        per-block per-key.  Callers receive a deep copy \u2014 mutating the
        result will not affect ``bundle_modules``.

    The non-``None`` path raises :class:`NotImplementedError` until C2/C3/C4
    land the per-block merges.
    """
    # Deep copy so callers cannot reach back into the bundle's declared
    # config by mutating our return value, and so per-block overlays can
    # mutate merged-block dicts in place safely.
    merged = copy.deepcopy(bundle_modules)
    if host_config is None:
        # D5 no-op path: no host tier, bundle defaults pass through.
        return merged

    # D4, D5: host.mcp -> tool-mcp module config (shallow per-key overlay).
    mcp_overrides = host_config.get("mcp")
    if isinstance(mcp_overrides, dict):
        base = merged.get("tool-mcp", {})
        merged["tool-mcp"] = {**base, **mcp_overrides}

    # D4, D5: host.approval -> hooks-approval module config (shallow per-key
    # overlay). List values (e.g. ``patterns``) are replaced wholesale by the
    # host's list -- there is no array merge, consistent with the per-key
    # overlay stance of D5.
    approval_overrides = host_config.get("approval")
    if isinstance(approval_overrides, dict):
        base = merged.get("hooks-approval", {})
        merged["hooks-approval"] = {**base, **approval_overrides}

    return merged
