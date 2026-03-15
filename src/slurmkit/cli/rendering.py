"""Shared CLI rendering helpers."""

from __future__ import annotations

import json
from typing import Any, Optional, Sequence

import typer

from slurmkit.cli.ui import (
    UIResolutionError,
    create_ui_backend,
    render_collection_analyze_report,
    render_collection_show_report,
    resolve_ui_context,
)
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


def render_collection_show(*, args: Any, config: Any, report: Any) -> None:
    try:
        ui_context = resolve_ui_context(args, config)
        backend = create_ui_backend(ui_context)
    except UIResolutionError as exc:
        raise RuntimeError(str(exc)) from exc
    render_collection_show_report(report, backend)


def render_collection_analyze(*, args: Any, config: Any, report: Any) -> None:
    try:
        ui_context = resolve_ui_context(args, config)
        backend = create_ui_backend(ui_context)
    except UIResolutionError as exc:
        raise RuntimeError(str(exc)) from exc
    render_collection_analyze_report(report, backend)
