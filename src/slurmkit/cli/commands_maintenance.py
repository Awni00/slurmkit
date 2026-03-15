"""Cleanup, sync, and migration commands."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer

from slurmkit.collections import CollectionManager
from slurmkit.workflows.maintenance import (
    clean_wandb_runs,
    execute_clean_collection_outputs,
    plan_clean_collection_outputs,
    sync_collections,
)
from slurmkit.workflows.migration import run_migration

from .helpers import resolve_collection_name
from .prompts import canceled, prompt_confirm
from .rendering import print_review
from .runtime import can_prompt, get_state


clean_app = typer.Typer(help="Cleanup helpers for collection outputs and W&B runs.")


def register(app: typer.Typer) -> None:
    app.add_typer(clean_app, name="clean")

    @app.command("sync")
    def sync_command(
        ctx: typer.Context,
        collection: Optional[list[str]] = typer.Option(None, "--collection", help="Optional collection name filter."),
        push: bool = typer.Option(False, "--push", help="Commit and push the sync file."),
    ) -> None:
        state = get_state(ctx)
        result = sync_collections(
            config=state.config,
            collection_names=collection,
            push=push,
        )
        typer.echo(f"Syncing job states on {result['hostname']}...")
        typer.echo(f"Synced {result['result']['total_collections']} collection(s)")
        typer.echo(f"Updated {result['result']['total_jobs_updated']} job state(s)")
        typer.echo(f"Sync file: {result['sync_file']}")
        if push:
            typer.echo("Successfully pushed sync file." if result["pushed"] else "Failed to push sync file.")
        raise typer.Exit(0 if (not push or result["pushed"]) else 1)

    @app.command("migrate")
    def migrate_command(ctx: typer.Context) -> None:
        state = get_state(ctx)
        result = run_migration(
            project_root=state.config.project_root,
        )
        typer.echo(f"Backup dir: {result.backup_dir}")
        typer.echo(f"Config migrated: {'yes' if result.migrated_config else 'no'}")
        typer.echo(f"Collections migrated: {result.migrated_collections}")
        typer.echo(f"Collections already current: {result.skipped_collections}")
        typer.echo(f"Specs migrated: {result.migrated_specs}")
        typer.echo(f"Specs already current: {result.skipped_specs}")
        raise typer.Exit(0)


@clean_app.command("outputs")
def clean_outputs_command(
    ctx: typer.Context,
    collection: Optional[str] = typer.Argument(None, help="Collection name."),
    threshold: int = typer.Option(300, "--threshold", help="Maximum runtime in seconds to delete."),
    min_age: int = typer.Option(3, "--min-age", help="Minimum age in days before deleting."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview without deleting files."),
    yes: bool = typer.Option(False, "-y", "--yes", help="Skip confirmation prompt."),
) -> None:
    state = get_state(ctx)
    manager = CollectionManager(config=state.config)
    resolved = resolve_collection_name(
        state,
        manager,
        collection,
        prompt_title="Select a collection to clean",
    )
    target = manager.load(resolved)
    plan = plan_clean_collection_outputs(
        config=state.config,
        collection=target,
        threshold_seconds=threshold,
        min_age_days=min_age,
    )
    print_review(plan.review)
    if not dry_run and not yes and can_prompt(state):
        confirmed = prompt_confirm("Delete these tracked output files?", default=False)
        if confirmed is None or not confirmed:
            raise typer.Exit(canceled())
    result = execute_clean_collection_outputs(plan=plan, dry_run=dry_run)
    for error in result["errors"]:
        typer.echo(f"Error deleting {error}", err=True)
    typer.echo(f"Deleted {result['deleted']}/{len(plan.files)} file(s).")
    raise typer.Exit(1 if result["errors"] else 0)


@clean_app.command("wandb")
def clean_wandb_command(
    ctx: typer.Context,
    projects: Optional[list[str]] = typer.Option(None, "--project", help="W&B project name."),
    entity: Optional[str] = typer.Option(None, "--entity", help="W&B entity."),
    threshold: int = typer.Option(300, "--threshold", help="Maximum runtime in seconds to delete."),
    min_age: int = typer.Option(3, "--min-age", help="Minimum age in days before deleting."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview without deleting runs."),
    yes: bool = typer.Option(False, "-y", "--yes", help="Skip confirmation prompt."),
) -> None:
    state = get_state(ctx)
    resolved_projects = list(projects or (state.config.get("wandb.default_projects", []) or []))
    if not resolved_projects:
        raise typer.BadParameter("No projects specified. Use --project or set wandb.default_projects in config.")
    result = clean_wandb_runs(
        config=state.config,
        projects=resolved_projects,
        entity=entity,
        threshold_seconds=threshold,
        min_age_days=min_age,
        dry_run=True if dry_run else False,
    )
    typer.echo(result["table"])
    if not dry_run and not yes and can_prompt(state):
        confirmed = prompt_confirm("Delete these failed W&B runs?", default=False)
        if confirmed is None or not confirmed:
            raise typer.Exit(canceled())
    if not dry_run:
        result = clean_wandb_runs(
            config=state.config,
            projects=resolved_projects,
            entity=entity,
            threshold_seconds=threshold,
            min_age_days=min_age,
            dry_run=False,
        )
    for error in result["errors"]:
        typer.echo(f"Error: {error}", err=True)
    typer.echo(f"Deleted {result['deleted']}/{len(result['runs'])} run(s).")
    raise typer.Exit(1 if result["errors"] else 0)
