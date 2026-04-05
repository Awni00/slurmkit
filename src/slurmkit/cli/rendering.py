"""Shared CLI rendering helpers."""

from __future__ import annotations

import io
import json
import shutil
from contextlib import redirect_stdout
from typing import Any, Optional, Sequence

import click
import typer

from slurmkit.cli.ui import (
    UIResolutionError,
    build_collection_list_report,
    create_ui_backend,
    render_collection_list_report,
    render_collection_analyze_report,
    render_collection_show_report,
    resolve_ui_context,
)
from slurmkit.cli.ui.context import UI_MODE_RICH
from slurmkit.cli.runtime import supports_interaction
from slurmkit.workflows.shared import ReviewPlan


def print_review(review: ReviewPlan) -> None:
    typer.echo("")
    typer.echo(review.title)
    typer.echo("-" * 80)
    for line in review.lines:
        typer.echo(line)
    if review.items:
        typer.echo("")
        for item in review.items:
            typer.echo(f"  - {item}")
    typer.echo("-" * 80)


def print_json(data: Any) -> None:
    typer.echo(json.dumps(data, indent=2, default=str))


def _resolve_collection_show_pager_mode(*, config: Any, report: Any, enable_pager: bool) -> str:
    if not enable_pager:
        return "none"
    jobs_table = getattr(report, "jobs_table", None)
    if jobs_table is None:
        return "none"
    if not supports_interaction():
        return "none"

    pager_mode = str(config.get("ui.collections_show.pager", "less")).strip().lower()
    if pager_mode not in {"less", "none"}:
        pager_mode = "less"
    if pager_mode != "less":
        return "none"
    return pager_mode


def _render_collection_show_to_text(*, ui_context: Any, report: Any) -> str:
    if getattr(ui_context, "effective_mode", "") == UI_MODE_RICH:
        from rich.console import Console

        from slurmkit.cli.ui.rich_backend import RichBackend

        width = max(shutil.get_terminal_size((120, 24)).columns, 80)
        console = Console(record=True, force_terminal=True, width=width)
        backend = RichBackend(console=console)
        render_collection_show_report(report, backend)
        return console.export_text(styles=True)

    buffer = io.StringIO()
    with redirect_stdout(buffer):
        backend = create_ui_backend(ui_context)
        render_collection_show_report(report, backend)
    return buffer.getvalue()


def render_collection_show(*, args: Any, config: Any, report: Any, enable_pager: bool = False) -> None:
    try:
        ui_context = resolve_ui_context(args, config)
    except UIResolutionError as exc:
        raise RuntimeError(str(exc)) from exc

    pager_mode = _resolve_collection_show_pager_mode(
        config=config,
        report=report,
        enable_pager=enable_pager,
    )
    if pager_mode == "less":
        click.echo_via_pager(
            _render_collection_show_to_text(ui_context=ui_context, report=report),
            color=True,
        )
        return

    backend = create_ui_backend(ui_context)
    render_collection_show_report(report, backend)


def render_collection_list(*, args: Any, config: Any, rows: Sequence[dict[str, Any]]) -> None:
    try:
        ui_context = resolve_ui_context(args, config)
        backend = create_ui_backend(ui_context)
    except UIResolutionError as exc:
        raise RuntimeError(str(exc)) from exc
    report = build_collection_list_report(rows=rows)
    render_collection_list_report(report, backend)


def render_collection_analyze(*, args: Any, config: Any, report: Any) -> None:
    try:
        ui_context = resolve_ui_context(args, config)
        backend = create_ui_backend(ui_context)
    except UIResolutionError as exc:
        raise RuntimeError(str(exc)) from exc
    render_collection_analyze_report(report, backend)
