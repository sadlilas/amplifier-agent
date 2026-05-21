# src/amplifier_agent_lib/protocol/_gen.py
"""Wire-spec generator.

Reads TypedDicts in this package and emits a language-neutral spec:
    <output_dir>/spec.md             — human-readable Markdown reference
    <output_dir>/schemas/*.schema.json — JSON Schema (Draft 2020-12) per TypedDict

Per design §8 D1, Python TypedDicts are the authoritative wire-spec source.
The Markdown and JSON Schema outputs are GENERATED — never hand-edit them.

Regenerate via:
    uv run python -m amplifier_agent_lib.protocol._gen \\
        --output-dir src/amplifier_agent_lib/protocol
"""

from __future__ import annotations

from pathlib import Path

import click


@click.command()
@click.option(
    "--output-dir",
    "output_dir",
    type=click.Path(file_okay=False, path_type=Path),
    required=True,
    help="Directory to write spec.md and schemas/ into.",
)
def main(output_dir: Path) -> None:
    """Generate spec.md and JSON Schemas from this package's TypedDicts."""
    output_dir.mkdir(parents=True, exist_ok=True)
    schemas_dir = output_dir / "schemas"
    schemas_dir.mkdir(exist_ok=True)
    click.echo(f"[gen] output directory ready: {output_dir}")


if __name__ == "__main__":
    main()
