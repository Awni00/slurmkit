"""Shared runtime helpers for the Typer-based CLI."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys
from typing import Optional

import typer

from slurmkit.config import CONFIG_FILENAME, METADATA_DIRNAME, Config, get_config


@dataclass
class CLIState:
    """Resolved global CLI state."""

    config: Config
    config_path: Optional[Path]
    ui: Optional[str]
    nointeractive: bool

    @property
    def interactive_enabled(self) -> bool:
        return bool(self.config.get("ui.interactive", True))

    @property
    def show_banner(self) -> bool:
        return bool(self.config.get("ui.show_banner", True))


def supports_interaction() -> bool:
    """Return whether the current streams support interactive prompts."""
    return sys.stdin.isatty() and sys.stdout.isatty()


def can_prompt(state: CLIState) -> bool:
    """Return whether interactive prompting is enabled and available."""
    return (
        not state.nointeractive
        and state.interactive_enabled
        and supports_interaction()
    )


def build_state(
    *,
    config_path: Optional[Path],
    ui: Optional[str],
    nointeractive: bool,
) -> CLIState:
    """Resolve global CLI state from root options."""
    project_root = None
    if config_path is not None:
        expanded = Path(config_path).expanduser()
        if expanded.name == CONFIG_FILENAME and expanded.parent.name in {METADATA_DIRNAME, ".slurm-kit"}:
            project_root = expanded.parent.parent
    config = get_config(config_path=config_path, project_root=project_root, reload=True)
    return CLIState(
        config=config,
        config_path=config_path,
        ui=ui,
        nointeractive=nointeractive,
    )


def get_state(ctx: typer.Context) -> CLIState:
    """Extract the shared CLI state from a Click/Typer context."""
    state = ctx.obj
    if not isinstance(state, CLIState):
        raise RuntimeError("CLI state has not been initialized.")
    return state


def is_structured_format(value: Optional[str]) -> bool:
    """Return whether an output format disables prompt fallback."""
    if value is None:
        return False
    return str(value).lower() not in {"table", "plain"}


def exit_with_error(message: str, code: int = 2) -> None:
    """Print an error and terminate with the provided exit code."""
    typer.echo(f"Error: {message}", err=True)
    raise typer.Exit(code)
