"""Regression test: provider_detect module is fully removed (E5).

E5 deletes ``src/amplifier_agent_cli/provider_detect.py`` entirely; provider
selection now comes from config / bundle.md default (D6). This test pins the
removal so a future inadvertent re-introduction of the module is caught.
"""

from __future__ import annotations

import importlib

import pytest


def test_provider_detect_module_no_longer_importable() -> None:
    """``amplifier_agent_cli.provider_detect`` must no longer exist (D6/E5)."""
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("amplifier_agent_cli.provider_detect")
