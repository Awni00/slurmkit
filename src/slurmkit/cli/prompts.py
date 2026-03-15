"""Prompt helpers for interactive CLI flows."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import typer

from slurmkit.collections import CollectionManager

from .runtime import can_prompt, supports_interaction, CLIState
from .selector_ui import (
    SelectionSeparator,
    SelectorUnavailableError,
    select_fuzzy,
    select_fuzzy_many,
    select_one,
    select_text,
)

_CREATE_NEW_SENTINEL = "__create_new__"


@dataclass(frozen=True)
class CommandPaletteEntry:
    command_id: str
    name: str
    summary: str


@dataclass(frozen=True)
class CommandPaletteSection:
    title: str
    commands: list[CommandPaletteEntry]


def _warn_selector_fallback(exc: Exception) -> None:
    message = str(exc)
    if not message:
        return
    typer.echo(f"Warning: {message}; falling back to text prompts.", err=True)


def _safe_prompt(message: str, *, default: str = "") -> str | None:
    try:
        selected = select_text(message, default_value=default)
    except SelectorUnavailableError:
        pass
    else:
        return selected

    try:
        return typer.prompt(message, default=default)
    except (typer.Abort, KeyboardInterrupt, EOFError):
        return None


def prompt_text(message: str, *, default: str = "") -> str | None:
    """Prompt for free-form text."""
    return _safe_prompt(message, default=default)


def prompt_confirm(message: str, *, default: bool = False) -> bool | None:
    """Prompt for a yes/no confirmation."""
    try:
        result = typer.confirm(message, default=default)
    except (typer.Abort, KeyboardInterrupt, EOFError):
        return None
    return bool(result)


def prompt_choice(
    message: str,
    options: list[tuple[str, str]],
    *,
    default_value: str | None = None,
    fuzzy: bool = False,
) -> str | None:
    """Prompt for a single selection."""
    if fuzzy:
        try:
            return select_fuzzy(message, options, default_value=default_value)
        except SelectorUnavailableError as exc:
            _warn_selector_fallback(exc)

    try:
        return select_one(message, options, default_value=default_value)
    except SelectorUnavailableError as exc:
        _warn_selector_fallback(exc)

    typer.echo(message)
    default_index = 1
    for index, (_value, label) in enumerate(options, start=1):
        typer.echo(f"{index}. {label}")
        if default_value is not None and options[index - 1][0] == default_value:
            default_index = index

    while True:
        raw = _safe_prompt("Enter number", default=str(default_index))
        if raw is None:
            return None
        try:
            selected = int(raw)
        except ValueError:
            typer.echo("Invalid selection. Enter a number.")
            continue
        if 1 <= selected <= len(options):
            return options[selected - 1][0]
        typer.echo("Selection out of range.")


def prompt_multi_choice(
    message: str,
    options: list[tuple[str, str]],
    *,
    default_values: Optional[list[str]] = None,
) -> list[str] | None:
    """Prompt for multiple selections."""
    try:
        return select_fuzzy_many(
            message,
            options,
            default_values=default_values,
        )
    except SelectorUnavailableError as exc:
        _warn_selector_fallback(exc)

    typer.echo(message)
    for index, (_value, label) in enumerate(options, start=1):
        typer.echo(f"{index}. {label}")

    raw = _safe_prompt("Enter comma-separated numbers", default="")
    if raw is None:
        return None
    if not raw.strip():
        return []

    indexes = []
    for token in raw.split(","):
        token = token.strip()
        if not token:
            continue
        try:
            indexes.append(int(token))
        except ValueError:
            typer.echo("Invalid selection. Use comma-separated numbers.")
            return None

    values = []
    for index in indexes:
        if 1 <= index <= len(options):
            values.append(options[index - 1][0])
    return values


def choose_command(sections: list[CommandPaletteSection]) -> str | None:
    """Prompt for a command from a sectioned palette."""
    options: list[tuple[str, str] | SelectionSeparator] = []
    for section in sections:
        options.append(SelectionSeparator(f"---- {section.title} ----"))
        for command in section.commands:
            options.append((command.command_id, f"{command.name:<28} {command.summary}"))
    try:
        return select_one("Choose a command", options)
    except SelectorUnavailableError as exc:
        _warn_selector_fallback(exc)

    flat_commands = [
        command
        for section in sections
        for command in section.commands
    ]
    typer.echo("Choose a command")
    for index, command in enumerate(flat_commands, start=1):
        typer.echo(f"{index}. {command.name} - {command.summary}")
    while True:
        raw = _safe_prompt("Enter number", default="1")
        if raw is None:
            return None
        try:
            selected = int(raw)
        except ValueError:
            typer.echo("Invalid selection. Enter a number.")
            continue
        if 1 <= selected <= len(flat_commands):
            return flat_commands[selected - 1].command_id
        typer.echo("Selection out of range.")


def discover_spec_files(root: Path) -> list[Path]:
    """Return candidate spec files under the repository root."""
    candidates: list[Path] = []
    for suffix in ("*.yaml", "*.yml"):
        for path in root.rglob(suffix):
            if any(part.startswith(".") for part in path.parts if part not in {".", ".."}):
                continue
            if path.is_file():
                candidates.append(path)
    unique = sorted(set(candidates))
    return unique


def pick_spec_file(state: CLIState) -> Path | None:
    """Prompt for a spec file path."""
    root = state.config.project_root
    files = discover_spec_files(root)
    if not files:
        typer.echo("No YAML spec files found under the project root.", err=True)
        return None
    options = [(str(path), str(path.relative_to(root))) for path in files]
    selected = prompt_choice("Select a spec file", options, fuzzy=True)
    if selected is None:
        return None
    return Path(selected)


def _collection_options(manager: CollectionManager) -> list[tuple[str, str]]:
    return [(name, name) for name in manager.list_collections()]


def pick_collection(
    state: CLIState,
    manager: CollectionManager,
    *,
    title: str = "Select a collection",
) -> str | None:
    """Prompt for a collection name."""
    options = _collection_options(manager)
    if not options:
        typer.echo("No collections found.", err=True)
        return None
    return prompt_choice(title, options, fuzzy=True)


def pick_collections(
    state: CLIState,
    manager: CollectionManager,
    *,
    title: str = "Select collections",
) -> list[str] | None:
    """Prompt for multiple collection names."""
    options = _collection_options(manager)
    if not options:
        return []
    return prompt_multi_choice(title, options)


def pick_or_create_collection(
    state: CLIState,
    manager: CollectionManager,
    *,
    default_name: str,
    title: str = "Select a collection",
) -> str | None:
    """Prompt for an existing collection or create a new one inline."""
    options = _collection_options(manager)
    options.insert(0, (_CREATE_NEW_SENTINEL, f"+ create new collection ({default_name})"))
    selected = prompt_choice(title, options, default_value=_CREATE_NEW_SENTINEL, fuzzy=True)
    if selected is None:
        return None
    if selected != _CREATE_NEW_SENTINEL:
        return selected
    return prompt_text("Collection name", default=default_name)


def discover_experiments(jobs_dir: Path) -> list[str]:
    """Return experiment directory names under the jobs root."""
    if not jobs_dir.exists():
        return []
    return sorted(path.name for path in jobs_dir.iterdir() if path.is_dir())


def pick_experiment(jobs_dir: Path) -> str | None:
    """Prompt for an experiment directory."""
    options = [(name, name) for name in discover_experiments(jobs_dir)]
    if not options:
        typer.echo("No experiment directories found.", err=True)
        return None
    return prompt_choice("Select an experiment", options, fuzzy=True)


def discover_job_scripts(jobs_dir: Path) -> list[Path]:
    """Return all job scripts under the jobs root."""
    if not jobs_dir.exists():
        return []
    return sorted(path for path in jobs_dir.rglob("*.job") if path.is_file())


def pick_job_scripts(jobs_dir: Path) -> list[Path] | None:
    """Prompt for one or more job scripts."""
    scripts = discover_job_scripts(jobs_dir)
    if not scripts:
        typer.echo("No job scripts found.", err=True)
        return None
    options = [(str(path), str(path.relative_to(jobs_dir.parent))) for path in scripts]
    selected = prompt_multi_choice("Select job scripts", options)
    if selected is None:
        return None
    return [Path(value) for value in selected]


def prompt_job_ids(default: str = "") -> list[str] | None:
    """Prompt for one or more job IDs."""
    raw = prompt_text("Job ID(s), comma-separated", default=default)
    if raw is None:
        return None
    values = [item.strip() for item in raw.split(",") if item.strip()]
    return values


pick_job_ids = prompt_job_ids


def prompt_comma_separated(message: str, *, default: str = "") -> list[str] | None:
    """Prompt for a comma-separated list of strings."""
    raw = prompt_text(message, default=default)
    if raw is None:
        return None
    return [item.strip() for item in raw.split(",") if item.strip()]


def prompt_home_next_step(
    state: CLIState,
    options: list[tuple[str, str]],
    *,
    title: str = "Next step",
) -> str | None:
    """Prompt for a next-step action."""
    if not can_prompt(state):
        return None
    return prompt_choice(title, options, default_value=options[0][0] if options else None)


def canceled() -> int:
    """Emit the canonical cancel message and return success."""
    typer.echo("Canceled.")
    return 0
