"""Guard test: PROVIDER_CATALOG (code) vs bundle.md `providers:` block (static mirror).

bundle.md cannot import Python -- its content hash is the bundle cache key --
so the ``providers:`` stub list is a hand-maintained mirror of
:data:`amplifier_agent_cli.provider_sources.PROVIDER_CATALOG`. This test does
NOT merge the two (bundle.md stays a static mirror per spec); it fails loudly
the moment they drift, so a future catalog edit doesn't silently desync the
bundle's install list.
"""

from __future__ import annotations

import re
from pathlib import Path

from amplifier_agent_cli.provider_sources import KNOWN_PROVIDERS, PROVIDER_CATALOG

BUNDLE_MD_PATH = Path(__file__).parents[2] / "src" / "amplifier_agent_lib" / "bundle" / "bundle.md"

_ENTRY_RE = re.compile(
    r"^\s*-\s*module:\s*(?P<module>\S+)\n\s*source:\s*(?P<source>\S+)",
    re.MULTILINE,
)


def _parse_bundle_md_providers() -> list[dict[str, str]]:
    """Parse the ``providers:`` YAML-like block out of bundle.md's frontmatter.

    Deliberately avoids a full YAML parser: bundle.md's frontmatter is
    hand-authored prose-adjacent YAML, and a regex scoped to the
    ``providers:`` block is simpler and matches exactly the shape this guard
    cares about (module/source pairs).
    """
    text = BUNDLE_MD_PATH.read_text(encoding="utf-8")
    # Isolate the providers: block (ends at the next top-level key, e.g. "session:").
    block_match = re.search(r"^providers:\n((?:  .*\n|\n)+)", text, re.MULTILINE)
    assert block_match, "bundle.md has no top-level `providers:` block"
    block = block_match.group(1)
    return [{"module": m.group("module"), "source": m.group("source")} for m in _ENTRY_RE.finditer(block)]


def test_provider_catalog_matches_bundle_md() -> None:
    """PROVIDER_CATALOG entries and bundle.md's providers: stubs must match exactly."""
    bundle_entries = _parse_bundle_md_providers()
    bundle_set = {(e["module"], e["source"]) for e in bundle_entries}
    catalog_set = {(row["module"], row["source"]) for row in PROVIDER_CATALOG.values()}

    assert bundle_set == catalog_set, (
        f"bundle.md providers: block has drifted from PROVIDER_CATALOG.\n"
        f"bundle.md only: {bundle_set - catalog_set}\n"
        f"PROVIDER_CATALOG only: {catalog_set - bundle_set}\n"
        "bundle.md is a static mirror (cannot import Python) -- update it by hand "
        "to match provider_sources.PROVIDER_CATALOG."
    )

    bundle_modules = {e["module"] for e in bundle_entries}
    catalog_modules = {PROVIDER_CATALOG[name]["module"] for name in KNOWN_PROVIDERS}
    assert bundle_modules == catalog_modules
