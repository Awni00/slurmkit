"""Typer-based CLI application for slurmkit."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer

from slurmkit import __version__

from .commands_collections import register as register_collections
from .commands_config import register as register_config
from .commands_jobs import register as register_jobs
from .commands_maintenance import register as register_maintenance
from .commands_notify import register as register_notify
from .prompts import CommandPaletteEntry, CommandPaletteSection, canceled, choose_command
from .runtime import build_state, can_prompt


app = typer.Typer(
    add_completion=False,
    no_args_is_help=False,
    help="CLI tools for managing and generating SLURM jobs.",
)

register_config(app)
register_jobs(app)
register_collections(app)
register_notify(app)
register_maintenance(app)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(__version__)
        raise typer.Exit(0)


def _command_sections() -> list[CommandPaletteSection]:
    return [
        CommandPaletteSection(
            title="Setup",
            commands=[
                CommandPaletteEntry("init", "init", "Initialize project config"),
                CommandPaletteEntry("install_skill", "install-skill", "Install the slurmkit skill"),
                CommandPaletteEntry("config_show", "config show", "Show resolved config"),
                CommandPaletteEntry("config_wizard", "config wizard", "Edit config in a guided wizard"),
                CommandPaletteEntry("migrate", "migrate", "Migrate local config and collections"),
            ],
        ),
        CommandPaletteSection(
            title="Main Workflow",
            commands=[
                CommandPaletteEntry("spec_template", "spec-template", "Create a starter job spec template"),
                CommandPaletteEntry("generate", "generate", "Generate jobs from a spec"),
                CommandPaletteEntry("submit", "submit", "Submit a collection"),
                CommandPaletteEntry("resubmit", "resubmit", "Resubmit failed jobs in a collection"),
                CommandPaletteEntry("status", "status", "View live status for a collection"),
            ],
        ),
        CommandPaletteSection(
            title="Collections",
            commands=[
                CommandPaletteEntry("collections_list", "collections list", "List tracked collections"),
                CommandPaletteEntry("collections_show", "collections show", "Show detailed collection status"),
                CommandPaletteEntry("collections_analyze", "collections analyze", "Analyze outcomes by parameter"),
                CommandPaletteEntry("collections_refresh", "collections refresh", "Refresh collection states"),
                CommandPaletteEntry("collections_cancel", "collections cancel", "Cancel active jobs in a collection"),
                CommandPaletteEntry("collections_delete", "collections delete", "Delete a collection"),
            ],
        ),
        CommandPaletteSection(
            title="Notifications & Sync",
            commands=[
                CommandPaletteEntry("notify_job", "notify job", "Send a job lifecycle notification"),
                CommandPaletteEntry("notify_test", "notify test", "Send a synthetic test notification"),
                CommandPaletteEntry("notify_collection_final", "notify collection-final", "Send a collection-final report"),
                CommandPaletteEntry("sync", "sync", "Write and optionally push sync state"),
            ],
        ),
        CommandPaletteSection(
            title="Cleanup",
            commands=[
                CommandPaletteEntry("clean_outputs", "clean outputs", "Delete tracked failed outputs"),
                CommandPaletteEntry("clean_wandb", "clean wandb", "Delete short failed W&B runs"),
            ],
        ),
    ]


def _home_impl(ctx: typer.Context) -> int:
    selected = choose_command(_command_sections())
    if selected is None:
        return canceled()

    command_args = {
        "init": ["init"],
        "install_skill": ["install-skill"],
        "config_show": ["config", "show"],
        "config_wizard": ["config", "wizard"],
        "migrate": ["migrate"],
        "spec_template": ["spec-template"],
        "generate": ["generate"],
        "submit": ["submit"],
        "resubmit": ["resubmit"],
        "status": ["status"],
        "collections_list": ["collections", "list"],
        "collections_show": ["collections", "show"],
        "collections_analyze": ["collections", "analyze"],
        "collections_refresh": ["collections", "refresh"],
        "collections_cancel": ["collections", "cancel"],
        "collections_delete": ["collections", "delete"],
        "notify_job": ["notify", "job"],
        "notify_test": ["notify", "test"],
        "notify_collection_final": ["notify", "collection-final"],
        "sync": ["sync"],
        "clean_outputs": ["clean", "outputs"],
        "clean_wandb": ["clean", "wandb"],
    }
    result = app(
        args=command_args[selected],
        prog_name="slurmkit",
        standalone_mode=False,
        obj=ctx.obj,
    )
    return int(result or 0)


@app.callback(invoke_without_command=True)
def main_callback(
    ctx: typer.Context,
    config_path: Optional[Path] = typer.Option(None, "--config", help="Path to a slurmkit config file."),
    ui: Optional[str] = typer.Option(None, "--ui", help="UI mode: plain, rich, or auto."),
    nointeractive: bool = typer.Option(False, "--nointeractive", help="Disable interactive prompting."),
    version: bool = typer.Option(False, "--version", callback=_version_callback, is_eager=True),
) -> None:
    del version
    state = build_state(config_path=config_path, ui=ui, nointeractive=nointeractive)
    ctx.obj = state
    if ctx.invoked_subcommand is None:
        if can_prompt(state):
            raise typer.Exit(_home_impl(ctx))
        typer.echo(ctx.get_help())
        raise typer.Exit(0)


@app.command("home")
def home_command(ctx: typer.Context) -> None:
    """Open the interactive command picker."""
    raise typer.Exit(_home_impl(ctx))
