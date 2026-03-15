"""Main CLI entry point for the Typer-based slurmkit application."""

from __future__ import annotations

from typing import List, Optional
import sys

import typer

from slurmkit.cli.app import app


def main(argv: Optional[List[str]] = None) -> int:
    """Run the slurmkit CLI and return an exit code."""
    try:
        result = app(
            args=argv,
            prog_name="slurmkit",
            standalone_mode=False,
        )
    except KeyboardInterrupt:
        typer.echo("\nAborted.")
        return 130
    except SystemExit as exc:
        code = exc.code
        return int(code) if isinstance(code, int) else 1

    if isinstance(result, int):
        return result
    return 0


if __name__ == "__main__":
    sys.exit(main())
