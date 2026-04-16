"""Notification commands."""

from __future__ import annotations

from typing import Optional

import typer

from slurmkit.collections import CollectionManager
from slurmkit.notifications import NotificationService
from slurmkit.workflows.notifications import (
    run_collection_final_notification,
    run_job_notification,
    run_test_notification,
)

from .runtime import get_state


notify_app = typer.Typer(help="Send notifications to configured routes.")


def _normalize_optional_collection_name(
    manager: CollectionManager,
    collection_name: Optional[str],
) -> Optional[str]:
    if collection_name is None:
        return None
    try:
        return manager.normalize_name(collection_name)
    except ValueError as exc:
        raise typer.BadParameter(str(exc), param_hint="--collection") from exc


def register(app: typer.Typer) -> None:
    app.add_typer(notify_app, name="notify")


@notify_app.command("job")
def notify_job_command(
    ctx: typer.Context,
    job_id: Optional[str] = typer.Option(None, "--job-id", help="SLURM job ID."),
    collection_name: Optional[str] = typer.Option(None, "--collection", help="Collection name."),
    exit_code: int = typer.Option(0, "--exit-code", help="Process exit code."),
    on: str = typer.Option("failed", "--on", help="Send only on failed or on any event."),
    route: Optional[list[str]] = typer.Option(None, "--route", help="Route name filter."),
    tail_lines: Optional[int] = typer.Option(None, "--tail-lines", help="Override failed-job output tail lines."),
    strict: bool = typer.Option(False, "--strict", help="Require all routes to succeed."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview without sending."),
) -> None:
    state = get_state(ctx)
    manager = CollectionManager(config=state.config)
    service = NotificationService(config=state.config)
    result = run_job_notification(
        service=service,
        job_id=job_id,
        collection_name=_normalize_optional_collection_name(manager, collection_name),
        exit_code=exit_code,
        on=on,
        routes=route,
        tail_lines=tail_lines,
        strict=strict,
        dry_run=dry_run,
    )
    for line in result.messages:
        typer.echo(line)
    raise typer.Exit(result.exit_code)


@notify_app.command("test")
def notify_test_command(
    ctx: typer.Context,
    route: Optional[list[str]] = typer.Option(None, "--route", help="Route name filter."),
    strict: bool = typer.Option(False, "--strict", help="Require all routes to succeed."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview without sending."),
) -> None:
    state = get_state(ctx)
    service = NotificationService(config=state.config)
    result = run_test_notification(
        service=service,
        routes=route,
        strict=strict,
        dry_run=dry_run,
    )
    for line in result.messages:
        typer.echo(line)
    raise typer.Exit(result.exit_code)


@notify_app.command("collection-final")
def notify_collection_final_command(
    ctx: typer.Context,
    job_id: Optional[str] = typer.Option(None, "--job-id", help="Trigger job ID."),
    trigger_exit_code: Optional[int] = typer.Option(None, "--trigger-exit-code", help="Exit code of the trigger job."),
    collection_name: Optional[str] = typer.Option(None, "--collection", help="Collection name."),
    route: Optional[list[str]] = typer.Option(None, "--route", help="Route name filter."),
    strict: bool = typer.Option(False, "--strict", help="Require all routes to succeed."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview without sending."),
    force: bool = typer.Option(False, "--force", help="Send even if the same terminal snapshot was already sent."),
    no_refresh: bool = typer.Option(False, "--no-refresh", help="Do not refresh collection state before evaluating finality."),
) -> None:
    state = get_state(ctx)
    manager = CollectionManager(config=state.config)
    service = NotificationService(config=state.config)
    result = run_collection_final_notification(
        service=service,
        job_id=job_id,
        trigger_exit_code=trigger_exit_code,
        collection_name=_normalize_optional_collection_name(manager, collection_name),
        routes=route,
        strict=strict,
        dry_run=dry_run,
        force=force,
        no_refresh=no_refresh,
    )
    for line in result.messages:
        typer.echo(line)
    raise typer.Exit(result.exit_code)
