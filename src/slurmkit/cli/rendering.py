"""Shared CLI rendering helpers."""

from __future__ import annotations

import io
import json
import shutil
from dataclasses import replace
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

    pager_mode = str(config.get("ui.collections_show.pager", "chunked")).strip().lower()
    if pager_mode not in {"less", "chunked", "none"}:
        pager_mode = "chunked"
    if pager_mode == "none":
        return "none"

    try:
        threshold = max(int(config.get("ui.collections_show.pager_row_threshold", 20)), 0)
    except (TypeError, ValueError):
        threshold = 20
    if len(getattr(jobs_table, "rows", [])) <= threshold:
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


def _render_collection_show_chunked(*, ui_context: Any, report: Any, chunk_size: int) -> None:
    backend = create_ui_backend(ui_context)
    jobs_table = getattr(report, "jobs_table", None)
    if jobs_table is None:
        render_collection_show_report(report, backend)
        return

    summary_only_report = replace(report, jobs_table=None)
    render_collection_show_report(summary_only_report, backend)

    rows = list(jobs_table.rows)
    total = len(rows)
    if total == 0:
        backend.table(
            title=jobs_table.title,
            headers=jobs_table.headers,
            rows=(),
            status_columns=jobs_table.status_columns,
            empty_message=jobs_table.empty_message,
        )
        return

    size = max(int(chunk_size), 1)
    start = 0
    while start < total:
        end = min(start + size, total)
        chunk_table = replace(
            jobs_table,
            title=f"{jobs_table.title} [{start + 1}-{end} of {total}]",
            rows=rows[start:end],
        )
        backend.table(
            title=chunk_table.title,
            headers=chunk_table.headers,
            rows=chunk_table.rows,
            status_columns=chunk_table.status_columns,
            empty_message=chunk_table.empty_message,
        )
        start = end
        if start >= total:
            break

        click.echo("")
        click.echo(
            "Press Enter/Space for next chunk, 'q' to stop.",
            err=False,
        )
        choice = click.getchar()
        click.echo("")
        if str(choice).strip().lower() == "q":
            break


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
    if pager_mode == "chunked":
        try:
            chunk_size = max(int(config.get("ui.collections_show.pager_row_threshold", 20)), 1)
        except (TypeError, ValueError):
            chunk_size = 20
        _render_collection_show_chunked(ui_context=ui_context, report=report, chunk_size=chunk_size)
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
