"""Typer-based CLI application for slurmkit."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path
import os
import subprocess
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence

from click.core import ParameterSource
import typer
import yaml

from slurmkit import __version__
from slurmkit.cli import commands as legacy_commands
from slurmkit.collections import Collection, CollectionManager
from slurmkit.config import DEFAULT_CONFIG
from slurmkit.generate import JobGenerator, load_job_spec, make_unique_job_name
from slurmkit.slurm import find_job_output, get_sacct_info, parse_elapsed_to_seconds, parse_timestamp

from .prompts import (
    CommandPaletteEntry,
    CommandPaletteSection,
    canceled,
    choose_command,
    pick_collection,
    pick_collections,
    pick_experiment,
    pick_job_ids,
    pick_job_scripts,
    pick_or_create_collection,
    pick_spec_file,
    prompt_choice,
    prompt_comma_separated,
    prompt_confirm,
    prompt_home_next_step,
    prompt_text,
)
from .runtime import (
    CLIState,
    build_state,
    can_prompt,
    exit_with_error,
    get_state,
    is_structured_format,
    make_namespace,
)

app = typer.Typer(
    add_completion=False,
    no_args_is_help=False,
    help="CLI tools for managing and generating SLURM jobs.",
)
config_app = typer.Typer(help="Inspect and edit slurmkit configuration.")
collections_app = typer.Typer(help="Manage tracked job collections.")
jobs_app = typer.Typer(help="Advanced raw job/script operations.")
notify_app = typer.Typer(help="Send notifications to configured routes.")
clean_app = typer.Typer(help="Cleanup helpers for collection outputs and W&B runs.")

app.add_typer(config_app, name="config")
app.add_typer(collections_app, name="collections")
app.add_typer(jobs_app, name="jobs")
app.add_typer(notify_app, name="notify")
app.add_typer(clean_app, name="clean")


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    merged = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = deepcopy(value)
    return merged


def _print_review(title: str, lines: Sequence[str], *, items: Optional[Sequence[str]] = None) -> None:
    typer.echo("")
    typer.echo(title)
    legacy_commands.print_separator()
    for line in lines:
        typer.echo(line)
    if items:
        typer.echo("")
        for item in items:
            typer.echo(f"  - {item}")
    legacy_commands.print_separator()


def _parameter_from_user(ctx: typer.Context, name: str) -> bool:
    try:
        source = ctx.get_parameter_source(name)
    except Exception:
        return False
    return source not in {None, ParameterSource.DEFAULT}


def _resolve_spec_path(state: CLIState, spec: Optional[Path]) -> Path:
    if spec is not None:
        return spec
    if not can_prompt(state):
        exit_with_error("Missing spec file argument.")
    selected = pick_spec_file(state)
    if selected is None:
        raise typer.Exit(canceled())
    return selected


def _default_collection_name_for_spec(spec_path: Path, spec_data: Dict[str, Any]) -> str:
    raw_name = spec_data.get("name")
    base_name = str(raw_name).strip() if raw_name is not None else ""
    if not base_name:
        base_name = spec_path.stem
    date_suffix = datetime.now().strftime("%Y%m%d")
    return f"{base_name}_{date_suffix}"


def _resolve_collection_name(
    state: CLIState,
    manager: CollectionManager,
    collection: Optional[str],
    *,
    prompt_title: str,
    structured_output: bool = False,
) -> str:
    if collection:
        return collection
    if structured_output or not can_prompt(state):
        exit_with_error("Missing collection argument.")
    selected = pick_collection(state, manager, title=prompt_title)
    if selected is None:
        raise typer.Exit(canceled())
    return selected


def _resolve_job_ids(state: CLIState, job_ids: Sequence[str]) -> list[str]:
    values = [value for value in (job_ids or []) if value]
    if values:
        return list(values)
    if not can_prompt(state):
        exit_with_error("Missing job IDs.")
    selected = pick_job_ids()
    if selected is None:
        raise typer.Exit(canceled())
    return selected


def _resolve_experiment_name(
    state: CLIState,
    experiment: Optional[str],
    *,
    jobs_dir: Path,
    structured_output: bool = False,
) -> str:
    if experiment:
        return experiment
    if structured_output or not can_prompt(state):
        exit_with_error("Missing experiment argument.")
    selected = pick_experiment(jobs_dir)
    if selected is None:
        raise typer.Exit(canceled())
    return selected


def _resolve_job_script_paths(
    state: CLIState,
    paths: Sequence[Path],
    *,
    jobs_dir: Path,
) -> list[Path]:
    values = [Path(path) for path in (paths or [])]
    if values:
        return values
    if not can_prompt(state):
        exit_with_error("Missing job script paths.")
    selected = pick_job_scripts(jobs_dir)
    if selected is None:
        raise typer.Exit(canceled())
    return selected


def _run_legacy(handler: Callable[[Any], int], state: CLIState, **kwargs: Any) -> int:
    return handler(make_namespace(state, **kwargs))


def _load_current_config_data(state: CLIState) -> Dict[str, Any]:
    path = state.config.config_path
    if path.exists():
        with open(path, "r") as handle:
            return yaml.safe_load(handle) or {}
    return {}


def _write_config_data(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as handle:
        yaml.dump(data, handle, default_flow_style=False, sort_keys=False)


def _prompt_notification_route(existing: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    route_type = prompt_choice(
        "Route type",
        [
            ("webhook", "Webhook"),
            ("slack", "Slack"),
            ("discord", "Discord"),
            ("email", "Email"),
        ],
        default_value=str(existing.get("type", "webhook")) if existing else "webhook",
    )
    if route_type is None:
        return None

    default_name = str(existing.get("name")) if existing and existing.get("name") else f"{route_type}_default"
    route_name = prompt_text("Route name", default=default_name)
    if route_name is None:
        return None

    default_events = ",".join(existing.get("events", ["job_failed"])) if existing else "job_failed"
    events = prompt_comma_separated("Events (comma-separated)", default=default_events)
    if events is None:
        return None
    if not events:
        events = ["job_failed"]

    if route_type == "email":
        recipients = prompt_comma_separated(
            "Email recipient(s), comma-separated",
            default=",".join(existing.get("to", [])) if existing else "",
        )
        if recipients is None:
            return None
        from_address = prompt_text("From address", default=str(existing.get("from", "")) if existing else "")
        if from_address is None:
            return None
        smtp_host = prompt_text("SMTP host", default=str(existing.get("smtp_host", "")) if existing else "")
        if smtp_host is None:
            return None
        smtp_port = prompt_text("SMTP port", default=str(existing.get("smtp_port", 587)) if existing else "587")
        if smtp_port is None:
            return None
        smtp_username = prompt_text(
            "SMTP username (optional)",
            default=str(existing.get("smtp_username", "")) if existing else "",
        )
        if smtp_username is None:
            return None
        smtp_password = prompt_text(
            "SMTP password (optional)",
            default=str(existing.get("smtp_password", "")) if existing else "",
        )
        if smtp_password is None:
            return None
        use_starttls = prompt_confirm(
            "Use STARTTLS?",
            default=bool(existing.get("smtp_starttls", True)) if existing else True,
        )
        if use_starttls is None:
            return None
        use_ssl = prompt_confirm(
            "Use SMTP SSL?",
            default=bool(existing.get("smtp_ssl", False)) if existing else False,
        )
        if use_ssl is None:
            return None
        return {
            "name": route_name,
            "type": route_type,
            "to": recipients,
            "from": from_address,
            "smtp_host": smtp_host,
            "smtp_port": int(smtp_port),
            "smtp_username": smtp_username or None,
            "smtp_password": smtp_password or None,
            "smtp_starttls": bool(use_starttls),
            "smtp_ssl": bool(use_ssl),
            "events": events,
        }

    url = prompt_text("Route URL", default=str(existing.get("url", "")) if existing else "")
    if url is None:
        return None
    return {
        "name": route_name,
        "type": route_type,
        "url": url,
        "events": events,
    }


def _run_config_wizard(
    state: CLIState,
    *,
    base_data: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    current = _deep_merge(DEFAULT_CONFIG, base_data)

    jobs_dir = prompt_text("Jobs directory", default=str(current.get("jobs_dir", "jobs/")))
    if jobs_dir is None:
        return None

    slurm_defaults = current.get("slurm_defaults", {})
    partition = prompt_text("Default partition", default=str(slurm_defaults.get("partition", "compute")))
    if partition is None:
        return None
    time_limit = prompt_text("Default time limit", default=str(slurm_defaults.get("time", "24:00:00")))
    if time_limit is None:
        return None
    memory = prompt_text("Default memory", default=str(slurm_defaults.get("mem", "16G")))
    if memory is None:
        return None

    wandb_entity = prompt_text(
        "W&B entity (optional)",
        default=str(current.get("wandb", {}).get("entity") or ""),
    )
    if wandb_entity is None:
        return None

    ui_mode = prompt_choice(
        "Default UI mode",
        [("auto", "Auto"), ("plain", "Plain"), ("rich", "Rich")],
        default_value=str(current.get("ui", {}).get("mode", "auto")),
    )
    if ui_mode is None:
        return None
    interactive_enabled = prompt_confirm(
        "Enable interactive prompts by default?",
        default=bool(current.get("ui", {}).get("interactive", True)),
    )
    if interactive_enabled is None:
        return None
    show_banner = prompt_confirm(
        "Show banner/help decorations by default?",
        default=bool(current.get("ui", {}).get("show_banner", True)),
    )
    if show_banner is None:
        return None

    existing_routes = current.get("notifications", {}).get("routes", [])
    configure_notifications = prompt_confirm(
        "Configure a notification route now?",
        default=bool(existing_routes),
    )
    if configure_notifications is None:
        return None

    route = None
    if configure_notifications:
        route = _prompt_notification_route(existing_routes[0] if existing_routes else None)
        if route is None:
            return None

    current["jobs_dir"] = jobs_dir
    current.setdefault("slurm_defaults", {})
    current["slurm_defaults"]["partition"] = partition
    current["slurm_defaults"]["time"] = time_limit
    current["slurm_defaults"]["mem"] = memory
    current.setdefault("wandb", {})
    current["wandb"]["entity"] = wandb_entity or None
    current.setdefault("ui", {})
    current["ui"]["mode"] = ui_mode
    current["ui"]["interactive"] = bool(interactive_enabled)
    current["ui"]["show_banner"] = bool(show_banner)
    current.setdefault("notifications", {})
    current["notifications"].setdefault("defaults", {})
    current["notifications"]["defaults"].setdefault("events", ["job_failed"])
    if route is not None:
        current["notifications"]["routes"] = [route]
        route_events = route.get("events") or ["job_failed"]
        current["notifications"]["defaults"]["events"] = [route_events[0]]

    return current


def _config_show_impl(state: CLIState) -> int:
    typer.echo(yaml.dump(state.config.as_dict(), default_flow_style=False, sort_keys=False))
    return 0


def _config_edit_impl(state: CLIState) -> int:
    config_path = state.config.config_path
    if not config_path.exists():
        exit_with_error("Config file does not exist yet. Run `slurmkit init` first.")

    editor = os.environ.get("EDITOR")
    if not editor:
        exit_with_error("EDITOR is not set.")

    result = subprocess.run([editor, str(config_path)], check=False)
    return int(result.returncode)


def _config_wizard_impl(state: CLIState, *, use_existing: bool) -> int:
    if not can_prompt(state):
        exit_with_error("Interactive config wizard requires a TTY. Omit --nointeractive.")

    base_data = _load_current_config_data(state) if use_existing else {}
    updated = _run_config_wizard(state, base_data=base_data)
    if updated is None:
        return canceled()

    _print_review(
        "Configuration review",
        [
            f"Config file: {state.config.config_path}",
            f"Jobs dir: {updated['jobs_dir']}",
            f"UI mode: {updated['ui']['mode']}",
            f"Interactive prompts: {'yes' if updated['ui']['interactive'] else 'no'}",
        ],
    )
    confirmed = prompt_confirm("Write this configuration?", default=True)
    if confirmed is None or not confirmed:
        return canceled()

    _write_config_data(state.config.config_path, updated)
    typer.echo(f"Wrote config: {state.config.config_path}")
    return 0


def _output_dir_from_spec(spec_path: Path, spec: Dict[str, Any], override: Optional[Path]) -> Path:
    if override is not None:
        return override
    output_dir = spec.get("output_dir", ".")
    resolved = Path(output_dir)
    if not resolved.is_absolute():
        resolved = spec_path.parent / resolved
    return resolved


def _build_generate_plan(
    generator: JobGenerator,
    *,
    output_dir: Path,
    collection: Optional[Collection],
) -> list[Dict[str, Any]]:
    return generator.plan(output_dir=output_dir, collection=collection)


def _offer_generate_next_steps(ctx: typer.Context, collection_name: str) -> None:
    state = get_state(ctx)
    selected = prompt_home_next_step(
        state,
        [
            ("submit", "Submit collection"),
            ("status", "View collection status"),
            ("analyze", "Analyze collection"),
            ("home", "Return to command picker"),
            ("done", "Done"),
        ],
    )
    if selected in {None, "done"}:
        return
    if selected == "submit":
        _submit_collection_impl(ctx, collection_name=collection_name, filter_name="unsubmitted", delay=0.0, dry_run=False, yes=False, offer_next=False)
    elif selected == "status":
        _status_impl(ctx, collection_name=collection_name, state_filter="all")
    elif selected == "analyze":
        _collection_analyze_impl(
            ctx,
            name=collection_name,
            format_name="table",
            no_refresh=False,
            min_support=3,
            params=None,
            attempt_mode="primary",
            submission_group=None,
            top_k=10,
        )
    elif selected == "home":
        _home_impl(ctx)


def _generate_impl(
    ctx: typer.Context,
    *,
    spec: Optional[Path],
    into: Optional[str],
    output_dir: Optional[Path],
    dry_run: bool,
) -> int:
    state = get_state(ctx)
    spec_path = _resolve_spec_path(state, spec)
    if not spec_path.exists():
        exit_with_error(f"Spec file not found: {spec_path}")

    spec_data = load_job_spec(spec_path)
    manager = CollectionManager(config=state.config)
    default_collection_name = _default_collection_name_for_spec(spec_path, spec_data)
    collection_name = into
    if collection_name is None:
        if not can_prompt(state):
            exit_with_error("Missing --into collection name.")
        collection_name = pick_or_create_collection(
            state,
            manager,
            default_name=default_collection_name,
            title="Select or create a collection",
        )
        if collection_name is None:
            return canceled()

    existing_collection = manager.load(collection_name) if manager.exists(collection_name) else None
    generator = JobGenerator.from_spec(spec_path, config=state.config)
    resolved_output_dir = _output_dir_from_spec(spec_path, spec_data, output_dir)
    plan = _build_generate_plan(
        generator,
        output_dir=resolved_output_dir,
        collection=existing_collection,
    )

    renamed = [
        f"{item['base_job_name']} -> {item['job_name']}"
        for item in plan
        if item["base_job_name"] != item["job_name"]
    ]
    lines = [
        f"Spec: {spec_path}",
        f"Collection: {collection_name} ({'existing' if existing_collection else 'new'})",
        f"Output dir: {resolved_output_dir}",
        f"Jobs to generate: {len(plan)}",
        "Mode: append-only",
    ]
    if renamed:
        lines.append(f"Renamed for collisions: {len(renamed)}")

    items = [item["job_name"] for item in plan[:10]]
    if len(plan) > 10:
        items.append(f"... and {len(plan) - 10} more")
    if renamed:
        items.extend([f"rename {entry}" for entry in renamed[:5]])

    _print_review("Generation plan", lines, items=items)

    if not plan:
        typer.echo("No jobs generated from the spec.")
        return 0

    if dry_run:
        typer.echo("")
        typer.echo("[DRY RUN] Preview of first job:")
        legacy_commands.print_separator()
        _slurm_args, preview = generator._render_job(plan[0]["parameters"], plan[0]["job_name"])
        typer.echo(preview.rstrip())
        legacy_commands.print_separator()
        return 0

    if can_prompt(state):
        confirmed = prompt_confirm("Generate these job scripts?", default=True)
        if confirmed is None or not confirmed:
            return canceled()

    collection = manager.get_or_create(
        collection_name,
        description=spec_data.get("description", ""),
    )
    result = generator.generate(
        output_dir=resolved_output_dir,
        collection=collection,
        dry_run=False,
    )
    collection.parameters = spec_data.get("parameters", {})
    if spec_data.get("description"):
        collection.description = spec_data.get("description", "")
    generation_meta = legacy_commands._build_generation_metadata(
        generator=generator,
        output_dir=resolved_output_dir,
        spec_path=spec_path,
        project_root=getattr(state.config, "project_root", None),
    )
    if not isinstance(collection.meta, dict):
        collection.meta = {}
    collection.meta["generation"] = generation_meta
    manager.save(collection)

    typer.echo(f"Generated {len(result)} job script(s) into collection '{collection_name}'.")
    if can_prompt(state):
        _offer_generate_next_steps(ctx, collection_name)
    return 0


def _offer_submit_next_steps(ctx: typer.Context, collection_name: str) -> None:
    state = get_state(ctx)
    selected = prompt_home_next_step(
        state,
        [
            ("status", "View collection status"),
            ("analyze", "Analyze collection"),
            ("home", "Return to command picker"),
            ("done", "Done"),
        ],
    )
    if selected in {None, "done"}:
        return
    if selected == "status":
        _status_impl(ctx, collection_name=collection_name, state_filter="all")
    elif selected == "analyze":
        _collection_analyze_impl(
            ctx,
            name=collection_name,
            format_name="table",
            no_refresh=False,
            min_support=3,
            params=None,
            attempt_mode="primary",
            submission_group=None,
            top_k=10,
        )
    elif selected == "home":
        _home_impl(ctx)


def _submit_collection_impl(
    ctx: typer.Context,
    *,
    collection_name: Optional[str],
    filter_name: str,
    delay: float,
    dry_run: bool,
    yes: bool,
    offer_next: bool,
) -> int:
    state = get_state(ctx)
    manager = CollectionManager(config=state.config)
    resolved_collection = _resolve_collection_name(
        state,
        manager,
        collection_name,
        prompt_title="Select a collection to submit",
    )
    if not manager.exists(resolved_collection):
        exit_with_error(f"Collection not found: {resolved_collection}")

    review_lines = [
        f"Collection: {resolved_collection}",
        f"Target scope: {filter_name}",
        f"Delay between submissions: {delay}s",
    ]
    _print_review("Submit plan", review_lines)
    if not dry_run and not yes and can_prompt(state):
        confirmed = prompt_confirm("Submit jobs now?", default=True)
        if confirmed is None or not confirmed:
            return canceled()
        yes = True

    result = _run_legacy(
        legacy_commands.cmd_submit,
        state,
        collection=resolved_collection,
        paths=[],
        filter=filter_name,
        delay=delay,
        dry_run=dry_run,
        yes=yes,
    )
    if result == 0 and offer_next and can_prompt(state) and not dry_run:
        _offer_submit_next_steps(ctx, resolved_collection)
    return result


def _resubmit_collection_impl(
    ctx: typer.Context,
    *,
    collection_name: Optional[str],
    filter_name: str,
    template: Optional[Path],
    extra_params: Optional[str],
    extra_params_file: Optional[Path],
    extra_params_function: str,
    select_file: Optional[Path],
    select_function: str,
    submission_group: Optional[str],
    regenerate: Optional[bool],
    dry_run: bool,
    yes: bool,
    offer_next: bool,
) -> int:
    state = get_state(ctx)
    manager = CollectionManager(config=state.config)
    resolved_collection = _resolve_collection_name(
        state,
        manager,
        collection_name,
        prompt_title="Select a collection to resubmit",
    )
    if not manager.exists(resolved_collection):
        exit_with_error(f"Collection not found: {resolved_collection}")

    review_lines = [
        f"Collection: {resolved_collection}",
        f"Target scope: {filter_name}",
        f"Regenerate scripts: {'yes' if regenerate is not False else 'no'}",
        f"Submission group: {submission_group or '(auto)'}",
    ]
    _print_review("Resubmit plan", review_lines)
    if not dry_run and not yes and can_prompt(state):
        confirmed = prompt_confirm("Resubmit jobs now?", default=True)
        if confirmed is None or not confirmed:
            return canceled()
        yes = True

    result = _run_legacy(
        legacy_commands.cmd_resubmit,
        state,
        collection=resolved_collection,
        filter=filter_name,
        job_ids=[],
        template=str(template) if template else None,
        extra_params=extra_params,
        extra_params_file=str(extra_params_file) if extra_params_file else None,
        extra_params_function=extra_params_function,
        select_file=str(select_file) if select_file else None,
        select_function=select_function,
        submission_group=submission_group,
        jobs_dir=None,
        regenerate=regenerate,
        dry_run=dry_run,
        yes=yes,
    )
    if result == 0 and offer_next and can_prompt(state) and not dry_run:
        _offer_submit_next_steps(ctx, resolved_collection)
    return result


def _status_impl(ctx: typer.Context, *, collection_name: Optional[str], state_filter: str) -> int:
    state = get_state(ctx)
    manager = CollectionManager(config=state.config)
    resolved_collection = _resolve_collection_name(
        state,
        manager,
        collection_name,
        prompt_title="Select a collection to inspect",
    )
    return _run_legacy(
        legacy_commands.cmd_collection_show,
        state,
        name=resolved_collection,
        format="table",
        state=state_filter,
        attempt_mode="latest",
        submission_group=None,
        show_primary=False,
        show_history=False,
        no_refresh=False,
    )


def _collection_show_impl(
    ctx: typer.Context,
    *,
    name: Optional[str],
    format_name: str,
    state_filter: str,
    attempt_mode: str,
    submission_group: Optional[str],
    show_primary: bool,
    show_history: bool,
    no_refresh: bool,
) -> int:
    state = get_state(ctx)
    manager = CollectionManager(config=state.config)
    resolved_name = _resolve_collection_name(
        state,
        manager,
        name,
        prompt_title="Select a collection to show",
        structured_output=is_structured_format(format_name),
    )
    return _run_legacy(
        legacy_commands.cmd_collection_show,
        state,
        name=resolved_name,
        format=format_name,
        state=state_filter,
        attempt_mode=attempt_mode,
        submission_group=submission_group,
        show_primary=show_primary,
        show_history=show_history,
        no_refresh=no_refresh,
    )


def _collection_analyze_impl(
    ctx: typer.Context,
    *,
    name: Optional[str],
    format_name: str,
    no_refresh: bool,
    min_support: int,
    params: Optional[list[str]],
    attempt_mode: str,
    submission_group: Optional[str],
    top_k: int,
) -> int:
    state = get_state(ctx)
    manager = CollectionManager(config=state.config)
    resolved_name = _resolve_collection_name(
        state,
        manager,
        name,
        prompt_title="Select a collection to analyze",
        structured_output=is_structured_format(format_name),
    )
    return _run_legacy(
        legacy_commands.cmd_collection_analyze,
        state,
        name=resolved_name,
        format=format_name,
        no_refresh=no_refresh,
        min_support=min_support,
        param=params,
        attempt_mode=attempt_mode,
        submission_group=submission_group,
        top_k=top_k,
    )


def _collection_groups_impl(ctx: typer.Context, *, name: Optional[str], format_name: str) -> int:
    state = get_state(ctx)
    manager = CollectionManager(config=state.config)
    resolved_name = _resolve_collection_name(
        state,
        manager,
        name,
        prompt_title="Select a collection",
        structured_output=is_structured_format(format_name),
    )
    return _run_legacy(
        legacy_commands.cmd_collection_groups,
        state,
        name=resolved_name,
        format=format_name,
    )


def _collection_list_impl(ctx: typer.Context, *, attempt_mode: str) -> int:
    state = get_state(ctx)
    return _run_legacy(
        legacy_commands.cmd_collection_list,
        state,
        attempt_mode=attempt_mode,
    )


def _collection_refresh_impl(ctx: typer.Context, *, name: Optional[str], refresh_all: bool) -> int:
    state = get_state(ctx)
    manager = CollectionManager(config=state.config)
    if refresh_all:
        collection_names = manager.list_collections()
        typer.echo(f"Refreshing {len(collection_names)} collection(s)...")
        total_updated = 0
        for collection_name in collection_names:
            collection = manager.load(collection_name)
            total_updated += collection.refresh_states()
            manager.save(collection)
        typer.echo(f"Updated {total_updated} job state(s) across {len(collection_names)} collection(s).")
        return 0

    resolved_name = _resolve_collection_name(
        state,
        manager,
        name,
        prompt_title="Select a collection to refresh",
    )
    return _run_legacy(legacy_commands.cmd_collection_update, state, name=resolved_name)


def _collection_create_impl(ctx: typer.Context, *, name: Optional[str], description: str) -> int:
    state = get_state(ctx)
    manager = CollectionManager(config=state.config)
    resolved_name = name
    if resolved_name is None:
        if not can_prompt(state):
            exit_with_error("Missing collection name.")
        resolved_name = prompt_text("Collection name")
        if resolved_name is None:
            return canceled()
    _print_review(
        "Create collection",
        [
            f"Name: {resolved_name}",
            f"Description: {description or '(none)'}",
        ],
    )
    if can_prompt(state):
        confirmed = prompt_confirm("Create this collection?", default=True)
        if confirmed is None or not confirmed:
            return canceled()
    return _run_legacy(
        legacy_commands.cmd_collection_create,
        state,
        name=resolved_name,
        description=description,
    )


def _collection_add_impl(ctx: typer.Context, *, name: Optional[str], job_ids: Sequence[str]) -> int:
    state = get_state(ctx)
    manager = CollectionManager(config=state.config)
    resolved_name = _resolve_collection_name(
        state,
        manager,
        name,
        prompt_title="Select a collection to add jobs to",
    )
    resolved_job_ids = _resolve_job_ids(state, job_ids)
    _print_review(
        "Add jobs to collection",
        [f"Collection: {resolved_name}", f"Jobs: {', '.join(resolved_job_ids)}"],
    )
    if can_prompt(state):
        confirmed = prompt_confirm("Add these jobs?", default=True)
        if confirmed is None or not confirmed:
            return canceled()
    return _run_legacy(
        legacy_commands.cmd_collection_add,
        state,
        name=resolved_name,
        job_ids=resolved_job_ids,
    )


def _collection_remove_impl(ctx: typer.Context, *, name: Optional[str], job_ids: Sequence[str]) -> int:
    state = get_state(ctx)
    manager = CollectionManager(config=state.config)
    resolved_name = _resolve_collection_name(
        state,
        manager,
        name,
        prompt_title="Select a collection to remove jobs from",
    )
    resolved_job_ids = _resolve_job_ids(state, job_ids)
    _print_review(
        "Remove jobs from collection",
        [f"Collection: {resolved_name}", f"Jobs: {', '.join(resolved_job_ids)}"],
    )
    if can_prompt(state):
        confirmed = prompt_confirm("Remove these jobs?", default=True)
        if confirmed is None or not confirmed:
            return canceled()
    return _run_legacy(
        legacy_commands.cmd_collection_remove,
        state,
        name=resolved_name,
        job_ids=resolved_job_ids,
    )


def _collection_cancel_impl(
    ctx: typer.Context,
    *,
    name: Optional[str],
    no_refresh: bool,
    dry_run: bool,
    yes: bool,
) -> int:
    state = get_state(ctx)
    manager = CollectionManager(config=state.config)
    resolved_name = _resolve_collection_name(
        state,
        manager,
        name,
        prompt_title="Select a collection to cancel",
    )
    _print_review(
        "Cancel collection jobs",
        [f"Collection: {resolved_name}", f"Refresh first: {'no' if no_refresh else 'yes'}"],
    )
    if not dry_run and not yes and can_prompt(state):
        confirmed = prompt_confirm("Cancel active jobs in this collection?", default=True)
        if confirmed is None or not confirmed:
            return canceled()
        yes = True
    return _run_legacy(
        legacy_commands.cmd_collection_cancel,
        state,
        name=resolved_name,
        no_refresh=no_refresh,
        dry_run=dry_run,
        yes=yes,
    )


def _collection_delete_impl(
    ctx: typer.Context,
    *,
    name: Optional[str],
    keep_scripts: bool,
    keep_outputs: bool,
    yes: bool,
) -> int:
    state = get_state(ctx)
    manager = CollectionManager(config=state.config)
    resolved_name = _resolve_collection_name(
        state,
        manager,
        name,
        prompt_title="Select a collection to delete",
    )
    _print_review(
        "Delete collection",
        [
            f"Collection: {resolved_name}",
            f"Keep scripts: {'yes' if keep_scripts else 'no'}",
            f"Keep outputs: {'yes' if keep_outputs else 'no'}",
        ],
    )
    if not yes and can_prompt(state):
        confirmed = prompt_confirm("Delete this collection?", default=False)
        if confirmed is None or not confirmed:
            return canceled()
        yes = True
    return _run_legacy(
        legacy_commands.cmd_collection_delete,
        state,
        name=resolved_name,
        keep_scripts=keep_scripts,
        keep_outputs=keep_outputs,
        yes=yes,
    )


def _jobs_status_impl(
    ctx: typer.Context,
    *,
    experiment: Optional[str],
    jobs_dir: Optional[Path],
    collection_name: Optional[str],
    state_filter: str,
    format_name: str,
) -> int:
    state = get_state(ctx)
    resolved_jobs_dir = jobs_dir or state.config.get_path("jobs_dir")
    resolved_experiment = experiment
    if experiment is None and can_prompt(state) and not is_structured_format(format_name):
        selected = prompt_choice(
            "Status target",
            [("__all__", "All experiments"), ("__pick__", "Choose one experiment")],
            default_value="__pick__",
        )
        if selected is None:
            return canceled()
        if selected == "__pick__":
            resolved_experiment = _resolve_experiment_name(
                state,
                None,
                jobs_dir=resolved_jobs_dir,
                structured_output=False,
            )
        else:
            resolved_experiment = None

    return _run_legacy(
        legacy_commands.cmd_status,
        state,
        experiment=resolved_experiment,
        jobs_dir=str(jobs_dir) if jobs_dir else None,
        collection=collection_name,
        state=state_filter,
        format=format_name,
    )


def _jobs_find_impl(
    ctx: typer.Context,
    *,
    job_id: Optional[str],
    jobs_dir: Optional[Path],
    preview: bool,
    lines: int,
    open_file: bool,
) -> int:
    state = get_state(ctx)
    resolved_job_id = job_id
    if resolved_job_id is None:
        if not can_prompt(state):
            exit_with_error("Missing job ID.")
        values = pick_job_ids()
        if values is None:
            return canceled()
        if not values:
            exit_with_error("Missing job ID.")
        resolved_job_id = values[0]
    return _run_legacy(
        legacy_commands.cmd_find,
        state,
        job_id=resolved_job_id,
        jobs_dir=str(jobs_dir) if jobs_dir else None,
        preview=preview,
        lines=lines,
        open=open_file,
    )


def _jobs_submit_impl(
    ctx: typer.Context,
    *,
    paths: Sequence[Path],
    delay: float,
    dry_run: bool,
    yes: bool,
) -> int:
    state = get_state(ctx)
    jobs_dir = state.config.get_path("jobs_dir")
    resolved_paths = _resolve_job_script_paths(state, paths, jobs_dir=jobs_dir)
    _print_review(
        "Submit raw job scripts",
        [f"Scripts: {len(resolved_paths)}", f"Delay between submissions: {delay}s"],
        items=[str(path) for path in resolved_paths[:10]],
    )
    if not dry_run and not yes and can_prompt(state):
        confirmed = prompt_confirm("Submit these job scripts?", default=True)
        if confirmed is None or not confirmed:
            return canceled()
        yes = True
    return _run_legacy(
        legacy_commands.cmd_submit,
        state,
        collection=None,
        paths=[str(path) for path in resolved_paths],
        filter="all",
        delay=delay,
        dry_run=dry_run,
        yes=yes,
    )


def _jobs_resubmit_impl(
    ctx: typer.Context,
    *,
    job_ids: Sequence[str],
    extra_params: Optional[str],
    extra_params_file: Optional[Path],
    extra_params_function: str,
    select_file: Optional[Path],
    select_function: str,
    submission_group: Optional[str],
    jobs_dir: Optional[Path],
    dry_run: bool,
    yes: bool,
) -> int:
    state = get_state(ctx)
    resolved_job_ids = _resolve_job_ids(state, job_ids)
    _print_review(
        "Resubmit raw jobs",
        [
            f"Jobs: {', '.join(resolved_job_ids)}",
            f"Submission group: {submission_group or '(auto)'}",
            "Regenerate scripts: no",
        ],
    )
    if not dry_run and not yes and can_prompt(state):
        confirmed = prompt_confirm("Resubmit these jobs?", default=True)
        if confirmed is None or not confirmed:
            return canceled()
        yes = True
    return _run_legacy(
        legacy_commands.cmd_resubmit,
        state,
        collection=None,
        filter="failed",
        job_ids=resolved_job_ids,
        template=None,
        extra_params=extra_params,
        extra_params_file=str(extra_params_file) if extra_params_file else None,
        extra_params_function=extra_params_function,
        select_file=str(select_file) if select_file else None,
        select_function=select_function,
        submission_group=submission_group,
        jobs_dir=str(jobs_dir) if jobs_dir else None,
        regenerate=None,
        dry_run=dry_run,
        yes=yes,
    )


def _jobs_clean_outputs_impl(
    ctx: typer.Context,
    *,
    experiment: Optional[str],
    jobs_dir: Optional[Path],
    threshold: int,
    min_age: int,
    dry_run: bool,
    yes: bool,
) -> int:
    state = get_state(ctx)
    resolved_jobs_dir = jobs_dir or state.config.get_path("jobs_dir")
    resolved_experiment = _resolve_experiment_name(
        state,
        experiment,
        jobs_dir=resolved_jobs_dir,
        structured_output=False,
    )
    _print_review(
        "Clean raw job outputs",
        [
            f"Experiment: {resolved_experiment}",
            f"Threshold: {threshold}s",
            f"Minimum age: {min_age} day(s)",
        ],
    )
    if not dry_run and not yes and can_prompt(state):
        confirmed = prompt_confirm("Delete matching output files?", default=False)
        if confirmed is None or not confirmed:
            return canceled()
        yes = True
    return _run_legacy(
        legacy_commands.cmd_clean_outputs,
        state,
        experiment=resolved_experiment,
        jobs_dir=str(jobs_dir) if jobs_dir else None,
        threshold=threshold,
        min_age=min_age,
        dry_run=dry_run,
        yes=yes,
    )


def _collection_clean_outputs_impl(
    ctx: typer.Context,
    *,
    collection_name: Optional[str],
    threshold: int,
    min_age: int,
    dry_run: bool,
    yes: bool,
) -> int:
    state = get_state(ctx)
    manager = CollectionManager(config=state.config)
    resolved_name = _resolve_collection_name(
        state,
        manager,
        collection_name,
        prompt_title="Select a collection to clean",
    )
    if not manager.exists(resolved_name):
        exit_with_error(f"Collection not found: {resolved_name}")

    collection = manager.load(resolved_name)
    collection.refresh_states()
    manager.save(collection)

    age_cutoff = datetime.now() - timedelta(days=min_age)
    effective_rows = collection.get_effective_jobs(attempt_mode="latest", state="failed")
    info_map = get_sacct_info(
        [str(row["effective_job_id"]) for row in effective_rows if row.get("effective_job_id")],
        fields=["JobID", "State", "Elapsed", "End"],
    )

    files_to_delete = []
    jobs_dir = state.config.get_path("jobs_dir")
    for row in effective_rows:
        job_id = row.get("effective_job_id")
        if not job_id:
            continue
        info = info_map.get(str(job_id), {})
        elapsed_seconds = parse_elapsed_to_seconds(info.get("Elapsed", ""))
        if elapsed_seconds < 0 or elapsed_seconds > threshold:
            continue
        end_time = parse_timestamp(info.get("End", ""))
        if end_time is None or end_time > age_cutoff:
            continue

        output_path = row["job"].get("output_path")
        if output_path:
            candidate = Path(output_path)
        else:
            matches = find_job_output(str(job_id), jobs_dir, state.config)
            candidate = matches[0] if matches else None
        if candidate is None or not Path(candidate).exists():
            continue
        files_to_delete.append(
            {
                "job_name": row.get("job_name"),
                "job_id": str(job_id),
                "elapsed": info.get("Elapsed", ""),
                "path": Path(candidate),
            }
        )

    if not files_to_delete:
        typer.echo(
            f"No tracked collection outputs matched threshold <= {threshold}s and age >= {min_age} days."
        )
        return 0

    _print_review(
        "Clean collection outputs",
        [
            f"Collection: {resolved_name}",
            f"Files to delete: {len(files_to_delete)}",
            f"Threshold: {threshold}s",
            f"Minimum age: {min_age} day(s)",
        ],
        items=[
            f"{item['job_name']} (ID: {item['job_id']}) -> {item['path']}"
            for item in files_to_delete[:10]
        ],
    )

    if dry_run:
        typer.echo("[DRY RUN] No files were deleted.")
        return 0
    if not yes and can_prompt(state):
        confirmed = prompt_confirm("Delete these tracked output files?", default=False)
        if confirmed is None or not confirmed:
            return canceled()
        yes = True

    deleted = 0
    for item in files_to_delete:
        try:
            item["path"].unlink()
            deleted += 1
            typer.echo(f"Deleted: {item['path']}")
        except OSError as exc:
            typer.echo(f"Error deleting {item['path']}: {exc}", err=True)

    typer.echo(f"Deleted {deleted}/{len(files_to_delete)} tracked output file(s).")
    return 0


def _clean_wandb_impl(
    ctx: typer.Context,
    *,
    projects: Optional[list[str]],
    entity: Optional[str],
    threshold: int,
    min_age: int,
    dry_run: bool,
    yes: bool,
) -> int:
    state = get_state(ctx)
    resolved_projects = list(projects or [])
    if not resolved_projects and can_prompt(state):
        defaults = state.config.get("wandb.default_projects", []) or []
        default_value = ",".join(defaults)
        prompted = prompt_comma_separated(
            "W&B project(s), comma-separated",
            default=default_value,
        )
        if prompted is None:
            return canceled()
        resolved_projects = prompted
    return _run_legacy(
        legacy_commands.cmd_clean_wandb,
        state,
        projects=resolved_projects or None,
        entity=entity,
        threshold=threshold,
        min_age=min_age,
        dry_run=dry_run,
        yes=yes,
    )


def _notify_job_impl(
    ctx: typer.Context,
    *,
    job_id: Optional[str],
    collection_name: Optional[str],
    exit_code: int,
    on: str,
    routes: Optional[list[str]],
    tail_lines: Optional[int],
    strict: bool,
    dry_run: bool,
) -> int:
    state = get_state(ctx)
    manager = CollectionManager(config=state.config)
    resolved_collection = collection_name
    if resolved_collection is None and can_prompt(state):
        choice = prompt_choice(
            "Collection scope",
            [("__none__", "No collection filter"), ("__pick__", "Pick a collection")],
            default_value="__none__",
        )
        if choice is None:
            return canceled()
        if choice == "__pick__":
            resolved_collection = pick_collection(state, manager, title="Select a collection")
            if resolved_collection is None:
                return canceled()
    return _run_legacy(
        legacy_commands.cmd_notify_job,
        state,
        job_id=job_id,
        collection=resolved_collection,
        exit_code=exit_code,
        on=on,
        route=routes,
        tail_lines=tail_lines,
        strict=strict,
        dry_run=dry_run,
    )


def _notify_test_impl(
    ctx: typer.Context,
    *,
    routes: Optional[list[str]],
    strict: bool,
    dry_run: bool,
) -> int:
    state = get_state(ctx)
    return _run_legacy(
        legacy_commands.cmd_notify_test,
        state,
        route=routes,
        strict=strict,
        dry_run=dry_run,
    )


def _notify_collection_final_impl(
    ctx: typer.Context,
    *,
    job_id: Optional[str],
    trigger_exit_code: Optional[int],
    collection_name: Optional[str],
    routes: Optional[list[str]],
    strict: bool,
    dry_run: bool,
    force: bool,
    no_refresh: bool,
) -> int:
    state = get_state(ctx)
    manager = CollectionManager(config=state.config)
    resolved_collection = collection_name
    if resolved_collection is None and can_prompt(state):
        choice = prompt_choice(
            "Collection scope",
            [("__auto__", "Auto-resolve from job"), ("__pick__", "Pick a collection")],
            default_value="__auto__",
        )
        if choice is None:
            return canceled()
        if choice == "__pick__":
            resolved_collection = pick_collection(state, manager, title="Select a collection")
            if resolved_collection is None:
                return canceled()
    return _run_legacy(
        legacy_commands.cmd_notify_collection_final,
        state,
        job_id=job_id,
        trigger_exit_code=trigger_exit_code,
        collection=resolved_collection,
        route=routes,
        strict=strict,
        dry_run=dry_run,
        force=force,
        no_refresh=no_refresh,
    )


def _sync_impl(
    ctx: typer.Context,
    *,
    collections: Optional[list[str]],
    output: Optional[Path],
    push: bool,
) -> int:
    state = get_state(ctx)
    resolved = list(collections or [])
    if not resolved and can_prompt(state):
        choice = prompt_choice(
            "Sync scope",
            [("__all__", "All collections"), ("__pick__", "Pick collections")],
            default_value="__all__",
        )
        if choice is None:
            return canceled()
        if choice == "__pick__":
            manager = CollectionManager(config=state.config)
            picked = pick_collections(state, manager, title="Select collections to sync")
            if picked is None:
                return canceled()
            resolved = picked
    return _run_legacy(
        legacy_commands.cmd_sync,
        state,
        collection=resolved or None,
        output=str(output) if output else None,
        push=push,
    )


def _config_picker(ctx: typer.Context) -> int:
    selected = choose_command(
        [
            CommandPaletteSection(
                "Config",
                [
                    CommandPaletteEntry("show", "show", "Print resolved configuration"),
                    CommandPaletteEntry("edit", "edit", "Open config in $EDITOR"),
                    CommandPaletteEntry("wizard", "wizard", "Run the interactive config wizard"),
                ],
            )
        ]
    )
    if selected is None:
        return canceled()
    state = get_state(ctx)
    if selected == "show":
        return _config_show_impl(state)
    if selected == "edit":
        return _config_edit_impl(state)
    return _config_wizard_impl(state, use_existing=True)


def _collections_picker(ctx: typer.Context) -> int:
    selected = choose_command(
        [
            CommandPaletteSection(
                "Collections",
                [
                    CommandPaletteEntry("list", "list", "List cached collection summaries"),
                    CommandPaletteEntry("show", "show", "Show one collection"),
                    CommandPaletteEntry("analyze", "analyze", "Analyze parameter outcomes"),
                    CommandPaletteEntry("groups", "groups", "Show resubmission groups"),
                    CommandPaletteEntry("refresh", "refresh", "Refresh SLURM states"),
                    CommandPaletteEntry("create", "create", "Create a collection"),
                    CommandPaletteEntry("add", "add", "Add job IDs to a collection"),
                    CommandPaletteEntry("remove", "remove", "Remove job IDs from a collection"),
                    CommandPaletteEntry("cancel", "cancel", "Cancel active jobs"),
                    CommandPaletteEntry("delete", "delete", "Delete a collection"),
                ],
            )
        ]
    )
    if selected is None:
        return canceled()
    if selected == "list":
        return _collection_list_impl(ctx, attempt_mode="latest")
    if selected == "show":
        return _collection_show_impl(ctx, name=None, format_name="table", state_filter="all", attempt_mode="latest", submission_group=None, show_primary=False, show_history=False, no_refresh=False)
    if selected == "analyze":
        return _collection_analyze_impl(ctx, name=None, format_name="table", no_refresh=False, min_support=3, params=None, attempt_mode="primary", submission_group=None, top_k=10)
    if selected == "groups":
        return _collection_groups_impl(ctx, name=None, format_name="table")
    if selected == "refresh":
        return _collection_refresh_impl(ctx, name=None, refresh_all=False)
    if selected == "create":
        return _collection_create_impl(ctx, name=None, description="")
    if selected == "add":
        return _collection_add_impl(ctx, name=None, job_ids=[])
    if selected == "remove":
        return _collection_remove_impl(ctx, name=None, job_ids=[])
    if selected == "cancel":
        return _collection_cancel_impl(ctx, name=None, no_refresh=False, dry_run=False, yes=False)
    return _collection_delete_impl(ctx, name=None, keep_scripts=False, keep_outputs=False, yes=False)


def _jobs_picker(ctx: typer.Context) -> int:
    selected = choose_command(
        [
            CommandPaletteSection(
                "Advanced Jobs",
                [
                    CommandPaletteEntry("submit", "submit", "Submit raw job scripts"),
                    CommandPaletteEntry("resubmit", "resubmit", "Resubmit raw job IDs"),
                    CommandPaletteEntry("status", "status", "Inspect experiment/job status"),
                    CommandPaletteEntry("find", "find", "Locate a job output file"),
                    CommandPaletteEntry("clean_outputs", "clean outputs", "Clean raw experiment outputs"),
                ],
            )
        ]
    )
    if selected is None:
        return canceled()
    if selected == "submit":
        return _jobs_submit_impl(ctx, paths=[], delay=0.0, dry_run=False, yes=False)
    if selected == "resubmit":
        return _jobs_resubmit_impl(ctx, job_ids=[], extra_params=None, extra_params_file=None, extra_params_function="get_extra_params", select_file=None, select_function="should_resubmit", submission_group=None, jobs_dir=None, dry_run=False, yes=False)
    if selected == "status":
        return _jobs_status_impl(ctx, experiment=None, jobs_dir=None, collection_name=None, state_filter="all", format_name="table")
    if selected == "find":
        return _jobs_find_impl(ctx, job_id=None, jobs_dir=None, preview=False, lines=50, open_file=False)
    return _jobs_clean_outputs_impl(ctx, experiment=None, jobs_dir=None, threshold=300, min_age=3, dry_run=False, yes=False)


def _notify_picker(ctx: typer.Context) -> int:
    selected = choose_command(
        [
            CommandPaletteSection(
                "Notifications",
                [
                    CommandPaletteEntry("job", "job", "Send a job notification"),
                    CommandPaletteEntry("test", "test", "Send a synthetic test notification"),
                    CommandPaletteEntry("collection_final", "collection-final", "Send a terminal collection report"),
                ],
            )
        ]
    )
    if selected is None:
        return canceled()
    if selected == "job":
        return _notify_job_impl(ctx, job_id=None, collection_name=None, exit_code=0, on="failed", routes=None, tail_lines=None, strict=False, dry_run=False)
    if selected == "test":
        return _notify_test_impl(ctx, routes=None, strict=False, dry_run=False)
    return _notify_collection_final_impl(ctx, job_id=None, trigger_exit_code=None, collection_name=None, routes=None, strict=False, dry_run=False, force=False, no_refresh=False)


def _clean_picker(ctx: typer.Context) -> int:
    selected = choose_command(
        [
            CommandPaletteSection(
                "Cleanup",
                [
                    CommandPaletteEntry("outputs", "outputs", "Clean collection output files"),
                    CommandPaletteEntry("wandb", "wandb", "Clean failed W&B runs"),
                ],
            )
        ]
    )
    if selected is None:
        return canceled()
    if selected == "outputs":
        return _collection_clean_outputs_impl(ctx, collection_name=None, threshold=300, min_age=3, dry_run=False, yes=False)
    return _clean_wandb_impl(ctx, projects=None, entity=None, threshold=300, min_age=3, dry_run=False, yes=False)


def _home_impl(ctx: typer.Context) -> int:
    selected = choose_command(
        [
            CommandPaletteSection(
                "Setup",
                [
                    CommandPaletteEntry("init", "init", "Initialize or update project config"),
                    CommandPaletteEntry("config_show", "config show", "Print resolved configuration"),
                    CommandPaletteEntry("config_edit", "config edit", "Open config in $EDITOR"),
                    CommandPaletteEntry("config_wizard", "config wizard", "Run the interactive config wizard"),
                ],
            ),
            CommandPaletteSection(
                "Main Workflow",
                [
                    CommandPaletteEntry("generate", "generate", "Generate jobs from a spec"),
                    CommandPaletteEntry("submit", "submit", "Submit a collection"),
                    CommandPaletteEntry("resubmit", "resubmit", "Retry failed jobs in a collection"),
                    CommandPaletteEntry("status", "status", "View live collection status"),
                ],
            ),
            CommandPaletteSection(
                "Collections",
                [
                    CommandPaletteEntry("collections_list", "collections list", "List collections"),
                    CommandPaletteEntry("collections_show", "collections show", "Show one collection"),
                    CommandPaletteEntry("collections_analyze", "collections analyze", "Analyze job outcomes"),
                    CommandPaletteEntry("collections_groups", "collections groups", "Show submission groups"),
                    CommandPaletteEntry("collections_refresh", "collections refresh", "Refresh collection state"),
                    CommandPaletteEntry("collections_create", "collections create", "Create a collection"),
                    CommandPaletteEntry("collections_add", "collections add", "Add jobs to a collection"),
                    CommandPaletteEntry("collections_remove", "collections remove", "Remove jobs from a collection"),
                    CommandPaletteEntry("collections_cancel", "collections cancel", "Cancel active jobs"),
                    CommandPaletteEntry("collections_delete", "collections delete", "Delete a collection"),
                ],
            ),
            CommandPaletteSection(
                "Notifications & Sync",
                [
                    CommandPaletteEntry("notify_job", "notify job", "Send a job notification"),
                    CommandPaletteEntry("notify_test", "notify test", "Send a test notification"),
                    CommandPaletteEntry("notify_collection_final", "notify collection-final", "Send a final collection report"),
                    CommandPaletteEntry("sync", "sync", "Sync collection state to disk"),
                ],
            ),
            CommandPaletteSection(
                "Cleanup",
                [
                    CommandPaletteEntry("clean_outputs", "clean outputs", "Clean tracked collection outputs"),
                    CommandPaletteEntry("clean_wandb", "clean wandb", "Clean failed W&B runs"),
                ],
            ),
            CommandPaletteSection(
                "Advanced Jobs",
                [
                    CommandPaletteEntry("jobs_submit", "jobs submit", "Submit raw job scripts"),
                    CommandPaletteEntry("jobs_resubmit", "jobs resubmit", "Resubmit raw job IDs"),
                    CommandPaletteEntry("jobs_status", "jobs status", "Inspect raw job status"),
                    CommandPaletteEntry("jobs_find", "jobs find", "Locate a job output file"),
                    CommandPaletteEntry("jobs_clean_outputs", "jobs clean outputs", "Clean raw experiment outputs"),
                ],
            ),
        ]
    )
    if selected is None:
        return canceled()

    state = get_state(ctx)
    if selected == "init":
        return _config_wizard_impl(state, use_existing=True)
    if selected == "config_show":
        return _config_show_impl(state)
    if selected == "config_edit":
        return _config_edit_impl(state)
    if selected == "config_wizard":
        return _config_wizard_impl(state, use_existing=True)
    if selected == "generate":
        return _generate_impl(ctx, spec=None, into=None, output_dir=None, dry_run=False)
    if selected == "submit":
        return _submit_collection_impl(ctx, collection_name=None, filter_name="unsubmitted", delay=0.0, dry_run=False, yes=False, offer_next=True)
    if selected == "resubmit":
        return _resubmit_collection_impl(ctx, collection_name=None, filter_name="failed", template=None, extra_params=None, extra_params_file=None, extra_params_function="get_extra_params", select_file=None, select_function="should_resubmit", submission_group=None, regenerate=None, dry_run=False, yes=False, offer_next=True)
    if selected == "status":
        return _status_impl(ctx, collection_name=None, state_filter="all")
    if selected == "collections_list":
        return _collection_list_impl(ctx, attempt_mode="latest")
    if selected == "collections_show":
        return _collection_show_impl(ctx, name=None, format_name="table", state_filter="all", attempt_mode="latest", submission_group=None, show_primary=False, show_history=False, no_refresh=False)
    if selected == "collections_analyze":
        return _collection_analyze_impl(ctx, name=None, format_name="table", no_refresh=False, min_support=3, params=None, attempt_mode="primary", submission_group=None, top_k=10)
    if selected == "collections_groups":
        return _collection_groups_impl(ctx, name=None, format_name="table")
    if selected == "collections_refresh":
        return _collection_refresh_impl(ctx, name=None, refresh_all=False)
    if selected == "collections_create":
        return _collection_create_impl(ctx, name=None, description="")
    if selected == "collections_add":
        return _collection_add_impl(ctx, name=None, job_ids=[])
    if selected == "collections_remove":
        return _collection_remove_impl(ctx, name=None, job_ids=[])
    if selected == "collections_cancel":
        return _collection_cancel_impl(ctx, name=None, no_refresh=False, dry_run=False, yes=False)
    if selected == "collections_delete":
        return _collection_delete_impl(ctx, name=None, keep_scripts=False, keep_outputs=False, yes=False)
    if selected == "notify_job":
        return _notify_job_impl(ctx, job_id=None, collection_name=None, exit_code=0, on="failed", routes=None, tail_lines=None, strict=False, dry_run=False)
    if selected == "notify_test":
        return _notify_test_impl(ctx, routes=None, strict=False, dry_run=False)
    if selected == "notify_collection_final":
        return _notify_collection_final_impl(ctx, job_id=None, trigger_exit_code=None, collection_name=None, routes=None, strict=False, dry_run=False, force=False, no_refresh=False)
    if selected == "sync":
        return _sync_impl(ctx, collections=None, output=None, push=False)
    if selected == "clean_outputs":
        return _collection_clean_outputs_impl(ctx, collection_name=None, threshold=300, min_age=3, dry_run=False, yes=False)
    if selected == "clean_wandb":
        return _clean_wandb_impl(ctx, projects=None, entity=None, threshold=300, min_age=3, dry_run=False, yes=False)
    if selected == "jobs_submit":
        return _jobs_submit_impl(ctx, paths=[], delay=0.0, dry_run=False, yes=False)
    if selected == "jobs_resubmit":
        return _jobs_resubmit_impl(ctx, job_ids=[], extra_params=None, extra_params_file=None, extra_params_function="get_extra_params", select_file=None, select_function="should_resubmit", submission_group=None, jobs_dir=None, dry_run=False, yes=False)
    if selected == "jobs_status":
        return _jobs_status_impl(ctx, experiment=None, jobs_dir=None, collection_name=None, state_filter="all", format_name="table")
    if selected == "jobs_find":
        return _jobs_find_impl(ctx, job_id=None, jobs_dir=None, preview=False, lines=50, open_file=False)
    return _jobs_clean_outputs_impl(ctx, experiment=None, jobs_dir=None, threshold=300, min_age=3, dry_run=False, yes=False)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"slurmkit {__version__}")
        raise typer.Exit()


@app.callback(invoke_without_command=True)
def root_callback(
    ctx: typer.Context,
    config: Optional[Path] = typer.Option(None, "--config", help="Path to config file."),
    ui: Optional[str] = typer.Option(None, "--ui", help="UI mode override: plain, rich, or auto."),
    nointeractive: bool = typer.Option(False, "--nointeractive", help="Disable prompt fallback."),
    version: Optional[bool] = typer.Option(None, "--version", callback=_version_callback, is_eager=True, help="Show version and exit."),
) -> None:
    """Root application callback."""
    ctx.obj = build_state(config_path=config, ui=ui, nointeractive=nointeractive)
    if ctx.invoked_subcommand is None:
        state = get_state(ctx)
        if can_prompt(state):
            raise typer.Exit(_home_impl(ctx))
        typer.echo(ctx.get_help())
        raise typer.Exit(0)


@app.command("home")
def home_command(ctx: typer.Context) -> None:
    """Open the command picker."""
    state = get_state(ctx)
    if not can_prompt(state):
        typer.echo(ctx.parent.get_help() if ctx.parent else ctx.get_help())
        raise typer.Exit(0)
    raise typer.Exit(_home_impl(ctx))


@app.command("init")
def init_command(ctx: typer.Context, force: bool = typer.Option(False, "--force", help="Ignore the current config file and start from defaults.")) -> None:
    """Initialize or update the project config via wizard."""
    state = get_state(ctx)
    if force:
        raise typer.Exit(_config_wizard_impl(state, use_existing=False))
    raise typer.Exit(_config_wizard_impl(state, use_existing=True))


@app.command("generate")
def generate_command(
    ctx: typer.Context,
    spec: Optional[Path] = typer.Argument(None, help="Path to a spec YAML file."),
    into: Optional[str] = typer.Option(None, "--into", help="Target collection name."),
    output_dir: Optional[Path] = typer.Option(None, "--output-dir", help="Override output directory from the spec."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview without writing files."),
) -> None:
    """Generate jobs from a spec into a collection."""
    raise typer.Exit(
        _generate_impl(
            ctx,
            spec=spec,
            into=into,
            output_dir=output_dir,
            dry_run=dry_run,
        )
    )


@app.command("submit")
def submit_command(
    ctx: typer.Context,
    collection: Optional[str] = typer.Argument(None, help="Collection to submit."),
    filter_name: str = typer.Option("unsubmitted", "--filter", help="Submit unsubmitted jobs or all jobs."),
    delay: float = typer.Option(0.0, "--delay", help="Seconds to wait between submissions."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview without submitting."),
    yes: bool = typer.Option(False, "-y", "--yes", help="Skip confirmation prompt."),
) -> None:
    """Submit a collection."""
    state = get_state(ctx)
    if can_prompt(state) and not _parameter_from_user(ctx, "filter_name"):
        selected = prompt_choice(
            "Submit which jobs?",
            [("unsubmitted", "Unsubmitted only"), ("all", "All jobs in collection")],
            default_value="unsubmitted",
        )
        if selected is None:
            raise typer.Exit(canceled())
        filter_name = selected
    raise typer.Exit(
        _submit_collection_impl(
            ctx,
            collection_name=collection,
            filter_name=filter_name,
            delay=delay,
            dry_run=dry_run,
            yes=yes,
            offer_next=True,
        )
    )


@app.command("resubmit")
def resubmit_command(
    ctx: typer.Context,
    collection: Optional[str] = typer.Argument(None, help="Collection to resubmit."),
    filter_name: str = typer.Option("failed", "--filter", help="Resubmit failed jobs or all jobs."),
    template: Optional[Path] = typer.Option(None, "--template", help="Template override for regenerated scripts."),
    extra_params: Optional[str] = typer.Option(None, "--extra-params", help="Extra KEY=VAL pairs."),
    extra_params_file: Optional[Path] = typer.Option(None, "--extra-params-file", help="Python file with get_extra_params(context)->dict."),
    extra_params_function: str = typer.Option("get_extra_params", "--extra-params-function", help="Extra-params callback name."),
    select_file: Optional[Path] = typer.Option(None, "--select-file", help="Python file with should_resubmit(context)->bool."),
    select_function: str = typer.Option("should_resubmit", "--select-function", help="Selection callback name."),
    submission_group: Optional[str] = typer.Option(None, "--submission-group", help="Submission group label."),
    regenerate: Optional[bool] = typer.Option(None, "--regenerate/--no-regenerate", help="Override regenerate behavior."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview without resubmitting."),
    yes: bool = typer.Option(False, "-y", "--yes", help="Skip confirmation prompt."),
) -> None:
    """Retry jobs in a collection."""
    state = get_state(ctx)
    if can_prompt(state) and not _parameter_from_user(ctx, "filter_name"):
        selected = prompt_choice(
            "Resubmit which jobs?",
            [("failed", "Latest failed jobs only"), ("all", "All jobs in collection")],
            default_value="failed",
        )
        if selected is None:
            raise typer.Exit(canceled())
        filter_name = selected
    if can_prompt(state) and not _parameter_from_user(ctx, "submission_group"):
        default_group = datetime.now().strftime("resubmit_%Y%m%d_%H%M%S")
        selected_group = prompt_text("Submission group", default=default_group)
        if selected_group is None:
            raise typer.Exit(canceled())
        submission_group = selected_group
    raise typer.Exit(
        _resubmit_collection_impl(
            ctx,
            collection_name=collection,
            filter_name=filter_name,
            template=template,
            extra_params=extra_params,
            extra_params_file=extra_params_file,
            extra_params_function=extra_params_function,
            select_file=select_file,
            select_function=select_function,
            submission_group=submission_group,
            regenerate=regenerate,
            dry_run=dry_run,
            yes=yes,
            offer_next=True,
        )
    )


@app.command("status")
def status_command(
    ctx: typer.Context,
    collection: Optional[str] = typer.Argument(None, help="Collection to inspect."),
    state_filter: str = typer.Option("all", "--state", help="Filter by normalized job state."),
) -> None:
    """Show live status for one collection."""
    raise typer.Exit(_status_impl(ctx, collection_name=collection, state_filter=state_filter))


@app.command("sync")
def sync_command(
    ctx: typer.Context,
    collections: Optional[list[str]] = typer.Option(None, "--collection", help="Limit sync to selected collections."),
    output: Optional[Path] = typer.Option(None, "--output", help="Override sync output path."),
    push: bool = typer.Option(False, "--push", help="Commit and push the sync file."),
) -> None:
    """Sync collection state to disk."""
    raise typer.Exit(_sync_impl(ctx, collections=collections, output=output, push=push))


@config_app.callback(invoke_without_command=True)
def config_callback(ctx: typer.Context) -> None:
    """Config group callback."""
    state = get_state(ctx)
    if ctx.invoked_subcommand is None:
        if can_prompt(state):
            raise typer.Exit(_config_picker(ctx))
        typer.echo(ctx.get_help())
        raise typer.Exit(0)


@config_app.command("show")
def config_show_command(ctx: typer.Context) -> None:
    """Show the resolved configuration."""
    raise typer.Exit(_config_show_impl(get_state(ctx)))


@config_app.command("edit")
def config_edit_command(ctx: typer.Context) -> None:
    """Open the config file in $EDITOR."""
    raise typer.Exit(_config_edit_impl(get_state(ctx)))


@config_app.command("wizard")
def config_wizard_command(ctx: typer.Context) -> None:
    """Run the interactive config wizard."""
    raise typer.Exit(_config_wizard_impl(get_state(ctx), use_existing=True))


@collections_app.callback(invoke_without_command=True)
def collections_callback(ctx: typer.Context) -> None:
    """Collections group callback."""
    state = get_state(ctx)
    if ctx.invoked_subcommand is None:
        if can_prompt(state):
            raise typer.Exit(_collections_picker(ctx))
        typer.echo(ctx.get_help())
        raise typer.Exit(0)


@collections_app.command("create")
def collections_create_command(
    ctx: typer.Context,
    name: Optional[str] = typer.Argument(None, help="Collection name."),
    description: str = typer.Option("", "--description", help="Collection description."),
) -> None:
    """Create a collection."""
    raise typer.Exit(_collection_create_impl(ctx, name=name, description=description))


@collections_app.command("list")
def collections_list_command(
    ctx: typer.Context,
    attempt_mode: str = typer.Option("latest", "--attempt-mode", help="Show primary or latest effective state."),
) -> None:
    """List collections."""
    raise typer.Exit(_collection_list_impl(ctx, attempt_mode=attempt_mode))


@collections_app.command("show")
def collections_show_command(
    ctx: typer.Context,
    name: Optional[str] = typer.Argument(None, help="Collection name."),
    format_name: str = typer.Option("table", "--format", help="Output format."),
    state_filter: str = typer.Option("all", "--state", help="Filter by state."),
    attempt_mode: str = typer.Option("latest", "--attempt-mode", help="Use primary or latest attempt state."),
    submission_group: Optional[str] = typer.Option(None, "--submission-group", help="Restrict to one submission group."),
    show_primary: bool = typer.Option(False, "--show-primary", help="Include primary job ID/state columns."),
    show_history: bool = typer.Option(False, "--show-history", help="Include attempt history."),
    no_refresh: bool = typer.Option(False, "--no-refresh", help="Do not refresh from SLURM before rendering."),
) -> None:
    """Show one collection."""
    raise typer.Exit(
        _collection_show_impl(
            ctx,
            name=name,
            format_name=format_name,
            state_filter=state_filter,
            attempt_mode=attempt_mode,
            submission_group=submission_group,
            show_primary=show_primary,
            show_history=show_history,
            no_refresh=no_refresh,
        )
    )


@collections_app.command("analyze")
def collections_analyze_command(
    ctx: typer.Context,
    name: Optional[str] = typer.Argument(None, help="Collection name."),
    format_name: str = typer.Option("table", "--format", help="Output format."),
    no_refresh: bool = typer.Option(False, "--no-refresh", help="Do not refresh from SLURM before analysis."),
    min_support: int = typer.Option(3, "--min-support", help="Minimum sample support."),
    params: Optional[list[str]] = typer.Option(None, "--param", help="Parameter key(s) to analyze."),
    attempt_mode: str = typer.Option("primary", "--attempt-mode", help="Use primary or latest attempt state."),
    submission_group: Optional[str] = typer.Option(None, "--submission-group", help="Restrict to one submission group."),
    top_k: int = typer.Option(10, "--top-k", help="Top-k risky/stable values."),
) -> None:
    """Analyze parameter outcome patterns."""
    raise typer.Exit(
        _collection_analyze_impl(
            ctx,
            name=name,
            format_name=format_name,
            no_refresh=no_refresh,
            min_support=min_support,
            params=params,
            attempt_mode=attempt_mode,
            submission_group=submission_group,
            top_k=top_k,
        )
    )


@collections_app.command("groups")
def collections_groups_command(
    ctx: typer.Context,
    name: Optional[str] = typer.Argument(None, help="Collection name."),
    format_name: str = typer.Option("table", "--format", help="Output format."),
) -> None:
    """List collection submission groups."""
    raise typer.Exit(_collection_groups_impl(ctx, name=name, format_name=format_name))


@collections_app.command("refresh")
def collections_refresh_command(
    ctx: typer.Context,
    name: Optional[str] = typer.Argument(None, help="Collection name."),
    refresh_all: bool = typer.Option(False, "--all", help="Refresh all collections."),
) -> None:
    """Refresh collection state from SLURM."""
    if refresh_all and name:
        exit_with_error("Do not pass a collection name with --all.")
    raise typer.Exit(_collection_refresh_impl(ctx, name=name, refresh_all=refresh_all))


@collections_app.command("add")
def collections_add_command(
    ctx: typer.Context,
    name: Optional[str] = typer.Argument(None, help="Collection name."),
    job_ids: list[str] = typer.Argument(None, help="Job IDs to add."),
) -> None:
    """Add jobs to a collection."""
    raise typer.Exit(_collection_add_impl(ctx, name=name, job_ids=job_ids))


@collections_app.command("remove")
def collections_remove_command(
    ctx: typer.Context,
    name: Optional[str] = typer.Argument(None, help="Collection name."),
    job_ids: list[str] = typer.Argument(None, help="Job IDs to remove."),
) -> None:
    """Remove jobs from a collection."""
    raise typer.Exit(_collection_remove_impl(ctx, name=name, job_ids=job_ids))


@collections_app.command("cancel")
def collections_cancel_command(
    ctx: typer.Context,
    name: Optional[str] = typer.Argument(None, help="Collection name."),
    no_refresh: bool = typer.Option(False, "--no-refresh", help="Do not refresh before cancellation."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview without calling scancel."),
    yes: bool = typer.Option(False, "-y", "--yes", help="Skip confirmation prompt."),
) -> None:
    """Cancel active jobs in a collection."""
    raise typer.Exit(_collection_cancel_impl(ctx, name=name, no_refresh=no_refresh, dry_run=dry_run, yes=yes))


@collections_app.command("delete")
def collections_delete_command(
    ctx: typer.Context,
    name: Optional[str] = typer.Argument(None, help="Collection name."),
    keep_scripts: bool = typer.Option(False, "--keep-scripts", help="Keep job scripts."),
    keep_outputs: bool = typer.Option(False, "--keep-outputs", help="Keep output files."),
    yes: bool = typer.Option(False, "-y", "--yes", help="Skip confirmation prompt."),
) -> None:
    """Delete a collection."""
    raise typer.Exit(_collection_delete_impl(ctx, name=name, keep_scripts=keep_scripts, keep_outputs=keep_outputs, yes=yes))


@jobs_app.callback(invoke_without_command=True)
def jobs_callback(ctx: typer.Context) -> None:
    """Jobs group callback."""
    state = get_state(ctx)
    if ctx.invoked_subcommand is None:
        if can_prompt(state):
            raise typer.Exit(_jobs_picker(ctx))
        typer.echo(ctx.get_help())
        raise typer.Exit(0)


@jobs_app.command("submit")
def jobs_submit_command(
    ctx: typer.Context,
    paths: list[Path] = typer.Argument(None, help="Job script path(s)."),
    delay: float = typer.Option(0.0, "--delay", help="Seconds to wait between submissions."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview without submitting."),
    yes: bool = typer.Option(False, "-y", "--yes", help="Skip confirmation prompt."),
) -> None:
    """Submit raw job scripts."""
    raise typer.Exit(_jobs_submit_impl(ctx, paths=paths, delay=delay, dry_run=dry_run, yes=yes))


@jobs_app.command("resubmit")
def jobs_resubmit_command(
    ctx: typer.Context,
    job_ids: list[str] = typer.Argument(None, help="Job ID(s) to resubmit."),
    extra_params: Optional[str] = typer.Option(None, "--extra-params", help="Extra KEY=VAL pairs."),
    extra_params_file: Optional[Path] = typer.Option(None, "--extra-params-file", help="Python file with get_extra_params(context)->dict."),
    extra_params_function: str = typer.Option("get_extra_params", "--extra-params-function", help="Extra-params callback name."),
    select_file: Optional[Path] = typer.Option(None, "--select-file", help="Python file with should_resubmit(context)->bool."),
    select_function: str = typer.Option("should_resubmit", "--select-function", help="Selection callback name."),
    submission_group: Optional[str] = typer.Option(None, "--submission-group", help="Submission group label."),
    jobs_dir: Optional[Path] = typer.Option(None, "--jobs-dir", help="Override jobs directory."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview without resubmitting."),
    yes: bool = typer.Option(False, "-y", "--yes", help="Skip confirmation prompt."),
) -> None:
    """Resubmit raw job IDs."""
    state = get_state(ctx)
    if can_prompt(state) and not _parameter_from_user(ctx, "submission_group"):
        default_group = datetime.now().strftime("resubmit_%Y%m%d_%H%M%S")
        selected_group = prompt_text("Submission group", default=default_group)
        if selected_group is None:
            raise typer.Exit(canceled())
        submission_group = selected_group
    raise typer.Exit(
        _jobs_resubmit_impl(
            ctx,
            job_ids=job_ids,
            extra_params=extra_params,
            extra_params_file=extra_params_file,
            extra_params_function=extra_params_function,
            select_file=select_file,
            select_function=select_function,
            submission_group=submission_group,
            jobs_dir=jobs_dir,
            dry_run=dry_run,
            yes=yes,
        )
    )


@jobs_app.command("status")
def jobs_status_command(
    ctx: typer.Context,
    experiment: Optional[str] = typer.Argument(None, help="Experiment directory name."),
    jobs_dir: Optional[Path] = typer.Option(None, "--jobs-dir", help="Override jobs directory."),
    collection_name: Optional[str] = typer.Option(None, "--collection", help="Filter to one collection."),
    state_filter: str = typer.Option("all", "--state", help="Filter by state."),
    format_name: str = typer.Option("table", "--format", help="Output format."),
) -> None:
    """Inspect raw job status."""
    raise typer.Exit(
        _jobs_status_impl(
            ctx,
            experiment=experiment,
            jobs_dir=jobs_dir,
            collection_name=collection_name,
            state_filter=state_filter,
            format_name=format_name,
        )
    )


@jobs_app.command("find")
def jobs_find_command(
    ctx: typer.Context,
    job_id: Optional[str] = typer.Argument(None, help="SLURM job ID."),
    jobs_dir: Optional[Path] = typer.Option(None, "--jobs-dir", help="Override jobs directory."),
    preview: bool = typer.Option(False, "--preview", help="Show an output preview."),
    lines: int = typer.Option(50, "--lines", help="Preview line count."),
    open_file: bool = typer.Option(False, "--open", help="Open in $EDITOR or pager."),
) -> None:
    """Find a raw job output file."""
    raise typer.Exit(
        _jobs_find_impl(
            ctx,
            job_id=job_id,
            jobs_dir=jobs_dir,
            preview=preview,
            lines=lines,
            open_file=open_file,
        )
    )


@jobs_app.command("clean-outputs", hidden=True)
def jobs_clean_outputs_hidden_command(
    ctx: typer.Context,
    experiment: Optional[str] = typer.Argument(None),
    jobs_dir: Optional[Path] = typer.Option(None, "--jobs-dir"),
    threshold: int = typer.Option(300, "--threshold"),
    min_age: int = typer.Option(3, "--min-age"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    yes: bool = typer.Option(False, "-y", "--yes"),
) -> None:
    raise typer.Exit(
        _jobs_clean_outputs_impl(
            ctx,
            experiment=experiment,
            jobs_dir=jobs_dir,
            threshold=threshold,
            min_age=min_age,
            dry_run=dry_run,
            yes=yes,
        )
    )


jobs_clean_outputs_app = typer.Typer(help="Clean raw experiment outputs.")
jobs_app.add_typer(jobs_clean_outputs_app, name="clean")


@jobs_clean_outputs_app.callback(invoke_without_command=True)
def jobs_clean_callback(ctx: typer.Context) -> None:
    """Jobs clean group callback."""
    state = get_state(ctx)
    if ctx.invoked_subcommand is None:
        if can_prompt(state):
            raise typer.Exit(
                _jobs_clean_outputs_impl(
                    ctx,
                    experiment=None,
                    jobs_dir=None,
                    threshold=300,
                    min_age=3,
                    dry_run=False,
                    yes=False,
                )
            )
        typer.echo(ctx.get_help())
        raise typer.Exit(0)


@jobs_clean_outputs_app.command("outputs")
def jobs_clean_outputs_command(
    ctx: typer.Context,
    experiment: Optional[str] = typer.Argument(None, help="Experiment directory name."),
    jobs_dir: Optional[Path] = typer.Option(None, "--jobs-dir", help="Override jobs directory."),
    threshold: int = typer.Option(300, "--threshold", help="Delete only failed jobs below this runtime."),
    min_age: int = typer.Option(3, "--min-age", help="Minimum job age in days."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview without deleting."),
    yes: bool = typer.Option(False, "-y", "--yes", help="Skip confirmation prompt."),
) -> None:
    """Clean raw experiment output files."""
    raise typer.Exit(
        _jobs_clean_outputs_impl(
            ctx,
            experiment=experiment,
            jobs_dir=jobs_dir,
            threshold=threshold,
            min_age=min_age,
            dry_run=dry_run,
            yes=yes,
        )
    )


@notify_app.callback(invoke_without_command=True)
def notify_callback(ctx: typer.Context) -> None:
    """Notify group callback."""
    state = get_state(ctx)
    if ctx.invoked_subcommand is None:
        if can_prompt(state):
            raise typer.Exit(_notify_picker(ctx))
        typer.echo(ctx.get_help())
        raise typer.Exit(0)


@notify_app.command("job")
def notify_job_command(
    ctx: typer.Context,
    job_id: Optional[str] = typer.Option(None, "--job-id", help="SLURM job ID."),
    collection_name: Optional[str] = typer.Option(None, "--collection", help="Optional collection name."),
    exit_code: int = typer.Option(0, "--exit-code", help="Process exit code."),
    on: str = typer.Option("failed", "--on", help="Trigger mode."),
    routes: Optional[list[str]] = typer.Option(None, "--route", help="Route name filter."),
    tail_lines: Optional[int] = typer.Option(None, "--tail-lines", help="Output tail lines."),
    strict: bool = typer.Option(False, "--strict", help="Require all routes to succeed."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview without sending."),
) -> None:
    """Send a job notification."""
    raise typer.Exit(
        _notify_job_impl(
            ctx,
            job_id=job_id,
            collection_name=collection_name,
            exit_code=exit_code,
            on=on,
            routes=routes,
            tail_lines=tail_lines,
            strict=strict,
            dry_run=dry_run,
        )
    )


@notify_app.command("test")
def notify_test_command(
    ctx: typer.Context,
    routes: Optional[list[str]] = typer.Option(None, "--route", help="Route name filter."),
    strict: bool = typer.Option(False, "--strict", help="Require all routes to succeed."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview without sending."),
) -> None:
    """Send a test notification."""
    raise typer.Exit(_notify_test_impl(ctx, routes=routes, strict=strict, dry_run=dry_run))


@notify_app.command("collection-final")
def notify_collection_final_command(
    ctx: typer.Context,
    job_id: Optional[str] = typer.Option(None, "--job-id", help="Trigger SLURM job ID."),
    trigger_exit_code: Optional[int] = typer.Option(None, "--trigger-exit-code", help="Trigger job exit code."),
    collection_name: Optional[str] = typer.Option(None, "--collection", help="Collection name."),
    routes: Optional[list[str]] = typer.Option(None, "--route", help="Route name filter."),
    strict: bool = typer.Option(False, "--strict", help="Require all routes to succeed."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview without sending."),
    force: bool = typer.Option(False, "--force", help="Bypass deduplication guard."),
    no_refresh: bool = typer.Option(False, "--no-refresh", help="Skip SLURM refresh."),
) -> None:
    """Send a final collection notification."""
    raise typer.Exit(
        _notify_collection_final_impl(
            ctx,
            job_id=job_id,
            trigger_exit_code=trigger_exit_code,
            collection_name=collection_name,
            routes=routes,
            strict=strict,
            dry_run=dry_run,
            force=force,
            no_refresh=no_refresh,
        )
    )


@clean_app.callback(invoke_without_command=True)
def clean_callback(ctx: typer.Context) -> None:
    """Clean group callback."""
    state = get_state(ctx)
    if ctx.invoked_subcommand is None:
        if can_prompt(state):
            raise typer.Exit(_clean_picker(ctx))
        typer.echo(ctx.get_help())
        raise typer.Exit(0)


@clean_app.command("outputs")
def clean_outputs_command(
    ctx: typer.Context,
    collection: Optional[str] = typer.Argument(None, help="Collection name."),
    threshold: int = typer.Option(300, "--threshold", help="Delete only failed jobs below this runtime."),
    min_age: int = typer.Option(3, "--min-age", help="Minimum job age in days."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview without deleting."),
    yes: bool = typer.Option(False, "-y", "--yes", help="Skip confirmation prompt."),
) -> None:
    """Clean tracked collection output files."""
    raise typer.Exit(
        _collection_clean_outputs_impl(
            ctx,
            collection_name=collection,
            threshold=threshold,
            min_age=min_age,
            dry_run=dry_run,
            yes=yes,
        )
    )


@clean_app.command("wandb")
def clean_wandb_command(
    ctx: typer.Context,
    projects: Optional[list[str]] = typer.Option(None, "--projects", help="W&B projects to clean."),
    entity: Optional[str] = typer.Option(None, "--entity", help="W&B entity."),
    threshold: int = typer.Option(300, "--threshold", help="Delete only failed runs below this runtime."),
    min_age: int = typer.Option(3, "--min-age", help="Minimum run age in days."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview without deleting."),
    yes: bool = typer.Option(False, "-y", "--yes", help="Skip confirmation prompt."),
) -> None:
    """Clean failed W&B runs."""
    raise typer.Exit(
        _clean_wandb_impl(
            ctx,
            projects=projects,
            entity=entity,
            threshold=threshold,
            min_age=min_age,
            dry_run=dry_run,
            yes=yes,
        )
    )
