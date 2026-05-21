"""Tests for protocol/_gen.py — the wire-spec generator."""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner


def test_gen_cli_runs_and_creates_output_dirs(tmp_path: Path) -> None:
    """The generator CLI runs cleanly and prepares the schemas/ subdirectory."""
    from amplifier_agent_lib.protocol._gen import main

    runner = CliRunner()
    result = runner.invoke(main, ["--output-dir", str(tmp_path)])

    assert result.exit_code == 0, f"stdout={result.output!r} exc={result.exception!r}"
    assert (tmp_path / "schemas").is_dir(), "schemas/ subdirectory should be created"
