"""Shared CLI command helpers."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import typer

from slurmkit.collections import CollectionManager
from slurmkit.generate import load_job_spec

from .prompts import canceled, pick_collection, pick_or_create_collection, pick_spec_file
from .runtime import CLIState, can_prompt, exit_with_error


def resolve_spec_path(state: CLIState, spec: Optional[Path]) -> Path:
    if spec is not None:
        return spec
    if not can_prompt(state):
        exit_with_error("Missing spec file argument.")
    selected = pick_spec_file(state)
    if selected is None:
        raise typer.Exit(canceled())
    return selected


def default_collection_name_for_spec(spec_path: Path, spec_data: dict[str, Any]) -> str:
    raw_name = spec_data.get("name")
    base_name = str(raw_name).strip() if raw_name is not None else ""
    if not base_name:
        base_name = spec_path.stem
    return f"{base_name}_{datetime.now().strftime('%Y%m%d')}"


def resolve_collection_name(
    state: CLIState,
    manager: CollectionManager,
    collection: Optional[str],
    *,
    prompt_title: str,
    structured_output: bool = False,
) -> str:
    if collection:
        try:
            return manager.normalize_name(collection)
        except ValueError as exc:
            raise typer.BadParameter(str(exc), param_hint="collection") from exc
    if structured_output or not can_prompt(state):
        exit_with_error("Missing collection argument.")
    selected = pick_collection(state, manager, title=prompt_title)
    if selected is None:
        raise typer.Exit(canceled())
    return selected


def resolve_target_collection_for_generate(
    state: CLIState,
    manager: CollectionManager,
    *,
    into: Optional[str],
    spec_path: Path,
) -> tuple[str, dict[str, Any]]:
    spec_data = load_job_spec(spec_path)
    if into is not None:
        try:
            return manager.normalize_name(into), spec_data
        except ValueError as exc:
            raise typer.BadParameter(str(exc), param_hint="--into") from exc
    if not can_prompt(state):
        exit_with_error("Missing --into collection name.")
    default_name = default_collection_name_for_spec(spec_path, spec_data)
    collection_name = pick_or_create_collection(
        state,
        manager,
        default_name=default_name,
        title="Select or create a collection",
    )
    if collection_name is None:
        raise typer.Exit(canceled())
    try:
        return manager.normalize_name(collection_name), spec_data
    except ValueError as exc:
        raise typer.BadParameter(str(exc), param_hint="--into") from exc
