"""Collection namespace commands."""

from __future__ import annotations

from typing import Optional

import typer

from slurmkit.collections import CollectionManager

from .helpers import resolve_collection_name
from .prompts import (
    CommandPaletteEntry,
    CommandPaletteSection,
    canceled,
    choose_command,
    prompt_confirm,
)
from .rendering import print_json, print_review, render_collection_analyze, render_collection_show
from .runtime import can_prompt, get_state
from slurmkit.workflows.collections import (
    analyze_collection,
    delete_collection,
    execute_cancel_collection,
    list_collection_summaries,
    plan_cancel_collection,
    refresh_collections,
    show_collection,
)


collections_app = typer.Typer(help="Manage tracked job collections.")


def _collections_sections() -> list[CommandPaletteSection]:
    return [
        CommandPaletteSection(
            title="Collections",
            commands=[
                CommandPaletteEntry("list", "list", "List tracked collections"),
                CommandPaletteEntry("show", "show", "Show detailed collection status"),
                CommandPaletteEntry("analyze", "analyze", "Analyze outcomes by parameter"),
                CommandPaletteEntry("refresh", "refresh", "Refresh collection states"),
                CommandPaletteEntry("cancel", "cancel", "Cancel active jobs in a collection"),
                CommandPaletteEntry("delete", "delete", "Delete a collection"),
            ],
        )
    ]


def _collections_home_impl(ctx: typer.Context) -> int:
    selected = choose_command(_collections_sections())
    if selected is None:
        return canceled()

    result = collections_app(
        args=[selected],
        prog_name="slurmkit collections",
        standalone_mode=False,
        obj=ctx.obj,
    )
    return int(result or 0)


def register(app: typer.Typer) -> None:
    app.add_typer(collections_app, name="collections")


@collections_app.callback(invoke_without_command=True)
def collections_callback(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        state = get_state(ctx)
        if can_prompt(state):
            raise typer.Exit(_collections_home_impl(ctx))
        typer.echo(ctx.get_help())
        raise typer.Exit(0)


@collections_app.command("list")
def list_command(
    ctx: typer.Context,
    json_mode: bool = typer.Option(False, "--json", help="Emit JSON output."),
) -> None:
    state = get_state(ctx)
    manager = CollectionManager(config=state.config)
    rows = list_collection_summaries(manager=manager, attempt_mode="latest")
    if json_mode:
        print_json(rows)
    else:
        for row in rows:
            typer.echo(
                f"{row['name']}: total={row['total']} completed={row['completed']} "
                f"failed={row['failed']} running={row['running']} pending={row['pending']}"
            )
    raise typer.Exit(0)


@collections_app.command("show")
def show_command(
    ctx: typer.Context,
    name: Optional[str] = typer.Argument(None, help="Collection name."),
    state_filter: str = typer.Option("all", "--state", help="Filter by normalized job state."),
    json_mode: bool = typer.Option(False, "--json", help="Emit JSON output."),
) -> None:
    state = get_state(ctx)
    manager = CollectionManager(config=state.config)
    resolved = resolve_collection_name(
        state,
        manager,
        name,
        prompt_title="Select a collection to show",
        structured_output=json_mode,
    )
    rendered = show_collection(
        config=state.config,
        manager=manager,
        name=resolved,
        refresh=True,
        state_filter=state_filter,
        json_mode=json_mode,
        attempt_mode="latest",
        show_primary=True,
        show_history=True,
    )
    if json_mode:
        print_json(rendered.payload)
    else:
        render_collection_show(args=type("Args", (), {"ui": state.ui})(), config=state.config, report=rendered.report)
    raise typer.Exit(0)


@collections_app.command("analyze")
def analyze_command(
    ctx: typer.Context,
    name: Optional[str] = typer.Argument(None, help="Collection name."),
    min_support: int = typer.Option(3, "--min-support", help="Minimum sample size for high-confidence highlights."),
    param: Optional[list[str]] = typer.Option(None, "--param", help="Limit analysis to one or more parameter names."),
    top_k: int = typer.Option(10, "--top-k", help="Number of risky/stable values to show."),
    json_mode: bool = typer.Option(False, "--json", help="Emit JSON output."),
) -> None:
    state = get_state(ctx)
    manager = CollectionManager(config=state.config)
    resolved = resolve_collection_name(
        state,
        manager,
        name,
        prompt_title="Select a collection to analyze",
        structured_output=json_mode,
    )
    rendered = analyze_collection(
        manager=manager,
        name=resolved,
        refresh=True,
        json_mode=json_mode,
        attempt_mode="latest",
        min_support=min_support,
        params=param,
        submission_group=None,
        top_k=top_k,
    )
    if json_mode:
        print_json(rendered.payload)
    else:
        render_collection_analyze(args=type("Args", (), {"ui": state.ui})(), config=state.config, report=rendered.report)
    raise typer.Exit(0)


@collections_app.command("refresh")
def refresh_command(
    ctx: typer.Context,
    name: Optional[str] = typer.Argument(None, help="Collection name."),
    refresh_all: bool = typer.Option(False, "--all", help="Refresh all collections."),
) -> None:
    state = get_state(ctx)
    manager = CollectionManager(config=state.config)
    if not refresh_all:
        resolved = resolve_collection_name(
            state,
            manager,
            name,
            prompt_title="Select a collection to refresh",
        )
    else:
        resolved = None
    result = refresh_collections(manager=manager, name=resolved, refresh_all=refresh_all)
    typer.echo(
        f"Refreshed {result['collections_refreshed']} collection(s); updated {result['jobs_updated']} job state(s)."
    )
    raise typer.Exit(0)


@collections_app.command("cancel")
def cancel_command(
    ctx: typer.Context,
    name: Optional[str] = typer.Argument(None, help="Collection name."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview without cancelling jobs."),
    yes: bool = typer.Option(False, "-y", "--yes", help="Skip confirmation prompt."),
) -> None:
    state = get_state(ctx)
    manager = CollectionManager(config=state.config)
    resolved = resolve_collection_name(
        state,
        manager,
        name,
        prompt_title="Select a collection to cancel",
    )
    collection = manager.load(resolved)
    collection.refresh_states()
    manager.save(collection)
    plan = plan_cancel_collection(collection=collection)
    print_review(plan.review)
    if not dry_run and not yes and can_prompt(state):
        confirmed = prompt_confirm("Cancel active jobs in this collection?", default=True)
        if confirmed is None or not confirmed:
            raise typer.Exit(canceled())
    result = execute_cancel_collection(manager=manager, plan=plan, dry_run=dry_run)
    if result["errors"]:
        for error in result["errors"]:
            typer.echo(f"Error cancelling {error}", err=True)
    typer.echo(f"Cancelled {len(result['cancelled_ids'])}/{len(plan.targets)} job(s).")
    raise typer.Exit(1 if result["errors"] else 0)


@collections_app.command("delete")
def delete_command(
    ctx: typer.Context,
    name: Optional[str] = typer.Argument(None, help="Collection name."),
    yes: bool = typer.Option(False, "-y", "--yes", help="Skip confirmation prompt."),
) -> None:
    state = get_state(ctx)
    manager = CollectionManager(config=state.config)
    resolved = resolve_collection_name(
        state,
        manager,
        name,
        prompt_title="Select a collection to delete",
    )
    review = typer.echo(f"Delete collection '{resolved}'.")
    if not yes and can_prompt(state):
        confirmed = prompt_confirm("Delete this collection?", default=False)
        if confirmed is None or not confirmed:
            raise typer.Exit(canceled())
    deleted = delete_collection(manager=manager, name=resolved)
    if not deleted:
        raise typer.BadParameter(f"Collection not found: {resolved}")
    typer.echo(f"Deleted collection '{resolved}'.")
    raise typer.Exit(0)
